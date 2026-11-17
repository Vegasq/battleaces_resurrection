"""Authored verifier controls only; no original DLL or native acceptance runs."""
import asyncio
import copy
import json
from pathlib import Path
import secrets
import struct
import tempfile
from types import SimpleNamespace
import unittest
from unittest import mock
import uuid

from server import admission, community_protocol as c, dedicated_server as ds, protocol as p, public_protocol as q, tls_transport as tls
from server.bot_catalog import BotCatalog
from server.game_data import encode_frame, encode_player_input
from server.profiles import ProfileStore
from server.protobuf_wire import field_bytes, get_bytes, get_repeated_bytes, get_repeated_uint, get_uint
from server.worker_client import SimulationWorker
from tests.test_bot_catalog import catalog_fixture
from tests.test_command_scheduling_experiment import schema
from tests.test_large_army_benchmark import configured
from tests.test_tls_transport import generate_test_pki, remove_test_pki
from tools import verify_hybrid_flows as flow


class EvidenceControls(unittest.TestCase):
    def test_solo_default_includes_observed_ai_activation_and_explicit_short_failure_can_be_reproduced(self):
        directory = flow.ROOT/'local'/('flow-arguments-'+uuid.uuid4().hex)
        arguments = [part for name in ('assets', 'output', 'wine', 'windows-python', 'prefix-template',
                                      'tls-cert', 'tls-key', 'tls-ca') for part in ('--'+name, str(directory/name))]
        with mock.patch.object(flow.sys, 'platform', 'linux'):
            self.assertGreater(flow.arguments(arguments+['--solo-team-only']).play_frames, 131)
            self.assertEqual(flow.arguments(arguments).play_frames, 120)
            self.assertEqual(flow.arguments(arguments+['--solo-team-only', '--play-frames', '120']).play_frames, 120)

    def test_public_and_custom_delivery_reconstruct_same_canonical_inputs(self):
        inputs = {0: b'first', 1: b'second'}
        custom = struct.pack('<II', 7, 5)+b'firstsecond'
        self.assertEqual(flow.decode_frame(p.FRAME, custom, 2), (7, inputs))
        self.assertEqual(flow.decode_frame(q.FRAME, q.frame(7, inputs), 2), (7, inputs))
        for kind, payload, count in ((p.FRAME, custom, 4), (p.FRAME, custom[:8], 2),
                (p.FRAME, struct.pack('<II', 7, 100)+b'a', 2), (q.FRAME, q.frame(7, inputs)+b'x', 2)):
            with self.subTest(kind=kind, count=count), self.assertRaises(ValueError):
                flow.decode_frame(kind, payload, count)

    def test_ordinary_concession_uses_only_owned_hq_and_configured_ability(self):
        template = SimpleNamespace(entity_abilities={3: {91}, 8: {92}}, abilities={91: field_bytes(24, b''), 92: field_bytes(24, b'')})
        validation = mock.Mock()
        room = SimpleNamespace(template=template, validation=validation,
                               match=SimpleNamespace(identities_by_slot={0: b'authored identity'}))
        state = dict(entities=[dict(id=9, army=1, type=3), dict(id=1, army=0, type=8), dict(id=12, army=0, type=3)])
        body, evidence = flow.concede_body(room, state, 0)
        self.assertEqual(evidence, dict(slot=0, entity=12, entity_type=3, ability=91))
        action, = get_repeated_bytes(body, 2)
        group = get_bytes(get_bytes(action, 1), 1)
        self.assertEqual((get_uint(group, 1), get_uint(group, 2), get_repeated_uint(group, 3)), (3, 91, (12,)))
        validation.validate_player_input.assert_called_once_with(0, body)
        with self.assertRaisesRegex(ValueError, 'no owned HQ'):
            flow.concede_body(room, dict(entities=state['entities'][:2]), 0)
        template.abilities[91] = field_bytes(25, b'')
        with self.assertRaisesRegex(ValueError, 'no owned HQ'):
            flow.concede_body(room, state, 0)

    def test_native_result_requires_exact_wire_result_and_whole_losing_alliance(self):
        native = dict(complete=True, winning_alliance=1, army_conceded_flag=5, game_over_frame=123)
        result = dict(match='a'*32, reason='native game complete', result=native)
        flow.validate_result(result, native, [0, 2], match='a'*32)
        for changed in (native | dict(complete=False), native | dict(winning_alliance=0), native | dict(army_conceded_flag=1)):
            with self.assertRaises(ValueError):
                flow.validate_result(result | dict(result=changed), changed, [0, 2], match='a'*32)
        with self.assertRaisesRegex(ValueError, 'differs'):
            flow.validate_result(result | dict(reason='authored completion'), native, [0, 2], match='a'*32)
        with self.assertRaisesRegex(ValueError, 'differs'):
            flow.validate_result(result, native | dict(game_over_frame=124), [0, 2], match='a'*32)
        with self.assertRaisesRegex(ValueError, 'match identity'):
            flow.validate_result(result, native, [0, 2], match='b'*32)

    def test_history_binds_human_ids_bot_slots_alliances_and_abort_classification(self):
        room = SimpleNamespace(match_id='a'*32, mode=5, public_match=True, slots={0, 1, 2, 3},
            bots={1: object(), 3: object()}, match_profiles={0: 'a', 2: 'b'},
            template=SimpleNamespace(alliances={0: 0, 1: 1, 2: 0, 3: 1}))
        row = dict(id=room.match_id, mode=5, kind='Public', state='completed', winning_alliance=1,
            players=[dict(slot=s, alliance=s%2, bot=bool(s%2), id=None if s%2 else room.match_profiles[s]) for s in range(4)])
        flow.validate_history(row, room, completed=True)
        for mutation in ('human', 'bot', 'alliance', 'missing', 'aborted'):
            changed = copy.deepcopy(row)
            if mutation == 'human': changed['players'][0]['id'] = 'different'
            elif mutation == 'bot': changed['players'][1]['bot'] = False
            elif mutation == 'alliance': changed['players'][2]['alliance'] = 1
            elif mutation == 'missing': changed['players'].pop()
            else: changed['state'] = 'aborted'
            with self.subTest(mutation=mutation), self.assertRaises(ValueError):
                flow.validate_history(changed, room, completed=True)
        flow.validate_history(row | dict(state='aborted', winning_alliance=None), room, completed=False)

    def test_bounded_matrix_covers_all_modes_and_losing_alliance_human_seats(self):
        self.assertEqual(flow.CASES, (('public1-humans', 1, 2), ('public1-ai', 1, 1),
            ('public2-ai-fill', 2, 3), ('public5', 5, 2), ('custom1', 1, 2)))
        for name, mode, humans in flow.CASES:
            count, eligible = q.MODES[mode]
            self.assertTrue({s for s in range(count) if s%2 == 0} <= set(eligible[:humans]))

    def test_solo_team_requires_original_ally_and_opponent_pools_and_exact_seats(self):
        room = SimpleNamespace(mode=5, peers={0: object()},
            bots={slot: SimpleNamespace(profile_id=60+slot,
                  choice=SimpleNamespace(profile=60+slot, source_mode=2 if slot == 2 else 5)) for slot in (1, 2, 3)},
            template=SimpleNamespace(alliances={0: 0, 1: 1, 2: 0, 3: 1}))
        flow.validate_solo_team_roster(room)
        for mutation in ('ally_pool', 'opponent_pool', 'profile', 'human', 'missing_bot', 'alliance'):
            changed = copy.deepcopy(room)
            if mutation == 'ally_pool': changed.bots[2].choice.source_mode = 5
            elif mutation == 'opponent_pool': changed.bots[3].choice.source_mode = 2
            elif mutation == 'profile': changed.bots[1].choice.profile += 1
            elif mutation == 'human': changed.peers[2] = object()
            elif mutation == 'missing_bot': del changed.bots[3]
            else: changed.template.alliances[2] = 1
            with self.subTest(mutation=mutation), self.assertRaises(ValueError):
                flow.validate_solo_team_roster(changed)

    def test_disconnect_publication_claim_is_exact_prefix_not_unreceived_tail(self):
        inputs = {0: encode_player_input(b'authored0'), 1: encode_player_input(b'authored1')}
        frames = [encode_frame(frame, inputs) for frame in range(3)]
        journal = b''.join(struct.pack('<I', len(frame))+frame for frame in frames)
        result = flow.publication_prefix(journal, frames[:2])
        self.assertEqual((result['delivered_frames'], result['authoritative_frames']), (2, 3))
        for bad_journal, delivered in ((journal, []), (journal, frames[1:]), (journal[:-1], frames[:2]),
                                       (journal, frames+[frames[-1]])):
            with self.assertRaises(ValueError):
                flow.publication_prefix(bad_journal, delivered)


class SupplementalRoutingControls(unittest.IsolatedAsyncioTestCase):
    async def test_solo_team_only_never_runs_prior_matrix_or_concession(self):
        check = flow.Verification(SimpleNamespace(solo_team_only=True))
        peer = object()
        check.connect = mock.AsyncMock(return_value=peer)
        check.solo_team = mock.AsyncMock()
        check.reconnect = mock.AsyncMock(side_effect=AssertionError('prior matrix forbidden'))
        check.complete = mock.AsyncMock(side_effect=AssertionError('team concession forbidden'))
        self.assertEqual(await check.exercise(), (1, 0))
        check.connect.assert_awaited_once()
        check.solo_team.assert_awaited_once_with(peer)
        check.reconnect.assert_not_called(); check.complete.assert_not_called()


class ProtocolControls(unittest.IsolatedAsyncioTestCase):
    @classmethod
    def setUpClass(cls):
        cls.folder = flow.ROOT/'local'/('hybrid-flow-tls-control-'+uuid.uuid4().hex)
        cls.pki = generate_test_pki(cls.folder)

    @classmethod
    def tearDownClass(cls):
        remove_test_pki(cls.folder)

    async def test_reused_public_sessions_reconnect_and_custom_keep_startup_and_frame_contracts(self):
        with tempfile.TemporaryDirectory(prefix='ba-authored-flow-') as temporary:
            output = Path(temporary)
            template, _, _ = configured(load='small')
            schema(output); template.descriptors_path = output
            (output/'bot-catalog.json').write_text(json.dumps(catalog_fixture()), encoding='utf-8')
            check = flow.Verification(SimpleNamespace(output=output))
            async def factory(data, bots=None):
                self.assertIsNone(bots)
                worker = await SimulationWorker.create(data, working_directory=output, _test_backend=True)
                check.workers.append(worker)
                return worker
            check.profiles = ProfileStore(output/'profiles', template)
            check.server = ds.DedicatedServer(template, check.profiles, bot_catalog=BotCatalog(output),
                sim_factory=factory, ai_factory=factory, audit=check.audit, data_dir=output, audit_state=False,
                tls_context=tls.load_server_context(self.pki['cert'], self.pki['key']),
                admission=admission.AdmissionController(None, rc_open=True, burst=32), experimental_command_scheduling=True)
            check.address = await check.server.start('127.0.0.1', 0)
            check.client_tls = tls.load_client_context(self.pki['ca'], 'localhost')
            identities = [dict(name=f'Authored {s}', token='ba1_'+secrets.token_urlsafe(32)) for s in range(2)]
            try:
                peers = [await check.connect(identity) for identity in identities]
                old_identity = peers[0].profile
                room, _ = await check.public(1, peers)
                await check.load(room, peers)
                await flow.until(lambda: all(len(peer.frames) >= 4 for peer in peers))
                await peers[0].close()
                await peers[1].receive(c.ABORTED)
                await flow.until(lambda: old_identity not in check.server.community.sessions)
                await peers[1].command(q.RETURN, match=room.match_id)
                peers[0] = await check.connect(identities[0])
                self.assertEqual(peers[0].profile, old_identity)
                replacement, _ = await check.public(1, peers)
                self.assertNotEqual(replacement.match_id, room.match_id)
                await check.load(replacement, peers)
                await flow.until(lambda: all(len(peer.frames) >= 4 for peer in peers))
                await replacement.finish('authored fixture teardown', aborted=True)
                for peer in peers:
                    await peer.receive(c.ABORTED)
                    await peer.command(q.RETURN, match=replacement.match_id)
                    peer.count = 4  # Prior team mode must not leak into Custom decoding.
                custom, _ = await check.custom(peers)
                await check.load(custom, peers)
                await flow.until(lambda: all(len(peer.frames) >= 4 for peer in peers))
                self.assertTrue(custom.command_scheduling)
                self.assertTrue(all(peer.count == 2 for peer in peers))
                self.assertFalse(any(row['event'] == 'protocol_error' for row in check.events))
            except BaseException:
                (flow.ROOT/f'local/hybrid-flow-authored-failure-{uuid.uuid4().hex}.json').write_text(json.dumps(dict(
                    events=check.events, peers=[dict(failure=peer.failure, frames=len(peer.frames)) for peer in check.peers]), indent=2))
                raise
            finally:
                await check.close()
            self.assertTrue(all(worker._test_backend and worker.process.poll() == 0 for worker in check.workers))
            self.assertFalse((output/'verification.json').exists())  # Controls never emit native qualification.


if __name__ == '__main__':
    unittest.main()
