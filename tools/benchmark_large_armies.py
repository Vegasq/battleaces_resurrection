"""Owned native large-army workloads; no game UI, listeners or host profiles.

Normal HQ builds and the original supply limit are retained. Optional accelerated
income is an explicit staging modifier, NOT ordinary economy or spawned units.
RPC timings include IPC; they do not independently measure native compute time.
Recorded replay checks every parsed observable state field, not hidden DLL state.
"""
from __future__ import annotations

import argparse
import asyncio
from dataclasses import replace
import gzip
import hashlib
import json
import math
import os
from pathlib import Path
import platform
import random
import statistics
import struct
import subprocess
import sys
import time
import traceback

from server.assets import verify_assets
from server.game_data import GameTemplate, InputValidation, canonical_gzip, encode_frame, encode_player_input
from server.protobuf_wire import field_bytes, field_packed_uint, field_uint, get_bytes, get_repeated_bytes, get_uint, replace_fields
from server.worker_ai import AISetup
from server.worker_client import SimulationWorker

ROOT = Path(__file__).resolve().parents[1]
Q32 = 1 << 32
LOADS = {'small': 0.1, 'medium': 0.5, 'large': 1.0}
MAPS = {1: 'map-1v1.pb.gz', 2: 'map-2v2.pb.gz', 5: 'map-2vai.pb.gz'}
MAX_FRAMES = 32000
MAX_FRAME_BYTES = 4 * 65536 + 1024


def require(condition, message):
    if not condition:
        raise ValueError(message)


def digest(data):
    return hashlib.sha256(data).hexdigest()


def state_digest(state):
    # Raw FlatBuffer storage may contain nonsemantic bytes; preserve and compare
    # ALL parsed fields, including entities, resources, result and canonical hash.
    return digest(json.dumps({k: v for k, v in state.items() if k != 'raw_sha256'},
                             sort_keys=True, separators=(',', ':'), allow_nan=False).encode())


def source_hashes():
    paths = sorted((ROOT/'server').glob('*.py')) + [Path(__file__)]
    for name in ('tools/profile_worker_timing.py', 'tools/summarize_worker_timing.py'):
        path = ROOT/name
        if path.exists():
            paths.append(path)
    return {p.relative_to(ROOT).as_posix(): digest(p.read_bytes()) for p in paths}


def summary(values):
    values = sorted(values)
    if not values:
        return {'count': 0}
    def percentile(p):
        return values[max(0, math.ceil(p*len(values))-1)]
    return dict(count=len(values), minimum=values[0], mean=statistics.fmean(values),
                p50=percentile(.50), p95=percentile(.95), p99=percentile(.99), maximum=values[-1],
                above_50ms=sum(v > 50 for v in values), above_100ms=sum(v > 100 for v in values))


def execute(entity_type, ability, ids, command):
    require(ids and len(ids) <= 200, 'command unit group outside supported benchmark bound')
    group = field_uint(1, entity_type) + field_uint(2, ability) + field_packed_uint(3, ids)
    return field_bytes(1, field_bytes(1, group) + field_bytes(3, command))


def ground_command(x, z):
    require(all(math.isfinite(v) and abs(v) <= 10000 for v in (x, z)), 'invalid movement coordinates')
    position = b''.join(field_uint(n, round(v*Q32) & ((1 << 64)-1)) for n, v in ((1, x), (2, 0), (3, z)))
    return field_bytes(3, field_bytes(1, position))


def configure_match(template, *, load, unit_id, opponent, profile, seed, multiplier, bot_choices=None):
    require(load in LOADS and unit_id in (1, 2, 75) and opponent in ('scripted', 'ai'), 'invalid workload')
    require(type(multiplier) is int and 1 <= multiplier <= 16, 'resource multiplier outside1..16')
    capacity = get_uint(template.global_config, 12)
    cost = template.catalog[unit_id]['supply_cost_raw']
    require(capacity > 0 and cost > 0 and capacity % Q32 == 0 and cost % Q32 == 0,
            'normal supply limit/cost must be positive integral Q32.32')
    target = math.floor(capacity * LOADS[load] / cost)
    require(1 <= target <= 200, 'target army outside supported benchmark bound')
    slots = tuple(sorted(template.armies))
    require(slots in ((0, 1), (0, 1, 2, 3)) and template.game_mode in MAPS, 'unsupported benchmark topology')
    require(template.game_mode != 5 or opponent == 'ai', 'mode5 requires original AI opponents')
    scripted = slots if opponent == 'scripted' else tuple(s for s in slots if s % 2 == 0)
    bot_slots = set(slots)-set(scripted)
    if len(slots) == 4 and bot_slots:
        require(bot_choices is not None and set(bot_choices) == bot_slots,
                'team AI requires original mode-compatible catalog choices')
    else:
        require(bot_choices is None, 'catalog choices only supported for the team AI arm')
    choices = bot_choices or {}
    bots = {s: choices[s].profile if s in choices else profile for s in bot_slots}
    decks = {s: choices[s].deck.units if s in choices else
             template.validate_deck((unit_id, *template.default_decks[s][1:])) for s in slots}
    roster = [dict(slot=s, name=choices[s].name if s in choices else f'Benchmark {s}', ai_profile_id=bots.get(s, 0))
              for s in slots]
    match = template.build_match(roster, decks, seed=seed, game_name='owned-large-army-benchmark', bot_choices=bot_choices)
    if multiplier != 1:
        # Same authored ArmyModifiers.resourcing_multiplier used by promo staging.
        # No cost, supply cap, health, damage, map or spawn configuration changes.
        armies = {}
        for slot, army in match.armies_by_slot.items():
            modifiers = get_bytes(army, 7)
            baseline = get_uint(modifiers, 1) if modifiers else Q32
            require(baseline == Q32, 'accelerated staging requires normal1x army income baseline')
            modifiers = replace_fields(modifiers, {1: [field_uint(1, baseline*multiplier)]})
            armies[slot] = replace_fields(army, {7: [field_bytes(7, modifiers)]})
        config = replace_fields(match.game_config, {2: [field_bytes(2, armies[s]) for s in sorted(armies)]})
        raw = replace_fields(match.raw_game_data, {1: [field_bytes(1, config)]})
        compressed = canonical_gzip(raw)
        match = replace(match, raw_game_data=raw, gzip_game_data=compressed, game_config=config,
                        raw_sha256=digest(raw), sha256=digest(compressed), armies_by_slot=armies)
    return match, dict(load=load, unit_id=unit_id, target_units_per_scripted_army=target,
                      normal_supply_capacity=capacity//Q32, unit_supply_cost=cost//Q32,
                      resource_multiplier=multiplier, ordinary_economy=multiplier == 1,
                      spawned_units=False, original_supply_limit=True, opponent=opponent,
                      ai_profile=profile if opponent == 'ai' and len(slots) == 2 else None, seed=seed,
                      mode=template.game_mode, player_count=len(slots), scripted_armies=list(scripted),
                      ai_profiles={str(s): p for s, p in sorted(bots.items())},
                      alliances={str(s): template.alliances[s] for s in slots},
                      decks={str(s): list(match.decks_by_slot[s]) for s in slots},
                      normal_unit_ids=sorted(u for u in template.allowed_entity_ids
                                             if template.catalog[u]['supply_cost_raw'] > 0))


def team_choices(assets, template, seed):
    from server.ai_rules import RuleBook
    from server.bot_catalog import BotCatalog
    catalog = BotCatalog(assets, template=template, rules=RuleBook(assets))
    generator, choices, names = random.Random(seed), {}, []
    for slot in sorted(s for s in template.armies if s % 2):
        choice = catalog.choose(template.game_mode, role='opponents', excluded_names=names,
                                difficulty='normal', randbelow=generator.randrange)
        choices[slot] = choice
        names.append(choice.name)
    return choices


class Workload:
    def __init__(self, template, match, spec, setup_frames, measure_frames):
        self.template, self.match, self.spec = template, match, spec
        self.setup_frames, self.measure_frames = setup_frames, measure_frames
        self.phase, self.phase_frame = 'setup', 0
        self.phase_start = None
        self.entities, self.hqs = {}, {}
        self.validator = InputValidation(match, template, entity_lookup=self.owner)
        self.slots = tuple(range(spec.get('player_count', 2)))
        self.scripted = tuple(spec.get('scripted_armies', self.slots if spec['opponent'] == 'scripted' else (0,)))
        self.reached_frame = None

    def owner(self, entity_id):
        entity = self.entities.get(entity_id)
        return None if entity is None else (entity.get('army'), entity.get('type'))

    def units(self, slot):
        return [e for e in self.entities.values() if e.get('army') == slot and e.get('type') == self.spec['unit_id']]

    def opponents(self, slot):
        alliances = self.spec.get('alliances', {str(s): s % 2 for s in self.slots})
        return tuple(s for s in self.slots if alliances[str(s)] != alliances[str(slot)])

    def update(self, state, frame):
        self.entities = {e['id']: e for e in state['entities']}
        for slot in self.slots:
            hq = next((e for e in state['entities'] if e.get('army') == slot and e.get('type') == 3), None)
            if hq and 'position' in hq:
                self.hqs[slot] = hq
            resource = state['resources'].get(slot, {})
            require(resource.get('current_supply', 0) <= self.spec['normal_supply_capacity'], 'original supply limit exceeded')
            if resource:
                require(resource['max_supply'] == self.spec['normal_supply_capacity'], 'native supply cap differs from template')
        if self.phase == 'setup':
            if all(len(self.units(s)) >= self.spec['target_units_per_scripted_army'] for s in self.scripted):
                self.reached_frame = frame
                self.phase, self.phase_start = 'movement', frame + 1
            else:
                require(frame + 1 < self.setup_frames, 'setup exhausted before requested army size was reached')
        elif frame + 1 - self.phase_start >= self.measure_frames:
            self.phase = 'combat' if self.phase == 'movement' else 'done'
            self.phase_start = frame + 1
        self.phase_frame = 0 if self.phase_start is None else frame + 1 - self.phase_start

    def inputs(self, frame):
        result, counts = {}, {}
        for slot in self.scripted:
            actions = []
            if frame == 0:
                join = field_uint(1, slot) + field_bytes(2, self.match.deck_messages_by_slot[slot])
                for target, source in ((3, 5), (4, 6)):
                    value = get_uint(self.match.armies_by_slot[slot], source)
                    if value:
                        join += field_uint(target, value)
                actions.append(field_bytes(3, join))
            units = self.units(slot)
            if self.phase == 'setup' and len(units) < self.spec['target_units_per_scripted_army'] and slot in self.hqs:
                hq = self.hqs[slot]
                ability = next((a for a in sorted(self.template.entity_abilities[hq['type']])
                                if self.template.build_ability_slots.get(a) == 0), None)
                require(ability is not None, 'HQ slot0 build ability missing')
                actions.append(execute(hq['type'], ability, [hq['id']], field_bytes(1, b'')))
            if units and self.phase == 'movement' and self.phase_frame % 100 == 0:
                require(set(self.hqs) == set(self.slots), 'all HQ positions required for movement workload')
                here = self.hqs[slot]['position']
                enemy = min(self.opponents(slot), key=lambda s: sum((self.hqs[s]['position'][i]-here[i])**2 for i in (0, 2)))
                there = self.hqs[enemy]['position']
                dx, dz = there[0]-here[0], there[2]-here[2]
                distance = math.hypot(dx, dz)
                require(distance > 40, 'HQ separation too short for isolated movement phase')
                lateral = 15 if (self.phase_frame//100) % 2 == 0 else -15
                command = ground_command(here[0]+.15*dx-lateral*dz/distance,
                                         here[2]+.15*dz+lateral*dx/distance)
                actions.append(execute(self.spec['unit_id'], 12, [e['id'] for e in units], command))
            if units and self.phase == 'combat' and self.phase_frame % 20 == 0:
                opponents = self.opponents(slot)
                enemies = [e for e in self.entities.values() if e.get('army') in opponents and
                           e.get('type') in self.spec['normal_unit_ids']]
                # Preserve the established 1v1 fixture; team groups select a
                # nearby opposing army, never a teammate or another army's IDs.
                origin = units[0].get('position', (0, 0, 0))
                key = (lambda e: e['id']) if len(self.slots) == 2 else (
                    lambda e: (sum((e.get('position', origin)[i]-origin[i])**2 for i in (0, 2)), e['id']))
                targets = enemies or [self.hqs[s] for s in opponents if s in self.hqs]
                target = min(targets, key=key) if targets else None
                if target and target['id'] in self.entities:
                    actions.append(execute(self.spec['unit_id'], 88, [e['id'] for e in units],
                                           field_bytes(2, field_uint(1, target['id']))))
            body = encode_player_input(self.match.identities_by_slot[slot], actions)
            result[slot] = self.validator.validate_player_input(slot, body)
            counts[str(slot)] = len(get_repeated_bytes(result[slot], 2))
        return result, counts


def observation(state, prior, spec):
    previous = {e['id']: e for e in (prior or {}).get('entities', [])}
    units, armies, types, moved, damaged, losses = {}, {}, {}, {}, {}, {}
    for slot in range(spec.get('player_count', 2)):
        army = [e for e in state['entities'] if e.get('army') == slot and e.get('type') in spec['normal_unit_ids']]
        units[str(slot)] = sum(e['type'] == spec['unit_id'] for e in army)
        armies[str(slot)] = len(army)
        types[str(slot)] = {str(t): sum(e['type'] == t for e in army) for t in sorted({e['type'] for e in army})}
        moved[str(slot)] = sum(e['id'] in previous and 'position' in e and e['position'] != previous[e['id']].get('position') for e in army)
        damaged[str(slot)] = sum(e.get('current_damage', 0) > previous.get(e['id'], {}).get('current_damage', 0) for e in army)
        now_resource, before_resource = state['resources'].get(slot, {}), (prior or {}).get('resources', {}).get(slot, {})
        losses[str(slot)] = sum(max(0, now_resource.get(k, 0)-before_resource.get(k, 0))
                                for k in ('primary_lost', 'secondary_lost'))
    return dict(unit_counts=units, army_unit_counts=armies, unit_types=types, moving_units=moved, newly_damaged_units=damaged,
                newly_lost_unit_resource_cost=losses,
                total_entities=len(state['entities']), resources=state['resources'],
                game_complete=state['game_state']['complete'])


def read_frame(stream):
    header = stream.read(4)
    require(len(header) == 4, 'missing/truncated journal length')
    length, = struct.unpack('<I', header)
    require(1 <= length <= MAX_FRAME_BYTES, 'invalid journal frame length')
    payload = stream.read(length)
    require(len(payload) == length, 'truncated journal frame')
    return payload


def check_record(frame, payload, state, expected):
    require(expected['frame'] == frame and state['frame'] == frame, 'nonsequential replay frame')
    require(digest(payload) == expected['input_sha256'], 'recorded input digest differs')
    require(state_digest(state) == expected['state_sha256'], 'observable native state differs')


def wine_requested(args):
    names = ('wine_executable', 'windows_python', 'wine_prefix_template')
    values = [getattr(args, name, None) for name in names]
    requested = any(value is not None for value in values)
    require(not requested or all(value is not None for value in values),
            '--wine-executable, --windows-python and --wine-prefix-template must be supplied together')
    require(requested or getattr(args, 'wine_cgroup_parent', None) is None,
            '--wine-cgroup-parent requires the three Wine runtime paths')
    if requested:
        require(all(Path(value).is_absolute() for value in values), 'Wine runtime paths must be explicit absolute paths')
        cgroup = getattr(args, 'wine_cgroup_parent', None)
        require(cgroup is None or Path(cgroup).is_absolute(), 'Wine cgroup parent must be an absolute path')
    return requested


def select_backend(args):
    if not wine_requested(args):
        return None
    from server.wine_worker import WineWorkerBackend
    kwargs = dict(wine_executable=args.wine_executable, windows_python=args.windows_python,
                  prefix_template=args.wine_prefix_template)
    if args.wine_cgroup_parent is not None:
        kwargs['cgroup_parent'] = args.wine_cgroup_parent
    return WineWorkerBackend(**kwargs)


def backend_identity(backend):
    if backend is None:
        return dict(kind='windows-worker', coordinator_python=sys.version,
                    worker_python=sys.version, worker_interpreter_sha256=digest(Path(sys.executable).read_bytes()))
    environment = dict(os.environ)
    for name in ('BA_ENABLE_SYNTHETIC_WORKER_TESTS', 'WINEPREFIX', 'WINEARCH', 'WINELOADER', 'WINESERVER',
                 'WINEDLLPATH', 'WINEDLLOVERRIDES', 'WINEDEBUG', 'LD_PRELOAD', 'LD_LIBRARY_PATH', 'PYTHONPATH', 'PYTHONHOME'):
        environment.pop(name, None)
    # --version exits without initializing a prefix or running a Windows app.
    # It is measured before startup, and never executes in the per-frame loop.
    began = time.perf_counter()
    version = subprocess.run([str(backend.wine_executable), '--version'], check=True, capture_output=True,
                             timeout=5, env=environment)
    require(len(version.stdout) <= 4096 and len(version.stderr) <= 4096, 'Wine version output exceeds bound')
    return dict(kind='native-linux-wine-worker', coordinator_python=sys.version,
                wine_executable=str(backend.wine_executable), wine_executable_sha256=digest(backend.wine_executable.read_bytes()),
                wine_version=version.stdout.decode('utf-8', 'strict').strip(),
                wine_version_probe_ms=(time.perf_counter()-began)*1000,
                windows_python=str(backend.windows_python), windows_python_sha256=digest(backend.windows_python.read_bytes()),
                prefix_template=str(backend.prefix_template), cgroup_parent=str(backend.cgroup_parent))


def backend_cleanup_complete(statistics):
    return (isinstance(statistics, dict) and statistics.get('cleanup_complete') is True
            and statistics.get('prefix_removed') is True and statistics.get('cgroup_removed') is True
            and all(type(statistics.get(key)) is int and statistics[key] == 0 for key in ('exit_code', 'native_exit_code')))


def validate_args(args):
    args.assets, args.output = args.assets.resolve(), args.output.resolve()
    hybrid = wine_requested(args)
    require(sys.platform.startswith('linux') if hybrid else os.name == 'nt',
            'explicit Wine backend requires native Linux; default workers require Windows; no fallback')
    require(args.output.is_relative_to(ROOT/'local') and not args.output.exists(), 'new ignored local output directory required')
    require(not args.output.is_relative_to(args.assets) and not args.assets.is_relative_to(args.output), 'assets and output must be separate')
    require(100 <= args.setup_frames <= 20000 and 20 <= args.measure_frames <= 6000, 'frame budget out of bounds')
    require(10 <= args.timeout_seconds <= 7200 and 0 <= args.seed < 1 << 64, 'time/seed budget out of bounds')
    require(1 <= args.resource_multiplier <= 16 and 0 < args.profile <= 0xffffffff, 'invalid income/AI profile')
    require(type(args.profile_thread_interval) is int and 0 <= args.profile_thread_interval <= 20000,
            'profile thread interval outside0..20000')
    if args.replay:
        args.replay = args.replay.resolve()
        require(args.replay != args.output and not args.output.is_relative_to(args.replay), 'replay output must be separate')


async def create_worker(args, data, output, *, ai=None, backend=None):
    kwargs = dict(working_directory=output, ai=ai, startup_timeout=120, request_timeout=10, close_timeout=3)
    if getattr(args, 'snapshot_decoder_library', None):
        require(not args.profile_worker and backend is None, 'decoder experiment requires unprofiled native worker')
        kwargs.update(snapshot_decoder_library=args.snapshot_decoder_library,
                      snapshot_decoder_sha256=args.snapshot_decoder_sha256)
    if args.profile_worker:
        from tools.profile_worker_timing import create_profiled_worker
        return await create_profiled_worker(data, args.assets/'Simulation.dll', profile_path=args.output/'worker-profile.json',
                                            max_records=20000, thread_sample_interval=args.profile_thread_interval, backend=backend, **kwargs)
    return await SimulationWorker.create(data, args.assets/'Simulation.dll', backend=backend, **kwargs)


def summarize_rows(rows):
    result = {}
    for phase in ('setup', 'movement', 'combat'):
        selected = [r for r in rows if r['phase'] == phase]
        if not selected:
            continue
        slots = sorted(selected[0]['unit_counts'], key=int)
        result[phase] = dict(frames=len(selected),
            timings_ms={k: summary([r[k] for r in selected]) for k in ('ai_rpc_ms', 'step_rpc_ms', 'work_ms', 'pacing_late_ms')},
            min_units={s: min(r['unit_counts'][s] for r in selected) for s in slots},
            max_units={s: max(r['unit_counts'][s] for r in selected) for s in slots},
            min_army_units={s: min(r['army_unit_counts'][s] for r in selected) for s in slots},
            max_army_units={s: max(r['army_unit_counts'][s] for r in selected) for s in slots},
            movement_by_army={s: any(r['moving_units'][s] > 0 for r in selected) for s in slots},
            combat_by_army={s: any(r['newly_damaged_units'][s] > 0 or r.get('newly_lost_unit_resource_cost', {}).get(s, 0) > 0
                                  for r in selected) for s in slots},
            movement_observed=any(any(r['moving_units'].values()) for r in selected),
            combat_observed=any(any(r['newly_damaged_units'].values()) for r in selected),
            command_counts={s: sum(r['commands'].get(s, 0) for r in selected) for s in slots})
    return result


def qualify_phases(phases, player_count):
    require(set(phases) == {'setup', 'movement', 'combat'}, 'workload phases missing')
    slots = {str(s) for s in range(player_count)}
    require(player_count in (2, 4) and all(set(phases[p][k]) == slots for p, k in
            (('movement', 'movement_by_army'), ('combat', 'combat_by_army'))), 'per-army evidence incomplete')
    require(all(phases['movement']['movement_by_army'].values()), 'movement not observed for every army')
    require(all(phases['combat']['combat_by_army'].values()), 'combat damage not observed for every army')


async def run(args):
    args.output.mkdir(parents=True, exist_ok=False)
    workdir = args.output/'worker'
    workdir.mkdir()
    report = dict(passed=False, scope=__doc__, source_at_start=source_hashes(), native_qualified=False,
                  platform=platform.platform(), python=sys.version, cpu_count=os.cpu_count(),
                  paced=args.paced, timestep_ms=50, profiled=args.profile_worker,
                  profile_thread_interval=args.profile_thread_interval if args.profile_worker else None,
                  accepted_native_runtime=True, replay=str(args.replay) if args.replay else None)
    started, worker, rows = time.perf_counter(), None, []
    try:
        backend = select_backend(args)
        report['backend'] = backend_identity(backend)
        verify_assets(args.assets)
        report['asset_manifest_sha256'] = digest((args.assets/'asset-manifest.json').read_bytes())
        if args.replay:
            source = json.loads((args.replay/'benchmark.json').read_text(encoding='utf-8'))
            require(source.get('passed') and source.get('native_qualified'), 'replay requires a completed native workload')
            require(source['asset_manifest_sha256'] == report['asset_manifest_sha256'], 'replay asset manifest differs')
            expected = [json.loads(line) for line in (args.replay/'frames.jsonl').read_text(encoding='utf-8').splitlines()]
            require(1 <= len(expected) <= MAX_FRAMES and len(expected) == source['frames'], 'replay frame count differs')
            compressed = (args.replay/'bootstrap.pb.gz').read_bytes()
            require(len(compressed) <= 32*1024*1024, 'bootstrap too large')
            data = gzip.decompress(compressed)
            require(len(data) <= 32*1024*1024 and digest(data) == source['bootstrap_sha256'], 'replay bootstrap differs')
            spec, workload = source['workload'], None
            report['replayed_source_hashes'] = source['source_at_start']
        else:
            template = GameTemplate.load(args.assets/MAPS[args.mode], catalog_path=args.assets/'unit-catalog.json',
                                         descriptors_path=args.assets/'descriptors')
            choices = team_choices(args.assets, template, args.seed) if template.player_count == 4 and args.opponent == 'ai' else None
            match, spec = configure_match(template, load=args.load, unit_id=args.unit_id, opponent=args.opponent,
                                          profile=args.profile, seed=args.seed, multiplier=args.resource_multiplier, bot_choices=choices)
            workload = Workload(template, match, spec, args.setup_frames, args.measure_frames)
            data, expected = match.raw_game_data, None
        report.update(workload=spec, bootstrap_sha256=digest(data))
        (args.output/'bootstrap.pb.gz').write_bytes(canonical_gzip(data))
        ai = AISetup(args.assets, {int(s): p for s, p in spec['ai_profiles'].items()}) if workload and args.opponent == 'ai' else None
        async with asyncio.timeout(args.timeout_seconds):
            startup = time.perf_counter()
            worker = await create_worker(args, data, workdir, ai=ai, backend=backend)
            report.update(startup_ms=(time.perf_counter()-startup)*1000, worker_pid=worker.pid,
                          native_worker_pid=getattr(worker, 'native_pid', worker.pid),
                          worker_runtime=getattr(worker, 'runtime_info', None),
                          simulation_sha256=worker.dll_sha256, ai=worker.ai_info)
            report['snapshot_decoder'] = getattr(worker, 'decoder_info', None)
            prior, paced_start = None, time.perf_counter()
            replay_stream = (args.replay/'frames.bin').open('rb') if args.replay else None
            try:
                with (args.output/'frames.bin').open('xb') as journal, (args.output/'frames.jsonl').open('x', encoding='utf-8') as trace:
                    for frame in range(MAX_FRAMES):
                        if expected is not None and frame == len(expected):
                            break
                        due = paced_start + frame*.05
                        if args.paced:
                            await asyncio.sleep(max(0, due-time.perf_counter()))
                        before = time.perf_counter()
                        late = max(0, before-due)*1000 if args.paced else 0
                        if workload:
                            phase = workload.phase
                            inputs, commands = workload.inputs(frame)
                            ai_start = time.perf_counter()
                            bots = await worker.bot_inputs(frame) if ai else {}
                            ai_ms = (time.perf_counter()-ai_start)*1000 if ai else 0
                            require(not set(inputs).intersection(bots), 'human/AI ownership overlap')
                            inputs.update(bots)
                            commands.update({str(s): len(get_repeated_bytes(body, 2)) for s, body in bots.items()})
                            payload = encode_frame(frame, inputs)
                        else:
                            payload = read_frame(replay_stream)
                            phase, commands, ai_ms = expected[frame]['phase'], expected[frame]['commands'], 0
                        step_start = time.perf_counter()
                        result = await worker.process_frame(payload, dt_ms=50)
                        stepped = time.perf_counter()
                        require(result.frame == frame, 'native frame differs')
                        state = result.state
                        if expected is not None:
                            check_record(frame, payload, state, expected[frame])
                        row = dict(frame=frame, phase=phase, input_sha256=digest(payload), state_sha256=state_digest(state),
                                   canonical_fnv1a64=state['canonical_fnv1a64'], commands=commands,
                                   ai_rpc_ms=ai_ms, step_rpc_ms=(stepped-step_start)*1000,
                                   work_ms=(stepped-before)*1000, pacing_late_ms=late,
                                   **observation(state, prior, spec))
                        journal.write(struct.pack('<I', len(payload))+payload)
                        trace.write(json.dumps(row, sort_keys=True, allow_nan=False)+'\n')
                        rows.append(row)
                        prior = state
                        if workload:
                            workload.update(state, frame)
                            if workload.phase == 'done':
                                break
                            require(not state['game_state']['complete'], 'match ended before workload phases completed')
                    if replay_stream:
                        require(not replay_stream.read(1), 'extra replay journal frames')
            finally:
                if replay_stream:
                    replay_stream.close()
            phases = summarize_rows(rows)
            qualify_phases(phases, spec.get('player_count', 2))
            if workload:
                require(workload.phase == 'done', 'workload exceeded frame budget')
                report['target_reached_frame'] = workload.reached_frame
            report.update(passed=True, native_qualified=True, phases=phases)
    except BaseException as error:
        report.update(error=f'{type(error).__name__}: {error}', traceback=traceback.format_exc())
    finally:
        if worker:
            try:
                await worker.close()
            except BaseException as error:
                report['cleanup_error'] = repr(error)
            report['cleanup'] = dict(exit_code=worker.process.poll(), failure=worker.failure,
                                     stderr_thread_closed=not worker._stderr_thread.is_alive(),
                                     io_threads_closed=all(not t.is_alive() for t in worker._io._threads))
            report['backend_statistics'] = worker.backend_statistics
            clean = (worker.process.poll() == 0 and worker.failure is None and report['cleanup']['stderr_thread_closed']
                     and report['cleanup']['io_threads_closed'] and 'cleanup_error' not in report)
            if backend is not None:
                clean &= backend_cleanup_complete(report['backend_statistics'])
        else:
            clean = False
        report.update(frames=len(rows), elapsed_seconds=time.perf_counter()-started, source_at_finish=source_hashes(),
                      phases=summarize_rows(rows))
        report['source_unchanged'] = report['source_at_start'] == report['source_at_finish']
        report['passed'] &= clean and report['source_unchanged']
        report['native_qualified'] &= report['passed']
        if not report['passed'] and 'error' not in report:
            report['error'] = 'worker cleanup or source stability failed'
        journal = args.output/'frames.bin'
        if journal.exists():
            report['input_journal_sha256'] = digest(journal.read_bytes())
        if args.profile_worker and worker:
            try:
                profile = json.loads((args.output/'worker-profile.json').read_text(encoding='utf-8'))
                require(profile['completed'] and profile['exit_code'] == 0 and profile['dropped_records'] == 0
                        and not profile['synthetic_test_backend'], 'incomplete/synthetic worker profile')
                report['worker_profile_sha256'] = digest((args.output/'worker-profile.json').read_bytes())
                from tools.summarize_worker_timing import validate_profile
                with journal.open('rb') as stream:
                    lengths = [len(read_frame(stream)) for _ in rows]
                    require(not stream.read(1), 'extra input journal frames')
                validate_profile(profile, dict(report=report, rows=rows, payload_lengths=lengths),
                                 report['worker_profile_sha256'])
            except (OSError, ValueError, KeyError) as error:
                report.update(passed=False, native_qualified=False, profile_error=str(error))
        (args.output/'benchmark.json').write_text(json.dumps(report, indent=2, sort_keys=True)+'\n', encoding='utf-8')
    print(json.dumps({key: report[key] for key in ('passed', 'frames', 'elapsed_seconds', 'error', 'cleanup') if key in report}))
    return 0 if report['passed'] else 1


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--assets', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--load', choices=LOADS, default='large')
    parser.add_argument('--mode', type=int, choices=MAPS, default=1)
    parser.add_argument('--unit-id', type=int, choices=(1, 2, 75), default=75)
    parser.add_argument('--opponent', choices=('scripted', 'ai'), default='scripted')
    parser.add_argument('--profile', type=int, default=58)
    parser.add_argument('--seed', type=int, default=20261117)
    parser.add_argument('--resource-multiplier', type=int, default=1)
    parser.add_argument('--setup-frames', type=int, default=4000)
    parser.add_argument('--measure-frames', type=int, default=600, help='frames in EACH movement and combat phase')
    parser.add_argument('--timeout-seconds', type=float, default=600)
    parser.add_argument('--paced', action='store_true', help='wall-clock20Hz; default accelerated wall clock')
    parser.add_argument('--profile-worker', action='store_true', help='explicit instrumented native timing arm')
    parser.add_argument('--profile-thread-interval', type=int, default=0,
                        help='0 disables costly thread inventory;20 explicitly samples every20requests')
    parser.add_argument('--wine-executable', type=Path, help='explicit native-Linux backend Wine executable')
    parser.add_argument('--windows-python', type=Path, help='Windows x64 Python executable on the Linux filesystem')
    parser.add_argument('--wine-prefix-template', type=Path, help='prepared private Wine worker template')
    parser.add_argument('--wine-cgroup-parent', type=Path, help='delegated cgroup2 parent for owned workers')
    parser.add_argument('--replay', type=Path, help='completed benchmark directory; exact recorded inputs, no AI regeneration')
    parser.add_argument('--snapshot-decoder-library', type=Path, help='explicit experimental Rust decoder library')
    parser.add_argument('--snapshot-decoder-sha256', help='required exact experimental decoder identity')
    args = parser.parse_args()
    validate_args(args)
    return asyncio.run(run(args))


if __name__ == '__main__':
    raise SystemExit(main())
