"""Prepare-only by default: owned Unity/Custom movement integration evidence.

An explicit coordinated --run-prepared starts only a local TLS authority and two
fresh suspended, retained-handle Job-owned clients. The reserved manual game and
production server are never used. Default startup scope is two 200-frame Custom
prefixes, normal Concede/result/Continue/Leave and original menu Quit. The
optional movement scope joins actual MOVEMENT FEEL command/Unity observations
with the closed worker's native state journal; pacing alone cannot substitute.
"""
from __future__ import annotations

import argparse
import ast
import asyncio
from collections import defaultdict
import csv
import ctypes as C
from dataclasses import replace
import hashlib
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
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from client_patch.prediction_worker.native import helper_receipt
from server.protocol import SIM_SHA as SUPPORTED_SIM_SHA256
from tools.verify_prediction_client_worker import (
    CREATE_SUSPENDED, RetainedJob, SHIPPING_EXPORTS, quit_trace_evidence)

MAX_LOG = 64 * 1024 * 1024
HEX64 = re.compile(r'[0-9a-f]{64}')
COMPLETE = 'COMMUNITY MATCH SMOKE passed: two native Start/result/Continue cycles;'
FEEL_PREFIX = 'MOVEMENT FEEL '
FEEL_CONTRACT = {
    'schema': 1, 'line_prefix': FEEL_PREFIX,
    'common': ['schema', 'event', 'match', 'world', 'entity', 'unit_type', 'incarnation', 'move_id', 'tick_ms'],
    'events': {
        'command_created': ['original_callback', 'ability', 'target', 'action_sha256'],
        'batch_registered': ['sequence', 'speculative_frame', 'body_sha256', 'action_sha256'],
        'transform': ['source', 'position'],
        'authority_received': ['frame', 'action_sha256'],
    },
    'transform_source': 'UnityEngine.Transform.get_position',
    'worker_state_file': 'worker-data-{client}/canonical-state.jsonl',
    'worker_state_event': 'confirmed_native_state',
    'worker_actor_join': 'verifier decoration only; worker records contain no actor IDs',
    'state_scope': 'actual original Spectator31 include_entities=True parsed fields except raw_sha256; no hidden-state claim',
    'required_continuation_frames': 20,
    'implementation_status': 'requires real client events plus actual native worker state records',
}


def require(value, message):
    if not value:
        raise AssertionError(message)


def digest(data):
    return hashlib.sha256(data).hexdigest()


def sha(path):
    with Path(path).open('rb') as stream:
        return hashlib.file_digest(stream, 'sha256').hexdigest()


def read(path, maximum=MAX_LOG):
    path = Path(path)
    require(path.stat().st_size <= maximum, 'evidence exceeds bound: ' + path.name)
    return path.read_bytes()


def read_fresh_native_log(path):
    """Whole fresh PID log; retain early worker route/bindings before menu entry."""
    path=Path(path)
    if not path.exists():return ''
    raw=read(path)
    # Live writes may end inside UTF8. Only completed lines are evidence;
    # unlike current_native_log, never trim at the later initial-state marker.
    return raw[:raw.rfind(b'\n')+1].decode('utf-8')


def normal_peer_eof(error, *, natural, exited_zero):
    return bool(natural and exited_zero and isinstance(error,ConnectionResetError) and
                getattr(error,'winerror',None) in (64,10054))


def recorded_peer_eof(row):
    return (type(row) is dict and row.get('step')=='close private bridge' and
            re.fullmatch(r'ConnectionResetError: \[WinError (64|10054)\] [^\r\n]+',row.get('error','')) is not None)


def write(path, value):
    with Path(path).open('x', encoding='utf-8') as stream:
        json.dump(value, stream, indent=2, allow_nan=False)
        stream.write('\n')


def source_hashes():
    # Includes imported verifier helpers and the complete local Python/native
    # source closure, without scanning game assets or private runtime output.
    paths = []
    for directory in ('client_patch', 'server', 'tools', 'tests'):
        paths.extend(p for p in (ROOT / directory).rglob('*') if p.is_file() and
                     p.suffix in ('.py', '.cpp', '.h', '.hpp', '.ps1'))
    require(1 <= len(paths) <= 8192, 'source inventory count differs')
    return {p.relative_to(ROOT).as_posix(): sha(p) for p in sorted(paths)}


def owned_paths(game, output):
    game, output = Path(game).resolve(), Path(output).resolve()
    expected = (ROOT / 'local/prediction-runtime/game').resolve()
    require(game == expected and game.is_relative_to((ROOT / 'local').resolve()),
            'only the independent local/prediction-runtime/game copy is permitted')
    for reserved in (ROOT / 'local/pw/game', ROOT / 'local/worker-manual-20261109'):
        require(not game.is_relative_to(reserved.resolve()), 'reserved manual game is forbidden')
    require(output.is_relative_to((ROOT / 'local').resolve()) and output != ROOT / 'local' and
            not output.is_relative_to(game) and not game.is_relative_to(output),
            'fresh ignored output must be separate from the owned game')
    require(not os.path.lexists(output), 'output already exists; preserve prior evidence')
    return game, output


def asset_files(directory):
    """Pin exactly the assets this two-human authority consumes, not all bundles."""
    directory = Path(directory).resolve(strict=True)
    manifest_path = directory / 'asset-manifest.json'
    manifest = json.loads(read(manifest_path, 4 * 1024 * 1024))
    require(manifest.get('schema') == 1 and manifest.get('game_build') == 37822 and
            manifest.get('simulation_sha256') == SUPPORTED_SIM_SHA256,
            'unsupported authority asset manifest')
    names = {'Simulation.dll', 'map-1v1.pb.gz', 'unit-catalog.json', 'cosmetic-catalog.json'}
    descriptors = list((directory / 'descriptors').glob('*.proto.json'))
    require(1 <= len(descriptors) <= 64, 'bounded original descriptor set required')
    names.update(p.relative_to(directory).as_posix() for p in descriptors)
    result = {'asset-manifest.json': dict(path=str(manifest_path), sha256=sha(manifest_path))}
    for name in sorted(names):
        path = (directory / name).resolve(strict=True)
        require(path.is_relative_to(directory) and HEX64.fullmatch(manifest['files'].get(name, '')),
                'consumed asset lacks safe declared identity')
        actual = sha(path)
        require(actual == manifest['files'][name], 'consumed authority asset differs: ' + name)
        result[name] = dict(path=str(path), sha256=actual)
    require(result['Simulation.dll']['sha256'] == SUPPORTED_SIM_SHA256,
            'authority must use the exact unmodified original Simulation.dll')
    return result


def prepare(args):
    from client_patch.patcher import prediction_actor_repair, prediction_worker
    game, output = owned_paths(args.game, args.output)
    require(Path(args.module_root).resolve() == ROOT, 'this exact module root is required')
    for value in (args.expected_helper_sha256, args.expected_gameassembly_sha256):
        require(isinstance(value, str) and HEX64.fullmatch(value), 'explicit lowercase SHA256 pins required')
    changing_rtt = bool(getattr(args, 'changing_rtt', False))
    transition_orders = bool(getattr(args, 'transition_orders', False))
    position_trace = getattr(args, 'native_position_trace', None)
    if position_trace is not None:
        from client_patch.prediction_worker.observation import parse_position_trace_spec
        position_spec = parse_position_trace_spec(position_trace)
        require(changing_rtt and transition_orders and position_spec.army == args.move_slot,
                'native position trace requires subject-owned changing RTT and transition orders')
    require(not transition_orders or changing_rtt, 'transition orders require explicit changing RTT')
    require(args.scenario in ('startup', 'movement', 'mobile'), 'unknown prepared scenario')
    frames = args.frames if args.frames is not None else (650 if changing_rtt or args.scenario == 'mobile' else 200 if args.scenario == 'startup' else 600)
    actor_correction = bool(getattr(args, 'actor_correction', False))
    mobile_correction = bool(getattr(args, 'mobile_correction', False))
    mobile_group_intent = bool(getattr(args, 'mobile_group_intent', False))
    mobile_group_user_edits = bool(getattr(args, 'mobile_group_user_edits', False))
    mobile_recovery_stall = bool(getattr(args, 'mobile_recovery_stall', False))
    mobile_recall = bool(getattr(args, 'mobile_recall', False))
    require(not mobile_group_intent or (args.scenario == 'mobile' and mobile_correction),
            'mobile group intent requires explicit mobile scenario/correction')
    require(not mobile_group_user_edits or mobile_group_intent,
            'mobile group user edits require explicit group intent')
    require(not mobile_recovery_stall or (args.scenario == 'mobile' and mobile_correction and
            mobile_group_intent and mobile_group_user_edits), 'mobile recovery stall requires explicit mobile group user edits')
    require(not mobile_recall or (args.scenario == 'mobile' and mobile_correction and mobile_group_intent and
            not mobile_group_user_edits and not mobile_recovery_stall),
            'mobile recall requires explicit mobile group intent without user edits/recovery stall')
    require(not (actor_correction and mobile_correction), 'HQ and mobile fixtures are mutually exclusive')
    require(not changing_rtt or (not actor_correction and not mobile_correction and args.scenario == 'movement' and args.lifecycle == 'natural' and
            args.move_slot == 0 and list(args.rtt_ms) == [130,475] and frames == 650),
            'changing RTT requires ordinary natural movement, slot0,130/475ms,650frames and no actor fixture')
    require(not actor_correction or (args.scenario == 'movement' and args.lifecycle == 'natural'),
            'actor correction fixture requires natural movement scenario')
    require(not mobile_correction or (args.scenario in ('movement', 'mobile') and args.lifecycle == 'natural' and args.move_slot == 0 and
                                     list(args.rtt_ms) == [130,475]),
            'mobile correction requires natural movement with slot0 and130/475ms RTT')
    require(args.scenario != 'mobile' or (mobile_correction and not actor_correction and not changing_rtt and
            not transition_orders and position_trace is None and args.lifecycle == 'natural' and frames == 650 and
            args.move_slot == 0 and list(args.rtt_ms) == [130,475]),
            'mobile scenario requires explicit mobile correction, natural650, slot0,130/475ms RTT and no other fixture')
    require((120 <= frames <= 200 if args.scenario == 'startup' else 500 <= frames <= 650),
            'startup requires120..200 frames; movement requires500..650')
    if position_trace is not None:
        require(position_spec.last_frame <= frames, 'native position trace exceeds prepared frame bound')
    require(60 <= args.timeout <= 240 and len(args.rtt_ms) == 2 and all(
        type(x) in (int, float) and math.isfinite(x) and 0 <= x <= 500 for x in args.rtt_ms),
        'bounded timeout and two finite RTTs0..500ms required')
    files = {name: dict(path=str(path.resolve(strict=True)), sha256=sha(path)) for name, path in {
        'game_exe': game / 'Battle Aces.exe', 'helper': game / 'BattleAcesOffline.dll',
        'gameassembly': game / 'GameAssembly.dll', 'python': Path(args.python),
        'patch_manifest': game / '.battleaces-resurrection/patch-manifest.json',
    }.items()}
    require(files['helper']['sha256'] == args.expected_helper_sha256 and
            files['gameassembly']['sha256'] == args.expected_gameassembly_sha256,
            'installed helper/GameAssembly differs from explicit pins')
    helper = read(files['helper']['path'])
    if position_trace is not None:
        require('-prediction-movement-observe-position='.encode('utf-16-le') in helper,
                'helper lacks selected native position option')
    if mobile_correction:
        require('-prediction-mobile-correction-smoke'.encode('utf-16-le') in helper,
                'helper lacks the explicit mobile correction fixture')
    for enabled,flag in ((mobile_group_intent,'-prediction-mobile-group-intent-smoke'),
                         (mobile_group_user_edits,'-prediction-mobile-group-user-edits-smoke'),
                         (mobile_recovery_stall,'-prediction-mobile-recovery-stall-smoke'),
                         (mobile_recall,'-prediction-mobile-recall-smoke')):
        require(not enabled or flag.encode('utf-16-le') in helper, 'helper lacks explicit ' + flag)
    required_hooks = prediction_worker.CALL_HOOKS + prediction_actor_repair.CALL_HOOKS
    require(all(marker in helper for marker in (
        b'BA_RESURRECTION_MOVEMENT_PIPELINE_V1', b'BA_RESURRECTION_NATIVE_WORKER_PROXY_V1',
        b'BA_RESURRECTION_ORIGINAL_COMMAND_SCHEDULING_V1')) and all(
            h['name'].encode('ascii') + b'\0' in helper for h in required_hooks),
            'helper lacks the explicit movement/actor/selection exports')
    manifest = json.loads(read(files['patch_manifest']['path'], 4 * 1024 * 1024))
    require(manifest.get('helper_sha256') == files['helper']['sha256'] and
            manifest.get('patched_sha256') == files['gameassembly']['sha256'],
            'owned patch manifest differs from installed pins')
    for hook in required_hooks:
        require(hook in manifest.get('call_hooks', []), 'owned manifest lacks movement hook: ' + hook['name'])
    plugins = list((game / 'Battle Aces_Data/Plugins').rglob('Simulation.dll'))
    require(len(plugins) == 1 and sha(plugins[0]) == SUPPORTED_SIM_SHA256,
            'one exact original client Simulation image is required')
    files['client_simulation'] = dict(path=str(plugins[0].resolve()), sha256=sha(plugins[0]))
    for key in ('heap_helper', 'cooperative'):
        path, receipt = helper_receipt(getattr(args, key), arena=key == 'heap_helper')
        files[key] = dict(path=str(path), sha256=sha(path))
        files[key + '_receipt'] = dict(path=str(path.with_name('build.json')), sha256=sha(path.with_name('build.json')))
    require(args.helper_build_receipt is not None, 'main helper source-bound build receipt is required')
    path = Path(args.helper_build_receipt).resolve(strict=True)
    receipt = json.loads(read(path, 256 * 1024))
    native_sources = [ROOT / 'client_patch/build.ps1'] + [p for directory in ('src', 'checkpoint')
        for p in (ROOT / 'client_patch' / directory).rglob('*')
        if p.is_file() and p.suffix in ('.cpp', '.h', '.hpp')]
    expected_build_sources = {p.relative_to(ROOT).as_posix(): sha(p) for p in native_sources}
    require(receipt.get('schema') == 1 and receipt.get('helper_sha256') == files['helper']['sha256'] and
            receipt.get('sources_unchanged_during_build') is True and
            receipt.get('source_sha256') == expected_build_sources,
            'main helper build receipt differs from installed helper/current native sources')
    files['helper_build_receipt'] = dict(path=str(path), sha256=sha(path))
    worker_module_root = ROOT
    worker_package = getattr(args, 'worker_package', None)
    if worker_package is not None:
        worker_package = Path(worker_package).resolve(strict=True)
        require(worker_package.is_relative_to((ROOT / 'local').resolve()),
                'packaged worker qualification requires an owned ignored package')
        from tools.package_integrity import verify, ordinary_file
        inventory = verify(worker_package, 'client')
        profile = json.loads(read(worker_package / 'program/prediction/prediction-profile.json'))
        require(profile.get('schema') == 1 and
                profile.get('profile') == 'private-custom-movement-prediction-v1',
                'explicit private prediction profile required')
        for key, relative in {
            'helper': 'program/client-helper/BattleAcesOffline.dll',
            'python': 'program/runtime/python.exe',
            'heap_helper': 'program/prediction/heap/BAHeap.dll',
            'cooperative': 'program/prediction/cooperative/PredictionCooperative.dll',
        }.items():
            packaged = ordinary_file(worker_package, relative)
            require(files[key]['sha256'] == sha(packaged), 'prepared input differs from worker package: ' + key)
            if key != 'helper':
                require(Path(files[key]['path']) == packaged,
                        'packaged worker must use its exact bundled path: ' + key)
        for index, relative in enumerate(sorted((*inventory['files'], 'package-manifest.json'))):
            packaged = ordinary_file(worker_package, relative)
            files['worker_package_' + str(index)] = dict(path=str(packaged), sha256=sha(packaged))
        worker_module_root = worker_package / 'program/app'
    assets = asset_files(args.assets)
    sources = source_hashes()
    prefix = 'nativestest_pm_' + secrets.token_hex(5)
    profiles = [prefix + '_' + str(index) for index in range(2)]
    require(all(not (game / '.battleaces-resurrection/profiles' / p).exists() for p in profiles),
            'fresh owned profile names required')
    invocation = dict(schema=1, native_executed=False, scope=__doc__, game=str(game),
        output=str(output), module_root=str(ROOT), assets=str(Path(args.assets).resolve()),
        worker_module_root=str(worker_module_root), worker_package=str(worker_package) if worker_package else None,
        files=files, asset_files=assets, source_sha256=sources, profiles=profiles,
        scenario=args.scenario, lifecycle=args.lifecycle, frames=frames, timeout=args.timeout,
        actor_correction=actor_correction,
        mobile_correction=mobile_correction,
        changing_rtt=changing_rtt,
        transition_orders=transition_orders,
        native_position_trace=position_trace,
        transition_phase_source='decision' if transition_orders else None,
        changing_pose_clock='sampled_us' if changing_rtt else None,
        publication_source='post-original-qpc' if changing_rtt else None,
        actor_fixture=mobile_fixture_metadata() if mobile_correction else actor_fixture_metadata() if actor_correction else None,
        rtt_ms=list(args.rtt_ms), surrender_frame=260 if args.scenario == 'startup' else 700,
        move_slot=args.move_slot, expected_matches=2 if args.lifecycle == 'natural' else 1,
        endpoint_scope='ephemeral loopback TLS only; no production endpoint',
        feel_contract=FEEL_CONTRACT, full_feature_accepted=False)
    if args.scenario == 'mobile':
        invocation.update(generic_movement_not_exercised=True,
            mobile_scope='Explicit original mobile release/reinit/freshMove; generic newborn440/460 feel is not exercised; group intent remains a separate open claim')
        if mobile_group_intent:invocation['mobile_group_intent']=True
        if mobile_group_user_edits:invocation['mobile_group_user_edits']=True
        if mobile_recovery_stall:invocation['mobile_recovery_stall']=True
        if mobile_recall:invocation['mobile_recall']=True
        validate_mobile_plan(invocation)
    output.mkdir(parents=True, exist_ok=False)
    for name in sources:
        target = output / 'source-at-prepare' / name
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(ROOT / name, target)
    require(source_hashes() == sources, 'source changed during preparation; preserve this incomplete preparation')
    write(output / 'invocation.json', invocation)
    write(output / 'feel-contract.json', FEEL_CONTRACT)
    return invocation


def validate_mobile_plan(plan):
    require(plan.get('scenario') == 'mobile' and plan.get('mobile_correction') is True and
            plan.get('lifecycle') == 'natural' and plan.get('frames') == 650 and plan.get('expected_matches') == 2 and
            plan.get('move_slot') == 0 and plan.get('rtt_ms') == [130,475] and
            plan.get('generic_movement_not_exercised') is True and not plan.get('actor_correction') and
            not plan.get('changing_rtt') and not plan.get('transition_orders') and plan.get('native_position_trace') is None,
            'prepared mobile scenario scope/fixture/650-frame natural contract differs')
    require(all(key not in plan or type(plan[key]) is bool for key in ('mobile_group_intent','mobile_group_user_edits','mobile_recovery_stall','mobile_recall')) and
            (not plan.get('mobile_group_user_edits') or plan.get('mobile_group_intent') is True) and
            (not plan.get('mobile_recovery_stall') or plan.get('mobile_group_user_edits') is True) and
            (not plan.get('mobile_recall') or (plan.get('mobile_group_intent') is True and
             not plan.get('mobile_group_user_edits') and not plan.get('mobile_recovery_stall'))),
            'prepared mobile group edits require typed explicit group intent')


def verify_prepared(output):
    output = Path(output).resolve(strict=True)
    require(output.is_relative_to((ROOT / 'local').resolve()), 'prepared output must be ignored and owned')
    plan = json.loads(read(output / 'invocation.json', 4 * 1024 * 1024))
    require(plan.get('schema') == 1 and plan.get('native_executed') is False and
            Path(plan['output']).resolve() == output and Path(plan['module_root']).resolve() == ROOT,
            'prepared invocation identity differs')
    if plan.get('scenario') == 'mobile':
        validate_mobile_plan(plan)
    require(Path(plan['game']).resolve() == (ROOT / 'local/prediction-runtime/game').resolve(),
            'prepared game is not the independent runtime copy')
    require(source_hashes() == plan['source_sha256'], 'source changed since preparation')
    for name, expected in plan['source_sha256'].items():
        require(sha(output / 'source-at-prepare' / name) == expected, 'retained source snapshot changed')
    for row in list(plan['files'].values()) + list(plan['asset_files'].values()):
        require(sha(row['path']) == row['sha256'], 'prepared binary/asset/receipt changed')
    require(not os.path.lexists(output / 'run'), 'prepared run already started; do not overwrite evidence')
    return plan


def command_extra(plan, index, run):
    role = ('host', 'guest')[index]
    result = [f'-community-match-{role}-smoke', '-lan-smoke', '-dedicated-surrender-smoke',
        '-dedicated-surrender-frame=' + str(plan['surrender_frame']),
        '-prediction-movement-experimental', '-frame-timing',
        '-frame-timing-frames=' + str(plan['frames']), '-lan-audit',
        '-prediction-worker-python=' + plan['files']['python']['path'],
        '-prediction-worker-module-root=' + plan.get('worker_module_root', plan['module_root']),
        '-prediction-worker-heap-helper=' + plan['files']['heap_helper']['path'],
        '-prediction-worker-cooperative=' + plan['files']['cooperative']['path'],
        '-prediction-worker-data-dir=' + str(run / f'worker-data-{index}')]
    if plan['scenario'] == 'movement':
        result += ['-prediction-movement-smoke','-prediction-movement-smoke-slot='+str(index),
            '-prediction-movement-smoke-start-frame='+str(440 if index==plan['move_slot']else 460)]
    if plan.get('actor_correction'):
        result.append('-prediction-actor-correction-smoke')
    if plan.get('mobile_correction'):
        result.append('-prediction-mobile-correction-smoke')
    if plan.get('mobile_group_intent'):
        result.append('-prediction-mobile-group-intent-smoke')
    if plan.get('mobile_group_user_edits'):
        result.append('-prediction-mobile-group-user-edits-smoke')
    if plan.get('mobile_recovery_stall'):
        result.append('-prediction-mobile-recovery-stall-smoke')
    if plan.get('mobile_recall'):
        result.append('-prediction-mobile-recall-smoke')
    if plan.get('changing_rtt') and index == plan['move_slot']:
        result.append('-prediction-movement-smoke-distance=48')
    if plan.get('transition_orders') and index == plan['move_slot']:
        result.append('-prediction-movement-smoke-transition-gates='+str(run/'transition-gates'))
    if plan.get('native_position_trace') is not None and index == plan['move_slot']:
        result.append('-prediction-movement-observe-position='+plan['native_position_trace'])
    if plan.get('publication_source')=='post-original-qpc' or plan.get('mobile_recovery_stall'):
        result.append('-frame-timing-worlds=2')
    if plan['lifecycle'] == 'natural':
        result += ['-native-quit-smoke', '-native-quit-mode=confirm', '-native-quit-gate-smoke',
                   '-community-match-leave-quit-smoke']
    return result


def refresh_round_trips(log):
    """Only actual own request55 -> validated ACK53 pairs, no estimated packets."""
    log = '\n'.join(log.splitlines())
    sends = {}
    pattern = r'^\[(\d+)\] Movement RTT refresh sent: generation=(\d+) request=(\d+) sent_us=(\d+) wire_bytes=9 interval_us=2000000$'
    for values in re.findall(pattern, log, re.M):
        tick, generation, request, sent = map(int, values)
        key = generation, request
        require(key not in sends, 'duplicate own RTT refresh request')
        sends[key] = dict(sent_tick_ms=tick, sent_us=sent)
    rows = []
    pattern = (r'^\[(\d+)\] Movement RTT sample: generation=(\d+) kind=(\d+) request=(\d+) '
        r'sent_us=(\d+) received_us=(\d+) accepted=(\d+) min_us=(\d+) samples=(\d+) '
        r'refresh=(\d+) directory_bytes_seen=(\d+) BA_RESURRECTION_MOVEMENT_PACING_V1$')
    seen = set()
    for values in re.findall(pattern, log, re.M):
        tick, generation, kind, request, sent, received, accepted, estimate, count, refresh, directory = map(int, values)
        if kind != 55 or accepted != 1 or refresh != 1:
            continue
        key = generation, request
        require(key not in seen and key in sends and sends[key]['sent_us'] == sent and
                0 < generation and 0 < request and 0 < received - sent <= 2_000_000 and
                0 < estimate <= 2_000_000 and 1 <= count <= 8 and tick >= sends[key]['sent_tick_ms'],
                'RTT sample lacks unique matching validated own refresh')
        seen.add(key)
        rows.append(dict(generation=generation, request=request, sent_us=sent, received_us=received,
            sent_tick_ms=sends[key]['sent_tick_ms'], received_tick_ms=tick,
            apparent_round_trip_us=received-sent, estimate_us=estimate, directory_bytes_seen=directory))
    require(len(sends) <= 512 and len(rows) <= 512, 'bounded own RTT sample count exceeded')
    return rows


def pose_metric_clock(poses, *, require_sampled_us=False):
    """Use genuine native samples only; never upscale coarse ticks into QPC."""
    supplied = ['sampled_us' in row for row in poses]
    require(not any(supplied) or all(supplied), 'mixed native pose clock coverage')
    require(not require_sampled_us or not poses or all(supplied), 'new changing RTT run requires native QPC sampled_us')
    if poses and all(supplied):
        require(all(type(row['sampled_us']) is int and 0 <= row['sampled_us'] <= 0xffffffffffffffff for row in poses),
                'invalid native QPC pose sample')
        require(all(b['sampled_us'] >= a['sampled_us'] for a,b in zip(poses,poses[1:])), 'native QPC pose clock regressed')
        require(all(b['sampled_us'] != a['sampled_us'] or b['position'] == a['position']
                    for a,b in zip(poses,poses[1:])), 'different poses share one native QPC timestamp')
        return 'sampled_us', 1000, False
    return 'tick_ms', 1, True


def pose_pair(a, b, clock, scale):
    value = dict(interval_ms=(b[clock]-a[clock])/scale,displacement=math.dist(a['position'],b['position']),
                 from_tick_ms=a['tick_ms'],to_tick_ms=b['tick_ms'])
    if clock == 'sampled_us':
        value.update(from_sampled_us=a['sampled_us'],to_sampled_us=b['sampled_us'])
    return value


def changing_poses(rows, match, *, require_sampled_us=False):
    poses = [row for row in rows if row['match'] == match and row['event'] == 'transform']
    require(all(type(row.get(key)) is int and row[key] >= -1 for row in poses
                for key in ('presented_frame','completed_frame')), 'changing RTT needs actual native pose frame counters')
    require(all(row['source'] == FEEL_CONTRACT['transform_source'] and type(row['position']) is list and
                len(row['position']) == 3 and all(type(value) in (int,float) and math.isfinite(value)
                for value in row['position']) for row in poses), 'changing RTT requires finite actual Unity positions')
    require(all(b['tick_ms'] >= a['tick_ms'] and b['presented_frame'] >= a['presented_frame']
                for a,b in zip(poses,poses[1:])), 'changing RTT native pose clock/publication regressed')
    pose_metric_clock(poses,require_sampled_us=require_sampled_us)
    return poses


class ChangingRttFixtureError(AssertionError):
    """Missing diagnostic acquisition/readiness; keep natural lifecycle capture."""


def changing_fixture_require(ok, reason):
    if not ok:
        raise ChangingRttFixtureError(reason)


def transition_rows(log):
    result=[]
    for line in log.splitlines():
        if 'MOVEMENT TURN ' not in line:continue
        raw=line.split('MOVEMENT TURN ',1)[1]
        require(len(raw)<=4096,'transition order diagnostic exceeds bound')
        row=json.loads(raw)
        require(type(row)is dict and row.get('schema')==1 and row.get('event')=='command_created' and
            row.get('ordinal')in (2,3) and row.get('move_id')==row['ordinal'] and
            row.get('originalCtor')is True and row.get('physicalUI')is False and row.get('queueDelta')==1 and
            row.get('original_callback')=='Uncapped.ExecuteTargetGroundCommand..ctor' and row.get('ability')==12,
            'invalid original transition order schema')
        for name in ('world','entity','unit_type','incarnation','tick_ms','sampled_us','motion_from_sampled_us',
                     'enqueue_sampled_us','physical_frame','presented_frame','completed_frame'):
            require(type(row.get(name))is int and 0<=row[name]<=0xffffffffffffffff,'invalid transition identity/clock')
        require(row['world']>0 and row['unit_type']>0 and row['incarnation']>0 and
                re.fullmatch('[a-f0-9]{32}',row.get('match','')) and HEX64.fullmatch(row.get('action_sha256','')) and
                row['motion_from_sampled_us']<row['sampled_us']<=row['enqueue_sampled_us'] and
                max(row['presented_frame'],row['completed_frame'])<650,
                'transition generation/clock/cutoff differs')
        for name in ('origin','target','motion_from'):
            require(type(row.get(name))is list and len(row[name])==3 and all(type(value)in(int,float)and
                math.isfinite(value)for value in row[name]),'invalid transition original vector')
        result.append(row);require(len(result)<=4,'bounded two-world transition order count exceeded')
    require(len({(row['match'],row['world'],row['ordinal'])for row in result})==len(result),'duplicate transition order')
    return result


def phase_rows(log, match, world):
    starts=list(re.finditer(r'Movement pacing START: match=([a-f0-9]{32}) world=(\d+) ',log))
    own=[(index,row)for index,row in enumerate(starts)if row[1]==match and int(row[2])==world]
    require(len(own)<=1,'duplicate current-match pacing START')
    if not own:return []
    index,start=own[0]
    segment=log[start.start():starts[index+1].start()if index+1<len(starts)else len(log)]
    pattern=(r'^\[(\d+)\] Movement pacing waiting: reason=(\d+) next=(\d+) confirmed=(-?\d+) received=(-?\d+) '
        r'networkReceived=(-?\d+) physical=(-?\d+) presented=(-?\d+) targetAssigned=(-?\d+) rtt_us=(\d+)')
    result=[]
    for values in re.findall(pattern,segment,re.M):
        tick,reason,nxt,confirmed,received,network,physical,presented,assigned,rtt=map(int,values)
        result.append(dict(tick_ms=tick,reason=reason,next=nxt,confirmed=confirmed,received=received,
            network_received=network,physical=physical,presented=presented,target_assigned=assigned,
            rtt_us=rtt,next_assignment_delta=assigned-nxt))
    return result


def decision_phase_rows(log, match, world):
    """Actual decide() observations; sparse status logs are not a fallback."""
    result=[];previous={};counts=defaultdict(int)
    fields={'schema','event','match','world','next','target_assigned','presented_frame',
            'rtt_us','allowed','wait','decision_us','sampled_us','tick_ms'}
    for line in log.splitlines():
        if 'MOVEMENT PHASE 'not in line:continue
        raw=line.split('MOVEMENT PHASE ',1)[1]
        require(len(raw)<=2048,'movement phase diagnostic exceeds bound')
        row=json.loads(raw)
        require(type(row)is dict and set(row)==fields and type(row['schema'])is int and
                row['schema']==1 and row['event']=='decision' and type(row['match'])is str and
                re.fullmatch('[a-f0-9]{32}',row['match']) and type(row['allowed'])is bool,
                'invalid actual movement phase schema')
        for name in fields-{'event','match','allowed'}:
            require(type(row[name])is int,'invalid actual movement phase numeric field')
        require(0<row['world']<2**64 and 400<=row['next']<650 and 1<=row['target_assigned']<2**31 and
                -1<=row['presented_frame']<2**31 and 0<=row['rtt_us']<=2_000_000 and
                0<=row['wait']<=6 and row['allowed']==(row['wait']==0) and
                0<=row['decision_us']<=row['sampled_us']<2**64 and
                row['sampled_us']-row['decision_us']<50_000 and 0<=row['tick_ms']<2**64,
                'actual movement phase scope/clock differs')
        key=row['match'],row['world'];prior=previous.get(key)
        require(prior is None or (row['sampled_us']-prior['sampled_us']>=10_000 and
                row['decision_us']>=prior['decision_us'] and row['tick_ms']>=prior['tick_ms']),
                'actual movement phase clock/throttle differs')
        previous[key]=row;counts[key]+=1
        require(len(counts)<=2 and counts[key]<=4096,'actual movement phase world/count bound exceeded')
        if key==(match,world):
            result.append(dict(row,next_assignment_delta=row['target_assigned']-row['next']))
    return result


def observed_phase_rows(log, match, world, source):
    require(source in ('pacer_wait','decision'),'unknown transition phase observation source')
    return decision_phase_rows(log,match,world)if source=='decision'else phase_rows(log,match,world)


def publish_transition_gate(directory, command, ordinal, tick, perf):
    require(ordinal in (2,3) and re.fullmatch('[a-f0-9]{32}',command['match']), 'invalid owned transition gate identity')
    for name,upper in (('world',2**64-1),('entity',2**32-1),('unit_type',2**32-1),('incarnation',2**64-1)):
        require(type(command[name])is int and 0<=command[name]<=upper,'transition gate numeric identity outside bound')
    directory=Path(directory)
    require(directory.is_absolute()and directory.is_dir()and not directory.is_symlink(),'owned transition gate directory unavailable')
    path=directory/f'{command["match"]}-{command["world"]}-turn{ordinal}.ready'
    require(not os.path.lexists(path),'transition gate already published; no overwrite')
    data=('BA_MOVEMENT_TURN_V1 '+command['match']+' '+str(command['world'])+' '+str(command['entity'])+' '+
          str(command['unit_type'])+' '+str(command['incarnation'])+' '+str(ordinal)+'\n').encode('ascii')
    temporary=directory/f'.{path.name}.{secrets.token_hex(4)}.tmp'
    try:
        with temporary.open('xb')as stream:stream.write(data)
        requested_tick,requested_perf=int(tick()),perf()
        os.rename(temporary,path)  # One event-loop owner; Native only reads immutable ready files.
    finally:
        if temporary.exists():temporary.unlink()
    return dict(path=str(path),sha256=digest(data),bytes=len(data),ordinal=ordinal,
                requested_tick_ms=requested_tick,requested_perf_counter_ns=requested_perf,
                published_tick_ms=int(tick()),published_perf_counter_ns=perf())


class ChangingRttController:
    """Diagnostic local relay control; existing client RTT traffic is the witness."""
    def __init__(self, tick, perf=time.perf_counter_ns, *, require_sampled_us=False, transition_gates=None,
                 phase_source='pacer_wait'):
        self.tick, self.perf = tick, perf
        self.require_sampled_us = require_sampled_us
        self.transition_gates = transition_gates
        require(phase_source in ('pacer_wait','decision'),'unknown transition phase observation source')
        self.phase_source = phase_source
        self.worlds = []
        self.last_clock = (-1,-1)

    def now(self):
        tick, perf = int(self.tick()), self.perf()
        require(type(perf) is int and tick >= self.last_clock[0] and perf >= self.last_clock[1],
                'changing RTT controller clock regressed')
        self.last_clock = tick, perf
        return tick, perf

    def begin(self, match, shaper):
        require(re.fullmatch('[a-f0-9]{32}',match) and len(self.worlds) < 2 and
                not any(row['match'] == match for row in self.worlds) and
                (not self.worlds or self.worlds[-1]['stage'] in ('complete','failed')),
                'changing RTT prior match did not finish both real transitions')
        self.now()
        reset = shaper.set_rtt_ms(130,tick=self.tick)
        self.worlds.append(dict(match=match,stage='waiting_for450',reset=reset,high_samples=[],low_samples=[]))

    @staticmethod
    def moving_unfinished(poses, command):
        changing_fixture_require(poses, 'changing RTT lacks actual subject positions')
        latest = poses[-1]
        changing_fixture_require(math.dist(latest['position'],command['target']) > .5,
                'changing RTT target already reached before transition')
        recent = [row for row in poses if latest['tick_ms']-500 <= row['tick_ms'] <= latest['tick_ms']]
        changing_fixture_require(any(math.dist(row['position'],latest['position']) > .05 for row in recent),
                'changing RTT subject is not demonstrably moving before transition')
        return latest

    def update(self, log, shaper):
        if not self.worlds:
            return
        state = self.worlds[-1]
        if state['stage']=='failed' or (state['stage']=='complete'and
            (self.transition_gates is None or 'turn3_gate'in state)):
            return
        try:
            now_tick, now_perf = self.now()
            rows = feel_rows(log)
            commands = [row for row in rows if row['match']==state['match'] and row['event']=='command_created']
            require(len(commands) <= 1, 'changing RTT duplicated subject Move')
            poses = changing_poses(rows,state['match'],require_sampled_us=self.require_sampled_us)
            samples = refresh_round_trips(log)
            if state['stage'] == 'waiting_for450':
                eligible = [row for row in poses if row['presented_frame'] >= 450]
                if not eligible:
                    return
                changing_fixture_require(len(commands)==1, 'changing RTT trigger lacks original subject Move')
                command = commands[0]
                before = [row for row in poses if row['tick_ms'] <= command['tick_ms']]
                changing_fixture_require(before and abs(math.dist(before[-1]['position'],command['target'])-48) <= .05,
                        'changing RTT requires the actual original48-unit Move target')
                latest = self.moving_unfinished(poses,command)
                changing_fixture_require(now_tick-latest['tick_ms'] <= 500, 'changing RTT trigger pose is stale')
                state.update(world=command['world'],command=command,trigger=eligible[0],rise_pose=latest,
                    rise=shaper.set_rtt_ms(475,tick=self.tick),stage='high')
                return
            if state['stage'] == 'high':
                elapsed = now_perf-state['rise']['effective_perf_counter_ns']
                changing_fixture_require(elapsed <= 6_000_000_000, 'changing RTT high estimate did not acquire within6seconds')
                fresh = [row for row in samples if row['sent_tick_ms'] > state['rise']['effective_tick_ms']]
                high = [row for row in fresh if row['apparent_round_trip_us'] >= 430_000]
                require(len({row['generation'] for row in fresh}) <= 1, 'changing RTT connection generation changed mid-match')
                state['high_samples'] = high
                if elapsed < 4_000_000_000 or len(high) < 2 or not fresh or fresh[-1]['estimate_us'] < 430_000:
                    return
                latest = self.moving_unfinished(poses,state['command'])
                changing_fixture_require(now_tick-latest['tick_ms'] <= 500, 'changing RTT fall pose is stale')
                fall = shaper.set_rtt_ms(130,tick=self.tick)
                state.update(fall_pose=latest,high_held_perf_ns=fall['effective_perf_counter_ns']-state['rise']['effective_perf_counter_ns'],
                    high_estimate_us=fresh[-1]['estimate_us'],fall=fall,stage='low')
                if self.transition_gates is not None:
                    state['turn2_gate']=publish_transition_gate(self.transition_gates,state['command'],2,self.tick,self.perf)
                return
            if state['stage'] == 'low':
                elapsed = now_perf-state['fall']['effective_perf_counter_ns']
                changing_fixture_require(elapsed <= 6_000_000_000, 'changing RTT low estimate did not recover within6seconds')
                low = [row for row in samples if row['sent_tick_ms'] > state['fall']['effective_tick_ms'] and
                       row['apparent_round_trip_us'] <= 200_000 and row['estimate_us'] <= 200_000]
                state['low_samples'] = low
                if low:
                    state.update(stage='complete',low_estimate_us=low[-1]['estimate_us'],low_observed_tick_ms=now_tick)
            if state['stage']=='complete'and self.transition_gates is not None and 'turn3_gate'not in state:
                turns=[row for row in transition_rows(log)if row['match']==state['match']and row['ordinal']==2]
                if not turns:return
                require(len(turns)==1,'transition2 original order is not unique')
                low_tick=state['low_samples'][-1]['received_tick_ms']
                observed_phases=observed_phase_rows(log,state['match'],state['world'],self.phase_source)
                phases=[row for row in observed_phases if
                    row['tick_ms']>=low_tick and row['tick_ms']>=state['fall']['effective_tick_ms']and
                    abs(row['next_assignment_delta'])<=1 and
                    row['presented_frame'if self.phase_source=='decision'else 'presented']<650 and
                    (self.phase_source!='decision'or (row['decision_us']>=state['low_samples'][-1]['received_us']and
                     row['decision_us']*1000>=state['fall']['effective_perf_counter_ns']))]
                latest_phase=observed_phases[-1]if observed_phases else None
                pair=next(((a,latest_phase)for a in reversed(phases[:-1])if latest_phase in phases and
                    latest_phase['tick_ms']-a['tick_ms']>=500 and 0<=now_tick-latest_phase['tick_ms']<=500 and
                    (self.phase_source!='decision'or (latest_phase['decision_us']-a['decision_us']>=500_000 and
                     0<=now_perf-latest_phase['sampled_us']*1000<=500_000_000))),None)
                if pair is None:return
                latest=self.moving_unfinished(poses,turns[0])
                changing_fixture_require(max(latest['presented_frame'],latest['completed_frame'])<650 and
                    now_tick-latest['tick_ms']<=500,'transition3 missed actual pose cutoff650')
                state['turn3_phase_rows']=list(pair)
                state['turn3_gate']=publish_transition_gate(self.transition_gates,state['command'],3,self.tick,self.perf)
        except ChangingRttFixtureError as error:
            state.update(stage='failed',error=str(error),failure_scope='fixture acquisition/readiness; natural lifecycle continues')
        except AssertionError as error:
            state.update(stage='failed',error=str(error))
            raise

    def snapshot(self):
        return dict(schema=1,worlds=self.worlds,require_sampled_us=self.require_sampled_us,
            phase_source=self.phase_source,
            transition_orders=self.transition_gates is not None,
            scope='Configured BOTH-direction FUTURE-read delay, not measured RTT; queued chunks keep original due times. '
                  'Own correlated application ACK estimates include directory transfer. No new network requests.')


def publication_segments(trace, matches):
    """Two ordered worlds; real post-original publication events, never TF fallback."""
    require(type(trace)is list and 0<len(trace)<=2_000_000 and len(matches)==2 and len(set(matches))==2,
            'two matched post-original publication traces required')
    starts=[index for index,row in enumerate(trace)if row.get('event')=='arrival'and row.get('frame')==0]
    require(len(starts)==len(matches),'missing/duplicate world frame0 in publication trace')
    require(not any(row.get('event')=='publication'for row in trace[:starts[0]]),
            'publication precedes first matched frame0')
    result={};last_clock=-1
    for match,start,end in zip(matches,starts,starts[1:]+[len(trace)]):
        part=trace[start:end]
        arrivals=[row['frame']for row in part if row.get('event')=='arrival']
        require(arrivals==list(range(len(arrivals))),'noncontiguous authoritative trace arrivals')
        publications=[row for row in part if row.get('event')=='publication']
        require(len(publications)>=650 and [row.get('frame')for row in publications]==list(range(len(publications))),
                'noncontiguous/incomplete post-original publications')
        for row in publications:
            require(all(type(row.get(key))is int for key in ('qpc_us','ms','frame','presented'))and
                    row['frame']==row['presented'] and 0<=row['ms']<2**64 and
                    last_clock<row['qpc_us']<2**64,
                    'post-original publication QPC/identity differs')
            last_clock=row['qpc_us']
        result[match]=publications
    return result


def changing_rtt_evidence(log, control, matches, *, require_sampled_us=False,
                          publication_source=None, publication_trace=None):
    """Preserve transition stalls as RED after collecting natural lifecycle."""
    require([row['match'] for row in control['worlds']] == matches, 'changing RTT controlled match identities differ')
    if any(row['stage']!='complete' for row in control['worlds']):
        return dict(passed=False,worlds=[],missing_gates=[dict(match=row['match'],stage=row['stage'],error=row.get('error'))
            for row in control['worlds'] if row['stage']!='complete'],scope='Transition acquisition/readiness incomplete; no smoothness acceptance')
    require(publication_source in (None,'post-original-qpc'),'unknown publication measurement source')
    require(publication_source is not None or publication_trace is None,'legacy TF gate cannot silently change measurement source')
    producer=publication_segments(publication_trace,matches)if publication_source is not None else None
    require(producer is None or require_sampled_us,'post-original producer gate requires actual QPC poses/setters')
    rows = feel_rows(log)
    worlds = []
    for state in control['worlds']:
        poses = changing_poses(rows,state['match'],require_sampled_us=require_sampled_us)
        clock, scale, approximate = pose_metric_clock(poses,require_sampled_us=require_sampled_us)
        rise, fall = state['rise']['effective_tick_ms'],state['fall']['effective_tick_ms']
        if clock == 'sampled_us':
            require(all(type(state[k].get('effective_perf_counter_ns')) is int and state[k]['effective_perf_counter_ns'] >= 0
                        for k in ('rise','fall')), 'native QPC poses lack actual setter perf clock')
            rise_clock,fall_clock=(state[k]['effective_perf_counter_ns']/1000 for k in ('rise','fall'))
        else:
            rise_clock,fall_clock=rise,fall
        require(poses and poses[0][clock] <= rise_clock and poses[-1][clock] >= fall_clock+2000*scale and
                max(max(row['presented_frame'],row['completed_frame']) for row in poses) >= 649,
                'changing RTT lacks actual poses through both transitions and650 cutoff')
        window = [row for row in poses if row[clock] >= rise_clock-250*scale]
        changes = [row for index,row in enumerate(window) if index==0 or
                   row['presented_frame'] != window[index-1]['presented_frame']]
        publications = [dict(from_tick_ms=a['tick_ms'],to_tick_ms=b['tick_ms'],gap_ms=(b[clock]-a[clock])/scale,
            from_frame=a['presented_frame'],to_frame=b['presented_frame']) for a,b in zip(changes,changes[1:])]
        if clock == 'sampled_us':
            for value,a,b in zip(publications,changes,changes[1:]):
                value.update(from_sampled_us=a['sampled_us'],to_sampled_us=b['sampled_us'])
        require(publications, 'changing RTT lacks observed publication progression')
        stationary = []
        anchor = window[0]
        for row in window[1:]:
            if math.dist(anchor['position'],state['command']['target']) <= .5:
                anchor = row
                continue
            if math.dist(row['position'],anchor['position']) > .025:
                value=dict(from_tick_ms=anchor['tick_ms'],to_tick_ms=row['tick_ms'],gap_ms=(row[clock]-anchor[clock])/scale)
                if clock == 'sampled_us':value.update(from_sampled_us=anchor['sampled_us'],to_sampled_us=row['sampled_us'])
                stationary.append(value)
                anchor = row
        if math.dist(anchor['position'],state['command']['target']) > .5:
            value=dict(from_tick_ms=anchor['tick_ms'],to_tick_ms=window[-1]['tick_ms'],gap_ms=(window[-1][clock]-anchor[clock])/scale)
            if clock == 'sampled_us':value.update(from_sampled_us=anchor['sampled_us'],to_sampled_us=window[-1]['sampled_us'])
            stationary.append(value)
        pairs = [pose_pair(a,b,clock,scale)for a,b in zip(window,window[1:])]
        peak_publication = max(publications,key=lambda row:row['gap_ms'])
        producer_peak=None;producer_window=None
        if producer is not None:
            producer_window=[row for row in producer[state['match']]
                if rise_clock-250_000<=row['qpc_us']<=poses[-1]['sampled_us']]
            require(len(producer_window)>1 and producer_window[0]['qpc_us']<=rise_clock and
                    producer_window[-1]['qpc_us']>=fall_clock+2_000_000 and producer_window[-1]['frame']>=649,
                    'post-original publications do not cover both transition windows')
            producer_gaps=[dict(from_frame=a['frame'],to_frame=b['frame'],from_qpc_us=a['qpc_us'],to_qpc_us=b['qpc_us'],
                gap_ms=(b['qpc_us']-a['qpc_us'])/1000)for a,b in zip(producer_window,producer_window[1:])]
            producer_peak=max(producer_gaps,key=lambda row:row['gap_ms'])
        peak_stationary = max(stationary,key=lambda row:row['gap_ms'],default=dict(gap_ms=0))
        baseline = [row for row in poses if rise_clock-500*scale <= row[clock] <= rise_clock]
        baseline_pairs = [(math.dist(a['position'],b['position']),(b[clock]-a[clock])/scale)
                          for a,b in zip(baseline,baseline[1:]) if b[clock]>a[clock]]
        baseline_speed = max((distance*1000/span for distance,span in baseline_pairs),default=0)
        peak_speed = max((row['displacement']*1000/row['interval_ms']for row in pairs if row['interval_ms']>0),default=0)
        worlds.append(dict(match=state['match'],world=state['world'],passed=max(
            (producer_peak or peak_publication)['gap_ms'],peak_stationary['gap_ms'])<=100,
            pose_clock=clock,pose_timing_approximate=approximate,
            pose_timing_scope='legacy GetTickCount64; coarse approximate intervals, no synthetic microseconds' if approximate else
                'checked native QPC sampled_us; first observation of counter change, not exact publication time',
            maximum_publication_observation_gap=peak_publication,maximum_unfinished_pose_gap=peak_stationary,
            maximum_transform_displacement=max(pairs,key=lambda row:row['displacement']),
            maximum_observed_speed=peak_speed,baseline_maximum_observed_speed=baseline_speed,
            transition_to_baseline_peak_speed_ratio=peak_speed/baseline_speed if baseline_speed>0 else None,
            minimum_publication_observation_gap_ms=min(row['gap_ms']for row in publications),
            transform_sample_interval_ms=dict(minimum=min(row['interval_ms']for row in pairs),maximum=max(row['interval_ms']for row in pairs)),
            first_pose_tick_ms=poses[0]['tick_ms'],last_pose_tick_ms=poses[-1]['tick_ms'],
            maximum_actual_presented_frame=max(row['presented_frame'] for row in poses),
            maximum_actual_completed_frame=max(row['completed_frame'] for row in poses)))
        if producer_peak is not None:
            worlds[-1].update(publication_gate_source=publication_source,maximum_post_original_publication_gap=producer_peak,
                producer_window_publications=len(producer_window),producer_full_prefix_publications=len(producer[state['match']]),
                producer_scope='Actual event=publication QPC after original PresentAvailableSimFrame returned and ac changed; '
                    'pacing bookkeeping precedes this trace sample. Ordered frame0 segments bind the two actual Custom worlds. '
                    'Transform first-observation gaps remain separate measurements, not exact producer timestamps.')
    return dict(passed=all(row['passed'] for row in worlds),worlds=worlds,
        scope=('Actual post-original publication QPC and unfinished Transform holds use unchanged100ms gates; TF first-observation gaps are separately retained. '
               if producer is not None else 'Actual original Unity poses/counters throughout transitions, >100ms gaps are RED. ')+
              'Counter-change first-observation times '
              'are sampled, not synthetic publication timestamps; speed/jumps reported without a universal speed threshold. '
              +('Fresh subject-order causality/phase is evaluated separately from these gap metrics.' if control.get('transition_orders') else
               'No new subject order after transition, so subject transition command latency is unmeasured.'))


def transition_order_binding(log, order, *, slot, raw_bodies, journal, commits):
    """Actual ctor/67/72/journal chain; no generated FEEL receipt rows."""
    from server.game_data import decode_player_input
    from server.protobuf_wire import get_bytes,get_repeated_bytes,get_repeated_uint,get_uint
    match=order['match'];action_hash=order['action_sha256'];bodies=[]
    for (body_match,owner,sequence),body in raw_bodies.items():
        if body_match!=match or owner!=slot:continue
        decoded=decode_player_input(body)
        selected=[action for action in decoded['actions']if digest(action)==action_hash]
        if not selected:continue
        require(len(selected)==1 and decoded['identity']['player_id']==slot+1 and decoded['identity']['is_aliased']and
                not decoded['identity']['ai_profile_id'],'transition immutable72 identity/action differs')
        bodies.append((sequence,body,selected[0],len(decoded['actions'])))
    require(len(bodies)==1,'transition action missing/duplicated in immutable72')
    sequence,body,action,count=bodies[0]
    execute=get_bytes(action,1,required=True);groups=get_repeated_bytes(execute,1)
    require(len(groups)==1 and get_uint(groups[0],1)==order['unit_type']and get_uint(groups[0],2)==12 and
            get_repeated_uint(groups[0],3)==(order['entity'],)and get_uint(execute,2)==0,
            'transition source/ability/queue differs from original constructor')
    position=get_bytes(get_bytes(get_bytes(execute,3,required=True),3,required=True),1,required=True)
    target=[]
    for number in (1,2,3):
        value=get_uint(position,number);require(value<2**64,'transition target uint64 overflow')
        target.append((value-2**64 if value>=2**63 else value)/2**32)
    require(all(abs(a-b)<=.0001 for a,b in zip(target,order['target'])),'transition original ToProto target differs')
    registered=[tuple(map(int,row))for row in re.findall(r'Movement local batch registered: sequence=(\d+) '
        r'speculativeFrame=(\d+) tick=(\d+) match='+re.escape(match)+r'(?:\s|$)',log)if int(row[0])==sequence]
    require(len(registered)==1 and registered[0][2]>=order['tick_ms'],'transition actual67 response missing/duplicated')
    sent=[row for row in re.findall(r'Original command batch submitted: match='+re.escape(match)+
        r' sequence=(\d+) actions=(\d+) bytes=(\d+) body_sha256=([a-f0-9]{64}) sendTick=(\d+) sourceNextFrame=(\d+)',log)
        if int(row[0])==sequence]
    require(len(sent)==1 and int(sent[0][1])==count and int(sent[0][2])==len(body)and sent[0][3]==digest(body)and
            int(sent[0][4])>=registered[0][2],'transition actual native72 sender differs')
    committed=[row for row in commits if row.get('event')=='command_batch_committed'and row.get('match')==match and
               row.get('slot')==slot and row.get('sequence')==sequence]
    require(len(committed)==1,'transition canonical commit missing/duplicated')
    frame=committed[0]['frame']
    occurrences=[(row['frame'],owner)for row in journal for owner,actions in row['players'].items()
                 for value in actions if digest(value)==action_hash]
    require(occurrences==[(frame,slot)],'transition canonical action lost/duplicated/rebound')
    return dict(sequence=sequence,body_sha256=digest(body),action_sha256=action_hash,
        assigned_frame=registered[0][1],canonical_frame=frame,assigned_minus_canonical=registered[0][1]-frame,
        native67_tick_ms=registered[0][2],native72_send_tick_ms=int(sent[0][4]))


def read_native_receipts(path, *, pid, match):
    """Native65 payload accounting has no receipt timestamp column."""
    raw=read(path,2*1024*1024).decode('utf-8')
    require(raw.endswith('\n'),'native65 receipt file is partial')
    reader=csv.DictReader(raw.splitlines(),delimiter='\t')
    require(reader.fieldnames==['pid','match','frame','actions','sim','sha256'],'native65 receipt schema differs')
    result=[]
    for source in reader:
        require(None not in source and source['match']==match and HEX64.fullmatch(source['sha256']),
                'native65 receipt identity/hash differs')
        row={key:int(source[key])for key in ('pid','frame','actions','sim')}
        require(row['pid']==pid and row['frame']==len(result) and 0<=row['actions']<=4096 and
                -1<=row['sim']<=0x7fffffff and len(result)<4096,'native65 receipt sequence/bound differs')
        result.append(dict(row,match=match,sha256=source['sha256']))
    require(result,'native65 receipt file is empty')
    return result


def early_empty_retime_evidence(log, *, match, slot, order, binding, authority, new_direction,
                                commits, raw_bodies, journal, canonical_states, canonical_payloads,
                                bridge_frames, worker_states, native_receipts):
    """A prediction assigned too early can be removed by an earlier EMPTY65.

    AUTH(S) precedes promotion(S) in the frozen worker source. The native TSV
    proves the real65 payload, not its wall time. Never invent that timestamp.
    """
    assigned,canonical=binding['assigned_frame'],binding['canonical_frame']
    require(binding['assigned_minus_canonical']<0 and assigned<canonical,
            'early empty retime requires negative actual command phase')
    rows=validate_worker_states(worker_states)
    promoted=[(index,row)for index,row in enumerate(rows)if row['world']==order['world']and row['frame']==assigned]
    require(len(promoted)==1,'early empty retime assigned native state missing/duplicated')
    frontier=promoted[0][1]['confirmed_frontier']
    group=[(index,row)for index,row in enumerate(rows)if row['world']==order['world']and row['confirmed_frontier']==frontier]
    require(assigned<=frontier<canonical and sum(row['replayed_frames_delta']for _,row in group)>0 and
            sum(row['corrections_delta']for _,row in group)>0,'early empty retime lacks its actual positive replay group')
    frames={row['frame']for _,row in group}
    require(all(row['parsed_state_sha256']==canonical_states.get(row['frame'])for _,row in group),
            'early empty retime native group differs from authority')
    inputs=[row for row in journal if row['frame']in frames]
    require(len(inputs)==len(frames) and {row['frame']for row in inputs}==frames and
            all(not actions for row in inputs for actions in row['players'].values()),
            'early empty retime group contains other canonical actions or missing inputs')
    receipts=[row for row in native_receipts if row['match']==match and row['frame']==assigned]
    bridge=[row for row in bridge_frames if row['match']==match and row['frame']==assigned]
    require(len(receipts)==len(bridge)==1 and receipts[0]['actions']==0 and receipts[0]['sim']>=assigned and
            receipts[0]['sha256']==bridge[0]['payload_sha256']==canonical_payloads.get(assigned),
            'early empty retime actual empty65/raw bridge/server hash differs')
    require(new_direction['tick_ms']<bridge[0]['received_tick_ms'] and
            all(bridge[0]['received_tick_ms']<=row['tick_ms']<authority['tick_ms']for _,row in group),
            'early empty retime motion/replay timing differs')
    # Only THIS local prediction may be outstanding while the empty group is
    # confirmed. Remote commands in that canonical group are forbidden above.
    pending=[];at=max(row['tick_ms']for _,row in group)
    registrations=re.findall(r'Movement local batch registered: sequence=(\d+) speculativeFrame=(\d+) '
                             r'tick=(\d+) match='+re.escape(match)+r'(?:\s|$)',log)
    require(len({int(row[0])for row in registrations})==len(registrations),'early empty retime duplicate local sequence')
    for sequence,_,tick in map(lambda values:tuple(map(int,values)),registrations):
        if tick>at:continue
        committed=[row for row in commits if row.get('event')=='command_batch_committed'and row.get('match')==match and
                   row.get('slot')==slot and row.get('sequence')==sequence]
        require(len(committed)==1 and (match,slot,sequence)in raw_bodies,
                'early empty retime pending local batch lacks exact canonical disposition')
        if committed[0]['frame']>frontier:pending.append(sequence)
    require(pending==[binding['sequence']],'early empty retime has another pending local prediction')
    from server.game_data import decode_player_input
    predicted=decode_player_input(raw_bodies[match,slot,binding['sequence']])['actions']
    require(len(predicted)==1 and digest(predicted[0])==binding['action_sha256'],
            'early empty retime pending batch contains another predicted action')
    final=joined_worker_evidence(rows,world=order['world'],authority=authority,canonical_states=canonical_states)
    require(any(rows[index]['frame']==canonical for index in final['promotion_group_row_indices'])and
            all(rows[index]['parsed_state_sha256']==canonical_states.get(rows[index]['frame'])
                for index in final['promotion_group_row_indices']),
            'early empty retime final canonical confirmation is unrelated')
    final['correction_required']=True
    witness=dict(kind='early_empty_retime',assigned_frame=assigned,canonical_frame=canonical,
        native65=receipts[0],native65_tick_ms=None,raw_bridge=bridge[0],
        promotion_group_row_indices=[index for index,_ in group],
        promotion_group_replayed_delta=sum(row['replayed_frames_delta']for _,row in group),
        promotion_group_corrections_delta=sum(row['corrections_delta']for _,row in group),
        pending_local_sequences=pending,
        ordering_scope='Source-ordered actual AUTH(S) before contiguous confirmed promotion(S); native TSV has no timestamp. '
                       'Actual positive replay group follows raw bridge(S) and precedes final command65(C).',
        source_contract=['client_patch/prediction_worker/prediction.py:_confirm_matches',
                         'client_patch/prediction_worker/native.py:_promote_identities'])
    return final,witness


def transition_order_evidence(log, control, *, match, slot, commits, raw_bodies, journal, canonical_states,
                              canonical_payloads, bridge_frames, worker_states, native_receipts=None):
    """New direction caused by each NEW local order, before both real receipts."""
    states=[row for row in control['worlds']if row['match']==match]
    require(len(states)==1,'transition controller match missing/duplicated')
    state=states[0];command=state['command']
    orders=[row for row in transition_rows(log)if row['match']==match]
    require([row['ordinal']for row in orders]==[2,3],'two fresh original transition orders required')
    require(len({row['action_sha256']for row in [command,*orders]})==3,'transition command hashes were replayed')
    poses=changing_poses(feel_rows(log),match,require_sampled_us=True)
    identity=lambda row:tuple(row[key]for key in ('world','entity','unit_type','incarnation'))
    require(all(identity(row)==identity(command)for row in [*orders,*poses]),'transition actor/incarnation changed')
    phases=state.get('turn3_phase_rows',[])
    actual_phases=observed_phase_rows(log,match,command['world'],control.get('phase_source','pacer_wait'))
    low_tick=state['low_samples'][-1]['received_tick_ms']
    require(len(phases)==2 and all(row in actual_phases and row['tick_ms']>=low_tick and
            row['tick_ms']>=state['fall']['effective_tick_ms']and abs(row['target_assigned']-row['next'])<=1 for row in phases)and
            phases[1]['tick_ms']-phases[0]['tick_ms']>=500,'transition3 lacks actual recovered phase observations')
    if control.get('phase_source')=='decision':
        require(all(row['decision_us']>=state['low_samples'][-1]['received_us'] and
                    row['decision_us']*1000>=state['fall']['effective_perf_counter_ns']for row in phases)and
                phases[1]['decision_us']-phases[0]['decision_us']>=500_000,
                'transition3 decision pair precedes actual low ACK or lacks real spacing')
    result=[]
    for order in orders:
        ordinal=order['ordinal'];gate=state.get(f'turn{ordinal}_gate')
        require(gate is not None and gate['requested_tick_ms']<=order['tick_ms']and
                gate['requested_perf_counter_ns']/1000<=order['enqueue_sampled_us'], 'transition order precedes its actual owned gate')
        path=Path(gate['path']);raw=read(path,256)
        expected=('BA_MOVEMENT_TURN_V1 '+match+' '+str(command['world'])+' '+str(command['entity'])+' '+
                  str(command['unit_type'])+' '+str(command['incarnation'])+' '+str(ordinal)+'\n').encode('ascii')
        require(raw==expected and digest(raw)==gate['sha256'],'transition immutable gate identity differs')
        if ordinal==2:
            require(gate['requested_perf_counter_ns']>=state['fall']['effective_perf_counter_ns'], 'turn2 precedes actual fall setter')
        else:
            require(gate['requested_tick_ms']>=phases[-1]['tick_ms']and
                    gate['requested_tick_ms']-phases[-1]['tick_ms']<=500,'turn3 precedes/stales recovered phase gate')
            if control.get('phase_source')=='decision':
                require(0<=gate['requested_perf_counter_ns']-phases[-1]['sampled_us']*1000<=500_000_000,
                        'turn3 actual decision is stale or follows its marker')
        origin=[row for row in poses if row['sampled_us']==order['sampled_us']and row['position']==order['origin']]
        prior=[row for row in poses if row['sampled_us']==order['motion_from_sampled_us']and row['position']==order['motion_from']]
        require(origin and prior and 100_000<=order['sampled_us']-order['motion_from_sampled_us']<=500_000,
                'turn reversal vectors lack actual QPC pose observations')
        motion=[b-a for a,b in zip(order['motion_from'],order['origin'])]
        direction=[b-a for a,b in zip(order['origin'],order['target'])]
        distance=math.dist(order['origin'],order['target']);motion_size=math.sqrt(sum(value*value for value in motion))
        require(abs(distance-(48 if ordinal==2 else 32))<=.05 and motion_size>.05 and
                sum(a*b for a,b in zip(motion,direction))/(motion_size*distance)<-.99,
                'new transition target does not reverse actual prior motion')
        binding=transition_order_binding(log,order,slot=slot,raw_bodies=raw_bodies,journal=journal,commits=commits)
        frame=binding['canonical_frame']
        authority=[row for row in authority_rows(log)if row['match']==match and row['world']==order['world']and row['frame']==frame]
        bridge=[row for row in bridge_frames if row['match']==match and row['frame']==frame]
        require(len(authority)==len(bridge)==1 and authority[0]['wire_sha256']==bridge[0]['payload_sha256']==canonical_payloads.get(frame)and
                bridge[0]['received_tick_ms']<=authority[0]['tick_ms'],'transition actual65/raw bridge wire binding differs')
        before=min(authority[0]['tick_ms'],bridge[0]['received_tick_ms'])
        turned=[]
        for a,b in zip(poses,poses[1:]):
            if a['sampled_us']<order['enqueue_sampled_us']or b['tick_ms']>=before:continue
            delta=[y-x for x,y in zip(a['position'],b['position'])]
            size=math.sqrt(sum(value*value for value in delta))
            if size>.025 and sum(x*y for x,y in zip(delta,direction))>size*distance*.5:
                turned.append((a,b))
        require(turned,'no actual NEW-direction motion before BOTH transition authority receipts')
        a,b=turned[0]
        early=None
        try:
            joined=joined_worker_evidence(worker_states,world=order['world'],authority=authority[0],canonical_states=canonical_states,
                                          require_replay=binding['assigned_minus_canonical']!=0)
            group=[worker_states[index]for index in joined['promotion_group_row_indices']]
            require(any(row['frame']==frame for row in group),'transition state/replay group does not include its own canonical command')
        except AssertionError:
            if binding['assigned_minus_canonical']>=0 or native_receipts is None:raise
            joined,early=early_empty_retime_evidence(log,match=match,slot=slot,order=order,binding=binding,
                authority=authority[0],new_direction=b,commits=commits,raw_bodies=raw_bodies,journal=journal,
                canonical_states=canonical_states,canonical_payloads=canonical_payloads,bridge_frames=bridge_frames,
                worker_states=worker_states,native_receipts=native_receipts)
        result.append(dict(ordinal=ordinal,original_order=order,**binding,**joined,
            new_direction_from_pose=a,new_direction_to_pose=b,
            enqueue_to_new_direction_ms=(b['sampled_us']-order['enqueue_sampled_us'])/1000,
            before_native65_ms=authority[0]['tick_ms']-b['tick_ms'],before_raw_bridge_ms=bridge[0]['received_tick_ms']-b['tick_ms'],
            native65=authority[0],raw_bridge=bridge[0],gate=gate,
            early_empty_retime=early,
            phase_gate_passed=ordinal==2 or abs(binding['assigned_minus_canonical'])<=1))
    require(result[0]['sequence']<result[1]['sequence'],'transition original command FIFO differs')
    return dict(passed=all(row['phase_gate_passed']for row in result),match=match,orders=result,recovered_phase_rows=phases,
        scope='Actual new original Move2/3 direction reversal before both receipts; true immutable67/72/commit and native continuation. '
              'Transient order2 phase reported without normalization; recovered order3 phase±1 required. No physical UI claim.')


def finalize_movement_observation(report, collect_independent):
    """Retain independent diagnostics before applying the unchanged primary gate."""
    collect_independent()
    require(report['feel']['passed'], 'actual movement feel contract remains missing')
    report['scoped_observation_passed'] = True


def mobile_closed_state_evidence(*, matches, states, worker_state_rows, client_logs, frames):
    """Bind every closed native row to its real BEGIN world and full authority.

    Checking only the650-frame presentation prefix or a correction's20-frame
    tail cannot substitute for this mobile-only all-row comparison.
    """
    require(type(matches) is list and len(matches) == 2 and len(set(matches)) == 2 and
            all(type(match) is str and re.fullmatch('[a-f0-9]{32}', match) for match in matches) and
            set(states) == set(matches) and set(worker_state_rows) == set(client_logs) == {0,1} and frames == 650,
            'mobile needs both closed clients and two exact authority matches')
    result=[];count=0
    for slot in (0,1):
        ready=re.findall(r'Movement prediction ready: generation=(\d+) match=([a-f0-9]{32}) world=(\d+) slot=(\d+) ',client_logs[slot])
        require([r[1]for r in ready] == matches and all(int(r[3]) == slot for r in ready) and
                len({r[2]for r in ready}) == 2 and all(0 < int(r[2]) < 2**64 for r in ready),
                'mobile closed-state BEGIN/match/world/slot binding differs')
        rows=validate_worker_states(worker_state_rows[slot])
        require(list(dict.fromkeys(r['world']for r in rows)) == [int(r[2])for r in ready],
                'mobile closed-state worlds differ from actual BEGIN')
        for (_,match,world,_),expected_match in zip(ready,matches):
            require(match == expected_match, 'mobile authority match order differs')
            canonical=states[match]
            require(len(canonical) >= frames and sorted(canonical) == list(range(len(canonical))),
                    'mobile complete authority prefix is missing/noncontiguous')
            own=[(index,row)for index,row in enumerate(rows)if row['world'] == int(world)]
            require([row['frame']for _,row in own] == list(range(len(canonical))) and all(
                    row['parsed_state_sha256'] == canonical[row['frame']] for _,row in own),
                    'mobile closed native state hashes differ from full authority')
            result.append(dict(slot=slot,match=match,world=int(world),frames_checked=len(own),
                first_frame=0,last_frame=len(canonical)-1,worker_row_indices=[index for index,_ in own]))
            count+=len(own)
    return dict(passed=True,checked_frames=count,clients=result,
        scope='Every actual closed Spectator31 parsed-state row in both clients/both BEGIN worlds equals the complete original authority timeline')


def finalize_mobile_observation(report, plan, *, states, worker_state_rows, client_logs):
    """New mobile-only scope; no synthetic generic newborn feel acceptance."""
    report['mobile_input_witness_passed']=False
    report['scoped_observation_passed']=False
    require(plan['scenario'] == 'mobile' and plan.get('mobile_correction') is True and
            plan['lifecycle'] == 'natural' and plan['frames'] == 650 and plan['expected_matches'] == 2 and
            not report.get('error'), 'mobile scenario is incomplete or already failed')
    matches=report.get('matches',[])
    require(len(matches) == 2 and all(row.get('canonical_frames') == 650 and
            row.get('exact_bridge_and_native_authority_receipts') is True for row in matches),
            'mobile exact650-frame bridge/native65 prefixes missing')
    created=[row['match']for row in matches]
    require(len(report.get('clients',[])) == 2 and {row['index']for row in report['clients']} == {0,1} and
            all(row.get('natural_worker_shutdown') is True and row.get('matches') == created for row in report['clients']),
            'mobile actual clients lack natural worker/native BEGIN evidence')
    mobile=report.get('mobile_correction',{})
    episodes=mobile.get('episodes',[])
    require(mobile.get('passed') is True and len(episodes) == 2 and
            [row.get('match')for row in episodes] == created and all(row.get('passed') is True for row in episodes),
            'both actual mobile input/lifecycle episodes are required')
    parity=mobile_closed_state_evidence(matches=created,states=states,worker_state_rows=worker_state_rows,
                                      client_logs=client_logs,frames=plan['frames'])
    victim={row['match']:row['world']for row in parity['clients']if row['slot'] == 1}
    require(all(row.get('world') == victim[row['match']]for row in episodes), 'mobile episode does not belong to victim BEGIN world')
    if plan.get('mobile_group_intent'):
        groups=report.get('mobile_group_intent',{})
        require(report.get('mobile_group_intent',{}).get('passed') is True and
                report.get('group_intent_witness_passed') is True and
                groups.get('user_edits') is bool(plan.get('mobile_group_user_edits')) and
                len(groups.get('episodes',[])) == 2 and [row.get('match')for row in groups['episodes']] == created and
                all(row.get('passed') is True and row.get('world') == victim[row['match']]for row in groups['episodes']),
                'explicit mobile group intent witness missing/failed')
    if plan.get('mobile_recovery_stall'):
        require(plan.get('mobile_group_user_edits') is True and report.get('recovery_stall_witness_passed') is True and
                report.get('mobile_recovery_stall',{}).get('passed') is True and
                report['mobile_recovery_stall'].get('match') == created[1] and
                report['mobile_recovery_stall'].get('world') == victim[created[1]],
                'explicit mobile recovery stall witness missing/failed')
    if plan.get('mobile_recall'):
        recall=report.get('mobile_recall',{})
        require(plan.get('mobile_group_intent') is True and not plan.get('mobile_group_user_edits') and
                not plan.get('mobile_recovery_stall') and report.get('recall_witness_passed') is True and
                recall.get('passed') is True and len(recall.get('episodes',[])) == 2 and
                [row.get('match')for row in recall['episodes']] == created and
                all(row.get('passed') is True and row.get('world') == victim[row['match']]for row in recall['episodes']),
                'explicit mobile recall witness missing/failed')
    report.update(mobile_state_parity=parity,mobile_input_witness_passed=True,scoped_observation_passed=True,
        generic_movement_not_exercised=True,movement_feel_witness_passed=False,full_mobile_controls_accepted=False,
        mobile_scope='Both original mobile release/reinit/freshMove episodes plus full closed native parity; generic newborn440/460 movement not exercised, group intent remains separately open')


def mobile_final_gate(plan, report):
    """Additional mobile-only final gate; the ordinary final expression remains."""
    return bool(plan.get('scenario') == 'mobile' and plan.get('expected_matches') == 2 and
        report.get('scoped_observation_passed') is True and report.get('mobile_input_witness_passed') is True and
        report.get('mobile_correction',{}).get('passed') is True and
        report.get('mobile_state_parity',{}).get('passed') is True and
        report.get('generic_movement_not_exercised') is True and report.get('movement_feel_witness_passed') is False and
        report.get('full_mobile_controls_accepted') is False and not report.get('error') and
        (not plan.get('mobile_group_intent') or (report.get('mobile_group_intent',{}).get('passed') is True and
            report.get('group_intent_witness_passed') is True and
            report['mobile_group_intent'].get('user_edits') is bool(plan.get('mobile_group_user_edits')))) and
        (not plan.get('mobile_recovery_stall') or (plan.get('mobile_group_intent') is True and
            plan.get('mobile_group_user_edits') is True and report.get('mobile_recovery_stall',{}).get('passed') is True and
            report.get('recovery_stall_witness_passed') is True and len(report.get('matches',[])) == 2 and
            report['mobile_recovery_stall'].get('match') == report['matches'][1].get('match') and
            report['mobile_recovery_stall'].get('world') == 2)) and
        (not plan.get('mobile_recall') or (plan.get('mobile_group_intent') is True and
            not plan.get('mobile_group_user_edits') and not plan.get('mobile_recovery_stall') and
            report.get('mobile_recall',{}).get('passed') is True and report.get('recall_witness_passed') is True and
            len(report['mobile_recall'].get('episodes',[])) == 2 and
            len(report['mobile_correction'].get('episodes',[])) == 2 and
            [row.get('match')for row in report['mobile_recall']['episodes']] == [row.get('match')for row in report.get('matches',[])] and
            all(row.get('passed') is True and row.get('world') == episode.get('world')for row,episode in
                zip(report['mobile_recall']['episodes'],report['mobile_correction'].get('episodes',[]))))) and
        report.get('source_unchanged') is True and report.get('files_unchanged') is True and
        not report.get('forced_cleanup') and not report.get('cleanup_errors') and
        len(report.get('game_cleanup',[])) == 2 and all(r.get('natural_game_exit') is True for r in report['game_cleanup']))


def timing_prefix_counts(prefix, frames, *, prediction, complete_delivery_proven):
    """Physical capture can finish before the last predicted authority arrives.

    The separate exact native65/raw-bridge comparison must already prove EVERY
    delivery. This only classifies bounded trailing rows absent from a timing
    capture; it never creates timestamps or substitutes for delivery evidence.
    """
    applied = [r['frame'] for r in prefix if r['event'] == 'apply']
    arrived = [r['frame'] for r in prefix if r['event'] == 'arrival']
    require(applied == list(range(frames)), 'native physical prefix incomplete')
    require(complete_delivery_proven, 'independent complete bridge/native65 delivery is required')
    require(arrived == list(range(len(arrived))), 'native arrival timing prefix is noncontiguous')
    require(len(arrived) == frames or
            (prediction and frames - 12 <= len(arrived) < frames),
            'native arrival timing cutoff exceeds prediction budget')
    return dict(trace_arrival_frames=len(arrived), trace_apply_frames=len(applied),
                missing_trailing_arrival_timings=frames-len(arrived),
                complete_delivery_proven=True, synthetic_timing_rows=0)


def actor_fixture_metadata():
    from tools.prediction_actor_fixture import metadata
    return metadata()


def mobile_fixture_metadata():
    from tools.prediction_actor_fixture import mobile_metadata
    return mobile_metadata()


def match_template(base, assets, *, actor_correction, mobile_correction=False):
    """Transform before DedicatedServer/ProfileStore build any MatchData."""
    require(not (actor_correction and mobile_correction), 'HQ and mobile fixtures are mutually exclusive')
    if mobile_correction:
        from tools.prediction_actor_fixture import make_mobile_template
        return make_mobile_template(base,assets)
    if not actor_correction:
        return base
    from tools.prediction_actor_fixture import make_template
    return make_template(base, assets)


def actor_native_observation(state, parsed_hash, *, fixture=None):
    """Actual authority queries, not expected fixture values or actor telemetry."""
    metadata = actor_fixture_metadata() if fixture is None else fixture
    if not metadata['selection_frame'] <= state['frame'] <= metadata.get('observation_last_frame',metadata['baseline_death_frame'] + 20):
        return None
    entities = {row['id']: row for row in state['entities']}
    mobile = 'victim_id' in metadata
    return dict(frame=state['frame'], parsed_state_sha256=parsed_hash,
                attacker=entities.get(metadata['attacker_id']), game_state=state['game_state'],
                **{('victim' if mobile else 'core'):entities.get(metadata['victim_id' if mobile else 'victim_core_id'])})


def actor_escape_evidence(log, *, match, commits, raw_bodies, journal, fixture=None, prefix='ACTOR ORDER '):
    """Bind original constructor bytes through actual67/72 and one native commit."""
    from server.game_data import decode_player_input
    from server.protobuf_wire import get_bytes, get_repeated_bytes, get_repeated_uint, get_uint, parse_fields
    metadata = actor_fixture_metadata() if fixture is None else fixture
    orders = []
    for line in log.splitlines():
        if prefix not in line:
            continue
        raw = line.split(prefix, 1)[1]
        require(len(raw) <= 2048, 'actor order diagnostic exceeds bound')
        row = json.loads(raw)
        require(type(row) is dict and row.get('schema') == 1 and
                row.get('event') == 'original_escape_move' and row.get('originalCtor') is True and
                row.get('physicalUI') is False, 'invalid original actor order schema')
        if row.get('match') == match:
            orders.append(row)
    require(len(orders) == 1, 'one original actor escape order required')
    order = orders[0]
    require(all(type(order.get(key)) is int and order[key] >= 0 for key in
                ('world', 'army', 'entity', 'unit_type', 'ability', 'frame', 'tick_ms')) and
            order['world'] > 0 and order['army'] == metadata['attacker_slot'] and
            order['entity'] == metadata['attacker_id'] and order['unit_type'] == metadata['attacker_type'] and
            order['ability'] == 12 and order['frame'] == metadata['escape_physical_frame'] and
            type(order.get('action_sha256')) is str and HEX64.fullmatch(order['action_sha256']),
            'original actor escape identity/frame differs')
    action_hash = order['action_sha256']
    candidates = []
    for (body_match, slot, sequence), body in raw_bodies.items():
        if body_match != match or slot != metadata['attacker_slot']:
            continue
        decoded = decode_player_input(body)
        matching = [action for action in decoded['actions'] if digest(action) == action_hash]
        if matching:
            require(len(matching) == 1, 'actor escape duplicated inside72')
            require(decoded['identity']['player_id'] == slot + 1 and decoded['identity']['is_aliased'] and
                    not decoded['identity']['ai_profile_id'], 'actor escape72 human identity differs')
            candidates.append((sequence, body, matching[0]))
    require(len(candidates) == 1, 'actor escape missing/duplicated in submitted72')
    sequence, body, action = candidates[0]
    require([field.number for field in parse_fields(action)] == [1], 'actor escape is not Execute')
    execute = get_bytes(action, 1, required=True)
    groups = get_repeated_bytes(execute, 1)
    require(len(groups) == 1 and get_uint(groups[0], 1) == metadata['attacker_type'] and
            get_uint(groups[0], 2) == 12 and
            get_repeated_uint(groups[0], 3) == (metadata['attacker_id'],) and get_uint(execute, 2) == 0,
            'actor escape source/ability/queued differs')
    command = get_bytes(execute, 3, required=True)
    require([field.number for field in parse_fields(command)] == [3], 'actor escape target case differs')
    position = get_bytes(get_bytes(command, 3, required=True), 1, required=True)
    target = []
    for number in (1, 2, 3):
        value = get_uint(position, number)
        require(value < 2**64, 'actor escape target exceeds signed Q32.32')
        target.append((value - 2**64 if value >= 2**63 else value) / 2**32)
    require(target == metadata['target'], 'actor escape original ToProto target differs')
    registrations = re.findall(r'Movement local batch registered: sequence=(\d+) speculativeFrame=(\d+) '
                               r'tick=(\d+) match=' + re.escape(match) + r'(?:\s|$)', log)
    registered = [tuple(map(int, row)) for row in registrations if int(row[0]) == sequence]
    require(len(registered) == 1 and registered[0][2] >= order['tick_ms'], 'actor escape actual67 receipt missing/duplicated')
    sent = re.findall(r'Original command batch submitted: match=' + re.escape(match) +
        r' sequence=(\d+) actions=(\d+) bytes=(\d+) body_sha256=([a-f0-9]{64}) sendTick=(\d+) sourceNextFrame=(\d+)', log)
    sent = [row for row in sent if int(row[0]) == sequence]
    require(len(sent) == 1 and int(sent[0][1]) == len(decode_player_input(body)['actions']) and
            int(sent[0][2]) == len(body) and sent[0][3] == digest(body) and int(sent[0][4]) >= registered[0][2],
            'actor escape native72 sender/body differs')
    accepted = [row for row in commits if row.get('event') == 'command_batch_committed' and
                row.get('match') == match and row.get('slot') == metadata['attacker_slot'] and row.get('sequence') == sequence]
    require(len(accepted) == 1 and type(accepted[0].get('frame')) is int and
            accepted[0]['frame'] in metadata['safe_canonical_frames'] and
            accepted[0]['frame'] < metadata['baseline_death_frame'], 'actor escape canonical commit outside qualified margin')
    frame = accepted[0]['frame']
    occurrences = [(row['frame'], slot) for row in journal for slot, actions in row['players'].items()
                   for value in actions if digest(value) == action_hash]
    require(occurrences == [(frame, metadata['attacker_slot'])], 'actor escape canonical journal duplicate/rebound/missing')
    return dict(order=order, sequence=sequence, action_sha256=action_hash, body_sha256=digest(body),
                canonical_commit_frame=frame, speculative_frame=registered[0][1], native67_tick_ms=registered[0][2],
                native72_send_tick_ms=int(sent[0][4]), target=target)


def actor_correction_evidence(log, *, attacker_log, match, commits, raw_bodies, journal,
                              bridge_frames, canonical_payloads, canonical_states, native_states, worker_states):
    metadata = actor_fixture_metadata()
    escape = actor_escape_evidence(attacker_log, match=match, commits=commits, raw_bodies=raw_bodies, journal=journal)
    rows = []
    for line in log.splitlines():
        if 'ACTOR CORRECTION ' in line:
            row = json.loads(line.split('ACTOR CORRECTION ', 1)[1])
            require(len(line) <= 4096 and type(row) is dict and row.get('schema') == 1 and row.get('physicalUI') is False,
                    'invalid actor correction diagnostic schema')
            require(type(row.get('focus_retained_at_death')) is bool, 'actor focus-at-death witness missing')
            require(row.get('original_focus_supported') is False and row.get('original_group_supported') is False and
                    row['focus_retained_at_death'] is False,
                    'original HQ eligibility forbids positive focus/control-group coverage')
            if row.get('match') == match:
                rows.append(row)
    names = ['original_hq_selection_established', 'original_dead_hq_retained',
             'original_hq_restored_and_admitted', 'hq_selection_correction_passed']
    require([r.get('event') for r in rows] == names, 'incomplete original HQ selection/correction episode')
    require(all(all(type(r.get(key)) is int and r[key] >= 0 for key in
                    ('world', 'entity', 'army', 'unit_type', 'frame', 'tick_ms')) and r['world'] > 0 and
                r['entity'] == metadata['victim_core_id'] and r['army'] == metadata['victim_slot'] and
                r['unit_type'] == metadata['core_type'] for r in rows),
            'actor episode numeric binding differs')
    valid_pointer = lambda value: isinstance(value, str) and re.fullmatch(r'[0-9A-Fa-f]{1,16}', value) and int(value, 16) != 0
    require(len({r['world'] for r in rows}) == 1 and len({r.get('original_actor') for r in rows}) == 1 and
            all(valid_pointer(r.get('current_actor')) and valid_pointer(r.get('original_actor')) for r in rows) and
            rows[0]['current_actor'] == rows[1]['current_actor'] == rows[0]['original_actor'] and
            rows[2]['current_actor'] == rows[3]['current_actor'],
            'actor episode world/root binding differs')
    require(all(b['frame'] > a['frame'] and b['tick_ms'] >= a['tick_ms'] for a, b in zip(rows, rows[1:])) and
            metadata['selection_frame'] <= rows[0]['frame'] < 145 and
            rows[1]['frame'] >= metadata['baseline_death_frame'] and rows[3]['frame'] >= rows[2]['frame'] + 2,
            'actor episode did not progress through separate physical frames')
    frame = escape['canonical_commit_frame']; world = rows[0]['world']
    receipts = [row for row in authority_rows(log) if row['world'] == world and row['match'] == match and row['frame'] == frame]
    bridge = [row for row in bridge_frames if row['match'] == match and row['frame'] == frame]
    require(len(receipts) == len(bridge) == 1 and
            receipts[0]['wire_sha256'] == bridge[0]['payload_sha256'] == canonical_payloads.get(frame),
            'actor escape victim65/raw bridge wire binding differs')
    require(rows[1]['tick_ms'] < min(receipts[0]['tick_ms'], bridge[0]['received_tick_ms']) and
            receipts[0]['tick_ms'] <= rows[2]['tick_ms'],
            'actor death must precede actual victim bridge/65 and restoration must follow65')
    joined = joined_worker_evidence(worker_states, world=world, authority=receipts[0],
                                   canonical_states=canonical_states, require_replay=True)
    # Tie the positive replay group to THIS restoration, not a later unrelated Move.
    group = [worker_states[index] for index in joined['promotion_group_row_indices']]
    corrected = [row for row in group if row['frame'] == frame]
    # One promotion can confirm several buffered canonical frames. Its frontier
    # need not equal the command frame; that exact frame/hash must be IN the
    # actual positive-replay group before the presentation restoration.
    require(len(corrected) == 1 and corrected[0]['parsed_state_sha256'] == canonical_states.get(frame) and
            all(receipts[0]['tick_ms'] <= row['tick_ms'] <= rows[2]['tick_ms'] for row in group),
            'actor restoration lacks its own native replay group')
    group_frames = {row['frame'] for row in group}
    group_actions = [dict(frame=row['frame'],slot=slot,action_sha256=digest(action))
                    for row in journal if row['frame'] in group_frames
                    for slot, actions in row['players'].items() for action in actions]
    require(group_actions == [dict(frame=frame,slot=metadata['attacker_slot'],action_sha256=escape['action_sha256'])],
            'actor replay group input is not solely the exact canonical escape Move')
    expected = range(metadata['selection_frame'], metadata['baseline_death_frame'] + 21)
    require([row['frame'] for row in native_states] == list(expected), 'actual actor native authority timeline incomplete')
    for row in native_states:
        core, attacker = row['core'], row['attacker']
        require(row['parsed_state_sha256'] == canonical_states.get(row['frame']) and type(core) is dict and
                (core.get('id'), core.get('army'), core.get('type')) == (5, 1, 3) and core.get('max_health') == 100 and
                core.get('current_damage') == (0 if row['frame'] < 144 else 50) and
                type(attacker) is dict and (attacker.get('id'), attacker.get('army'), attacker.get('type')) == (10, 0, 1) and
                row['game_state'].get('complete') is False,
                'actual canonical actor timeline does not preserve living victim/Core native identity')
    focus = [re.match(r'^\[(\d+)\] Prediction actor focus cancelled: group=4 ', line) for line in log.splitlines()]
    cancelled = any(m and rows[0]['tick_ms'] <= int(m[1]) <= rows[3]['tick_ms'] for m in focus)
    require(not cancelled, 'HQ fixture cannot claim original focus cancellation')
    retired = []
    for line in log.splitlines():
        stamp = re.match(r'^\[(\d+)\] Prediction actor retired: ', line)
        if not stamp:
            continue
        fields = dict(re.findall(r'(\w+)=([^\s]+)', line))
        if fields.get('match') != match or fields.get('world') != str(world) or fields.get('entity') != '5':
            continue
        require(fields.get('actor') is not None and valid_pointer(fields['actor']) and
                int(fields['actor'], 16) == int(rows[0]['original_actor'], 16) and
                all(fields.get(key) == value for key, value in {
                    'oldType':'3', 'oldArmy':'1', 'selectionBatch':'1', 'originalPool':'1',
                    'oldMembershipRemoved':'1', 'retainedHQ':'1'}.items()) and
                rows[1]['tick_ms'] <= int(stamp[1]) <= rows[2]['tick_ms'],
                'original retained-HQ pool repair binding differs')
        retired.append(dict(tick_ms=int(stamp[1]), **fields))
    require(len(retired) == 1,
            'original retained-HQ pool repair witness missing')
    return dict(passed=True, rows=rows, escape=escape, actual_victim65=receipts[0],
                victim_raw_bridge_tick_ms=bridge[0]['received_tick_ms'], native_authority_timeline=native_states,
                retained_hq_original_pool=retired[0],
                corrected_command_frame=frame, replay_group_input_actions=group_actions,
                hq_selection_retraction_exercised=True,
                original_focus_supported=False, original_group_supported=False,
                repair_focus_cancellation_exercised=False, control_group_cleanup_exercised=False,
                focus_cancellation_scope='not exercised; original HQ control-group eligibility excludes assignment/focus',
                **joined, scope='Scripted original Move12 constructor; actual HQ death/retraction/admission and native replay+20; no physical UI or VFX claim')


def resume(process):
    ntdll = C.WinDLL('ntdll', use_last_error=True)
    ntdll.NtResumeProcess.argtypes, ntdll.NtResumeProcess.restype = [C.c_void_p], C.c_long
    require(ntdll.NtResumeProcess(C.c_void_p(int(process._handle))) == 0,
            'retained suspended process resume failed')


class ObservedJob(RetainedJob):
    def __init__(self, process):
        self.final_accounting = None
        self.forced = False
        super().__init__(process)

    def terminate_owned(self):
        self.forced = True
        super().terminate_owned()

    def close(self):
        if getattr(self, 'handle', None):
            try:
                self.final_accounting = self.accounting()
                self.forced |= bool(self.final_accounting['active'])
            finally:
                super().close()


class WorkerJobLease:
    """Let the fixture controller observe natural descendant drain.

    SimulationWorker always calls its job.close during its own I/O cleanup,
    including after a successful CLOSE and retained main-process exit0. Closing
    the real kill-on-close Job there can kill a still-exiting owned descendant.
    An abort still terminates/closes the exact retained Job before I/O drain.
    """
    def __init__(self, job, worker):
        self.job,self.worker = job,worker
        self.close_requested = False

    def close(self):
        self.close_requested = True
        if not self.job.handle:
            return
        if self.worker.process.poll() == 0 and not self.worker.failure:
            return
        try:
            self.job.terminate_owned()
        finally:
            self.job.close()


async def close_owned_job(job, timeout=5.0, *, clock=time.monotonic, sleep=asyncio.sleep):
    """Bounded drain using only this retained Job; never enumerate/kill PIDs."""
    async def drained():
        deadline = clock() + timeout
        while job.handle:
            if job.accounting()['active'] == 0:
                return True
            remaining = deadline - clock()
            if remaining <= 0:
                return False
            await sleep(min(.01, remaining))
        return True

    try:
        if job.handle and not await drained():
            job.terminate_owned()
            await drained()  # Bound termination observation too; close still owns survivors.
    finally:
        job.close()


def spawn_owned(argv, *, before_resume=None, job_type=None, popen=None, resume_child=None, **kwargs):
    """Assign the exact retained Popen handle before any original child code."""
    process = job = None
    try:
        flags = kwargs.pop('creationflags', 0) | CREATE_SUSPENDED | getattr(subprocess, 'CREATE_NO_WINDOW', 0)
        process = (popen or subprocess.Popen)(argv, creationflags=flags, **kwargs)
        job = (job_type or ObservedJob)(process)
        if before_resume:
            before_resume(process)
        (resume_child or resume)(process)
        return process, job
    except BaseException:
        if process is not None:
            try:
                if process.poll() is None:
                    try:
                        if job is not None:
                            job.terminate_owned()
                        else:
                            process.terminate()  # Exact still-suspended Popen handle.
                    finally:
                        if job is not None:
                            job.close()  # Kill-on-close still owns only this exact child.
            finally:
                try:
                    try:
                        process.wait(timeout=5)
                    except subprocess.TimeoutExpired:
                        process.kill()
                        process.wait(timeout=5)
                finally:
                    if job is not None:
                        job.close()
                    for stream in (getattr(process, name, None) for name in ('stdin', 'stdout', 'stderr')):
                        if stream is not None:
                            stream.close()
                    process._handle.Close()
        raise


def feel_rows(log):
    result = []
    for line in log.splitlines():
        if FEEL_PREFIX not in line:
            continue
        raw = line.split(FEEL_PREFIX, 1)[1]
        require(len(raw) <= 8192, 'feel diagnostic line exceeds bound')
        row = json.loads(raw)
        require(type(row) is dict and row.get('schema') == 1 and row.get('event') in FEEL_CONTRACT['events'],
                'unknown feel diagnostic schema/event')
        for key in ('world', 'entity', 'unit_type', 'incarnation', 'move_id', 'tick_ms'):
            require(type(row.get(key)) is int and row[key] >= 0, 'invalid feel identity/clock')
        require(0<row['unit_type']<=0xffffffff,'invalid feel unit type')
        require(row['world'] > 0 and re.fullmatch('[a-f0-9]{32}', row.get('match', '')),
                'feel diagnostic lacks exact world/match')
        for key in FEEL_CONTRACT['events'][row['event']]:
            require(key in row, 'feel diagnostic lacks event field: ' + key)
        if row['event'] == 'transform':
            for key in ('presented_frame','completed_frame'):
                if key in row:
                    require(type(row[key]) is int and -1 <= row[key] <= 0x7fffffff,
                            'invalid actual native pose frame counter')
            if 'sampled_us' in row:
                require(type(row['sampled_us']) is int and 0 <= row['sampled_us'] <= 0xffffffffffffffff,
                        'invalid native QPC pose sample')
        result.append(row)
        require(len(result) <= 65536, 'feel event count exceeds bound')
    return result


def validate_worker_states(rows):
    """Validate the real diagnostic file, never actor-decorated/native FEEL rows."""
    fields={'schema','event','world','frame','parsed_state_sha256','confirmed_frontier','corrections',
            'corrections_delta','replayed_frames_total','replayed_frames_delta','tick_ms'}
    require(type(rows)is list and 0<len(rows)<=4096,'worker state row count outside bound')
    previous={};worlds=[];last_tick=-1;groups={}
    for index,row in enumerate(rows):
        require(type(row)is dict and set(row)==fields and type(row['schema'])is int and row['schema']==1 and
            row['event']=='confirmed_native_state','unknown worker native-state schema/fields')
        for name in fields-{'event','parsed_state_sha256','schema'}:
            require(type(row[name])is int and 0<=row[name]<=0xffffffffffffffff,'invalid worker state counter/clock')
        world=row['world'];frame=row['frame'];frontier=row['confirmed_frontier']
        require(world>0 and frame<=frontier<=0x7fffffff and frontier-frame<32 and
            type(row['parsed_state_sha256'])is str and HEX64.fullmatch(row['parsed_state_sha256']),
            'invalid worker world/frame/hash')
        require(row['tick_ms']>=last_tick,'worker state clock regressed');last_tick=row['tick_ms']
        if not worlds or world!=worlds[-1]:
            require(world not in previous,'worker world records interleaved/reused');worlds.append(world)
        old=previous.get(world,dict(frame=-1,confirmed_frontier=-1,corrections=0,replayed_frames_total=0))
        require(frame==old['frame']+1 and frontier>=old['confirmed_frontier'],'worker frame/frontier duplicate or noncontiguous')
        for total,delta in (('corrections','corrections_delta'),('replayed_frames_total','replayed_frames_delta')):
            require(row[total]>=old[total] and row[delta]==row[total]-old[total],'worker replay/correction counter/delta differs')
        key=world,frontier
        group=groups.setdefault(key,[])
        if group:
            require(all(row[name]==rows[group[0]][name] for name in ('corrections','replayed_frames_total')),
                    'worker promotion group metrics changed')
        group.append(index);previous[world]=row
    require(all(rows[indices[-1]]['frame']==key[1] for key,indices in groups.items()),'worker promotion group missing frontier row')
    return rows


def authority_rows(log):
    """Actual post-response65 Native-gate receipts; never inferred from FEEL."""
    result=[];seen=set();previous={};last_tick=-1
    for line in log.splitlines():
        if 'MOVEMENT AUTHORITY 'not in line:continue
        raw=line.split('MOVEMENT AUTHORITY ',1)[1]
        require(len(raw)<=2048,'native authority diagnostic line exceeds bound')
        row=json.loads(raw)
        require(type(row)is dict and set(row)=={'schema','world','match','frame','tick_ms','canonical_sha256','wire_sha256'}and
            type(row['schema'])is int and row['schema']==1,'unknown native authority schema/fields')
        require(all(type(row[k])is int for k in ('world','frame','tick_ms'))and
            0<row['world']<=0xffffffffffffffff and 0<=row['frame']<=0x7fffffff and
            0<=row['tick_ms']<=0xffffffffffffffff and row['tick_ms']>=last_tick and
            type(row['match'])is str and re.fullmatch('[a-f0-9]{32}',row['match'])and
            all(type(row[key])is str and HEX64.fullmatch(row[key])for key in ('canonical_sha256','wire_sha256')),
            'invalid native authority identity/frame/hash/clock')
        key=row['world'],row['match'];identity=key+(row['frame'],)
        require(identity not in seen and row['frame']>previous.get(key,-1),'duplicate/regressing native authority frame')
        seen.add(identity);previous[key]=row['frame'];last_tick=row['tick_ms'];result.append(row)
        require(len(result)<=4096,'native authority diagnostic count exceeds bound')
    return result


def read_worker_states(path):
    raw=read(path,4*1024*1024)
    require(raw.endswith(b'\n'),'closed worker state file is partial')
    lines=raw.decode('utf-8').splitlines()
    require(all(0<len(line)<=2048 for line in lines),'worker state line outside bound')
    return validate_worker_states([json.loads(line)for line in lines])


def joined_worker_evidence(worker_states, *, world, authority, canonical_states, require_replay=False):
    """Compare a real confirmed frontier; require replay only for its separate witness."""
    rows=validate_worker_states(worker_states)
    own=[(index,row)for index,row in enumerate(rows)if row['world']==world]
    require(own,'worker state file lacks selected RPC world')
    groups=defaultdict(list)
    for index,row in own:groups[row['confirmed_frontier']].append((index,row))
    candidates=[]
    for frontier,group in groups.items():
        replayed=sum(row['replayed_frames_delta']for _,row in group)
        if frontier>=authority['frame'] and (replayed>0 or not require_replay) and all(row['tick_ms']>=authority['tick_ms']for _,row in group):
            candidates.append((frontier,group,replayed))
    require(candidates,'no actual confirmed native'+(' replay'if require_replay else '')+' group after matching65')
    frame,group,replayed=candidates[0];correction=group[-1][1]
    require(correction['frame']==frame and canonical_states.get(frame)==correction['parsed_state_sha256'],
            'confirmed native worker state differs from server')
    by_frame={row['frame']:(index,row)for index,row in own}
    tail=[]
    for number in range(frame+1,frame+21):
        require(number in by_frame and number in canonical_states,'20 contiguous canonical worker continuations missing')
        index,row=by_frame[number]
        require(row['tick_ms']>=correction['tick_ms'] and row['parsed_state_sha256']==canonical_states[number],
                'canonical native worker continuation differs from server')
        tail.append(index)
    return dict(confirmed_state_frame=frame,correction_required=require_replay,continuation_frames=20,frontier_row_index=group[-1][0],
        promotion_group_row_indices=[index for index,_ in group],promotion_group_replayed_delta=replayed,
        frontier_row_replayed_delta=correction['replayed_frames_delta'],continuation_row_indices=tail,
        worker_scope='Actual cached original Spectator31 decode_snapshot(include_entities=True); parsed fields excluding raw_sha256')


async def full_authority_frame(worker,process_frame,actions,dt_ms=None):
    """Movement diagnostic only: preserve FrameResult fields, replace actual state."""
    result=await process_frame(actions,dt_ms)
    actual=await worker.state(31,include_entities=True)
    require(actual.get('frame')==result.frame and actual.get('viewer')==31 and type(actual.get('entities'))is list,
            'authority full native state query differs from actual frame')
    worker.last_state=actual
    return replace(result,state=actual)


def command_phase(rows, *, match, slot, commits):
    batches=[r for r in rows if r['match']==match and r['event']=='batch_registered']
    require(len(batches)==1,'one actual67 Move registration required for phase')
    batch=batches[0]
    accepted=[r for r in commits if r.get('match')==match and r.get('slot')==slot and
              r.get('sequence')==batch['sequence'] and r.get('event','command_batch_committed')=='command_batch_committed']
    require(len(accepted)==1 and type(batch.get('speculative_frame'))is int and
        type(accepted[0].get('frame'))is int,'Move phase requires unique canonical commit')
    delta=batch['speculative_frame']-accepted[0]['frame']
    return dict(speculative_frame=batch['speculative_frame'],canonical_commit_frame=accepted[0]['frame'],
        speculative_minus_canonical_frames=delta,command_phase_passed=abs(delta)<=1,
        phase_scope='Controlled steady-RTT actual67 assignment versus unique original server commit; tolerance1frame')


def normal_build_units(log,slot):
    builds=re.findall(r'LAN NORMAL BUILD smoke frame(\d+) slot(\d+) army\d+ HQ\d+ deckSlot\d+ unitType(\d+) '
        r'ability\d+ cost=\([^\n]+ prerequisite=1 queued=1 commandQueueDelta=1 ',log)
    return [int(unit)for frame,owner,unit in builds if int(owner)==slot and int(frame)==300+slot*100]


def native_position_bindings(log, *, matches, slot, spec, commands):
    """Join caller-validated original commands to actual native BEGIN records."""
    ready = re.findall(r'Movement prediction ready: generation=(\d+) match=([a-f0-9]{32}) world=(\d+) slot=(\d+) ', log)
    require(len(matches) == 2 and len(set(matches)) == 2 and
            [row[1] for row in ready] == matches and len({row[2] for row in ready}) == 2 and
            all(int(row[3]) == slot for row in ready), 'native position BEGIN/match/world/slot binding differs')
    require(len(commands) == 2, 'native position trace requires two validated original commands')
    result = []
    for command, (_, match, world, _) in zip(commands, ready):
        require(command['match'] == match and command['world'] == int(world) and
                command['entity'] == spec.entity_id and command['unit_type'] == spec.unit_type and
                command['incarnation'] > 0 and spec.army == slot,
                'native position watch differs from actual original FEEL actor')
        result.append(dict(world=int(world), match=match, entity=command['entity'],
                           unit_type=command['unit_type'], army=slot, incarnation=command['incarnation']))
    return result


def native_position_evidence(path, *, log, matches, slot, specification, contexts, catalog_units, entity_abilities):
    """Closed file-only diagnostic; canonical command/state gates stay separate."""
    from client_patch.prediction_worker.observation import parse_position_trace_spec
    from tools.prediction_position_trace import analyze, read_trace
    spec = parse_position_trace_spec(specification)
    require([row['match'] for row in contexts] == matches, 'native position command contexts incomplete')
    commands = []
    for context in contexts:
        require(context['slot'] == slot, 'native position command context owner differs')
        validated = validate_move_command(feel_rows(log), match=context['match'], slot=slot,
            commits=context['commits'], raw_bodies=context['raw_bodies'], journal=context['journal'],
            catalog_units=catalog_units, entity_abilities=entity_abilities, built_units=normal_build_units(log,slot))
        commands.append(validated['command'])
    bindings = native_position_bindings(log, matches=matches, slot=slot, spec=spec, commands=commands)
    rows = read_trace(path)
    result = analyze(rows, identity=dict(id=spec.entity_id, type=spec.unit_type, army=spec.army), worlds=bindings)
    require(all(row['event'] == 'before_restore_cached_head' or spec.first_frame <= row['frame'] <= spec.last_frame
                for row in rows), 'native position query lies outside the explicit prepared window')
    result['external_binding_source'] = 'Actual native BEGIN plus original FEEL command checked against immutable67/72/canonical journal'
    result['frame_window'] = [spec.first_frame,spec.last_frame]
    return result


def validate_move_command(rows, *, match, slot, commits, raw_bodies, journal,
                          catalog_units=None, entity_abilities=None, built_units=None):
    """Bind one original command to actual67/72 and its unique canonical action."""
    from server.game_data import decode_player_input
    from server.protobuf_wire import get_bytes, get_repeated_bytes, get_repeated_uint, get_uint
    relevant = [r for r in rows if r['match'] == match]
    created = [r for r in relevant if r['event'] == 'command_created']
    require(len(created) == 1, 'one original Move command is required for the bounded feel case')
    command = created[0]
    identity = tuple(command[k] for k in ('world', 'entity', 'unit_type', 'incarnation', 'move_id'))
    same = [r for r in relevant if tuple(r[k] for k in ('world', 'entity', 'unit_type', 'incarnation', 'move_id')) == identity]
    require(len(same) == len(relevant), 'feel observation changed actor incarnation/world/intent')
    unit=command['unit_type']
    require(type(unit)is int and 0<unit<=0xffffffff and unit in (catalog_units or {}) and
        12 in (entity_abilities or {}).get(unit,()) and unit in (built_units or ()),
        'Move unit type lacks actual asset Move12 metadata or original normal-build witness')
    require(command['incarnation'] > 0 and command['ability'] == 12 and command['original_callback'] in (
        'Uncapped.ExecuteTargetGroundCommand..ctor', 'Uncapped.UnitSelector.ProcessContextualRightClick_Pointer',
        'Uncapped.UnitSelector.ProcessContextualRightClick_Minimap'), 'not an original native Move constructor/callback')
    action_hash = command['action_sha256']
    require(HEX64.fullmatch(action_hash), 'invalid Move action digest')
    registered = [r for r in same if r['event'] == 'batch_registered']
    received = [r for r in same if r['event'] == 'authority_received']
    require(len(registered) == len(received) == 1, 'Move batch/authority occurrence is not unique')
    batch, authority = registered[0], received[0]
    require(batch['action_sha256'] == authority['action_sha256'] == action_hash and
            command['tick_ms'] <= batch['tick_ms'] < authority['tick_ms'], 'Move registration/65 order differs')
    key = match, slot, batch['sequence']
    require(key in raw_bodies and digest(raw_bodies[key]) == batch['body_sha256'], 'native67 body differs from actual72')
    decoded = decode_player_input(raw_bodies[key])
    require(decoded['identity']['player_id'] == slot + 1 and decoded['identity']['is_aliased'] and
            not decoded['identity']['ai_profile_id'], 'Move batch identity is not the assigned human')
    submitted = decoded['actions']
    selected = [a for a in submitted if digest(a) == action_hash]
    require(len(selected) == 1, 'Move is missing/duplicated in the immutable submitted batch')
    execute = get_bytes(selected[0], 1, required=True)
    groups = get_repeated_bytes(execute, 1)
    require(len(groups) == 1 and get_uint(groups[0], 1) == unit and get_uint(groups[0], 2) == 12 and
            get_repeated_uint(groups[0], 3, max_values=256) == (command['entity'],),
            'Move sources/ability differ from the actual stamped actor')
    position = get_bytes(get_bytes(get_bytes(execute, 3, required=True), 3, required=True), 1, required=True)
    target = []
    for number in (1, 2, 3):
        value = get_uint(position, number)
        require(value < 2**64, 'Move target exceeds signed Q32.32 range')
        target.append((value - 2**64 if value >= 2**63 else value) / 2**32)
    require(type(command['target']) is list and len(command['target']) == 3 and all(
        type(value) in (int, float) and math.isfinite(value) and abs(value - encoded) <= .0001
        for value, encoded in zip(command['target'], target)), 'Move target differs from original ToProto bytes')
    committed = [r for r in commits if r.get('match') == match and r.get('slot') == slot and
                 r.get('sequence') == batch['sequence'] and r.get('event','command_batch_committed')=='command_batch_committed']
    require(len(committed) == 1 and committed[0]['frame'] == authority['frame'], 'Move lacks unique canonical commit')
    phase=command_phase(rows,match=match,slot=slot,commits=commits)
    occurrences = [(f['frame'], digest(a)) for f in journal for a in f['players'][slot] if digest(a) == action_hash]
    require(occurrences == [(authority['frame'], action_hash)], 'canonical journal lost/duplicated/rebound Move')
    return dict(command=command, same=same, unit=unit, action_hash=action_hash,
        batch=batch, authority=authority, target=target, phase=phase)


def evaluate_feel(rows, *, match, slot, commits, raw_bodies, journal, canonical_states,
                  worker_states=None,bridge_frames=None,catalog_units=None,entity_abilities=None,built_units=None):
    """A bounded actual-command/render/correction claim, never a pacing proxy."""
    relevant = [r for r in rows if r['match'] == match]
    missing = [name for name in FEEL_CONTRACT['events'] if not any(r['event']==name for r in relevant)]
    if worker_states is None:missing += ['confirmed_state','continuation_state']
    if missing:
        return dict(passed=False, missing_gates=missing, scope='no inferred or synthetic replacement evidence')
    validated=validate_move_command(rows,match=match,slot=slot,commits=commits,raw_bodies=raw_bodies,
        journal=journal,catalog_units=catalog_units,entity_abilities=entity_abilities,built_units=built_units)
    command,same,unit,batch,authority,target,phase=(validated[name]for name in
        ('command','same','unit','batch','authority','target','phase'))
    bridge=[row for row in bridge_frames or []if row['match']==match and row['frame']==authority['frame']]
    require(len(bridge)==1 and type(bridge[0].get('received_tick_ms'))is int and
        batch['tick_ms']<bridge[0]['received_tick_ms']<=authority['tick_ms'],
        'matching raw authority bridge arrival/65 order missing or different')
    bridge_tick=bridge[0]['received_tick_ms']
    transforms = [r for r in same if r['event'] == 'transform']
    require(all(r['source'] == FEEL_CONTRACT['transform_source'] and len(r['position']) == 3 and
                all(type(v) in (int, float) and math.isfinite(v) for v in r['position']) for r in transforms),
            'transform samples must come from the actual original Unity Transform')
    before = [r for r in transforms if r['tick_ms'] <= command['tick_ms']]
    require(len(before)>=5 and max(r['tick_ms']for r in before)-min(r['tick_ms']for r in before)>=250,
            'at least5 original Unity baseline samples spanning250ms required')
    origin = max(before, key=lambda r: r['tick_ms'])
    baseline_spread=max(math.dist(r['position'],origin['position'])for r in before)
    require(baseline_spread<=.03,'original Unity actor was moving before the controlled Move')
    direction=[value-start for value,start in zip(target,origin['position'])]
    origin_distance=math.dist(origin['position'],target)
    moved = [r for r in transforms if batch['tick_ms'] <= r['tick_ms'] < min(authority['tick_ms'],bridge_tick) and
             math.dist(r['position'], origin['position']) > .05 and
             sum((value-start)*toward for value,start,toward in zip(r['position'],origin['position'],direction))>0 and
             origin_distance-math.dist(r['position'],target)>.05]
    require(moved, 'no actual Unity transform movement toward Move target before BOTH raw bridge and65 authority')
    joined=joined_worker_evidence(worker_states,world=command['world'],authority=authority,canonical_states=canonical_states)
    first = min(moved, key=lambda r: r['tick_ms'])
    ordered=sorted(transforms,key=lambda r:r['tick_ms'])
    pose_clock, pose_scale, pose_approximate = pose_metric_clock(ordered)
    pairs=[pose_pair(a,b,pose_clock,pose_scale)for a,b in zip(ordered,ordered[1:])]
    largest=max(pairs,key=lambda r:r['displacement'])
    confirmed_tick=worker_states[joined['frontier_row_index']]['tick_ms']
    near=lambda tick:[dict(tick_ms=r['tick_ms'],position=r['position'])for r in ordered if abs(r['tick_ms']-tick)<=250]
    return dict(passed=phase['command_phase_passed'], missing_gates=[]if phase['command_phase_passed']else['command_phase'],
        match=match, slot=slot, entity=command['entity'],unit_type=unit,**phase,
        sequence=batch['sequence'], command_to_visible_ms=first['tick_ms'] - command['tick_ms'],
        visibility_before_authority_ms=authority['tick_ms'] - first['tick_ms'],
        visibility_before_bridge_ms=bridge_tick-first['tick_ms'],
        maximum_transform_sample_displacement=largest,
        pose_metric_clock=pose_clock,pose_timing_approximate=pose_approximate,
        maximum_sample_speed_units_per_second=max((r['displacement']*1000/r['interval_ms']for r in pairs if r['interval_ms']>0),default=0),
        transform_samples_near65=near(authority['tick_ms']),transform_samples_near_confirmed_state=near(confirmed_tick),
        baseline_samples=len(before),baseline_span_ms=max(r['tick_ms']for r in before)-min(r['tick_ms']for r in before),
        baseline_max_displacement=baseline_spread,target_distance_reduction=origin_distance-math.dist(first['position'],target),
        **joined,worker_actor_join=dict(kind='verifier decoration only; worker records do not contain actor IDs',
            match=match,world=command['world'],entity=command['entity'],incarnation=command['incarnation'],move_id=command['move_id']),
        scope='One original Move; actual Unity Transform before bridge AND65; confirmed native full parsed state/continuation, no rollback required; diagnostic queries,not manual input or pure timing')


def evaluate_remote_correction(rows, *, match, slot, host_world, host_authorities, host_worker_states,
        host_bridge_frames, canonical_payloads, canonical_states, commits, raw_bodies, journal,
        catalog_units=None, entity_abilities=None, built_units=None):
    """Independent original remote Move causes real host replay, not an own-Move label."""
    move=validate_move_command(rows,match=match,slot=slot,commits=commits,raw_bodies=raw_bodies,journal=journal,
        catalog_units=catalog_units,entity_abilities=entity_abilities,built_units=built_units)
    command,batch,frame=move['command'],move['batch'],move['authority']['frame']
    native=[r for r in host_authorities if r['match']==match and r['world']==host_world and r['frame']==frame]
    require(len(native)==1,'remote Move lacks unique actual host65 receipt')
    receipt=native[0]
    bridge=[r for r in host_bridge_frames if r['match']==match and r['frame']==frame]
    require(len(bridge)==1 and type(bridge[0].get('received_tick_ms'))is int and
        batch['tick_ms']<bridge[0]['received_tick_ms']<=receipt['tick_ms']and
        receipt['wire_sha256']==bridge[0]['payload_sha256']==canonical_payloads.get(frame),
        'remote host bridge/65 wire payload or receipt order differs')
    state=joined_worker_evidence(host_worker_states,world=host_world,authority=receipt,
        canonical_states=canonical_states,require_replay=True)
    return dict(passed=True,scope='Independent other-player original Move; actual subject-client65 then genuine native replay and20 full parsed continuations',
        remote_slot=slot,remote_world=command['world'],remote_entity=command['entity'],unit_type=command['unit_type'],
        sequence=batch['sequence'],canonical_commit_frame=frame,actual_host65=receipt,
        hash_scope='wire_sha256 binds exact raw FRAME payload; canonical_sha256 is worker serialization debug only; original action bytes and full parsed state are checked separately',
        host_raw_bridge_tick_ms=bridge[0]['received_tick_ms'],remote_command_phase=move['phase'],**state,
        actor_join=dict(kind='verifier decoration only; host native-state records do not contain actor IDs',
            host_world=host_world,match=match,remote_owner_slot=slot,remote_entity=command['entity'],
            remote_incarnation=command['incarnation'],move_id=command['move_id']))


def native_evidence(log, *, matches, slot, profile, natural):
    forbidden = ('Movement prediction stopped;', 'Native worker request failed:', 'Native worker startup refused:',
        'Native worker shutdown failed:', 'Offline loop stopped in ', 'Original command scheduling failed:',
        'Prediction actor repair failed:', 'Prediction actors blocked:', 'Client lifecycle invariant failed:',
        'Native Quit probe failed:', 'Frame timing capture stopped:', 'LAN audit disabled:', 'Mobile correction smoke failed:')
    require(not any(x in log for x in forbidden), 'native movement/lifecycle failure in helper log')
    routes = re.findall(r'Native worker movement route active: pid=(\d+) assignedBeforeResume=1 .*movementRequested=1', log)
    require(len(routes) == 1, 'one actual Job-owned movement worker route required')
    bindings = re.findall(r'Native worker export lookup: name=(\w+) count=(\d+) thread=(\d+)', log)
    require(len(bindings) == 18 and {r[0] for r in bindings} == SHIPPING_EXPORTS and
            [int(r[1]) for r in bindings] == list(range(1, 19)), 'exact18 shipping bindings required')
    ready = re.findall(r'Movement prediction ready: generation=(\d+) match=([a-f0-9]{32}) world=(\d+) slot=(\d+) ', log)
    require([r[1] for r in ready] == matches and all(int(r[3]) == slot for r in ready) and
            len({r[2] for r in ready}) == len(matches), 'movement BEGIN/world/rematch identity differs')
    names = set(re.findall(r'Native worker API observed: name=(\w+) thread=\d+ ', log))
    require({'SimInit', 'SimCreateWorld', 'SimProcessMsg', 'SimStep', 'SimMakeSimFrame',
             'SimGetSimFrameBuffer'} <= names, 'actual Unity native frame APIs not observed')
    result = dict(worker_pid=int(routes[0]), matches=matches, native_frame_api_names=sorted(names),
                  movement_route=True, natural_worker_shutdown=False)
    if natural:
        closed = re.findall(r'Native worker closed: pid=(\d+) exit=(\d+) natural=(\d+) reaped=(\d+) '
                            r'ioJoined=(\d+) abandoned=(\d+) requests=(\d+) responses=(\d+)', log)
        require(len(closed) == 1, 'one complete worker shutdown receipt required')
        pid, code, normal, reaped, joined, abandoned, requests, responses = map(int, closed[0])
        require(pid == int(routes[0]) and code == abandoned == 0 and normal == reaped == joined == 1 and
                requests == responses and requests > 0, 'worker shutdown was not natural/complete')
        markers = (COMPLETE, 'COMMUNITY MATCH SMOKE original post-match Leave dispatched:',
            'COMMUNITY MATCH SMOKE post-match leave passed:', 'NATIVE QUIT owned gate released:',
            'NATIVE QUIT owned menu verified: profile=' + profile)
        indices = [log.find(m) for m in markers]
        require(all(i >= 0 for i in indices) and indices == sorted(indices), 'Custom returns/Leave/Quit order differs')
        require(log.count('COMMUNITY MATCH SMOKE native Continue') == 2, 'two original Continue callbacks required')
        quits = re.findall(r'\[(\d+)\] NATIVE QUIT original confirmation dispatch: thread=(\d+) '
                           r'worldIdle=1 assetLoadingCount=0 naturalExitDeadlineSeconds=60', log)
        require(len(quits) == 1, 'original native Quit confirmation missing')
        result.update(natural_worker_shutdown=True, quit_tick=int(quits[0][0]), quit_thread=int(quits[0][1]),
                      requests=requests, responses=responses)
    return result


def publish_gate(game, profile, name):
    directory = (game / '.battleaces-resurrection/profiles' / profile).resolve(strict=True)
    require(directory.is_relative_to((game / '.battleaces-resurrection/profiles').resolve()) and
            name in ('custom-match-leave.ready', 'native-quit.ready'), 'gate escaped fresh owned profile')
    with (directory / name).open('xb'):
        pass


async def run_prepared(output):
    from client_patch.transport import bridge, launcher
    from server import admission, command_scheduling, simulation_worker as ipc, tls_transport as tls
    from server.cosmetics import CosmeticCatalog
    from server.credentials import AuthenticationError
    from server.dedicated_server import Audit, DedicatedServer, Room
    from server.game_data import GameTemplate
    from server.profiles import ProfileStore
    from server.worker_client import SimulationWorker
    from tests.test_tls_transport import generate_test_pki, remove_test_pki
    from tools import frame_timing
    from tools.stream_shaper import StreamShaper
    from tools.verify_high_latency_clients import prefix_trace, state_digest
    from tools.verify_original_command_scheduling import ObservedBridge, cleanup_step, read_journal

    require(os.name == 'nt', 'actual Unity run requires Windows')
    plan = verify_prepared(output)
    fixture_active = bool(plan.get('actor_correction') or plan.get('mobile_correction'))
    output, game, assets = Path(plan['output']), Path(plan['game']), Path(plan['assets'])
    run = output / 'run'; run.mkdir(exist_ok=False)
    pki_folder = run / 'ephemeral-pki'
    clients, workers, shapers, events, raw_bodies = [], [], [], [], {}
    states = defaultdict(dict)
    actor_states = defaultdict(list)
    feel_context = remote_context = actor_context = None
    mobile_contexts = []
    turn_contexts=[];native_receipt_rows={}
    server = audit = pki = None
    tick = C.WinDLL('kernel32').GetTickCount64; tick.restype = C.c_uint64
    turn_directory=run/'transition-gates'if plan.get('transition_orders')else None
    if turn_directory is not None:turn_directory.mkdir(exist_ok=False)
    changing = ChangingRttController(tick,require_sampled_us=plan.get('changing_pose_clock')=='sampled_us',
        transition_gates=turn_directory,phase_source=plan.get('transition_phase_source')or 'pacer_wait') if plan.get('changing_rtt') else None
    started = time.monotonic()
    report = dict(passed=False, scoped_observation_passed=False, movement_feel_witness_passed=False,
        full_feature_accepted=False, scope=__doc__, scenario=plan['scenario'], lifecycle=plan['lifecycle'],
        invocation_sha256=sha(output / 'invocation.json'), source_sha256_at_start=source_hashes(),
        forced_cleanup=False, clients=[], authority_workers=[])
    if plan['scenario'] == 'mobile':
        report.update(mobile_input_witness_passed=False,generic_movement_not_exercised=True,
            full_mobile_controls_accepted=False,mobile_scope=plan['mobile_scope'])
    identities = [('p_' + secrets.token_hex(16), 'ba1_' + secrets.token_urlsafe(32)) for _ in range(2)]

    class Store:
        def authenticate(self, token):
            for identity, expected in identities:
                if secrets.compare_digest(token, expected):
                    return identity
            raise AuthenticationError()

    def observe(event, **fields):
        row = dict(event=event, probe_tick_ms=int(tick()), **fields)
        if event == 'match_created' and changing is not None:
            require(len(shapers)==2, 'changing RTT match started before owned relays')
            changing.begin(fields['match'],shapers[plan['move_slot']])
        if event == 'frame_queued':
            room = server.rooms[fields['room']]
            row['parsed_state_sha256'] = state_digest(room.sim.last_state)
            states[fields['match']][fields['frame']] = row['parsed_state_sha256']
            if fixture_active:
                actual = actor_native_observation(room.sim.last_state, row['parsed_state_sha256'],fixture=plan['actor_fixture'])
                if actual is not None:
                    actor_states[fields['match']].append(actual)
        elif event == 'match_created' and fixture_active:
            room = server.rooms[fields['room']]
            require(fields['seed'] == plan['actor_fixture']['seed'] and
                    room.match.raw_game_data == workers[-1]['bootstrap'], 'actor fixture bootstrap/seed differs from actual worker')
            report.setdefault('actor_fixture_bootstraps', []).append(dict(
                match=fields['match'], fixture=plan['actor_fixture'], seed=fields['seed'],
                bootstrap_sha256=fields['bootstrap_sha256'], raw_game_data_sha256=digest(room.match.raw_game_data),
                raw_path=workers[-1]['bootstrap_path'], authority_worker_pid=room.sim.pid,
                delivery_scope='one frozen MatchData BOOTSTRAP broadcast to both clients; native worker CREATE uses same raw bytes'))
        events.append(row)
        require(len(events) <= 30000, 'authority event count exceeds bound')
        audit(event, **{k: v for k, v in row.items() if k != 'event'})

    async def factory(data):
        # Use the existing original worker protocol/class, replacing ONLY its
        # unsafe PID-relookup launch with this retained suspended ownership.
        folder = run / ('authority-' + str(len(workers))); folder.mkdir()
        if fixture_active:
            bootstrap_path = folder / 'actor-bootstrap.pb'
            bootstrap_path.write_bytes(data)
        bootstrap = "import runpy,sys;sys.path.insert(0,sys.argv.pop(1));runpy.run_module('server.simulation_worker',run_name='__main__')"
        argv = [plan['files']['python']['path'], '-I', '-S', '-B', '-u', '-c', bootstrap, str(ROOT), '--stdio']
        environment = os.environ.copy(); environment.pop('BA_ENABLE_SYNTHETIC_WORKER_TESTS', None)
        process, job = spawn_owned(argv, cwd=folder, env=environment, stdin=subprocess.PIPE,
            stdout=subprocess.PIPE, stderr=subprocess.PIPE, bufsize=0, close_fds=True)
        row = dict(process=process, job=job, assigned_before_resume=True, worker=None)
        if fixture_active:
            row.update(bootstrap=data, bootstrap_path=str(bootstrap_path.relative_to(run)))
        workers.append(row)
        worker = SimulationWorker(process, request_timeout=10, close_timeout=5, test_backend=False)
        row['worker'] = worker; worker._job = WorkerJobLease(job, worker)
        try:
            async with worker._lock:
                response, payload = await worker._exchange(ipc.CREATE, -1,
                    {'dll_path': str(assets / 'Simulation.dll')}, data, timeout=45)
                require(not payload and response.get('pid') == process.pid and
                    response.get('game_data_sha256') == digest(data) and
                    response.get('dll_sha256') == SUPPORTED_SIM_SHA256 and
                    response.get('synthetic_test_backend') is False and response.get('ai') is None,
                    'original authority worker CREATE provenance differs')
                worker.game_data_sha256, worker.dll_sha256 = digest(data), response['dll_sha256']
            if plan['scenario'] in ('movement','mobile'):
                original_frame = worker.process_frame
                async def diagnostic_frame(actions, dt_ms=None, w=worker, original=original_frame):
                    return await full_authority_frame(w, original, actions, dt_ms)
                worker.process_frame = diagnostic_frame
            return worker
        except BaseException:
            await worker._abort()
            raise

    original_message = Room.on_message

    async def witnessed_message(room, peer, kind, body):
        result = await original_message(room, peer, kind, body)
        if room.server is server and kind == command_scheduling.BATCH:
            match, sequence, payload = command_scheduling.decode_batch(body)
            key = match, peer.slot, sequence
            require(key not in raw_bodies and len(raw_bodies) < 4096, 'duplicate/unbounded submitted batch capture')
            raw_bodies[key] = payload
        return result

    try:
        for index in range(2):
            (run / f'worker-data-{index}').mkdir()
        pki = generate_test_pki(pki_folder)
        audit = Audit(run)
        template = GameTemplate.load(assets / 'map-1v1.pb.gz', catalog_path=assets / 'unit-catalog.json',
                                     descriptors_path=assets / 'descriptors')
        template = match_template(template, assets, actor_correction=plan.get('actor_correction', False),
                                  mobile_correction=plan.get('mobile_correction',False))
        if fixture_active:
            expected_fixture = mobile_fixture_metadata() if plan.get('mobile_correction') else actor_fixture_metadata()
            require(plan.get('actor_fixture') == expected_fixture, 'prepared actor fixture metadata changed')
            write(run / 'actor-fixture.json', plan['actor_fixture'])
        server = DedicatedServer(template, ProfileStore(run / 'profiles', template, catalog=CosmeticCatalog(assets)),
            templates={1: template}, sim_factory=factory, audit=observe, data_dir=run,
            input_timeout=30, experimental_command_scheduling=True,
            tls_context=tls.load_server_context(pki['cert'], pki['key']),
            admission=admission.AdmissionController(Store()))
        port = (await server.start('127.0.0.1', 0))[1]
        report['endpoint'] = dict(host='127.0.0.1', ephemeral_port=port, tls=True, fixture_identities=2)
        context = tls.load_client_context(pki['ca'], 'localhost')
        runtime = game / 'investigation/runtime'; runtime.mkdir(parents=True, exist_ok=True)
        with mock.patch.object(Room, 'on_message', witnessed_message):
            for index, role in enumerate(('host', 'guest')):
                shaper = StreamShaper(port, rtt_ms=plan['rtt_ms'][index], seed=710 + index,
                                      metadata_limit=8192 if changing is not None and index==plan['move_slot'] else 0)
                shapers.append(shaper); delayed = await shaper.start()
                parent, child = socket.socketpair(socket.AF_INET); parent.setblocking(False)
                try:
                    reader, writer = await asyncio.open_connection(sock=parent)
                except BaseException:
                    parent.close(); child.close()
                    raise
                row = dict(index=index, profile=plan['profiles'][index], child=child, writer=writer,
                           log='', wire=[], launch_tick=int(tick()))
                clients.append(row)
                async def resolve(index=index, delayed=delayed):
                    return bridge.Remote('127.0.0.1', delayed, context, *identities[index])
                config = dict(game_directory=game, server_host='127.0.0.1', server_port=delayed,
                    display_name='Prediction ' + role, room='community', fullscreen=False,
                    local_profile=row['profile'], solo_ai_host='server')
                options = argparse.Namespace(run_name='prediction-' + role, unified_experimental=True,
                    player_features=True, original_command_scheduling_experimental=True)
                argv = launcher.game_arguments(config, None, child.fileno(), options)
                argv[argv.index('-logFile') + 1] = str(run / f'game-{index}.log')
                argv += command_extra(plan, index, run)
                info = subprocess.STARTUPINFO(); info.dwFlags |= subprocess.STARTF_USESHOWWINDOW; info.wShowWindow = 0
                info.lpAttributeList = {'handle_list': [child.fileno()]}
                def before_resume(process, row=row):
                    row['native_path'] = runtime / f'dedicated-native-{process.pid}.log'
                    row['trace'] = runtime / f'frame-timing-{process.pid}.tsv'
                    require(not row['native_path'].exists() and not row['trace'].exists(), 'reused PID evidence is not fresh')
                child.set_inheritable(True)
                try:
                    row['process'], row['job'] = spawn_owned(argv, cwd=game, startupinfo=info,
                        close_fds=True, before_resume=before_resume)
                finally:
                    child.set_inheritable(False); child.close()
                row['assigned_before_resume'] = True
                row['task'] = asyncio.create_task(ObservedBridge(reader, writer, resolve, version=2,
                    evidence=row['wire'], tick=lambda: int(tick())).run())
                write(run / f'client-{index}-process.json', dict(pid=row['process'].pid,
                    profile=row['profile'], launch_tick=row['launch_tick'], command=argv,
                    retained_handle_used=True, assigned_before_resume=True))
            leave_stage, quit_released = 0, False
            while True:
                for row in clients:
                    process = row['process']
                    require(quit_released or process.poll() is None, 'owned game exited before original Quit release')
                    require(quit_released or not row['task'].done(), 'owned bridge stopped before native lifecycle')
                    row['log'] = await asyncio.to_thread(read_fresh_native_log, row['native_path'])
                    require(not any(x in row['log'] for x in ('Movement prediction stopped;',
                        'Native worker request failed:', 'Native worker startup refused:',
                        'Prediction actor repair failed:', 'Prediction selection admission failed:',
                        'Actor correction smoke failed:',
                        'Mobile correction smoke failed:',
                        'Offline loop stopped in ', 'Native Quit probe failed:')),
                        'actual movement client reported failure')
                if changing is not None:
                    changing.update(clients[plan['move_slot']]['log'],shapers[plan['move_slot']])
                require(not any(r['event'] in ('protocol_error', 'match_aborted', 'custom_match_setup_error') for r in events),
                        'owned Custom authority failed')
                created = [r['match'] for r in events if r['event'] == 'match_created']
                require(len(created) <= plan['expected_matches'], 'unexpected extra Custom match')
                if plan['lifecycle'] == 'prefix' and created and all(r['trace'].exists() for r in clients):
                    break  # Forced diagnostic prefix; never natural Quit acceptance.
                if plan['lifecycle'] == 'natural':
                    if leave_stage == 0 and all(COMPLETE in r['log'] for r in clients) and not server.rooms and not server.retired:
                        publish_gate(game, clients[1]['profile'], 'custom-match-leave.ready'); leave_stage = 1
                    elif leave_stage == 1 and 'post-match leave passed: role=guest' in clients[1]['log']:
                        publish_gate(game, clients[0]['profile'], 'custom-match-leave.ready'); leave_stage = 2
                    if not quit_released and leave_stage == 2 and not server.community.lobbies and all(
                            'COMMUNITY MATCH SMOKE post-match leave passed:' in r['log'] for r in clients):
                        for row in clients:
                            publish_gate(game, row['profile'], 'native-quit.ready')
                        quit_released = True
                    if quit_released and all(r['process'].poll() is not None for r in clients):
                        break
                require(time.monotonic() - started < plan['timeout'], 'bounded multiplayer deadline reached')
                await asyncio.sleep(.15)
            require(len(created) == plan['expected_matches'], 'Custom match count differs')
            if server.rooms:
                for room in server.rooms.values():
                    if room.history: room.history.flush()
            report['matches'] = []
            for match in created:
                queued = [r for r in events if r['event'] == 'frame_queued' and r.get('match') == match and r['frame'] < plan['frames']]
                require([r['frame'] for r in queued] == list(range(plan['frames'])), 'canonical prefix incomplete')
                journal = read_journal(run, match, plan['frames'])
                for row in clients:
                    delivered = [r for r in row['wire'] if r['match'] == match and r['frame'] < plan['frames']]
                    require([r['frame'] for r in delivered] == list(range(plan['frames'])) and all(
                        r['payload_sha256'] == queued[r['frame']]['frame_payload_sha256'] for r in delivered),
                        'actual private bridge prefix differs from authoritative frames')
                    receipt = runtime / f'dedicated-receipts-{row["process"].pid}-{match}.tsv'
                    native_receipt_rows[row['index'],match]=read_native_receipts(receipt,pid=row['process'].pid,match=match)
                    receipts=[r for r in native_receipt_rows[row['index'],match]if r['frame']<plan['frames']]
                    require([r['frame'] for r in receipts] == list(range(plan['frames'])) and all(
                        r['sha256'] == queued[r['frame']]['frame_payload_sha256'] for r in receipts),
                        'native65 authority accounting prefix differs')
                    shutil.copyfile(receipt, run / receipt.name)
                report['matches'].append(dict(match=match, canonical_frames=plan['frames'], exact_bridge_and_native_authority_receipts=True))
            for row in clients:
                row['log'] = read_fresh_native_log(row['native_path'])
                evidence = native_evidence(row['log'], matches=created, slot=row['index'], profile=row['profile'],
                                           natural=plan['lifecycle'] == 'natural')
                trace = frame_timing.matches(frame_timing.read_trace(row['trace']))[0]
                prefix = prefix_trace(trace, plan['frames'])
                evidence['timing_capture'] = timing_prefix_counts(prefix, plan['frames'],
                    prediction=plan['scenario'] in ('movement','mobile'),
                    complete_delivery_proven=len(report['matches']) == plan['expected_matches'] and all(
                        m['exact_bridge_and_native_authority_receipts'] for m in report['matches']))
                require(any(r['event'] == 'publication' and r['presented'] >= plan['frames'] - 1 for r in prefix),
                        'actual native output publication did not reach prefix end')
                evidence['first_prefix_timing'] = frame_timing.measure(prefix)
                if plan['lifecycle'] == 'natural':
                    require(row['process'].poll() == 0, 'game did not exit naturally with code0')
                    quit_path = game / '.battleaces-resurrection/profiles' / row['profile'] / 'quit-trace.jsonl'
                    evidence['quit_trace'] = quit_trace_evidence(read(quit_path, 64 * 1024), pid=row['process'].pid,
                        launch_tick=row['launch_tick'], transport=evidence)
                report['clients'].append(dict(index=row['index'], pid=row['process'].pid, profile=row['profile'], **evidence))
            slot = plan['move_slot']; first = created[0]
            if plan.get('transition_orders'):
                for match in created:
                    # A late (<650) order still needs genuine20-frame native
                    # continuation. Retain the FULL journal/state tail through
                    # normal Concede700; never substitute the650 render prefix.
                    count=sum(row['event']=='frame_queued'and row.get('match')==match for row in events)
                    turn_contexts.append(dict(log=clients[slot]['log'],match=match,slot=slot,commits=events,
                        raw_bodies=raw_bodies,journal=read_journal(run,match,count),canonical_states=states[match],
                        canonical_payloads={row['frame']:row['frame_payload_sha256']for row in events
                            if row['event']=='frame_queued'and row.get('match')==match},bridge_frames=clients[slot]['wire'],
                        native_receipts=native_receipt_rows[slot,match]))
            if plan.get('actor_correction'):
                actor_context = dict(log=clients[1]['log'], attacker_log=clients[0]['log'], match=first,
                    commits=events, raw_bodies=raw_bodies, journal=read_journal(run, first, plan['frames']),
                    bridge_frames=clients[1]['wire'], canonical_payloads={r['frame']:r['frame_payload_sha256']
                        for r in events if r['event']=='frame_queued' and r.get('match')==first},
                    canonical_states=states[first], native_states=actor_states[first])
            if plan.get('mobile_correction'):
                for match in created:
                    count = sum(row['event']=='frame_queued' and row.get('match')==match for row in events)
                    mobile_contexts.append(dict(log=clients[1]['log'],attacker_log=clients[0]['log'],match=match,
                        commits=events,raw_bodies=raw_bodies,journal=read_journal(run,match,count),
                        bridge_frames=clients[1]['wire'],canonical_payloads={row['frame']:row['frame_payload_sha256']
                            for row in events if row['event']=='frame_queued' and row.get('match')==match},
                        canonical_states=states[match],native_states=actor_states[match]))
            if plan['scenario'] != 'mobile':
                feel_context = dict(rows=feel_rows(clients[slot]['log']), match=first, slot=slot,
                    commits=events, raw_bodies=raw_bodies, journal=read_journal(run, first, plan['frames']),
                    canonical_states=states[first], bridge_frames=clients[slot]['wire'],
                    catalog_units=template.catalog,entity_abilities=template.entity_abilities,
                    built_units=normal_build_units(clients[slot]['log'],slot))
            if plan['scenario']=='movement':
                subject=[r for r in feel_context['rows']if r['match']==first and r['event']=='command_created']
                require(len(subject)==1,'one subject Move required before independent remote correction')
                other=1-slot
                remote_context=dict(rows=feel_rows(clients[other]['log']),match=first,slot=other,
                    host_world=subject[0]['world'],host_authorities=authority_rows(clients[slot]['log']),
                    host_bridge_frames=clients[slot]['wire'],canonical_payloads={r['frame']:r['frame_payload_sha256']
                        for r in events if r['event']=='frame_queued'and r.get('match')==first},
                    canonical_states=states[first],commits=events,raw_bodies=raw_bodies,journal=feel_context['journal'],
                    catalog_units=template.catalog,entity_abilities=template.entity_abilities,
                    built_units=normal_build_units(clients[other]['log'],other))
            if plan['scenario'] not in ('movement','mobile'):
                report['feel'] = evaluate_feel(**feel_context)
                report['movement_feel_witness_passed'] = report['feel']['passed']
                report['scoped_observation_passed'] = True
    except BaseException as error:
        report.update(error=repr(error), traceback=traceback.format_exc())
    finally:
        errors = []
        worker_state_rows = {}
        for row in clients:
            process, job = row.get('process'), row.get('job')
            if process is not None:
                if process.poll() is None:
                    report['forced_cleanup'] = True
                    await cleanup_step(errors, 'terminate owned game', job.terminate_owned if job else process.terminate)
                await cleanup_step(errors, 'reap owned game', lambda p=process: asyncio.to_thread(p.wait, timeout=10))
            if row.get('task'):
                row['task'].cancel()
            await cleanup_step(errors, 'close child socket', row['child'].close)
        await asyncio.gather(*(r['task'] for r in clients if r.get('task')), return_exceptions=True)
        for row in clients:
            await cleanup_step(errors, 'start private bridge close', row['writer'].close)
            async def finish_writer(row=row):
                try: await asyncio.wait_for(row['writer'].wait_closed(), 2)
                except ConnectionResetError as error:
                    if not normal_peer_eof(error,natural=plan['lifecycle']=='natural',
                                           exited_zero=row.get('process') is not None and row['process'].poll()==0):
                        raise
                    report.setdefault('classified_bridge_eof',[]).append(dict(index=row['index'],
                        pid=row['process'].pid,winerror=error.winerror,classification='normal_peer_quit_eof'))
                finally: row['writer'].transport.abort()
            await cleanup_step(errors, 'close private bridge', finish_writer)
        if server:
            # This is only the local fixture. Finish in-flight native requests
            # before closing, so forced prefix teardown cannot cancel IPC mid-step.
            for room in list(server.rooms.values()):
                if room.state == 'running': room.state = 'completed'
            deadline = time.monotonic() + 5
            while any(r['worker'] and r['worker']._lock.locked() for r in workers) and time.monotonic() < deadline:
                await asyncio.sleep(.01)
            await cleanup_step(errors, 'close local authority', lambda: asyncio.wait_for(server.close(), 30))
        for row in workers:
            worker, process, job = row['worker'], row['process'], row['job']
            if worker: await cleanup_step(errors, 'close authority worker', worker.close)
            elif process.poll() is None: await cleanup_step(errors, 'stop incomplete authority', job.terminate_owned)
            await cleanup_step(errors, 'reap authority', lambda p=process: asyncio.to_thread(p.wait, timeout=10))
            await cleanup_step(errors, 'drain and close authority job', lambda j=job: close_owned_job(j))
            report['authority_workers'].append(dict(pid=process.pid, exit_code=process.poll(),
                assigned_before_resume=True, job=job.final_accounting, forced=job.forced,
                failure=worker.failure if worker else 'incomplete startup'))
            await cleanup_step(errors, 'close authority retained handle', process._handle.Close)
        for shaper in shapers:
            await cleanup_step(errors, 'close stream shaper', lambda s=shaper: asyncio.wait_for(s.close(), 5))
        if changing is not None:
            report['changing_rtt_control'] = changing.snapshot()
            for index,shaper in enumerate(shapers):
                await cleanup_step(errors,'retain payload-free shaper timing',lambda index=index,shaper=shaper:
                    write(run/f'shaper-delay-{index}.json',shaper.delay_metadata()))
        for row in clients:
            process, job = row.get('process'), row.get('job')
            if job:
                await cleanup_step(errors, 'drain and close game job', lambda j=job: close_owned_job(j))
                report['forced_cleanup'] |= job.forced
            if process:
                await cleanup_step(errors, 'retain private bridge hashes', lambda row=row:
                    write(run/f'bridge-wire-{row["index"]}.json',row['wire']))
                if row.get('native_path') and row['native_path'].exists():
                    await cleanup_step(errors, 'retain native log', lambda row=row:
                        (run / f'native-{row["index"]}.log').write_bytes(read(row['native_path'])))
                    if plan['scenario'] in ('movement','mobile'):
                        await cleanup_step(errors,'retain native authority diagnostics',lambda row=row:
                            write(run/f'movement-authorities-{row["index"]}.json',authority_rows(read_fresh_native_log(row['native_path']))))
                        await cleanup_step(errors,'retain original Move diagnostics',lambda row=row:
                            write(run/f'movement-feel-{row["index"]}.json',feel_rows(read_fresh_native_log(row['native_path']))))
                        if plan.get('transition_orders'):
                            await cleanup_step(errors,'retain fresh transition orders',lambda row=row:
                                write(run/f'movement-turns-{row["index"]}.json',transition_rows(read_fresh_native_log(row['native_path']))))
                if row.get('trace') and row['trace'].exists():
                    await cleanup_step(errors, 'retain native timing', lambda row=row:
                        shutil.copyfile(row['trace'], run / row['trace'].name))
                for match in dict.fromkeys(event['match']for event in events if event['event']=='match_created'):
                    receipt=game/'investigation/runtime'/f'dedicated-receipts-{process.pid}-{match}.tsv'
                    if receipt.exists()and not (run/receipt.name).exists():
                        await cleanup_step(errors,'retain native65 accounting on failed capture',
                            lambda receipt=receipt:shutil.copyfile(receipt,run/receipt.name))
                quit_path=game/'.battleaces-resurrection/profiles'/row['profile']/'quit-trace.jsonl'
                if quit_path.exists():
                    await cleanup_step(errors,'retain original Quit trace',lambda row=row,p=quit_path:
                        (run/f'quit-trace-{row["index"]}.jsonl').write_bytes(read(p,64*1024)))
                def close_game_handle(row=row, process=process):
                    process._handle.Close(); row['retained_handle_closed'] = True
                await cleanup_step(errors, 'close game retained handle', close_game_handle)
                report.setdefault('game_cleanup', []).append(dict(index=row['index'], pid=process.pid,
                    exit_code=process.poll(), reaped=process.poll() is not None, assigned_before_resume=True,
                    retained_handle_closed=row.get('retained_handle_closed', False),
                    natural_game_exit=process.poll() == 0 and not (job and job.forced),
                    job=job.final_accounting if job else None))
            if plan['scenario'] in ('movement','mobile'):
                def retain_worker_states(row=row):
                    source = run / f'worker-data-{row["index"]}' / 'canonical-state.jsonl'
                    raw = read(source, 4 * 1024 * 1024)
                    target = run / f'canonical-state-{row["index"]}.jsonl'
                    target.write_bytes(raw)
                    record = dict(index=row['index'], source=str(source), copy=str(target),
                        source_sha256=digest(raw), copy_sha256=sha(target), bytes=len(raw))
                    report.setdefault('worker_state_files', []).append(record)
                    require(record['source_sha256'] == record['copy_sha256'], 'worker state retained copy differs')
                    actual = read_worker_states(target)
                    record.update(rows=len(actual), worlds=list(dict.fromkeys(r['world'] for r in actual)))
                    worker_state_rows[row['index']] = actual
                await cleanup_step(errors, 'retain closed worker native states', retain_worker_states)
        if plan.get('mobile_correction'):
            try:
                from tools.prediction_mobile_evidence import evaluate
                require(len(mobile_contexts)==plan['expected_matches'] and 1 in worker_state_rows,
                        'mobile correction lacks both actual match contexts or closed victim states')
                episodes = [evaluate(**context,worker_states=worker_state_rows[1],escape_check=actor_escape_evidence,
                                    join_check=joined_worker_evidence,authority_rows=authority_rows)
                            for context in mobile_contexts]
                report['mobile_correction'] = dict(passed=all(row['passed'] for row in episodes),episodes=episodes)
            except BaseException as error:
                report['mobile_correction'] = dict(passed=False,error=repr(error),
                    scope='No substituted mobile lifecycle, input or correction evidence')
        if plan.get('mobile_group_intent'):
            try:
                from tools.prediction_mobile_evidence import evaluate_group_intent
                report['mobile_group_intent'] = evaluate_group_intent(clients[1]['log'],attacker_log=clients[0]['log'],
                    mobile_episodes=report.get('mobile_correction',{}).get('episodes',[]),
                    user_edits=bool(plan.get('mobile_group_user_edits')))
                report['group_intent_witness_passed']=report['mobile_group_intent']['passed']
            except BaseException as error:
                report['mobile_group_intent']=dict(passed=False,error=repr(error),
                    scope='No substituted group preservation, explicit original edits or canonical death purge')
                report['group_intent_witness_passed']=False
        if plan.get('mobile_recovery_stall'):
            try:
                from tools.prediction_mobile_evidence import evaluate_recovery_stall
                report['mobile_recovery_stall']=evaluate_recovery_stall(clients[1]['log'],attacker_log=clients[0]['log'],
                    matches=[event['match'] for event in events if event['event']=='match_created'])
                report['recovery_stall_witness_passed']=report['mobile_recovery_stall']['passed']
            except BaseException as error:
                report['mobile_recovery_stall']=dict(passed=False,error=repr(error),
                    scope='No substituted stall marker, original snapshot bracket or QPC elapsed time')
                report['recovery_stall_witness_passed']=False
        if plan.get('mobile_recall'):
            try:
                from tools.prediction_mobile_evidence import evaluate_group_recall
                report['mobile_recall']=evaluate_group_recall(clients[1]['log'],attacker_log=clients[0]['log'],
                    mobile_episodes=report.get('mobile_correction',{}).get('episodes',[]),
                    group_intent=report.get('mobile_group_intent',{}))
                report['recall_witness_passed']=report['mobile_recall']['passed']
            except BaseException as error:
                report['mobile_recall']=dict(passed=False,error=repr(error),
                    scope='No substituted original recall callback, absent admission filter or restored selection')
                report['recall_witness_passed']=False
        if plan['scenario'] == 'mobile':
            try:
                finalize_mobile_observation(report,plan,states=states,worker_state_rows=worker_state_rows,
                    client_logs={row['index']:row['log']for row in clients})
            except BaseException as error:
                report.setdefault('error',repr(error))
                report['mobile_input_witness_passed']=False
                report['scoped_observation_passed']=False
        if plan.get('native_position_trace') is not None:
            try:
                slot = plan['move_slot']
                source = run / f'worker-data-{slot}' / 'native-positions.jsonl'
                target = run / f'native-positions-{slot}.jsonl'
                raw = read(source, 16 * 1024 * 1024)
                target.write_bytes(raw)
                require(digest(raw) == sha(target), 'closed native position copy differs')
                report['native_position_file'] = dict(source=str(source), copy=str(target), sha256=digest(raw), bytes=len(raw))
                report['native_position_trace'] = native_position_evidence(target, log=clients[slot]['log'],
                    matches=created, slot=slot, specification=plan['native_position_trace'], contexts=turn_contexts,
                    catalog_units=template.catalog, entity_abilities=template.entity_abilities)
            except BaseException as error:
                report['native_position_trace'] = dict(passed=False, error=repr(error), scope='No substituted native position or renderer-cause evidence')
        if plan['scenario'] == 'movement' and feel_context is not None and 'error' not in report:
            try:
                if plan.get('actor_correction'):
                    require(actor_context is not None and 1 in worker_state_rows, 'victim actor native-state file unavailable')
                    report['actor_correction'] = actor_correction_evidence(**actor_context, worker_states=worker_state_rows[1])
                require(plan['move_slot'] in worker_state_rows, 'selected closed worker native-state file unavailable')
                report['command_phase']=command_phase(feel_context['rows'],match=feel_context['match'],
                    slot=feel_context['slot'],commits=events)
                report['feel'] = evaluate_feel(**feel_context, worker_states=worker_state_rows[plan['move_slot']])
                require(remote_context is not None,'independent other-player correction fixture missing')
                require(report['feel']['canonical_commit_frame']<command_phase(remote_context['rows'],match=remote_context['match'],
                    slot=remote_context['slot'],commits=events)['canonical_commit_frame'],
                    'independent remote Move must follow subject Move')
                report['remote_correction']=evaluate_remote_correction(**remote_context,
                    host_worker_states=worker_state_rows[plan['move_slot']])
                report['movement_feel_witness_passed'] = report['feel']['passed']and report['remote_correction']['passed']
                def collect_independent():
                    if changing is not None:
                        report['changing_rtt_observation'] = changing_rtt_evidence(clients[plan['move_slot']]['log'],
                            report['changing_rtt_control'],created,require_sampled_us=plan.get('changing_pose_clock')=='sampled_us',
                            publication_source=plan.get('publication_source'),publication_trace=(
                                frame_timing.read_trace(clients[plan['move_slot']]['trace'])
                                if plan.get('publication_source')=='post-original-qpc'else None))
                        report['changing_rtt_smoothness_passed'] = report['changing_rtt_observation']['passed']
                        other=1-plan['move_slot']
                        try:
                            report['changing_rtt_other_client_feel'] = evaluate_feel(remote_context['rows'],
                                match=remote_context['match'],slot=other,commits=events,raw_bodies=raw_bodies,
                                journal=remote_context['journal'],canonical_states=remote_context['canonical_states'],
                                worker_states=worker_state_rows[other],bridge_frames=clients[other]['wire'],
                                catalog_units=template.catalog,entity_abilities=template.entity_abilities,
                                built_units=normal_build_units(clients[other]['log'],other))
                        except AssertionError as error:
                            report['changing_rtt_other_client_feel'] = dict(passed=False,error=repr(error),
                                scope='Other owned original unit readiness/Move-before-authority is unqualified; no substituted movement')
                        if plan.get('transition_orders'):
                            try:
                                require(len(turn_contexts)==plan['expected_matches'],'transition order match contexts incomplete')
                                episodes=[transition_order_evidence(control=report['changing_rtt_control'],
                                    worker_states=worker_state_rows[plan['move_slot']],**context)for context in turn_contexts]
                                report['transition_orders'] = dict(passed=all(row['passed']for row in episodes),episodes=episodes)
                            except AssertionError as error:
                                report['transition_orders'] = dict(passed=False,error=repr(error),
                                    scope='Fresh transition input remains unqualified; no synthetic direction/phase/state evidence')
                finalize_movement_observation(report,collect_independent)
            except BaseException as error:
                report.update(error=repr(error), traceback=traceback.format_exc(), scoped_observation_passed=False)
        if pki: await cleanup_step(errors, 'remove ephemeral PKI', lambda: remove_test_pki(pki_folder))
        if audit: await cleanup_step(errors, 'close fixture audit', audit.close)
        report['source_unchanged'] = report['files_unchanged'] = False
        try:
            report['source_sha256_at_finish'] = source_hashes()
            report['source_unchanged'] = report['source_sha256_at_start'] == report['source_sha256_at_finish']
            report['files_unchanged'] = all(sha(r['path']) == r['sha256'] for r in
                list(plan['files'].values()) + list(plan['asset_files'].values()))
        except BaseException as error:
            errors.append(dict(step='final source/binary identity', error=repr(error)))
        report['cleanup_errors'] = errors
        report['elapsed_seconds'] = time.monotonic() - started
        report['teardown_scope'] = ('original result/Continue/Leave/Quit required' if plan['lifecycle'] == 'natural'
                                    else 'forced owned prefix teardown; no native Quit or acceptance claim')
        report['passed'] = bool(report['scoped_observation_passed'] and report['source_unchanged'] and
            (plan['scenario'] != 'mobile' or mobile_final_gate(plan,report)) and
            (changing is None or (report.get('changing_rtt_smoothness_passed') is True and
             report.get('changing_rtt_other_client_feel',{}).get('passed') is True)) and
            (not plan.get('transition_orders')or report.get('transition_orders',{}).get('passed')is True)and
            (not plan.get('mobile_correction')or report.get('mobile_correction',{}).get('passed')is True)and
            (plan.get('native_position_trace') is None or report.get('native_position_trace',{}).get('passed') is True)and
            report['files_unchanged'] and not report['forced_cleanup'] and not errors and
            len(report.get('game_cleanup', [])) == 2 and all(r['reaped'] and r['retained_handle_closed'] and r['exit_code'] == 0 and
            r['job'] and r['job']['active'] == r['job']['terminated'] == 0 for r in report['game_cleanup']) and
            len(workers) == plan['expected_matches'] and all(r['exit_code'] == 0 and not r['failure'] and
            not r['forced'] and r['job'] and r['job']['active'] == r['job']['terminated'] == 0
            for r in report['authority_workers']))
        write(run / 'verification.json', report)
        write(run / 'server-states.json', dict(states))
        if fixture_active:
            write(run / 'actor-native-authority.json', dict(actor_states))
        body_dir = run / 'submitted-batches'; body_dir.mkdir()
        for (match, slot, sequence), body in raw_bodies.items():
            (body_dir / f'{match}-{slot}-{sequence}.pb').write_bytes(body)
    return report


def startup_failure_scope(previous,plan,invocation_sha256):
    """Only the retained early-log parser failure and normal peer EOF qualify."""
    require(previous.get('passed') is False and previous.get('error')==
        "AssertionError('one actual Job-owned movement worker route required')",
        'reanalysis only repairs the retained early-route parser failure')
    require(plan.get('scenario')=='startup' and plan.get('lifecycle')=='natural' and
        plan.get('frames')==200 and plan.get('expected_matches')==2 and
        previous.get('scenario')=='startup' and previous.get('lifecycle')=='natural',
        'reanalysis requires the bounded two-round natural startup scenario')
    require(previous.get('invocation_sha256')==invocation_sha256 and
        previous.get('source_unchanged') is True and previous.get('files_unchanged') is True and
        previous.get('source_sha256_at_start')==previous.get('source_sha256_at_finish')==plan['source_sha256'],
        'original invocation/source/file bindings differ')
    require(previous.get('forced_cleanup') is False and previous.get('clients')==[],
        'original failure occurred outside the explained pre-client parser gate')
    for key in ('game_cleanup','authority_workers'):
        rows=previous.get(key,[])
        require(len(rows)==2 and all(row.get('exit_code')==0 and
            row.get('assigned_before_resume') is True and row.get('job') and
            row['job']['active']==row['job']['terminated']==0 for row in rows),
            'original owned process/Job teardown was not natural and complete')
    require(all(row.get('reaped') is True and row.get('retained_handle_closed') is True and
        row.get('natural_game_exit') is True for row in previous['game_cleanup']) and
        all(row.get('forced') is False and row.get('failure') is None for row in previous['authority_workers']),
        'original native process teardown contains failure/force')
    errors=previous.get('cleanup_errors',[])
    require(len(errors)==2 and all(recorded_peer_eof(row) for row in errors),
        'unexplained original cleanup failure remains')
    matches=previous.get('matches',[])
    require(len(matches)==2 and len({row.get('match') for row in matches})==2 and all(
        row.get('canonical_frames')==200 and row.get('exact_bridge_and_native_authority_receipts') is True
        for row in matches),'original bridge/native prefix gate was not already passed')
    return [row['match'] for row in matches]


def reanalyze_startup(source,output,*,expected_failed_report_sha256,expected_invocation_sha256):
    """File-only correction. Preserve every original report/capture and fail closed.

    Old raw Bridge arrays were not retained. Reuse only its source-bound, already
    passed predicate; independently reparse journals/native65 receipts/audit and
    lifecycle evidence. This is startup integration, never movement-feel proof.
    """
    source,output=Path(source).resolve(strict=True),Path(output).resolve()
    require(source.is_relative_to((ROOT/'local').resolve()) and
        output.is_relative_to((ROOT/'local').resolve()) and not os.path.lexists(output) and
        not output.is_relative_to(source/'run') and not output.is_relative_to(source/'source-at-prepare') and
        not output.is_relative_to(ROOT/'local/prediction-runtime/game'),
        'fresh separate ignored reanalysis output required')
    for pin in (expected_failed_report_sha256,expected_invocation_sha256):
        require(type(pin) is str and HEX64.fullmatch(pin),'explicit reanalysis SHA256 pins required')
    output.mkdir(parents=True,exist_ok=False)
    inputs={}
    def pin(path):
        path=Path(path).resolve(strict=True)
        value=dict(sha256=sha(path),bytes=path.stat().st_size)
        require(str(path) not in inputs or inputs[str(path)]==value,'original input changed while reanalyzing')
        inputs[str(path)]=value
        return path
    def retain(path,name,maximum=MAX_LOG):
        path=pin(path);target=output/name;target.parent.mkdir(parents=True,exist_ok=True)
        with target.open('xb') as stream:stream.write(read(path,maximum))
        require(sha(target)==inputs[str(path)]['sha256'],'reanalysis evidence copy differs')
        return target
    report=dict(passed=False,file_only=True,native_executed=False,scenario='startup',
        lifecycle='natural',full_feature_accepted=False,movement_feel_witness_passed=False,
        scope='Two owned Unity Custom rounds/terminal drain/Continue/Leave/original Quit; no visible movement claim',
        original_report_preserved=True,source=str(source),clients=[],matches=[])
    try:
        failed=pin(source/'run/verification.json');invocation=pin(source/'invocation.json')
        require(sha(failed)==expected_failed_report_sha256 and sha(invocation)==expected_invocation_sha256,
                'explicit failed report/invocation pins differ')
        previous=json.loads(read(failed,2*1024*1024));plan=json.loads(read(invocation,2*1024*1024))
        created=startup_failure_scope(previous,plan,sha(invocation))
        game=Path(plan['game']).resolve(strict=True);runtime=game/'investigation/runtime';run=source/'run'
        require(game==(ROOT/'local/prediction-runtime/game').resolve() and
            Path(plan['output']).resolve()==source,'original scenario ownership paths differ')
        retain(failed,'original-failed-report.json');retain(invocation,'original-invocation.json')
        require(1<=len(plan['source_sha256'])<=8192,'original source inventory outside bound')
        for name,expected in plan['source_sha256'].items():
            path=(source/'source-at-prepare'/name).resolve(strict=True)
            require(path.is_relative_to(source/'source-at-prepare') and sha(pin(path))==expected,
                    'original prepared source snapshot differs: '+name)
        # Only parsers used below must equal their retained versions. Product
        # sources may have moved on; their at-run versions/binaries stay pinned.
        parsers=('tools/frame_timing.py','tools/verify_high_latency_clients.py',
            'tools/verify_original_command_scheduling.py','tools/verify_prediction_client_worker.py',
            'server/game_data.py','server/protobuf_wire.py','server/native_simulation.py','server/protocol.py')
        for name in parsers:
            require(sha(pin(ROOT/name))==plan['source_sha256'][name],'reanalysis parser changed: '+name)
        old_tool=source/'source-at-prepare/tools/verify_prediction_multiplayer.py'
        def function_text(path,name):
            text=read(path).decode('utf-8');tree=ast.parse(text)
            return ast.get_source_segment(text,next(n for n in tree.body if isinstance(n,ast.FunctionDef) and n.name==name))
        require(function_text(old_tool,'native_evidence')==function_text(Path(__file__),'native_evidence'),
                'native lifecycle parser changed from original predicate')
        for row in list(plan['files'].values())+list(plan['asset_files'].values()):
            require(sha(pin(row['path']))==row['sha256'],'original binary/asset identity changed')
        from tools import frame_timing
        from tools.verify_high_latency_clients import prefix_trace
        from tools.verify_original_command_scheduling import read_journal
        from server.native_simulation import decode_snapshot
        events=[json.loads(line) for line in read(pin(run/'events.jsonl'),4*1024*1024).splitlines()]
        states=json.loads(read(pin(run/'server-states.json'),2*1024*1024))
        require([row['match'] for row in events if row['event']=='match_created']==created and not any(
            row['event'] in ('protocol_error','match_aborted','custom_match_setup_error') for row in events),
            'retained authority match/order/failure evidence differs')
        processes=[]
        for index in range(2):
            process=json.loads(read(pin(run/f'client-{index}-process.json')));processes.append(process)
            require(process['profile']==plan['profiles'][index] and process['retained_handle_used'] is True and
                process['assigned_before_resume'] is True and process['pid']==previous['game_cleanup'][index]['pid'],
                'retained process identity differs')
        for match in created:
            queued=[r for r in events if r['event']=='frame_queued' and r.get('match')==match]
            require([r['frame'] for r in queued]==list(range(len(queued))) and len(queued)>=200,
                    'retained canonical frames incomplete')
            for row in queued:
                require(states[match][str(row['frame'])]==row['parsed_state_sha256'] and
                    HEX64.fullmatch(row['parsed_state_sha256']),'server state digest journal differs')
            for name in ('frames.bin','bootstrap.pb.gz','match.json'):pin(run/'matches'/match/name)
            journal=read_journal(run,match,len(queued))
            require(len(journal)==len(queued),'authoritative input journal incomplete')
            for index,process in enumerate(processes):
                receipt=retain(run/f'dedicated-receipts-{process["pid"]}-{match}.tsv',
                               f'receipts/{process["pid"]}-{match}.tsv')
                with receipt.open(encoding='utf-8') as stream:
                    rows=[r for r in csv.DictReader(stream,delimiter='\t') if int(r['frame'])<200]
                require([int(r['frame']) for r in rows]==list(range(200)) and all(
                    r['match']==match and int(r['pid'])==process['pid'] and
                    r['sha256']==queued[int(r['frame'])]['frame_payload_sha256'] for r in rows),
                    'reparsed native65 receipts differ from canonical200 prefix')
                audit=retain(runtime/f'lan-audit-{process["pid"]}-{match}.tsv',f'audit/{index}-{match}.tsv')
                with audit.open(encoding='utf-8') as stream:audit_rows=list(csv.DictReader(stream,delimiter='\t'))
                snapshots=[r for r in events if r['event']=='native_snapshot' and r.get('match')==match and r['frame']<200]
                require(snapshots,'no retained server prefix snapshots')
                for row in snapshots:
                    path=pin(run/'matches'/match/'snapshots'/f'{row["frame"]:08d}-{row["viewer"]}.bin')
                    raw=read(path);decoded=decode_snapshot(raw,row['viewer'])
                    require(sha(path)==row['sha256'] and decoded['canonical_fnv1a64']==row['canonical_fnv1a64'],
                            'retained authority snapshot/hash differs')
                    matching=[r for r in audit_rows if int(r['frame'])==row['frame'] and int(r['viewer'])==row['viewer']]
                    require(matching and all(int(r['pid'])==process['pid'] and
                        r['canonical_fnv1a64']==decoded['canonical_fnv1a64'] for r in matching),
                        'sampled native canonical field audit differs from original authority')
            report['matches'].append(dict(match=match,canonical_frames=200,
                native_receipts_reparsed=True,input_journal_frames=len(journal),
                sampled_client_authority_canonical_fields=True,
                bridge_scope='Source-bound original already-passed200-frame exact bridge predicate; raw bridge arrays not retained'))
        for index,process in enumerate(processes):
            pid=process['pid'];live=runtime/f'dedicated-native-{pid}.log';saved=run/f'native-{index}.log'
            require(sha(pin(live))==sha(pin(saved)),'full retained/raw native logs differ')
            native=retain(live,f'native-full-{index}.log');log=read_fresh_native_log(native)
            require(log and all(int(value)>=process['launch_tick'] for value in re.findall(r'^\[(\d+)\]',log,re.M)),
                    'full native log predates owned launch')
            require('Prediction selection admission failed:' not in log,'native selection admission failure')
            evidence=native_evidence(log,matches=created,slot=index,profile=process['profile'],natural=True)
            ready=re.findall(r'Movement prediction ready: generation=(\d+) match=([a-f0-9]{32}) world=(\d+) slot=(\d+) ',log)
            require([int(r[0]) for r in ready]==[1,2],'native generation progression differs')
            drained=re.findall(r'Movement terminal drain complete: match=([a-f0-9]{32}) confirmed=(\d+) physical=(\d+) presented=(\d+) target=(\d+)',log)
            require([r[0] for r in drained]==created,'two native terminal drains required')
            for match,confirmed,physical,presented,target in drained:
                completed=[r for r in events if r['event']=='match_completed' and r.get('match')==match]
                require(len(completed)==1 and completed[0]['reason']=='native game complete' and
                    int(confirmed)==completed[0]['next_frame']-1 and int(presented)>=int(target)==int(physical) and
                    0<=int(physical)-int(confirmed)<=13,'native terminal/authority watermark differs')
            timing=pin(run/f'frame-timing-{pid}.tsv')
            prefix=prefix_trace(frame_timing.matches(frame_timing.read_trace(timing))[0],200)
            require(all([r['frame'] for r in prefix if r['event']==event]==list(range(200)) for event in ('arrival','apply')) and
                any(r['event']=='publication' and r['presented']>=199 for r in prefix),'native200-frame physical prefix incomplete')
            quit_path=retain(game/'.battleaces-resurrection/profiles'/process['profile']/'quit-trace.jsonl',f'quit-trace-{index}.jsonl',64*1024)
            evidence['quit_trace']=quit_trace_evidence(read(quit_path,64*1024),pid=pid,
                launch_tick=process['launch_tick'],transport=evidence)
            evidence.update(index=index,pid=pid,profile=process['profile'],terminal_drains=drained,
                first_prefix_timing=frame_timing.measure(prefix))
            report['clients'].append(evidence)
        report.update(passed=True,scoped_observation_passed=True,forced_cleanup=False,
            game_cleanup=previous['game_cleanup'],authority_workers=previous['authority_workers'],
            explained_reclassifications=['Whole fresh native log restores early route/18bindings',
                'Two ConnectionResetError WinError64/10054 after proven normal peer Quit are EOF'],
            classified_bridge_eof=previous['cleanup_errors'],cleanup_errors=[])
    except BaseException as error:
        report.update(passed=False,error=repr(error),traceback=traceback.format_exc())
    finally:
        changed=[]
        for path,row in inputs.items():
            try:
                if not Path(path).is_file() or sha(path)!=row['sha256']:changed.append(path)
            except Exception as error:changed.append(dict(path=path,error=repr(error)))
        report['original_inputs_unchanged']=not changed;report['changed_inputs']=changed
        if changed:report['passed']=False
        report['input_sha256']=inputs;report['reanalysis_tool_sha256']=sha(__file__)
        write(output/'verification.json',report)
    return report


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--run-prepared', type=Path, help='Explicit coordinated native execution; preparation is default')
    parser.add_argument('--reanalyze-startup',type=Path,help='File-only retained natural startup parser/EOF correction')
    parser.add_argument('--reanalysis-output',type=Path)
    parser.add_argument('--expected-failed-report-sha256')
    parser.add_argument('--expected-invocation-sha256')
    for name in ('game', 'assets', 'output', 'python', 'module-root', 'heap-helper', 'cooperative', 'helper-build-receipt'):
        parser.add_argument('--' + name, type=Path)
    parser.add_argument('--worker-package', type=Path,
                        help='Owned frozen private package; bind all files and use its actual worker imports/runtime')
    parser.add_argument('--expected-helper-sha256'); parser.add_argument('--expected-gameassembly-sha256')
    parser.add_argument('--scenario', choices=('startup', 'movement', 'mobile'), default='startup')
    parser.add_argument('--lifecycle', choices=('natural', 'prefix'), default='natural')
    parser.add_argument('--frames', type=int); parser.add_argument('--timeout', type=float, default=180)
    parser.add_argument('--rtt-ms', type=float, nargs=2, default=(130, 475))
    parser.add_argument('--move-slot', type=int, choices=(0, 1), default=0)
    parser.add_argument('--actor-correction', action='store_true',
                        help='Explicit original Gunbot Move12/Core5 fixture; both clients use the same authored bootstrap')
    parser.add_argument('--mobile-correction', action='store_true',
                        help='Explicit Gunbot10/11 fixture: original mobile group/focus death, correction and fresh Move')
    parser.add_argument('--mobile-group-intent', action='store_true',
                        help='With mobile scenario only: retained original manual group through provisional absence and canonical death purge')
    parser.add_argument('--mobile-group-user-edits', action='store_true',
                        help='With mobile group intent: original Clear in round1 and original empty replace in round2 during absence')
    parser.add_argument('--mobile-recovery-stall', action='store_true',
                        help='With mobile group user edits: one owned250ms main-thread hold after victim world2 snapshot152')
    parser.add_argument('--mobile-recall', action='store_true',
                        help='With retained mobile group intent: original recall during absence and again after restored admission')
    parser.add_argument('--changing-rtt', action='store_true',
                        help='Owned ordinary650-frame movement: subject future-read130->475->130ms while original48-unit Move is unfinished')
    parser.add_argument('--transition-orders', action='store_true',
                        help='With --changing-rtt only: new original subject reversals immediately afterfall and after measured recovery')
    parser.add_argument('--native-position-trace', metavar='ID:TYPE:ARMY:FIRST:LAST',
                        help='With changing RTT/transition orders: copy the subject native identity from existing decoded queries')
    args = parser.parse_args(argv)
    if args.reanalyze_startup:
        require(not args.run_prepared and args.reanalysis_output is not None,'file-only reanalysis cannot launch native')
        report=reanalyze_startup(args.reanalyze_startup,args.reanalysis_output,
            expected_failed_report_sha256=args.expected_failed_report_sha256,
            expected_invocation_sha256=args.expected_invocation_sha256)
        print(json.dumps({k:report[k] for k in ('passed','file_only','native_executed','scoped_observation_passed',
            'full_feature_accepted','original_inputs_unchanged','error') if k in report}))
        return 0 if report['passed'] else 1
    if args.run_prepared:
        report = asyncio.run(run_prepared(args.run_prepared))
        print(json.dumps({k: report[k] for k in ('passed', 'scoped_observation_passed', 'movement_feel_witness_passed',
            'mobile_input_witness_passed','group_intent_witness_passed','recovery_stall_witness_passed','recall_witness_passed','generic_movement_not_exercised',
            'full_feature_accepted', 'forced_cleanup', 'error') if k in report}))
        return 0 if report['passed'] else 1
    required = ('game', 'assets', 'output', 'python', 'module_root', 'heap_helper', 'cooperative', 'helper_build_receipt',
                'expected_helper_sha256', 'expected_gameassembly_sha256')
    require(all(getattr(args, k) is not None for k in required), 'all preparation paths and explicit binary pins required')
    invocation = prepare(args)
    print(json.dumps(dict(prepared=True, native_executed=False, output=invocation['output'],
                         scenario=invocation['scenario'], full_feature_accepted=False)))
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
