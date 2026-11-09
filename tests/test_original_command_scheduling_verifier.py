"""Offline diagnostic regressions: tuple normalization and byte-stream evidence."""
import asyncio
import copy
from pathlib import Path
import struct
import subprocess
import tempfile
import unittest
from unittest import mock

from client_patch.transport import bridge
from server import protocol as p
from server.game_data import encode_frame, encode_identity, encode_player_input
from server.protobuf_wire import field_bytes, field_uint
from tools.verify_original_command_scheduling import (ObservedBridge, cleanup_step, conservation,
                                                       digest, first_output_ready, native_builds, read_journal,
                                                       startup_barrier, stop_owned_process)

ROOT = Path(__file__).resolve().parents[1]
MATCH = '0123456789abcdef0123456789abcdef'


def fixture():
    identities = [encode_identity(slot+1, 'Fixture '+str(slot)) for slot in (0,1)]
    # Authored protobuf InputActions fixtures; no native legality/state claim.
    joins = [field_bytes(3,field_uint(1,slot)) for slot in (0,1)]
    commands = [field_bytes(5,field_bytes(case,b'')) for case in (1,2)]
    authored = [(0,1,0,(joins[0],)),(1,1,0,(joins[1],)),
                (0,2,1,(commands[0],)),(0,3,1,(commands[1],))]
    bodies, events, frames = {}, [], []
    for slot,sequence,frame,actions in authored:
        body = encode_player_input(identities[slot],actions)
        bodies[(MATCH,slot,sequence)] = body
        common = dict(match=MATCH,slot=slot,sequence=sequence,body_sha256=digest(body),action_count=len(actions))
        events.append(dict(common,event='command_batch_accepted',earliest_frame=frame))
        events.append(dict(common,event='command_batch_committed',frame=frame))
    for frame in range(3):
        by_slot = {slot:tuple(action for owner,sequence,target,actions in authored if owner == slot and target == frame
                             for action in actions) for slot in (0,1)}
        inputs = {slot:encode_player_input(identities[slot],by_slot[slot]) for slot in (0,1)}
        frames.append(encode_frame(frame,inputs))
    return bodies,events,frames


class JournalEvidenceTests(unittest.TestCase):
    def setUp(self):
        (ROOT/'local').mkdir(exist_ok=True)
        self.temporary = tempfile.TemporaryDirectory(prefix='scheduling-verifier-',dir=ROOT/'local')
        self.output = Path(self.temporary.name)
        self.addCleanup(self.temporary.cleanup)
        self.bodies,self.events,frames = fixture()
        folder = self.output/'matches'/MATCH
        folder.mkdir(parents=True)
        with (folder/'frames.bin').open('wb') as stream:
            for frame in frames:
                stream.write(struct.pack('<I',len(frame))+frame)
        self.journal = read_journal(self.output,MATCH,3)

    def test_idle_and_nonempty_journal_players_use_decoder_tuples(self):
        self.assertEqual(self.journal[1]['players'][1],())
        self.assertEqual(self.journal[2]['players'],{0:(),1:()})
        self.assertTrue(all(isinstance(actions,tuple) for frame in self.journal for actions in frame['players'].values()))

    def test_retained_actual_native_build_log_has_no_equals_after_ability(self):
        line = ('[640403578] LAN NORMAL BUILD smoke frame300 slot0 army0 HQ0 deckSlot0 unitType1 '
                'ability34 cost=(50,0) prerequisite=1 queued=1 commandQueueDelta=1 presentedFrame=293')
        self.assertEqual(native_builds(line),[('640403578','300','0','34')])

    def test_ordered_nonempty_and_idle_conservation_passes(self):
        result = conservation(MATCH,self.journal,self.events,self.bodies,3)
        self.assertEqual(result['prefix_committed_batches'],4)
        self.assertEqual(result['prefix_actions'],4)

    def test_reordered_commands_and_missing_commit_fail(self):
        changed = copy.deepcopy(self.journal)
        changed[1]['players'][0] = tuple(reversed(changed[1]['players'][0]))
        with self.assertRaisesRegex(AssertionError,'order/content differs'):
            conservation(MATCH,changed,self.events,self.bodies,3)
        missing = [row for row in self.events if not(row['event'] == 'command_batch_committed' and row['slot'] == 0 and row['sequence'] == 3)]
        with self.assertRaisesRegex(AssertionError,'accepted prefix batch was lost'):
            conservation(MATCH,self.journal,missing,self.bodies,3)


class FirstOutputBarrierTests(unittest.TestCase):
    def events(self):
        rows = [dict(event='probe_command_frame_sealed',frame=0,observed_at=9.99),
                dict(event='frame_queued',frame=0,observed_at=10),
                dict(event='command_startup_waiting',frame=0,ready_slots=[0,1],observed_at=10),
                dict(event='command_startup_ready',slot=0,frame=0,ready_count=1,all_ready=False,observed_at=10.4),
                dict(event='command_startup_ready',slot=1,frame=0,ready_count=2,all_ready=True,observed_at=10.6),
                dict(event='command_startup_released',frame=1,ready_slots=[0,1],observed_at=10.6,
                     rebased_at=510.6,next_tick=510.65,wait_ms=600),
                dict(event='probe_command_frame_sealed',frame=1,observed_at=10.651),
                dict(event='frame_queued',frame=1,observed_at=10.66)]
        # Windows monotonic and perf_counter can have distinct epochs. Only
        # perf_counter timestamps may be compared to the server's next_tick.
        return [dict(match=MATCH,observed_perf_counter=row['observed_at']+500,**row) for row in rows]

    def test_both_readies_rebase_before_frame1_seal(self):
        events = self.events()
        self.assertTrue(startup_barrier(MATCH,events)['frame1_sealed_after_release'])
        events[-2]['observed_at'] = 10.5
        with self.assertRaisesRegex(AssertionError,'frame1 was sealed before'):
            startup_barrier(MATCH,events)
        events = self.events()
        events[-2]['observed_perf_counter'] = 510.64
        with self.assertRaisesRegex(AssertionError,'frame1 was sealed before'):
            startup_barrier(MATCH,events)

    def test_ready_requires_publication_not_just_application(self):
        log = 'Original command first output ready: match='+MATCH+' presentedFrame=0 sendTick=800'
        events = [dict(event='command_startup_ready',match=MATCH,slot=0,probe_tick_ms=850)]
        published = dict(event='publication',frame=0,presented=0,ms=790)
        self.assertTrue(first_output_ready(log,MATCH,0,[published],events)['actual_publication_before_ready'])
        with self.assertRaisesRegex(AssertionError,'actual first native output publication'):
            first_output_ready(log,MATCH,0,[dict(published,event='apply')],events)


class PrivateStreamEvidenceTests(unittest.IsolatedAsyncioTestCase):
    async def test_cleanup_failure_retains_error_and_still_attempts_next_resource(self):
        errors,completed = [],[]
        def fail():
            raise OSError('fixture cleanup failure')
        await cleanup_step(errors,'first resource',fail)
        await cleanup_step(errors,'second resource',lambda:completed.append('closed'))
        self.assertEqual(completed,['closed'])
        self.assertEqual(errors,[dict(step='first resource',error='OSError: fixture cleanup failure')])

    async def test_owned_wait_timeout_still_kills_and_reaps_without_hiding_failure(self):
        class OwnedProcess:
            waits = 0
            killed = False
            def poll(self): return 1 if self.killed else None
            def terminate(self): pass
            def wait(self,timeout):
                self.waits += 1
                if not self.killed:
                    raise subprocess.TimeoutExpired('owned fixture',timeout)
                return 1
            def kill(self): self.killed = True
        process,errors = OwnedProcess(),[]
        await cleanup_step(errors,'owned process',lambda:stop_owned_process(process,timeout=.001))
        self.assertTrue(process.killed)
        self.assertEqual(process.waits,2)
        self.assertIn('TimeoutExpired',errors[0]['error'])

    async def test_split_packets_bind_exact_frame_hash_to_match(self):
        evidence = []
        observed = ObservedBridge(None,None,None,version=2,evidence=evidence,tick=lambda:123)
        payload = struct.pack('<II',0,0)+b'fixture'
        stream = p.encode(p.MATCH_INFO,MATCH.encode())+p.encode(p.FRAME,payload)
        with mock.patch.object(bridge.Bridge,'send',new=mock.AsyncMock()):
            for part in (stream[:1],stream[1:6],stream[6:37],stream[37:]):
                await observed.send(bridge.DATA,1,part)
        self.assertEqual(evidence,[dict(match=MATCH,frame=0,payload_sha256=digest(payload),received_tick_ms=123)])

    async def test_invalid_length_and_unassigned_frame_fail_closed(self):
        with mock.patch.object(bridge.Bridge,'send',new=mock.AsyncMock()):
            for length in (0,p.MAX_BODY+1):
                observed = ObservedBridge(None,None,None,version=2,evidence=[],tick=lambda:0)
                with self.assertRaisesRegex(AssertionError,'packet length'):
                    await observed.send(bridge.DATA,1,struct.pack('<I',length))
            observed = ObservedBridge(None,None,None,version=2,evidence=[],tick=lambda:0)
            with self.assertRaisesRegex(AssertionError,'precedes Custom assignment'):
                await observed.send(bridge.DATA,1,p.encode(p.FRAME,struct.pack('<II',0,0)))


if __name__ == '__main__':
    unittest.main()
