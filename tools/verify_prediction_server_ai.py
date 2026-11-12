"""Prepare-only one-client public mode1 server-AI prediction qualification.

Only --run-prepared launches the isolated loopback TLS authority and retained,
suspended/Job-owned client and native AI worker. The first scope is canonical
AI correction/startup/result/Continue/menu Quit. Explicit --human-move additionally
requires original Move440/Unity response; default startup makes no Move claim.
Explicit --visual-correction keeps that human-Move scope and enables the same
render correction flag as the private human launcher, without visual observers.
The shared multiplayer preparer freezes runtime inputs only; its Custom runner
and every Custom-only gameplay fixture are never invoked by this controller.
"""
from __future__ import annotations

import argparse
import asyncio
from collections import defaultdict
import ctypes as C
import json
import math
import os
from pathlib import Path
import re
import secrets
import shutil
import socket
import struct
import subprocess
import sys
import time
import traceback

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from tools import verify_prediction_multiplayer as owned
from client_patch.transport import bridge
from server import public_protocol as public, loadout_protocol, protocol
from server.game_data import encode_player_input
from server.protobuf_wire import get_bytes, get_repeated_bytes, get_uint, parse_fields

require, read, sha, digest, write = owned.require, owned.read, owned.sha, owned.digest, owned.write
SCOPE = 'public-mode1-server-ai-startup-canonical-correction-v1'
MOVE_SCOPE = 'public-mode1-server-ai-human-move-canonical-correction-v1'
OBSERVER_MARKER = b'BA_RESURRECTION_SERVER_AI_PREDICTION_OBSERVE_V1'
MOVE_MARKER = b'BA_RESURRECTION_SERVER_AI_MOVEMENT_SMOKE_V1'
MAX_FRAMES = 2048


def visual_option(human_move, value):
    require(type(human_move)is bool,'human Move option must be Boolean')
    require(type(value)is bool,'server AI visual correction option must be Boolean')
    require(not value or human_move,'server AI visual correction requires explicit human Move scope')
    return value


def visual_helper(enabled, helper):
    if enabled:
        require(b'OfflinePredictionVisualJoin\0'in helper and
                '-prediction-visual-correction'.encode('utf-16-le')in helper,
                'server AI helper lacks visual join or correction flag')


def packaged_source_closure(inputs, visual_enabled):
    if not inputs.get('worker_package'):return
    from tools.build_windows_packages import PREDICTION_CLIENT
    from tools.package_integrity import verify
    app=Path(inputs['worker_module_root'])
    sources=inputs['source_sha256']
    inventory=verify(Path(inputs['worker_package']),'client')
    names={name for name in PREDICTION_CLIENT if name.endswith('.py')}
    actual={name[len('program/app/'):]for name in inventory['files']
            if name.startswith('program/app/')and name.endswith('.py')}
    require(actual==names,'packaged private client Python module inventory differs')
    require(names<=sources.keys(),'packaged private client source pins missing')
    # The authority is frozen from ROOT; the worker ships only its declared
    # dependency subset. Bind every packaged module, including human launchers,
    # without demanding unshipped authority modules inside the client bundle.
    for name in sorted(names):
        require(sha(app/name)==sources[name],'packaged server AI worker/source differs: '+name)


def bootstrap_preflight(template, catalog):
    """Pure schema/control check; not the eventual randomly assigned match."""
    from client_patch.prediction_worker.commands import CanonicalRoster
    choice = catalog.choose(1, role='opponents')
    players = [dict(slot=0, player_id=1, army_id=0, name='Prediction preflight', ai_profile_id=0),
               dict(slot=1, player_id=2, army_id=1, name=choice.name, ai_profile_id=choice.profile)]
    match = template.build_match(players, {0: template.default_decks[0], 1: choice.deck.units},
                                 seed=791, game_mode=1, bot_choices={1: choice})
    roster = CanonicalRoster.from_game_data(match.raw_game_data)
    require(roster.identities == tuple(match.identities_by_slot[slot] for slot in (0, 1)),
            'real template/catalog bootstrap schema differs from exact MatchData identities')
    return match.raw_game_data, dict(native_executed=False, mode=1, human_slots=[0], bot_slots=[1],
        bot_profile=choice.profile, bootstrap_sha256=digest(match.raw_game_data),
        identity_sha256=[digest(identity) for identity in roster.identities])


def validate_plan(plan):
    human_move = plan.get('human_move', False)
    require(type(human_move) is bool, 'human Move option must be Boolean')
    visual_option(human_move,plan.get('visual_correction',False))
    require(type(plan.get('schema')) is int and plan['schema'] == 1 and
            plan.get('scope') == (MOVE_SCOPE if human_move else SCOPE) and
            plan.get('native_executed') is False and type(plan.get('mode')) is int and plan['mode'] == 1 and
            plan.get('human_slots') == [0] and plan.get('bot_slots') == [1] and
            plan.get('expected_matches') == 1 and plan.get('solo_ai_host') == 'server' and
            plan.get('human_movement_exercised') is False and plan.get('full_feature_accepted') is False,
            'server AI prepared scope/roster differs')
    require(type(plan.get('surrender_frame')) is int and 400 <= plan['surrender_frame'] <= 1200 and
            type(plan.get('timeout')) in (int, float) and 90 <= plan['timeout'] <= 240 and
            type(plan.get('rtt_ms')) in (int, float) and math.isfinite(plan['rtt_ms']) and
            130 <= plan['rtt_ms'] <= 500, 'server AI finite timing bounds differ')
    require(not human_move or plan['surrender_frame'] == 600,
            'human Move440 requires the unchanged Concede600 fixture')
    require(type(plan.get('profile')) is str and re.fullmatch(r'nativestest_pm_[a-f0-9]{10}_0', plan['profile']),
            'server AI requires its fresh owned profile')


def prepare(args):
    human_move = getattr(args, 'human_move', False)
    require(type(human_move) is bool, 'human Move option must be Boolean')
    visual_enabled=visual_option(human_move,getattr(args,'visual_correction',False))
    game, output = owned.owned_paths(args.game, args.output)
    # Reuse all source/build-receipt/export/patch/arena/package input checks.
    # This nested invocation is a frozen resource preflight, never executed.
    options = argparse.Namespace(**vars(args))
    options.output, options.module_root = output / 'frozen-inputs', ROOT
    options.scenario, options.lifecycle, options.frames = 'startup', 'natural', 200
    # Nested preparation freezes resources only. Its visual option belongs to
    # a different Custom/changing-RTT fixture and must never be activated here.
    options.visual_correction=False
    options.rtt_ms, options.move_slot = [args.rtt_ms, args.rtt_ms], 0
    inputs = owned.prepare(options)
    from server.assets import verify_assets
    from server.ai_rules import RuleBook, SUPPORTED_AI_SHA256
    verify_assets(args.assets)
    assets = Path(args.assets).resolve(strict=True)
    rules = RuleBook(assets)
    names = set(rules.files) | {'aiprogram.dll', 'bot-catalog.json'}
    extra_assets = {name: dict(path=str((assets / name).resolve(strict=True)), sha256=sha(assets / name))
                    for name in sorted(names)}
    require(extra_assets['aiprogram.dll']['sha256'] == SUPPORTED_AI_SHA256,
            'one exact original native AI producer is required')
    helper = read(inputs['files']['helper']['path'])
    require(OBSERVER_MARKER in helper and '-prediction-server-ai-observe'.encode('utf-16-le') in helper,
            'helper lacks observation-only public server AI journal capability')
    require(not human_move or (MOVE_MARKER in helper and
            '-prediction-server-ai-move-smoke'.encode('utf-16-le') in helper),
            'helper lacks explicit public server AI original Move fixture')
    visual_helper(visual_enabled,helper)
    from server.game_data import GameTemplate
    from server.bot_catalog import BotCatalog
    template = GameTemplate.load(assets / 'map-1v1.pb.gz', catalog_path=assets / 'unit-catalog.json',
                                 descriptors_path=assets / 'descriptors')
    bootstrap, control = bootstrap_preflight(template, BotCatalog(assets, template=template, rules=rules))
    (output / 'bootstrap-preflight.pb').write_bytes(bootstrap)
    write(output / 'bootstrap-preflight.json', control)
    # A package may be used only when its actual worker Python equals this source.
    packaged_source_closure(inputs,visual_enabled)
    plan = dict(schema=1, native_executed=False, scope=MOVE_SCOPE if human_move else SCOPE,
                output=str(output), game=str(game),
                mode=1, solo_ai_host='server', human_slots=[0], bot_slots=[1], expected_matches=1,
                profile=inputs['profiles'][0], surrender_frame=args.surrender_frame,
                rtt_ms=args.rtt_ms, timeout=args.timeout, human_movement_exercised=False,
                visual_correction=visual_enabled,
                full_feature_accepted=False, frozen_inputs_sha256=sha(output / 'frozen-inputs/invocation.json'),
                extra_asset_files=extra_assets, bootstrap_preflight_sha256=digest(bootstrap),
                bootstrap_preflight_report_sha256=sha(output / 'bootstrap-preflight.json'))
    if human_move:
        plan['human_move'] = True
    validate_plan(plan)
    write(output / 'invocation.json', plan)
    return plan


def verify_prepared(output):
    output = Path(output).resolve(strict=True)
    require(output.is_relative_to((ROOT / 'local').resolve()) and output != (ROOT / 'local').resolve(),
            'server AI output must be ignored and owned')
    plan = json.loads(read(output / 'invocation.json', 4 * 1024 * 1024))
    validate_plan(plan)
    require(Path(plan['output']).resolve() == output and not os.path.lexists(output / 'run'),
            'server AI run already exists or invocation owner changed; preserve prior evidence')
    require(sha(output / 'frozen-inputs/invocation.json') == plan['frozen_inputs_sha256'],
            'frozen runtime preflight changed')
    require(sha(output / 'bootstrap-preflight.pb') == plan['bootstrap_preflight_sha256'] and
            sha(output / 'bootstrap-preflight.json') == plan['bootstrap_preflight_report_sha256'],
            'preparation-only real template/catalog control changed')
    inputs = owned.verify_prepared(output / 'frozen-inputs')
    visual_helper(plan.get('visual_correction',False),read(inputs['files']['helper']['path']))
    packaged_source_closure(inputs,plan.get('visual_correction',False))
    require(inputs['game'] == plan['game'] and inputs['profiles'][0] == plan['profile'],
            'server AI resource/profile ownership changed')
    for row in plan['extra_asset_files'].values():
        require(sha(row['path']) == row['sha256'], 'server AI asset changed after preparation')
    return plan, inputs


def command_extra(plan, inputs, run):
    validate_plan(plan)
    result = ['-public-queue-smoke', '-public-queue-smoke-mode=1', '-lan-smoke', '-lan-audit',
              '-dedicated-rematch-smoke', '-dedicated-surrender-smoke',
              '-dedicated-surrender-frame=' + str(plan['surrender_frame']),
              '-prediction-movement-experimental', '-prediction-server-ai-observe',
              '-frame-timing', '-frame-timing-frames=2000',
              '-native-quit-smoke', '-native-quit-mode=confirm', '-native-quit-gate-smoke']
    for flag, key in (('python', 'python'), ('heap-helper', 'heap_helper'), ('cooperative', 'cooperative')):
        result.append('-prediction-worker-' + flag + '=' + inputs['files'][key]['path'])
    result += ['-prediction-worker-module-root=' + inputs['worker_module_root'],
               '-prediction-worker-data-dir=' + str(Path(run) / 'worker-data')]
    if plan.get('human_move'):
        result.append('-prediction-server-ai-move-smoke')
    if plan.get('visual_correction'):
        result.append('-prediction-visual-correction')
    return result


class SubmittedBatches:
    """Immutable accepted socket72 bodies, never reconstructed from authority."""
    def __init__(self, directory=None):
        self.directory, self.bodies, self.rows = directory, {}, []
        self.total_bytes = 0
        if directory is not None:
            directory.mkdir(exist_ok=False)

    def record(self, match, slot, sequence, body, tick):
        require(type(match) is str and re.fullmatch('[a-f0-9]{32}', match) and type(slot) is int and slot == 0 and
                type(sequence) is int and 1 <= sequence <= 1024 and type(body) is bytes and 0 < len(body) <= 65536,
                'submitted72 match/human/sequence/body differs')
        key = match, slot, sequence
        previous = [row for row in self.rows if row['match'] == match]
        require(key not in self.bodies and sequence == len(previous) + 1 and len(self.rows) < 1024 and
                self.total_bytes + len(body) <= 16 * 1024 * 1024, 'submitted72 sequence duplicate/gap or budget exceeded')
        filename = f'{match}-{slot}-{sequence}.pb'
        if self.directory is not None:
            with (self.directory / filename).open('xb') as stream:
                stream.write(body)
        self.bodies[key] = body
        self.total_bytes += len(body)
        self.rows.append(dict(match=match, slot=slot, sequence=sequence, bytes=len(body),
                              body_sha256=digest(body), received_tick_ms=tick, file=filename))


class PublicPackets:
    """Readonly, bounded public assignment/raw64 association before bridge delivery."""
    def __init__(self):
        self.buffers, self.assignments, self.frames = defaultdict(bytearray), {}, []

    def feed(self, identity, data, tick):
        pending = self.buffers[identity]
        pending.extend(data)
        require(len(pending) <= protocol.MAX_BODY + bridge.CHUNK + 4, 'private public packet buffer exceeded bound')
        emitted = []
        while len(pending) >= 4:
            length, = struct.unpack_from('<I', pending)
            require(1 <= length <= protocol.MAX_BODY, 'invalid public wire packet size')
            if len(pending) < length + 4:
                break
            packet, body = pending[4], bytes(pending[5:length + 4])
            del pending[:length + 4]
            if packet in (public.MATCH, loadout_protocol.MATCH_LOADOUT):
                seat = public.decode_assignment(body, complete=packet == loadout_protocol.MATCH_LOADOUT)
                require(identity not in self.assignments and seat['mode'] == 1 and seat['count'] == 2 and
                        seat['slot'] == 0 and seat['human_mask'] == 1, 'public AI assignment differs or repeats')
                self.assignments[identity] = seat
            elif packet == public.FRAME:
                require(identity in self.assignments, 'public64 precedes owned assignment')
                frame, _ = public.decode_frame(body, 2)
                own = [row for row in self.frames if row['identity'] == identity]
                require(frame == len(own) and len(self.frames) < MAX_FRAMES,
                        'public64 duplicate/noncontiguous/unbounded frame')
                row = dict(identity=identity, match=self.assignments[identity]['match'], frame=frame,
                           payload_sha256=digest(body), received_tick_ms=tick)
                self.frames.append(row)
                emitted.append(body)
        return emitted


class ObservedPublicBridge(bridge.Bridge):
    def __init__(self, *args, packets, raw_stream, tick, **kwargs):
        super().__init__(*args, **kwargs)
        self.packets, self.raw_stream, self.tick = packets, raw_stream, tick

    async def send(self, kind, identity, data=b''):
        if kind == bridge.DATA:
            for body in self.packets.feed(identity, data, self.tick()):
                self.raw_stream.write(struct.pack('<I', len(body)) + body)
                self.raw_stream.flush()
        await super().send(kind, identity, data)


def records(path, *, maximum=MAX_FRAMES):
    """Read a CLOSED length-prefixed raw capture; never repair a partial row."""
    raw = read(path, 64 * 1024 * 1024)
    result, offset = [], 0
    while offset < len(raw):
        require(offset + 4 <= len(raw), 'partial raw capture header')
        size, = struct.unpack_from('<I', raw, offset)
        offset += 4
        require(0 < size <= 1024 * 1024 and offset + size <= len(raw), 'partial/unbounded raw capture row')
        result.append(raw[offset:offset + size])
        offset += size
        require(len(result) <= maximum, 'raw capture row budget exceeded')
    return result


def canonical_inputs(raw, identities, expected_frame):
    from server.game_data import decode_frame
    decoded = decode_frame(raw)
    require(decoded['frame'] == expected_frame and decoded['timestep_ms'] == 50 and
            decoded['frames_per_second'] == 20 and decoded['speed'] == 1,
            'canonical frame/timing differs')
    inputs = {slot: encode_player_input(identity) for slot, identity in enumerate(identities)}
    seen = set()
    for body in get_repeated_bytes(raw, 6):
        identity = get_bytes(body, 1, required=True)
        require(identity in identities, 'canonical player differs from frozen bootstrap')
        slot = identities.index(identity)
        require(slot not in seen, 'duplicate canonical player')
        seen.add(slot)
        inputs[slot] = body
    return inputs


def bind_frames(bootstrap, journal, public_frames, bot_inputs):
    """Join exact original AI prepared bytes -> canonical journal -> raw public64."""
    from client_patch.prediction_worker.commands import CanonicalRoster
    identities = CanonicalRoster.from_game_data(bootstrap).identities
    require(1 <= len(journal) <= MAX_FRAMES and len(journal) == len(public_frames) == len(bot_inputs),
            'closed canonical/public/bot capture counts differ')
    frames, ai_frames = [], []
    for frame, (raw, delivered, bot) in enumerate(zip(journal, public_frames, bot_inputs)):
        inputs = canonical_inputs(raw, identities, frame)
        require(get_bytes(bot, 1, required=True) == identities[1], 'prepared bot identity differs')
        require(inputs[1] == bot, 'canonical input changed exact prepared native bot bytes')
        require(delivered == public.frame(frame, inputs), 'raw public64 differs from canonical body association')
        actions = {slot: get_repeated_bytes(body, 2) for slot, body in inputs.items()}
        for slot in (0, 1):
            joins = [action for action in actions[slot] if parse_fields(action)[0].number == 3]
            require(len(joins) == int(frame == 0) and (frame != 0 or actions[slot][0] == joins[0]),
                    'both original JoinArmy actions must occur once at frame0')
            if joins:
                require(get_uint(parse_fields(joins[0])[0].value, 1) == slot, 'canonical JoinArmy seat differs')
        if frame > 0 and actions[1]:
            require(all(len(parse_fields(action)) == 1 and parse_fields(action)[0].number in (1, 5)
                        for action in actions[1]), 'native AI action case differs')
            ai_frames.append(frame)
        frames.append(dict(frame=frame, human_actions=len(actions[0]), bot_actions=len(actions[1]),
                           input_sha256=digest(raw), wire_sha256=digest(delivered)))
    require(ai_frames, 'native AI produced no non-Join canonical action')
    return frames, ai_frames


def ai_correction_evidence(frames, ai_frames, worker_rows, authority, canonical_states, *, match):
    rows = owned.validate_worker_states(worker_rows)
    require(len({row['world'] for row in rows}) == 1, 'one actual client worker world required')
    require([row['frame'] for row in rows] == list(range(len(frames))) and
            set(canonical_states) == set(range(len(frames))) and all(
                row['parsed_state_sha256'] == canonical_states[row['frame']] for row in rows),
            'full closed client/server parsed native states differ')
    require(len(authority) == len(frames) and [row['frame'] for row in authority] == list(range(len(frames))) and
            all(row['world'] == rows[0]['world'] and row['match'] == match and
                row['wire_sha256'] == frames[row['frame']]['wire_sha256']
                for row in authority), 'native65 public64 receipts incomplete or mismatched')
    groups = defaultdict(list)
    for row in rows:
        groups[row['confirmed_frontier']].append(row)
    for frontier, group in groups.items():
        if not (sum(row['corrections_delta'] for row in group) > 0 and
                sum(row['replayed_frames_delta'] for row in group) > 0):
            continue
        candidates = [frame for frame in ai_frames if group[0]['frame'] <= frame <= frontier]
        if not candidates or any(frames[row['frame']]['human_actions'] for row in group):
            continue
        frame = candidates[0]
        if frontier + 20 >= len(frames) or group[-1]['tick_ms'] < authority[frame]['tick_ms']:
            continue
        return dict(bot_action_frame=frame, confirmed_frontier=frontier,
                    correction_delta=sum(row['corrections_delta'] for row in group),
                    replayed_frames_delta=sum(row['replayed_frames_delta'] for row in group),
                    continuation_frames=20, continuation_last_frame=frontier + 20,
                    matched_full_states=len(rows), world=rows[0]['world'],
                    attribution='canonical promotion contains actual AI actions and no human actions')
    raise AssertionError('actual AI-only canonical correction/replay plus20 continuations missing')


def startup_evidence(events, match):
    selected = [row for row in events if row.get('match') == match]
    one = lambda event: [row for row in selected if row['event'] == event]
    waiting, ready, released = one('command_startup_waiting'), one('command_startup_ready'), one('command_startup_released')
    require(len(waiting) == len(ready) == len(released) == 1 and ready[0]['slot'] == 0 and
            ready[0]['all_ready'] is True and released[0]['ready_slots'] == [0],
            'public solo requires one real human presentation READY, no fabricated bot readiness')
    require(waiting[0]['frame'] == 0 and ready[0]['frame'] == 0 and released[0]['frame'] == 1 and
            waiting[0]['ready_slots'] == [0] and
            selected.index(waiting[0]) < selected.index(ready[0]) < selected.index(released[0]),
            'public solo startup ordering differs')
    entered = [row for row in events if row['event'] == 'public_queue_entered']
    offered = one('public_match_offered')
    require(len(entered) == len(offered) == 1 and entered[0]['mode'] == offered[0]['mode'] == 1 and
            entered[0]['command_scheduling'] is offered[0]['command_scheduling'] is True and
            offered[0]['fallback'] is True and offered[0]['humans'] == [entered[0]['profile']] and
            0 <= entered[0]['wait_ms'] <= 30000 and offered[0]['monotonic'] - entered[0]['monotonic'] >=
            entered[0]['wait_ms'] / 1000 - .050, 'negotiated solo cohort/original fallback deadline differs')
    return dict(real_human_ready_slots=[0], bot_ready_messages=0)


def lifecycle_evidence(log, *, match, profile):
    base = owned.native_evidence(log, matches=[match], slot=0, profile=profile, natural=False)
    require('Public fallback accepted:' not in log and 'owner=local-practice' not in log and
            'Public client failure:' not in log and 'Prediction selection admission failed:' not in log,
            'public AI failed or silently fell back locally')
    markers = ['Public native match joined:', 'Movement terminal drain complete:',
               'DEDICATED REMATCH SMOKE automated original MatchResultVM.OnContinue;',
               'PUBLIC QUEUE completed return:', 'NATIVE QUIT owned gate released:',
               'NATIVE QUIT owned menu verified: profile=' + profile]
    offsets = [log.find(marker) for marker in markers]
    require(all(offset >= 0 for offset in offsets) and offsets == sorted(offsets),
            'public result/Continue/menu Quit lifecycle incomplete')
    closed = re.findall(r'Native worker closed: pid=(\d+) exit=(\d+) natural=(\d+) reaped=(\d+) '
                        r'ioJoined=(\d+) abandoned=(\d+) requests=(\d+) responses=(\d+)', log)
    require(len(closed) == 1, 'one natural client worker shutdown receipt required')
    pid, code, normal, reaped, joined, abandoned, requests, responses = map(int, closed[0])
    require(pid == base['worker_pid'] and code == abandoned == 0 and normal == reaped == joined == 1 and
            requests == responses and requests > 0, 'client worker shutdown incomplete or forced')
    quits = re.findall(r'\[(\d+)\] NATIVE QUIT original confirmation dispatch: thread=(\d+) '
                       r'worldIdle=1 assetLoadingCount=0 naturalExitDeadlineSeconds=60', log)
    require(len(quits) == 1, 'one original menu Quit callback required')
    return dict(base, quit_tick=int(quits[0][0]), quit_thread=int(quits[0][1]), natural_worker_shutdown=True)


def human_move_evidence(rows, *, authority_rows, bridge_frames, **context):
    """Reuse the qualified original Move gate with actual accepted65/public64."""
    proof = owned.evaluate_feel(rows, bridge_frames=bridge_frames, **context)
    require(proof.get('passed') is True, 'original public human Move feel/phase evidence failed')
    selected = [row for row in rows if row['event'] == 'authority_received' and row['match'] == context['match']]
    require(len(selected) == 1, 'human Move requires one actual FEEL65 receipt')
    feel = selected[0]
    native = [row for row in authority_rows if row['match'] == feel['match'] and
              row['world'] == feel['world'] and row['frame'] == feel['frame']]
    wire = [row for row in bridge_frames if row['match'] == feel['match'] and row['frame'] == feel['frame']]
    require(len(native) == len(wire) == 1 and native[0]['wire_sha256'] == wire[0]['payload_sha256'] and
            wire[0]['received_tick_ms'] <= native[0]['tick_ms'] <= feel['tick_ms'],
            'human Move raw public64/generic accepted65/FEEL65 binding differs')
    proof['accepted65'] = native[0]
    proof['scope'] = ('One original Move440 after original Build300; actual immutable67/72/canonical phase, '
                      'Unity Transform before raw public64 and accepted65; full native+20; no physical UI claim')
    return proof


async def run_prepared(output):
    require(os.name == 'nt', 'actual Unity qualification requires Windows')
    plan, inputs = verify_prepared(output)
    from client_patch.transport import launcher
    from server import admission, command_scheduling, protocol as p, simulation_worker as ipc, tls_transport as tls
    from server.ai_rules import RuleBook, SUPPORTED_AI_SHA256
    from server.bot_catalog import BotCatalog
    from server.cosmetics import CosmeticCatalog
    from server.credentials import AuthenticationError
    from server.dedicated_server import Audit, DedicatedServer
    from server.game_data import GameTemplate
    from server.profiles import ProfileStore
    from server.worker_ai import AISetup, BotRoster
    from server.worker_client import SimulationWorker
    from tests.test_tls_transport import generate_test_pki, remove_test_pki
    from tools.stream_shaper import StreamShaper
    from tools.verify_high_latency_clients import state_digest
    from tools.verify_original_command_scheduling import cleanup_step, read_journal

    output, game, assets = Path(plan['output']), Path(plan['game']), Path(inputs['assets'])
    run = output / 'run'
    run.mkdir(exist_ok=False)
    (run / 'worker-data').mkdir()
    report = dict(passed=False, scope=plan['scope'], human_movement_exercised=False, full_feature_accepted=False,
                  visual_correction=plan.get('visual_correction',False),
                  invocation_sha256=sha(output / 'invocation.json'), forced_cleanup=False,
                  source_sha256_at_start=owned.source_hashes(), pid_evidence_refusals=[])
    events, workers, states = [], [], {}
    process = job = writer = child = bridge_task = shaper = server = audit = pki = None
    packets = PublicPackets()
    submitted = SubmittedBatches(run / 'submitted-batches' if plan.get('human_move') else None)
    streams = {}
    tick = C.WinDLL('kernel32').GetTickCount64
    tick.restype = C.c_uint64
    started = time.monotonic()
    identity, token = 'p_' + secrets.token_hex(16), 'ba1_' + secrets.token_urlsafe(32)

    class Store:
        def authenticate(self, received):
            if secrets.compare_digest(received, token):
                return identity
            raise AuthenticationError()

    def observe(event, **fields):
        row = dict(event=event, probe_tick_ms=int(tick()), monotonic=time.monotonic(), **fields)
        if event == 'frame_queued':
            require(fields['frame'] < MAX_FRAMES and fields['frame'] not in states,
                    'canonical frame duplicate/budget exceeded')
            state = server.rooms[fields['room']].sim.last_state
            states[fields['frame']] = state_digest(state)
            row['parsed_state_sha256'] = states[fields['frame']]
            streams['states'].write(json.dumps(dict(frame=fields['frame'], sha256=states[fields['frame']],
                                                    state=state), allow_nan=False).encode() + b'\n')
            streams['states'].flush()
        events.append(row)
        require(len(events) <= 30000, 'authority event budget exceeded')
        audit(event, **{key: value for key, value in row.items() if key != 'event'})

    async def factory(data, bots):
        require(not workers and set(bots) == {1}, 'exactly one original AI authority worker required')
        setup, roster = AISetup(assets, bots), BotRoster(data, bots)
        folder = run / 'authority'
        folder.mkdir()
        (folder / 'bootstrap.pb').write_bytes(data)
        boot = "import runpy,sys;sys.path.insert(0,sys.argv.pop(1));runpy.run_module('server.simulation_worker',run_name='__main__')"
        argv = [inputs['files']['python']['path'], '-I', '-S', '-B', '-u', '-c', boot, str(ROOT), '--stdio']
        env = os.environ.copy()
        env.pop('BA_ENABLE_SYNTHETIC_WORKER_TESTS', None)
        proc, lease = owned.spawn_owned(argv, cwd=folder, env=env, stdin=subprocess.PIPE,
                                       stdout=subprocess.PIPE, stderr=subprocess.PIPE, bufsize=0, close_fds=True)
        row = dict(process=proc, job=lease, worker=None)
        workers.append(row)
        worker = SimulationWorker(proc, request_timeout=10, close_timeout=5, test_backend=False)
        row['worker'] = worker
        worker._job = owned.WorkerJobLease(lease, worker)
        async with worker._lock:
            reply, payload = await worker._exchange(ipc.CREATE, -1,
                dict(dll_path=str(assets / 'Simulation.dll'), ai=setup.wire()), data, timeout=45)
            info = reply.get('ai')
            require(not payload and reply.get('pid') == proc.pid and reply.get('game_data_sha256') == digest(data) and
                    reply.get('dll_sha256') == owned.SUPPORTED_SIM_SHA256 and reply.get('synthetic_test_backend') is False and
                    type(info) is dict and info.get('bots') == setup.wire()['bots'] and
                    info.get('dll_sha256') == SUPPORTED_AI_SHA256 and
                    info.get('manifest_sha256') == sha(assets / 'ai-rules.json'), 'actual native AI CREATE provenance differs')
            worker.ai_info, worker._bot_roster = info, roster
            worker.game_data_sha256, worker.dll_sha256 = digest(data), reply['dll_sha256']
        write(folder / 'create.json', reply)
        original_bot, original_frame = worker.bot_inputs, worker.process_frame
        async def capture_bot(frame):
            actual = await original_bot(frame)
            require(set(actual) == {1}, 'actual native AI roster changed')
            raw = actual[1]
            streams['bot'].write(struct.pack('<I', len(raw)) + raw)
            streams['bot'].flush()
            return actual
        async def full_frame(actions, dt_ms=None):
            return await owned.full_authority_frame(worker, original_frame, actions, dt_ms)
        worker.bot_inputs, worker.process_frame = capture_bot, full_frame
        return worker

    try:
        for name, path in (('public', 'public64.bin'), ('bot', 'bot-inputs.bin'), ('states', 'canonical-states.jsonl')):
            streams[name] = (run / path).open('xb')
        pki = generate_test_pki(run / 'ephemeral-pki')
        audit = Audit(run)
        template = GameTemplate.load(assets / 'map-1v1.pb.gz', catalog_path=assets / 'unit-catalog.json',
                                     descriptors_path=assets / 'descriptors')
        cosmetics = CosmeticCatalog(assets)
        server = DedicatedServer(template, ProfileStore(run / 'profiles', template, catalog=cosmetics),
            templates={1: template}, bot_catalog=BotCatalog(assets, template=template, rules=RuleBook(assets)),
            ai_factory=factory, data_dir=run, audit=observe, audit_state=False, input_timeout=30,
            experimental_command_scheduling=True, tls_context=tls.load_server_context(pki['cert'], pki['key']),
            admission=admission.AdmissionController(Store()))
        if plan.get('human_move'):
            original_handle = server.community.handle
            async def witnessed_handle(peer, kind, payload):
                room, slot = peer.room, peer.slot
                active = room is not None and room.server is server and room.state not in ('completed', 'closed')
                result = await original_handle(peer, kind, payload)
                if kind == command_scheduling.BATCH and active:
                    match, sequence, body = command_scheduling.decode_batch(payload)
                    require(room.command_scheduling and room.public_match == match and slot == 0,
                            'submitted72 belongs to a foreign/non-public human owner')
                    submitted.record(match, slot, sequence, body, int(tick()))
                return result
            server.community.handle = witnessed_handle
        port = (await server.start('127.0.0.1', 0))[1]
        shaper = StreamShaper(port, rtt_ms=plan['rtt_ms'], seed=791)
        delayed = await shaper.start()
        context = tls.load_client_context(pki['ca'], 'localhost')
        async def resolve():
            return bridge.Remote('127.0.0.1', delayed, context, identity, token)
        parent, child = socket.socketpair(socket.AF_INET)
        parent.setblocking(False)
        try:
            reader, writer = await asyncio.open_connection(sock=parent)
        except BaseException:
            parent.close()
            raise
        config = dict(game_directory=game, server_host='127.0.0.1', server_port=delayed,
                      display_name='Prediction Server AI', room='community', fullscreen=False,
                      local_profile=plan['profile'], solo_ai_host='server')
        options = argparse.Namespace(run_name='prediction-server-ai', unified_experimental=True,
                                     player_features=True, original_command_scheduling_experimental=True)
        argv = launcher.game_arguments(config, None, child.fileno(), options)
        argv[argv.index('-logFile') + 1] = str(run / 'game-0.log')
        argv += command_extra(plan, inputs, run)
        info = subprocess.STARTUPINFO()
        info.dwFlags |= subprocess.STARTF_USESHOWWINDOW
        info.wShowWindow = 0
        info.lpAttributeList = {'handle_list': [child.fileno()]}
        launch_tick = int(tick())
        child.set_inheritable(True)
        try:
            process, job = owned.spawn_fresh_owned(argv, cwd=game, startupinfo=info, close_fds=True,
                runtime=game / 'investigation/runtime', refusals=report['pid_evidence_refusals'], client_index=0)
        finally:
            child.set_inheritable(False)
            child.close()
            child = None
        native = game / 'investigation/runtime' / f'dedicated-native-{process.pid}.log'
        write(run / 'client-process.json', dict(pid=process.pid, launch_tick=launch_tick, argv=argv,
                                               assigned_before_resume=True, retained_handle_used=True))
        bridge_task = asyncio.create_task(ObservedPublicBridge(reader, writer, resolve, version=2,
            packets=packets, raw_stream=streams['public'], tick=lambda: int(tick())).run())
        quit_released = False
        while True:
            owned.check_owned_unity_log(run, 0)
            log = owned.read_fresh_native_log(native)
            require(not any(marker in log for marker in ('Public client failure:', 'Offline loop stopped in ',
                'Movement prediction stopped;', 'Native worker request failed:', 'Native worker startup refused:',
                'Prediction selection admission failed:', 'Prediction visual correction failed:',
                'Native Quit probe failed:')), 'original public AI client failed')
            require(not any(row['event'] in ('protocol_error', 'match_aborted', 'public_match_setup_error') for row in events),
                    'original public AI authority failed')
            if not quit_released and 'PUBLIC QUEUE completed return:' in log and not server.rooms and not server.retired:
                require(not server.community.public.entries and not server.community.public.offers,
                        'public seat/ticket remained after native return')
                owned.publish_gate(game, plan['profile'], 'native-quit.ready')
                quit_released = True
            if process.poll() is not None:
                require(quit_released and process.poll() == 0, 'owned client exited before genuine Quit or nonzero')
                break
            require(not bridge_task.done(), 'private bridge stopped before native lifecycle')
            require(time.monotonic() - started < plan['timeout'], 'bounded public server AI deadline reached')
            await asyncio.sleep(.15)
        report.update(lifecycle_observed=True, game_pid=process.pid, launch_tick=launch_tick)
    except BaseException as error:
        report['error'] = f'{type(error).__name__}: {error}'
        report['traceback'] = traceback.format_exc()
    finally:
        errors = []
        if server:
            await cleanup_step(errors, 'close owned authority', server.close)
        for row in workers:
            proc, lease, worker = row['process'], row['job'], row['worker']
            if worker:
                await cleanup_step(errors, 'close authority worker', worker.close)
            elif proc.poll() is None:
                await cleanup_step(errors, 'stop incomplete authority', lease.terminate_owned)
            await cleanup_step(errors, 'reap authority', lambda proc=proc: asyncio.to_thread(proc.wait, timeout=10))
            await cleanup_step(errors, 'drain authority Job', lambda lease=lease: owned.close_owned_job(lease))
            receipt = dict(pid=proc.pid, exit_code=proc.poll(), reaped=proc.poll() is not None,
                assigned_before_resume=True, forced=lease.forced, job=lease.final_accounting,
                retained_handle_closed=False, failure=worker.failure if worker else 'incomplete startup')
            report.setdefault('authority_cleanup', []).append(receipt)
            def close_authority_handle(proc=proc, receipt=receipt):
                proc._handle.Close()
                receipt['retained_handle_closed'] = True
            await cleanup_step(errors, 'close authority retained handle', close_authority_handle)
        if process:
            if process.poll() is None:
                await cleanup_step(errors, 'stop failed retained game Job', job.terminate_owned)
            await cleanup_step(errors, 'reap game', lambda: asyncio.to_thread(process.wait, timeout=10))
            await cleanup_step(errors, 'drain game Job', lambda: owned.close_owned_job(job))
            closed = False
            try:
                process._handle.Close()
                closed = True
            except Exception as error:
                errors.append(dict(step='close game retained handle', error=str(error)))
            report['game_cleanup'] = dict(pid=process.pid, exit_code=process.poll(), reaped=process.poll() is not None,
                assigned_before_resume=True, forced=job.forced, job=job.final_accounting, retained_handle_closed=closed)
            path = game / 'investigation/runtime' / f'dedicated-native-{process.pid}.log'
            if path.exists():
                await cleanup_step(errors, 'retain whole native log', lambda: (run / 'native.log').write_bytes(read(path)))
            for path in (game / 'investigation/runtime').glob(f'*{process.pid}*.tsv'):
                await cleanup_step(errors, 'retain native timing/receipts', lambda path=path: shutil.copyfile(path, run / path.name))
            path = game / '.battleaces-resurrection/profiles' / plan['profile'] / 'quit-trace.jsonl'
            if path.exists():
                await cleanup_step(errors, 'retain original Quit trace', lambda: (run / 'quit-trace.jsonl').write_bytes(read(path)))
        if writer:
            writer.close()
            async def close_bridge():
                try:
                    await asyncio.wait_for(writer.wait_closed(), 5)
                except Exception as error:
                    if not owned.normal_peer_eof(error, natural=bool(report.get('lifecycle_observed')),
                                                  exited_zero=bool(process and process.poll() == 0)):
                        raise
                    report['normal_bridge_eof'] = repr(error)
            await cleanup_step(errors, 'close private bridge', close_bridge)
        if bridge_task:
            if not bridge_task.done():
                bridge_task.cancel()
            result = await asyncio.gather(bridge_task, return_exceptions=True)
            for value in result:
                if isinstance(value, BaseException) and not isinstance(value, asyncio.CancelledError):
                    if not owned.normal_peer_eof(value, natural=bool(report.get('lifecycle_observed')),
                                                  exited_zero=bool(process and process.poll() == 0)):
                        errors.append(dict(step='bridge task', error=str(value)))
        if shaper:
            await cleanup_step(errors, 'close private shaper', shaper.close)
        if child:
            child.close()
        for name, stream in streams.items():
            await cleanup_step(errors, 'close ' + name + ' capture', stream.close)
        if audit:
            await cleanup_step(errors, 'close authority audit', audit.close)
        if pki:
            await cleanup_step(errors, 'remove ephemeral PKI', lambda: remove_test_pki(run / 'ephemeral-pki'))
        report['cleanup_errors'] = errors
        report['forced_cleanup'] = bool((job and job.forced) or any(row['job'].forced for row in workers))
        await cleanup_step(errors, 'retain authority events', lambda: write(run / 'events.json', events))
        await cleanup_step(errors, 'retain bridge frame hashes', lambda: write(run / 'bridge-frames.json', packets.frames))
        if plan.get('human_move'):
            await cleanup_step(errors, 'retain submitted72 index', lambda: write(run / 'submitted-batches.json', submitted.rows))
        try:
            report['source_unchanged'] = owned.source_hashes() == inputs['source_sha256']
            report['files_unchanged'] = all(sha(row['path']) == row['sha256'] for row in
                [*inputs['files'].values(), *inputs['asset_files'].values(), *plan['extra_asset_files'].values()])
            require(report.get('lifecycle_observed') and not errors and not report['forced_cleanup'] and
                    report['source_unchanged'] and report['files_unchanged'], 'natural lifecycle/cleanup/frozen inputs gate failed')
            created = [row for row in events if row['event'] == 'match_created']
            require(len(created) == 1 and len(workers) == 1 and len(packets.assignments) == 1,
                    'one real public AI match/worker/assignment required')
            match = created[0]['match']
            require(next(iter(packets.assignments.values()))['match'] == match and
                    all(row['match'] == match for row in packets.frames), 'public assignment/frame match changed')
            startup = startup_evidence(events, match)
            journal = records(run / 'matches' / match / 'frames.bin')
            bootstrap = read(run / 'authority/bootstrap.pb')
            frames, ai_frames = bind_frames(bootstrap, journal,
                                            records(run / 'public64.bin'), records(run / 'bot-inputs.bin'))
            require(len(frames) >= 320, 'canonical public AI prefix too short for original build/continuations')
            log = read(run / 'native.log').decode('utf-8')
            builds = re.findall(r'LAN NORMAL BUILD smoke frame300 slot0 [^\r\n]*ability(\d+) '
                                r'[^\r\n]*prerequisite=1 queued=1 commandQueueDelta=1', log)
            require(len(builds) == 1,
                    'existing original normal build did not queue successfully')
            from client_patch.prediction_worker.commands import CanonicalRoster
            identities = CanonicalRoster.from_game_data(bootstrap).identities
            built = []
            for frame, raw in enumerate(journal):
                human = canonical_inputs(raw, identities, frame)[0]
                for action in get_repeated_bytes(human, 2):
                    value = parse_fields(action)[0]
                    if value.number == 1 and any(get_uint(group, 2) == int(builds[0])
                            for group in get_repeated_bytes(value.value, 1)):
                        built.append(frame)
            require(len(built) == 1 and 300 <= built[0] <= 320, 'original normal build lacks one canonical action')
            over = [row for row in events if row['event'] == 'native_game_over' and row.get('match') == match]
            queued = [row['frame'] for row in events if row['event'] == 'frame_queued' and row.get('match') == match]
            require(len(over) == 1 and over[0]['result']['complete'] is True and
                    queued == list(range(len(frames))) and len(frames) >= over[0]['result']['game_over_frame'] + 20,
                    'native result/closed20-frame completion tail missing')
            native_rows = owned.authority_rows(log)
            receipts = owned.read_native_receipts(run / f'dedicated-receipts-{process.pid}-{match}.tsv', pid=process.pid, match=match)
            require(len(receipts) == len(frames) and [row['frame'] for row in receipts] == list(range(len(frames))) and
                    all(row['sha256'] == frames[row['frame']]['wire_sha256'] for row in receipts),
                    'closed original native authority receipts differ')
            rows = owned.read_worker_states(run / 'worker-data/canonical-state.jsonl')
            correction = ai_correction_evidence(frames, ai_frames, rows, native_rows, states, match=match)
            if plan.get('human_move'):
                require(submitted.bodies, 'actual submitted72 bodies unavailable; canonical reconstruction forbidden')
                report['human_move'] = human_move_evidence(owned.feel_rows(log), match=match, slot=0,
                    commits=events, raw_bodies=submitted.bodies, journal=read_journal(run, match, len(frames)),
                    canonical_states=states, worker_states=rows, bridge_frames=packets.frames,
                    authority_rows=native_rows, catalog_units=template.catalog,
                    entity_abilities=template.entity_abilities, built_units=owned.normal_build_units(log, 0))
                report['human_movement_exercised'] = True
            transport = lifecycle_evidence(log, match=match, profile=plan['profile'])
            owned.quit_trace_evidence(read(run / 'quit-trace.jsonl', 64 * 1024), pid=process.pid,
                                      launch_tick=report['launch_tick'], transport=transport)
            require(all(row['exit_code'] == 0 and row['reaped'] and row['retained_handle_closed'] and
                        not row['failure'] and row['job']['active'] == 0 and
                        row['job']['terminated'] == 0 for row in report['authority_cleanup']) and
                    report['game_cleanup']['reaped'] and report['game_cleanup']['retained_handle_closed'] and
                    report['game_cleanup']['job']['active'] == report['game_cleanup']['job']['terminated'] == 0,
                    'retained jobs did not exit naturally and empty')
            report.update(passed=True, match=match, startup=startup, correction=correction,
                          canonical_frames=len(frames), non_join_ai_frames=len(ai_frames), transport=transport,
                          original_build_canonical_frame=built[0])
        except BaseException as error:
            report.setdefault('error', f'{type(error).__name__}: {error}')
            report.setdefault('evidence_traceback', traceback.format_exc())
        report['elapsed_seconds'] = time.monotonic() - started
        try:
            paths = [path for path in run.rglob('*') if path.is_file()]
            require(len(paths) <= 8192 and all(path.resolve().is_relative_to(run.resolve()) for path in paths),
                    'closed evidence inventory exceeds owned bound')
            report['closed_capture_sha256'] = {path.relative_to(run).as_posix(): sha(path) for path in sorted(paths)}
        except BaseException as error:
            report['passed'] = False
            report.setdefault('error', f'closed capture inventory: {error!r}')
        write(run / 'verification.json', report)
    return report


def parser():
    value = argparse.ArgumentParser(description=__doc__)
    value.add_argument('--run-prepared', type=Path)
    value.add_argument('--game', type=Path)
    value.add_argument('--output', type=Path)
    value.add_argument('--assets', type=Path)
    value.add_argument('--python', type=Path)
    value.add_argument('--heap-helper', type=Path)
    value.add_argument('--cooperative', type=Path)
    value.add_argument('--helper-build-receipt', type=Path)
    value.add_argument('--worker-package', type=Path)
    value.add_argument('--expected-helper-sha256')
    value.add_argument('--expected-gameassembly-sha256')
    value.add_argument('--rtt-ms', type=float)
    value.add_argument('--surrender-frame', type=int)
    value.add_argument('--timeout', type=float)
    value.add_argument('--human-move', action='store_true', help='explicit original Move440/8m response scope')
    value.add_argument('--visual-correction',action='store_true',help='human Move scope with the private human render correction flag')
    return value


def main(argv=None):
    cli = parser()
    args = cli.parse_args(argv)
    if args.run_prepared:
        require(not args.human_move, 'run-prepared cannot replace frozen human Move scope')
        require(not args.visual_correction,'run-prepared cannot replace frozen visual correction scope')
        require(not any(getattr(args, name) is not None for name in
                ('game', 'output', 'assets', 'python', 'heap_helper', 'cooperative', 'helper_build_receipt',
                 'worker_package', 'expected_helper_sha256', 'expected_gameassembly_sha256',
                 'rtt_ms', 'surrender_frame', 'timeout')),
                'run-prepared cannot replace frozen inputs')
        report = asyncio.run(run_prepared(args.run_prepared))
        print(json.dumps({key: report.get(key) for key in ('passed', 'scope', 'error', 'canonical_frames')}))
        return 0 if report['passed'] else 1
    for name in ('output', 'assets', 'python', 'heap_helper', 'cooperative', 'helper_build_receipt',
                 'expected_helper_sha256', 'expected_gameassembly_sha256'):
        if getattr(args, name) is None:
            cli.error('--' + name.replace('_', '-') + ' is required for preparation')
    args.game = args.game or ROOT / 'local/prediction-runtime/game'
    args.rtt_ms = 475 if args.rtt_ms is None else args.rtt_ms
    args.surrender_frame = 600 if args.surrender_frame is None else args.surrender_frame
    args.timeout = 210 if args.timeout is None else args.timeout
    plan = prepare(args)
    print(json.dumps(dict(prepared=True, native_executed=False, output=plan['output'], scope=plan['scope'])))
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
