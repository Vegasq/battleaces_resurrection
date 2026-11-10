"""File-only native same-head position evidence; no runtime/native imports.

The caller supplies independently validated ready/FEEL/journal actor bindings.
Worker positions contain native identities only. Query brackets use this worker
process's perf_counter clock; this module never aligns another process's clock
or attributes a Unity/rendering effect to a native correction.
"""
from __future__ import annotations

import json
import math
from pathlib import Path
import re
import struct


MAX_RECORDS = 8192
MAX_BYTES = 16 * 1024 * 1024
CONTEXT = {'stage', 'head', 'confirmed', 'received', 'corrections', 'replayed_frames',
           'query_begin_us', 'query_end_us'}
FIELDS = {'schema', 'event', 'world', 'frame', 'revision', 'query_revision', 'checkpoint_base',
          'first_divergent_frame', 'watched_identity', 'context_source', *CONTEXT, 'status',
          'observed_identity', 'missing_components', 'position', 'position_bits', 'record',
          'clock_source', 'query_scope'}
BEFORE_FIELDS = (FIELDS - {'checkpoint_base', 'first_divergent_frame'}) | {
    'checkpoint_base', 'first_divergent_frame', 'cached_from_record', 'cached_physical_head'}
PRESERVED = {'frame', 'stage', 'head', 'confirmed', 'received', 'corrections', 'replayed_frames',
             'query_begin_us', 'query_end_us', 'query_revision', 'watched_identity',
             'observed_identity', 'missing_components'}


class TraceError(ValueError):
    pass


def require(value, reason):
    if not value:
        raise TraceError(reason)


def integer(value, low=0, high=0xffffffffffffffff):
    return type(value) is int and low <= value <= high


def native_identity(value, *, partial=False):
    require(type(value) is dict and set(value) == {'id', 'type', 'army'}, 'native identity schema differs')
    require(all((partial and name != 'id' and item is None) or integer(item, 0, 0xffffffff)
                for name, item in value.items()), 'invalid native identity number')


def _object(pairs):
    result = {}
    for name, value in pairs:
        require(name not in result, 'duplicate JSON field')
        result[name] = value
    return result


def _constant(value):
    raise TraceError('nonfinite JSON number: ' + value)


def read_trace(path):
    """Read only a closed, bounded trace. Empty output means no witness."""
    path = Path(path)
    size = path.stat().st_size
    require(size <= MAX_BYTES, 'native position file exceeds byte bound')
    raw = path.read_bytes()
    require(len(raw) == size and (not raw or raw.endswith(b'\n')), 'native position file is partial/changed')
    lines = raw.splitlines()
    require(len(lines) <= MAX_RECORDS and all(0 < len(line) <= 4096 for line in lines),
            'native position line/count bound exceeded')
    try:
        return [json.loads(line.decode('utf-8'), object_pairs_hook=_object, parse_constant=_constant) for line in lines]
    except (UnicodeError, json.JSONDecodeError) as error:
        raise TraceError('invalid native position JSON') from error


def _position(row, identity):
    missing = row['missing_components']
    require(type(missing) is list and all(type(name) is str and name in ('army', 'type', 'position', 'position_vec3') for name in missing) and
            len(set(missing)) == len(missing),
            'invalid missing native components')
    status = row['status']
    if status == 'present':
        native_identity(row['observed_identity'])
        require(row['observed_identity'] == identity and not missing, 'present native identity differs from watch')
        vector, bits = row['position'], row['position_bits']
        require(type(vector) is list and len(vector) == 3 and type(bits) is list and len(bits) == 3 and
                all(integer(item, 0, 0xffffffff) for item in bits), 'native position Vec3/bit schema differs')
        try:
            require(all(type(item) in (int, float) and math.isfinite(item) for item in vector),
                    'nonfinite/invalid native position')
            raw = struct.pack('<fff', *vector)
        except (OverflowError, struct.error) as error:
            raise TraceError('native position is not finite float32') from error
        require(list(struct.unpack('<fff', raw)) == vector and list(struct.unpack('<III', raw)) == bits,
                'native float32 position bits differ')
        return
    require(row['position'] is None and row['position_bits'] is None, 'unavailable position must not become zeros')
    if status == 'absent':
        require(row['observed_identity'] is None and not missing, 'absent entity metadata differs')
    elif status == 'partial':
        native_identity(row['observed_identity'], partial=True)
        require(row['observed_identity']['id'] == identity['id'] and missing, 'partial entity lacks explicit missing components')
    elif status == 'identity_mismatch':
        native_identity(row['observed_identity'])
        require(row['observed_identity']['id'] == identity['id'] and row['observed_identity'] != identity and not missing,
                'mismatched native identity is not explicit')
    elif status not in ('outside_window', 'no_cached_state', 'cached_frame_not_head'):
        raise TraceError('unknown selected native position status')


def _bindings(identity, worlds):
    native_identity(identity)
    require(identity['type'] > 0, 'watched native type must be positive')
    require(type(worlds) is list and len(worlds) == 2, 'exactly two independently bound worlds required')
    result = {}
    for binding in worlds:
        require(type(binding) is dict and set(binding) == {'world', 'match', 'entity', 'unit_type', 'army', 'incarnation'},
                'external ready/FEEL binding schema differs')
        require(integer(binding['world'], 1) and integer(binding['incarnation'], 1) and
                type(binding['match']) is str and re.fullmatch('[a-f0-9]{32}', binding['match']) and
                all(integer(binding[key], 0, 0xffffffff) for key in ('entity', 'unit_type', 'army')) and
                (binding['entity'], binding['unit_type'], binding['army']) ==
                (identity['id'], identity['type'], identity['army']), 'external ready/FEEL native binding differs')
        require(binding['world'] not in result and binding['match'] not in [row['match'] for row in result.values()],
                'external world/match binding is reused')
        result[binding['world']] = dict(binding)
    return result


def analyze(rows, *, identity, worlds):
    """Require a changed, present same-H witness in each externally bound world.

    Each incomplete/unavailable episode remains unqualified with delta=None.
    A true zero correction is valid data but does not meet the changed-witness
    requirement. Passing this narrow requirement does not qualify all episodes.
    """
    bindings = _bindings(identity, worlds)
    require(type(rows) is list and len(rows) <= MAX_RECORDS, 'native position record bound/type differs')
    state = {}; seen = []; current = None; last_end = -1
    for index, row in enumerate(rows):
        require(type(row) is dict and row.get('event') in ('native_position', 'before_restore_cached_head', 'after_replay_same_head'),
                'unknown native position event')
        before = row['event'] == 'before_restore_cached_head'
        require(set(row) == (BEFORE_FIELDS if before else FIELDS) and type(row['schema']) is int and row['schema'] == 1 and
                type(row['record']) is int and row['record'] == index, 'native position schema/serial differs')
        require(integer(row['world'], 1) and row['world'] in bindings and row['watched_identity'] == identity,
                'native position world/watch differs')
        require(integer(row['frame'], -1, 0x7fffffff), 'invalid native decoded frame')
        native_identity(row['watched_identity'])
        require(row['clock_source'] == 'python.perf_counter_ns//1000' and
                row['query_scope'] == 'existing-native-make-get-and-decode', 'native query clock/scope differs')
        world = row['world']
        if world != current:
            require(world not in seen and world == list(bindings)[len(seen)], 'native worlds interleaved/reused/out of order')
            seen.append(world); current = world
            state[world] = dict(revision=0, base=None, latest=None, metrics=(0, 0), pending=None,
                                episodes=[], frames=[])
        s = state[world]
        require(integer(row['revision'], 0, MAX_RECORDS), 'invalid native invalidation revision')
        _position(row, identity)
        if before:
            require(row['revision'] == s['revision']+1 and integer(row['checkpoint_base'], -1, 0x7ffffffe) and
                    integer(row['first_divergent_frame'], 0, 0x7fffffff) and row['first_divergent_frame'] == row['checkpoint_base']+1 and
                    row['context_source'] == 'cached_query_before_restore', 'native checkpoint revision/D differs')
            reference = row['cached_from_record']
            require(row['cached_physical_head'] is None or integer(row['cached_physical_head'], 0, 0x7fffffff),
                    'invalid cached native physical head')
            if reference is None:
                require(row['status'] in ('outside_window', 'no_cached_state') and row['cached_physical_head'] is None and
                        row['query_revision'] is None and row['observed_identity'] is None and not row['missing_components'] and
                        all(row[name] is None for name in CONTEXT) and integer(row['frame'], -1, 0x7fffffff) and
                        (row['frame'] == -1) == (row['status'] == 'no_cached_state'), 'unavailable pre-restore cache is not explicit')
            else:
                require(integer(reference, 0, index-1) and reference == s['latest'], 'pre-restore cache is not the latest actual query')
                original = rows[reference]
                require(original['event'] != 'before_restore_cached_head' and original['world'] == world and
                        all(type(row[name]) is type(original[name]) and row[name] == original[name] for name in PRESERVED),
                        'cached query context/timestamps changed')
                is_head = original['stage'] == 'ordinary' or original['head'] == original['frame']
                require(row['cached_physical_head'] == (original['frame'] if is_head else None), 'cached physical H is not actual decoded head')
                if is_head:
                    require(all(row[name] == original[name] for name in ('status', 'position', 'position_bits')),
                            'cached selected position changed before restore')
                else:
                    require(row['status'] == 'cached_frame_not_head', 'partial replay cache claimed as physical H')
            episode = dict(revision=row['revision'], checkpoint_base=row['checkpoint_base'],
                first_divergent_frame=row['first_divergent_frame'], before_record=index, after_record=None,
                physical_head=row['cached_physical_head'], qualified=False, changed=False, delta=None, magnitude=None,
                reason='actual same-H replay sample missing')
            if row['cached_physical_head'] is None:
                episode['reason'] = row['status']
            elif row['cached_physical_head'] <= row['checkpoint_base']:
                episode['reason'] = 'checkpoint has no replay tail at cached H'
            s['episodes'].append(episode)
            s.update(revision=row['revision'], base=row['checkpoint_base'], pending=episode)
            continue
        require(integer(row['frame'], 0, 0x7fffffff) and integer(row['query_revision'], 0, MAX_RECORDS) and
                row['revision'] == row['query_revision'] == s['revision'] and
                type(row['checkpoint_base']) is type(s['base']) and row['checkpoint_base'] == s['base'] and row['first_divergent_frame'] ==
                (None if s['base'] is None else s['base']+1) and row['context_source'] == 'same_decoded_native_query',
                'actual query frame/revision/base differs')
        require((row['first_divergent_frame'] is None if s['base'] is None else integer(row['first_divergent_frame'], 0, 0x7fffffff)),
                'actual query first divergent frame differs')
        require(row['status'] in ('present', 'absent', 'partial', 'identity_mismatch'), 'actual query has a cached-only status')
        require(row['stage'] in ('ordinary', 'replay') and all(integer(row[name], -1, 0x7fffffff) for name in ('head', 'confirmed', 'received')) and
                row['confirmed'] <= row['received'] and
                (row['frame'] == row['head']+1 if row['stage'] == 'ordinary' else
                 s['base'] is not None and s['base'] < row['frame'] <= row['head']), 'actual native query stage/head differs')
        require(integer(row['query_begin_us']) and integer(row['query_end_us']) and
                last_end <= row['query_begin_us'] <= row['query_end_us'] and
                all(integer(row[name]) for name in ('corrections', 'replayed_frames')), 'actual native query clock/metrics invalid')
        metrics = row['corrections'], row['replayed_frames']
        require(all(a >= b for a, b in zip(metrics, s['metrics'])), 'native correction/replay metrics regressed')
        pending = s['pending']
        reaches = (row['stage'] == 'replay' and pending is not None and pending['after_record'] is None and
                   pending['physical_head'] is not None and pending['physical_head'] > pending['checkpoint_base'] and
                   row['frame'] == pending['physical_head'])
        require((row['event'] == 'after_replay_same_head') == reaches, 'same-H replay event is missing/unbound')
        if reaches:
            require(row['head'] == row['frame'], 'actual replay query is not the cached physical H')
            first = rows[pending['before_record']]
            pending['after_record'] = index
            if first['status'] == row['status'] == 'present':
                delta = [b-a for a, b in zip(first['position'], row['position'])]
                magnitude = math.sqrt(sum(value*value for value in delta))
                pending.update(qualified=True, changed=magnitude > 0, delta=delta, magnitude=magnitude,
                               reason=None, before_position=list(first['position']), after_position=list(row['position']))
            else:
                pending['reason'] = 'selected position unavailable: '+first['status']+' -> '+row['status']
        s['latest'], s['metrics'], last_end = index, metrics, row['query_end_us']
        s['frames'].append(row['frame'])
    result = []
    for world, binding in bindings.items():
        s = state.get(world, dict(episodes=[], frames=[]))
        frames = s['frames']
        require(not frames or max(frames)-min(frames) < 4096, 'observed native frame window exceeds bound')
        positive = [episode for episode in s['episodes'] if episode['qualified'] and episode['changed']]
        result.append(dict(binding=binding, passed=bool(positive), positive_same_head_pairs=len(positive),
            qualified_pairs=sum(e['qualified'] for e in s['episodes']), episodes=s['episodes'],
            observed_frame_window=[min(frames), max(frames)] if frames else None,
            missing_gates=[] if positive else ['no changed present actual same-H pair']))
    return dict(schema=1, passed=all(row['passed'] for row in result), records=len(rows), worlds=result,
        all_episodes_qualified=all(bool(row['episodes']) for row in result) and
            all(e['qualified'] for row in result for e in row['episodes']),
        scope='Native same-H decoded position deltas only; external ready/FEEL/journal bindings are caller-validated decoration. '
              'Requires one changed present pair per world, not completeness across all corrections. No worker Unity incarnation, '
              'cross-process QPC alignment, physical UI, renderer-cause or full feature acceptance claim.',
        full_feature_accepted=False)
