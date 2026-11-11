"""Bounded original Mortar setup identity control, separate from Unity acceptance.

The fixture adds one INITIAL Mortar, selects a legal custom deck, and preserves
the shipped entity/ability configurations. No runtime spawn, identity edit,
prediction, manual-group write, client input, or live server is exercised.
"""
from __future__ import annotations

import hashlib
import json
import math
from pathlib import Path
import struct
import traceback

from server.game_data import GameTemplate
from server.protobuf_wire import field_bytes, field_uint, get_bytes, get_repeated_bytes, get_uint, replace_fields
from tools.prediction_actor_fixture import _position, _position_bytes

SEED = 20261113
SUBJECT = 10
UNIT_TYPE = 9
DECK = (75, 74, 9, 73, 77, 47, 80, 70)
BASE_LABELS = frozenset(('Ground', 'ThreatToGround'))
EFFECT_LABELS = frozenset(('Immobile', 'Deployed', 'SettingUp', 'UnsettingUp'))


def require(ok, reason):
    if not ok:
        raise AssertionError('original setup identity control: ' + reason)


def digest(raw):
    return hashlib.sha256(raw).hexdigest()


def build_fixture(assets):
    assets = Path(assets)
    base = GameTemplate.load(assets/'map-1v1.pb.gz', catalog_path=assets/'unit-catalog.json',
                             descriptors_path=assets/'descriptors')
    initial = get_repeated_bytes(base.raw_game_data, 2)
    require(base.game_mode == 1 and base.player_count == 2 and len(initial) == SUBJECT,
            'the original ten-entity two-human map is required')
    require(base.validate_deck(DECK) == DECK and base.active_groups_for_deck(DECK) == (4, 0, 0, 0),
            'legal original Mortar deck/active ability group differs')
    require({12, 21, 22} <= base.entity_abilities.get(UNIT_TYPE, set()), 'Mortar setup abilities differ')
    core = get_bytes(initial[0], 2, required=True)
    require(get_uint(core, 1) == 3 and get_uint(core, 2) == 0, 'initial local Core differs')
    x, y, z = _position(get_bytes(core, 3, required=True))
    position = (x-8.0, y, z)
    create = field_uint(1, UNIT_TYPE) + field_bytes(3, _position_bytes(position))
    create += field_bytes(4, field_uint(4, 1 << 32))  # Original identity quaternion.
    raw = replace_fields(base.raw_game_data, {2: [field_bytes(2, value) for value in
        (*initial, field_bytes(2, create))]})
    template = GameTemplate(raw, catalog_path=assets/'unit-catalog.json', descriptors_path=assets/'descriptors')
    require(template.game_config == base.game_config, 'fixture changed shipped configuration')
    roster = [dict(slot=slot, army_id=slot, player_id=slot+1, name='Setup identity control '+str(slot))
              for slot in (0, 1)]
    decks = dict(template.default_decks)
    decks[0] = DECK
    match = template.build_match(roster, decks, seed=SEED, game_name='original-mortar-setup-identity')
    # The normal match builder freezes human identity/decks and startup settings;
    # all entity, ability, and modifier definitions stay byte-identical.
    for number in (1, 5, 6, 10):
        require(get_repeated_bytes(match.game_config, number) == get_repeated_bytes(base.game_config, number),
                'normal match changed entity, modifier, label, or ability definitions')
    return template, match, dict(seed=SEED, subject=SUBJECT, unit_type=UNIT_TYPE, army=0,
        position=list(position), selected_deck=list(DECK), active_groups=[4, 0, 0, 0],
        original_map_raw_sha256=digest(base.raw_game_data), bootstrap_sha256=digest(match.raw_game_data),
        entity_definitions_sha256=digest(b''.join(get_repeated_bytes(base.game_config, 1))),
        setup_ability_sha256={str(key): digest(base.abilities[key]) for key in (21, 22)},
        authored_initial_entity=True, runtime_writes=False, original_player_build_exercised=False,
        unity_or_manual_groups_exercised=False)


def classify(rows, command_frames):
    """An unchanged ID is meaningful only after both real timed setup effects."""
    require(type(rows) is list and rows and all(type(row) is dict for row in rows), 'missing observations')
    require([row.get('frame') for row in rows] == list(range(len(rows))), 'frame census has a gap/duplicate')
    require(type(command_frames) in (list, tuple) and len(command_frames) == 2 and
            all(type(value) is int for value in command_frames), 'two command frames are required')
    first, second = command_frames
    require(140 <= first < second and second-first == 70 and len(rows) == first+141,
            'finite command/observation schedule differs')
    for row in rows:
        require(type(row.get('labels')) is list and len(row['labels']) <= 256 and
                all(type(value) is str for value in row['labels']) and
                len(set(row['labels'])) == len(row['labels']), 'invalid resolved label census')
        require(type(row.get('state')) is int and 0 <= row['state'] < 2**32, 'missing actual native state')
        value = row.get('setup_time')
        require(value is None or type(value) in (float, int) and math.isfinite(value), 'invalid original setup timer')
        identity = row.get('identity')
        require(type(identity) is list and len(identity) == 4 and
                all(type(value) is int and 0 <= value < 2**64 for value in identity) and
                identity[0] == SUBJECT and identity[-1] > 0, 'missing confirmed full identity/token')
    require(rows[first-1]['identity'][:3] == [SUBJECT, 0, UNIT_TYPE], 'initial confirmed Mortar identity differs')
    for frame in (first-1, second-1, len(rows)-1):
        require(rows[frame]['state'] == 0, 'original unit is not idle at a phase boundary')
    baseline = set(rows[first-1]['labels'])
    require(BASE_LABELS <= baseline <= BASE_LABELS | {'OutOfCombat'} and set(rows[-1]['labels']) == baseline,
            'initial/finished native labels do not establish the original mobile state')
    deployed = rows[second-1]
    require(set(deployed['labels']) == baseline | {'Immobile', 'Deployed'},
            'completed Setup21 did not establish deployed labels')
    effects = []
    for start, stop, active, forbidden in ((first, second, 'SettingUp', 'UnsettingUp'),
                                          (second, len(rows), 'UnsettingUp', 'SettingUp')):
        phases = [row for row in rows[start:stop] if active in row['labels']]
        require(len(phases) >= 10 and phases[0]['frame'] <= start+2,
                'real setup effect missing; valid/no-op input is inconclusive')
        require([row['frame'] for row in phases] == list(range(phases[0]['frame'], phases[-1]['frame']+1)),
                'original setup effect was interrupted')
        require(all(row['state'] == 11 and set(row['labels']) == baseline | {'Immobile', active} and
                    forbidden not in row['labels'] for row in phases), 'labels do not join actual SETUP state')
        if active == 'UnsettingUp':
            require(all('Deployed' not in row['labels'] for row in phases), 'Setup22 did not remove Deployed')
        timed = [row for row in phases if row['setup_time'] is not None]
        require(len(timed) >= 10, 'actual interior setup timer signals are missing')
        boundary = [row['frame'] for row in phases if row['setup_time'] is None]
        # Original02 snapshots190/260 retain state/label while the timer has
        # already been removed;191/261 publish the completed state/labels.
        require(not boundary or boundary == [timed[-1]['frame']+1] and boundary[0] == phases[-1]['frame'],
                'missing timer is not a single original completion boundary')
        timers = [row['setup_time'] for row in timed]
        require(all(.049 <= after-before <= .051 for before, after in zip(timers, timers[1:])),
                'original elapsed setup timer did not advance monotonically with50ms steps')
        require(max(timers)-min(timers) > 1.0 and 47 <= timed[-1]['frame']-start <= 52,
                'original timed setup did not progress for the configured 2.5 seconds')
        before_labels = baseline if active == 'SettingUp' else baseline | {'Immobile', 'Deployed'}
        require(all(row['state'] == 11 and set(row['labels']) == before_labels and
                    row['setup_time'] is not None for row in rows[start:phases[0]['frame']]),
                'original setup did not begin at the recorded command boundary')
        after_labels = baseline | {'Immobile', 'Deployed'} if active == 'SettingUp' else baseline
        completed = rows[phases[-1]['frame']+1:stop]
        require(completed and all(row['state'] == 0 and set(row['labels']) == after_labels and
                                  row['setup_time'] is None for row in completed),
                'original setup did not complete immediately and remain stable before the next command')
        effects.append(dict(command_frame=start, first_observed=phases[0]['frame'],
            last_observed=phases[-1]['frame'], timer_min=min(timers), timer_max=max(timers),
            samples=len(phases), timed_samples=len(timed), timer_completion_boundary=boundary))
    identities = sorted({tuple(row['identity']) for row in rows})
    changed = len(identities) != 1
    return dict(passed=True, setup21_and_22_exercised=True, identity_changed=changed,
        observed_identities=[list(value) for value in identities], baseline_labels=sorted(baseline), phases=effects,
        classification='identity-change route observed' if changed else 'Setup21/22 did not change observed identity',
        hidden_allocation_identity_proven=False, unity_group_coverage=False, full_feature_accepted=False)


def _records(path, header_format='<I', maximum=420):
    require(path.stat().st_size <= 512*1024*1024, 'capture exceeds file bound')
    header_size = struct.calcsize(header_format)
    with path.open('rb') as stream:
        count = 0
        while header := stream.read(header_size):
            require(len(header) == header_size and count < maximum, 'capture record header/count differs')
            fields = struct.unpack(header_format, header)
            require(0 < fields[-1] <= 16*1024*1024, 'capture record size differs')
            raw = stream.read(fields[-1])
            require(len(raw) == fields[-1], 'truncated capture record')
            count += 1
            yield (*fields[:-1], raw)


def analyze_capture(output, *, observations_output=None):
    """Pure file-only interpretation after original world close; no native calls."""
    from client_patch.prediction_worker.entities import ActiveIdentityHistory
    from client_patch.prediction_worker.commands import player_slot
    from server.protobuf_wire import get_repeated_uint, parse_fields
    from server.native_simulation import _protobuf_header
    from tools.prediction_setup_observation import LabelRegistry, decode, label_names_from_config

    output = Path(output)
    config = get_bytes((output/'bootstrap.pb').read_bytes(), 1, required=True)
    registry = LabelRegistry(label_names_from_config(config))
    history = ActiveIdentityHistory()
    history.bootstrap((output/'bootstrap-snapshot.bin').read_bytes())
    calls = json.loads((output/'registry-calls.json').read_text())
    census = [json.loads(line) for line in (output/'census.jsonl').read_text().splitlines()]
    snapshots = list(_records(output/'snapshots.bin'))
    journal = list(_records(output/'canonical-frames.bin'))
    registry_records = iter(_records(output/'registry1.bin', '<III', maximum=840))
    require(len(census) == len(snapshots) == len(journal) == 281 and len(calls) == 562,
            'complete canonical/snapshot/census/registry-call records required')
    rows, commands = [], []
    for frame, ((raw,), (body,), original) in enumerate(zip(snapshots, journal, census)):
        require(original['frame'] == frame and original['input_sha256'] == digest(body) and
                original['snapshot_sha256'] == digest(raw), 'capture bytes differ from original census')
        require(_protobuf_header(body) == (frame, 50), 'original canonical frame/step differs')
        for player in get_repeated_bytes(body, 6):
            slot = player_slot(player)
            for action in get_repeated_bytes(player, 2):
                fields = parse_fields(action)
                if frame == 0:
                    require(len(fields) == 1 and fields[0].number == 3, 'unexpected bootstrap action')
                    continue
                require(frame in (140, 210) and slot == 0 and len(fields) == 1 and fields[0].number == 1,
                        'unrelated or repeated original action')
                payload = fields[0].value
                groups = get_repeated_bytes(payload, 1)
                require(len(groups) == 1 and get_uint(groups[0], 1) == UNIT_TYPE and
                        get_uint(groups[0], 2) == (21 if frame == 140 else 22) and
                        get_repeated_uint(groups[0], 3) == (SUBJECT,) and get_bytes(payload, 3) == field_bytes(1, b''),
                        'original setup action identity/ability/target differs')
                commands.append(frame)
        for phase, name in enumerate(('before', 'after')):
            call = calls[2*frame+phase]
            require(call['next_frame'] == frame and call['phase'] == name and type(call['size']) is int,
                    'registry query order differs')
            if call['size']:
                record_frame, record_phase, labels = next(registry_records)
                require((record_frame, record_phase, len(labels), digest(labels)) ==
                        (frame, phase, call['size'], call['sha256']), 'registry bytes differ from query receipt')
                registry.observe(labels)
            else:
                require(call['sha256'] == digest(b''), 'empty registry query hash differs')
        observed = decode(raw, registry, expected_frame=frame)['entities'].get(SUBJECT, {})
        history.observe(raw, physical_frame=frame)
        history.confirm(frame)
        active = history.active.get(SUBJECT)
        require(original['identity'] == ([SUBJECT, *active] if active else None), 'original identity census differs')
        require(original['native_state'] == observed.get('state'), 'raw native state disagrees with decoded state')
        rows.append(dict(original, **observed))
    require(next(registry_records, None) is None, 'unjoined registry records')
    destination = Path(observations_output) if observations_output is not None else output/'observations.jsonl'
    with destination.open('x', encoding='utf-8') as stream:
        for row in rows:
            stream.write(json.dumps(row, separators=(',', ':'), allow_nan=False)+'\n')
    return classify(rows, commands)


def run_native(assets, output):
    """Capture first in the retained Job-owned child; interpret after close."""
    from client_patch.prediction_worker.entities import ActiveIdentityHistory
    from server.native_simulation import NativeSimulation, SUPPORTED_DLL_SHA256, decode_snapshot
    from tools.verify_movement_prediction import canonical_frame, decode_cooldowns, execute, opening_actions
    from tools.verify_prediction_combat_fixture import entity_states

    assets, output = Path(assets), Path(output)
    require(digest((assets/'Simulation.dll').read_bytes()) == SUPPORTED_DLL_SHA256, 'original DLL differs')
    template, match, fixture = build_fixture(assets)
    require((output/'bootstrap.pb').read_bytes() == match.raw_game_data, 'prepared bootstrap drift')
    commands, registry_calls, world, frames = [], [], None, 0
    report = dict(passed=False, native_executed=False, native_world_closed=False, native_capture_completed=False,
        scope=__doc__, fixture=fixture, label_interpretation_after_native_close=True,
        registry_tape_format='Repeated uint32(next_frame,phase0_before_or1_after,size), then exact registry1 bytes')
    try:
        world = NativeSimulation(match.raw_game_data, assets/'Simulation.dll')
        report['native_executed'] = True
        history = ActiveIdentityHistory()
        raw = world.snapshot(31)
        (output/'bootstrap-snapshot.bin').write_bytes(raw)
        history.bootstrap(raw)
        state = decode_snapshot(raw, 31, include_entities=True)
        initial = next(entity for entity in state['entities'] if entity['id'] == SUBJECT)
        require((initial['army'], initial['type']) == (0, UNIT_TYPE), 'original initial Mortar was not created')
        with (output/'canonical-frames.bin').open('xb') as journal, (output/'snapshots.bin').open('xb') as snapshots, \
             (output/'private0-snapshots.bin').open('xb') as private_snapshots, \
             (output/'registry1.bin').open('xb') as registries, (output/'census.jsonl').open('x', encoding='utf-8') as observations:
            for frame in range(281):
                labels = world.label_bytes(1)
                registry_calls.append(dict(next_frame=frame, phase='before', size=len(labels), sha256=digest(labels)))
                if labels:
                    registries.write(struct.pack('<III', frame, 0, len(labels)) + labels)
                actions = opening_actions(template, match, 0, state) if frame == 0 else {0: [], 1: []}
                if frame in (140, 210):
                    entity = next(item for item in state['entities'] if item['id'] == SUBJECT)
                    ability = 21 if frame == 140 else 22
                    action = execute(entity, ability, field_bytes(1, b''))
                    actions[0].append(action)
                    commands.append(dict(frame=frame, ability=ability, action_sha256=digest(action)))
                body = canonical_frame(template, match, frame, actions, state)
                journal.write(struct.pack('<I', len(body)) + body)
                world.process_frame(body, dt_ms=50)
                raw = world.snapshot(31)
                snapshots.write(struct.pack('<I', len(raw)) + raw)
                private = world.snapshot(0)
                require(decode_snapshot(private, 0)['frame'] == frame, 'private charge observation has another frame')
                private_snapshots.write(struct.pack('<I', len(private)) + private)
                labels = world.label_bytes(1)
                registry_calls.append(dict(next_frame=frame, phase='after', size=len(labels), sha256=digest(labels)))
                if labels:
                    registries.write(struct.pack('<III', frame, 1, len(labels)) + labels)
                history.observe(raw, physical_frame=frame)
                history.confirm(frame)
                state = decode_snapshot(raw, 31, include_entities=True)
                active = history.active.get(SUBJECT)
                row = dict(frame=frame, native_state=entity_states(raw).get(SUBJECT),
                    identity=([SUBJECT, *active] if active else None),
                    census=[dict(id=entity, army=value[0], unit_type=value[1], token=value[2])
                            for entity, value in sorted(history.active.items())],
                    private_charge_rows=decode_cooldowns(private), charge_entity_association_claimed=False,
                    input_sha256=digest(body), snapshot_sha256=digest(raw))
                observations.write(json.dumps(row, separators=(',', ':'), allow_nan=False)+'\n')
                frames += 1
        report['native_capture_completed'] = True
    except BaseException as error:
        report.update(error=repr(error), traceback=traceback.format_exc())
    finally:
        report.update(commands=commands, observed_frames=frames, registry_calls=registry_calls)
        (output/'registry-calls.json').write_text(json.dumps(registry_calls, indent=2)+'\n')
        if world is not None:
            try:
                world.close()
                report['native_world_closed'] = True
            except BaseException as error:
                report.update(cleanup_error=repr(error))
    if report['native_capture_completed'] and report['native_world_closed']:
        try:
            report['identity_control'] = analyze_capture(output)
            report['passed'] = True
        except BaseException as error:
            report.update(error=repr(error), traceback=traceback.format_exc())
    return report
