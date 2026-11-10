"""Explicit diagnostic-only confirmed native-state journal.

Candidates must come from an actual quiescent original Spectator31 Make/Get
pair. Confirmation publishes cached hashes only; it never queries or invents
native state. This is an observable parsed-state witness, not a checkpoint or
complete hidden-world fingerprint.
"""
from __future__ import annotations

import _thread
import ctypes as C
from dataclasses import dataclass
import hashlib
import json
import math
from pathlib import Path
import re
import struct


class ObservationError(ValueError):
    pass


@dataclass(frozen=True)
class PositionTraceSpec:
    """One native identity, not a Unity actor/incarnation binding."""
    entity_id: int
    unit_type: int
    army: int
    first_frame: int
    last_frame: int

    def __post_init__(self):
        if any(type(value) is not int or not 0 <= value <= 0xffffffff
               for value in (self.entity_id, self.unit_type, self.army)):
            raise ObservationError('invalid selected native identity')
        if self.unit_type == 0:
            raise ObservationError('selected native unit type must be positive')
        if (type(self.first_frame) is not int or type(self.last_frame) is not int or
                not 0 <= self.first_frame <= self.last_frame <= 0x7fffffff or
                self.last_frame-self.first_frame >= 4096):
            raise ObservationError('invalid selected native frame window')


def parse_position_trace_spec(value):
    """Shared strict spelling for the worker CLI and owned capture controller."""
    if (type(value) is not str or len(value) > 64 or
            re.fullmatch(r'(?:0|[1-9][0-9]*)(?::(?:0|[1-9][0-9]*)){4}', value) is None):
        raise ObservationError('expected ID:TYPE:ARMY:FIRST:LAST in canonical ASCII decimal')
    return PositionTraceSpec(*(int(field) for field in value.split(':')))


class _PositionTrace:
    """External Python-owned copies; never part of restored native memory."""
    context_fields = {'stage', 'head', 'confirmed', 'received', 'corrections',
                      'replayed_frames', 'query_begin_us', 'query_end_us'}

    def __init__(self, path, spec, maximum):
        if type(spec) is not PositionTraceSpec or type(maximum) is not int or not 1 <= maximum <= 8192:
            raise ObservationError('invalid selected native trace budget/specification')
        self.spec, self.maximum = spec, maximum
        self.stream = path.open('x', encoding='utf-8')
        self.buffer, self.total = [], 0
        self.world, self.revision = None, 0
        self.restore_base = None
        self.latest, self.last_frame, self.same_head = None, -1, None
        self.last_end = -1
        self.last_metrics = (0, 0)
        self.failed = self.closed = False

    def begin(self, world):
        if self.world is not None or self.buffer or self.failed or self.closed:
            raise ObservationError('selected native trace has an unfinished world/buffer')
        self.world, self.revision = world, 0
        self.restore_base = None
        self.latest, self.last_frame, self.same_head = None, -1, None
        self.last_metrics = (0, 0)

    def active(self, frame):
        return self.spec.first_frame <= frame <= self.spec.last_frame

    def _budget(self):
        if self.failed or self.closed or self.total >= self.maximum:
            raise ObservationError('selected native trace is closed/failed or its row budget reached')

    def _append(self, row):
        row['record'] = self.total
        row['clock_source'] = 'python.perf_counter_ns//1000'
        row['query_scope'] = 'existing-native-make-get-and-decode'
        self.buffer.append(row)
        self.total += 1

    def _entity(self, state):
        matches = []
        for entity in state['entities']:
            if type(entity) is not dict:
                raise ObservationError('selected native entities are malformed')
            if entity.get('id') == self.spec.entity_id:
                matches.append(entity)
        if len(matches) > 1:
            raise ObservationError('ambiguous selected native entity ID')
        if not matches:
            return dict(status='absent', observed_identity=None, missing_components=[],
                        position=None, position_bits=None)
        entity = matches[0]
        for name in ('id', 'army', 'type'):
            if name in entity and (type(entity[name]) is not int or not 0 <= entity[name] <= 0xffffffff):
                raise ObservationError('selected native identity component is invalid')
        missing = [name for name in ('army', 'type', 'position') if name not in entity]
        position, bits = None, None
        if 'position' in entity:
            vector = entity['position']
            if type(vector) is not list or len(vector) != 3:
                missing.append('position_vec3')
            else:
                try:
                    finite = all(type(value) in (int, float) and math.isfinite(value) for value in vector)
                except OverflowError:
                    finite = False
                if not finite:
                    raise ObservationError('selected native position is nonfinite/invalid')
                try:
                    raw = struct.pack('<fff', *vector)
                except (OverflowError, struct.error) as error:
                    raise ObservationError('selected native position is not finite float32') from error
                copied = list(struct.unpack('<fff', raw))
                if copied != vector:
                    raise ObservationError('selected native position is not the decoded float32 value')
                position, bits = copied, list(struct.unpack('<III', raw))
        identity = {name: entity.get(name) for name in ('id', 'army', 'type')}
        status = ('partial' if missing else 'identity_mismatch' if
                  (entity['army'], entity['type']) != (self.spec.army, self.spec.unit_type) else 'present')
        return dict(status=status, observed_identity=identity, missing_components=missing,
                    position=position if status == 'present' else None,
                    position_bits=bits if status == 'present' else None)

    def record(self, frame, state, context):
        if self.failed or self.closed:
            raise ObservationError('selected native trace is closed/failed')
        if not self.active(frame):
            # A clipped old sample cannot later masquerade as the physical H.
            self.latest, self.last_frame = None, frame
            return
        self._budget()
        if type(context) is not dict or set(context) != self.context_fields or context['stage'] not in ('ordinary', 'replay'):
            raise ObservationError('selected native position context is incomplete/unknown')
        for name in self.context_fields-{'stage'}:
            lower = -1 if name in ('head', 'confirmed', 'received') else 0
            upper = 0x7fffffff if lower == -1 else 0xffffffffffffffff
            if type(context[name]) is not int or not lower <= context[name] <= upper:
                raise ObservationError('selected native position context counter/clock invalid')
        if (context['confirmed'] > context['received'] or
                context['stage'] == 'ordinary' and frame != context['head']+1 or
                context['stage'] == 'replay' and (self.restore_base is None or not self.restore_base < frame <= context['head'])):
            raise ObservationError('selected native position context differs from actual decoded frame')
        begin, end = context['query_begin_us'], context['query_end_us']
        metrics = context['corrections'], context['replayed_frames']
        if begin < self.last_end or end < begin or any(a < b for a, b in zip(metrics, self.last_metrics)):
            raise ObservationError('selected native query clock/metrics regressed')
        entity = self._entity(state)
        after = context['stage'] == 'replay' and self.same_head is not None and frame == self.same_head
        row = dict(schema=1, event='after_replay_same_head' if after else 'native_position',
            world=self.world, frame=frame, revision=self.revision, query_revision=self.revision,
            checkpoint_base=self.restore_base, first_divergent_frame=None if self.restore_base is None else self.restore_base+1,
            watched_identity=dict(id=self.spec.entity_id, type=self.spec.unit_type, army=self.spec.army),
            context_source='same_decoded_native_query', **context, **entity)
        self._append(row)
        self.latest, self.last_frame = row, frame
        self.last_end, self.last_metrics = end, metrics
        if after:
            self.same_head = None

    def invalidate(self, frame):
        if type(frame) is not int or not -1 <= frame < 0x7fffffff:
            raise ObservationError('selected native checkpoint base is invalid')
        self._budget()
        revision = self.revision+1
        if self.latest is None:
            row = dict(schema=1, world=self.world, frame=self.last_frame, status='outside_window' if self.last_frame >= 0 else 'no_cached_state',
                position=None, position_bits=None, observed_identity=None, missing_components=[],
                watched_identity=dict(id=self.spec.entity_id, type=self.spec.unit_type, army=self.spec.army),
                stage=None, head=None, confirmed=None, received=None, corrections=None, replayed_frames=None,
                query_begin_us=None, query_end_us=None, query_revision=None, cached_from_record=None)
        else:
            row = dict(self.latest, cached_from_record=self.latest['record'])
        cached_is_head = self.latest is not None and (self.latest['stage'] == 'ordinary' or self.latest['head'] == self.last_frame)
        row['cached_physical_head'] = self.last_frame if cached_is_head else None
        if self.latest is not None and not cached_is_head:
            row.update(status='cached_frame_not_head', position=None, position_bits=None)
        row.update(event='before_restore_cached_head', revision=revision, checkpoint_base=frame,
                   first_divergent_frame=frame+1, context_source='cached_query_before_restore')
        self._append(row)
        self.revision = revision
        self.restore_base = frame
        self.same_head = self.last_frame if cached_is_head and self.last_frame > frame else None

    def flush(self):
        if self.failed or self.closed:
            raise ObservationError('selected native trace is closed/failed')
        try:
            for row in self.buffer:
                self.stream.write(json.dumps(row, separators=(',', ':'), allow_nan=False)+'\n')
            self.stream.flush()
        except BaseException:
            self.failed = True  # Preserve a partial failure, never retry duplicate writes.
            raise
        self.buffer.clear()

    def finish(self):
        self.flush()
        self.world, self.latest, self.same_head, self.last_frame = None, None, None, -1
        self.restore_base = None

    def close(self):
        if self.closed:
            return
        try:
            if not self.failed:
                self.flush()
        finally:
            self.closed = True
            self.stream.close()


def state_digest(state):
    # Exactly tools.verify_high_latency_clients.state_digest's normalization.
    canonical = {key: value for key, value in state.items() if key != 'raw_sha256'}
    return hashlib.sha256(json.dumps(canonical, sort_keys=True, separators=(',', ':')).encode()).hexdigest()


def windows_tick():
    clock = C.WinDLL('kernel32').GetTickCount64
    clock.argtypes, clock.restype = [], C.c_uint64
    return clock


class CanonicalStateObserver:
    def __init__(self, path, *, tick=None, max_pending=32, max_rows=4096,
                 position_trace=None, max_position_records=8192):
        if (type(max_pending) is not int or not 1 <= max_pending <= 32 or
                type(max_rows) is not int or not 1 <= max_rows <= 4096):
            raise ObservationError('invalid diagnostic state observation budget')
        self.path = Path(path).resolve()
        self.tick = tick if tick is not None else windows_tick()
        self.max_pending, self.max_rows = max_pending, max_rows
        self.owner = _thread.get_ident()
        self.stream = self.path.open('x', encoding='utf-8')
        self.position_trace = position_trace
        self._positions = None
        if position_trace is not None:
            try:
                self._positions = _PositionTrace(self.path.with_name('native-positions.jsonl'), position_trace, max_position_records)
            except BaseException:
                self.stream.close()
                raise
        self.world = None
        self.pending = {}
        self.published = -1
        self.rows = self.last_replayed = self.last_corrections = 0
        self.closed = False

    def _owner(self):
        if _thread.get_ident() != self.owner or self.closed:
            raise ObservationError('diagnostic state observer is closed/foreign-thread')

    def begin_world(self, world):
        self._owner()
        if self.world is not None or type(world) is not int or not 1 <= world <= 0xffffffffffffffff:
            raise ObservationError('diagnostic state world lifecycle differs')
        if self._positions is not None:
            self._positions.begin(world)
        self.world, self.pending, self.published = world, {}, -1
        self.last_replayed = self.last_corrections = 0

    def _world(self, world):
        self._owner()
        if type(world) is not int or world != self.world or self.world is None:
            raise ObservationError('diagnostic state belongs to another world')

    def prepare_frame(self, world, frame):
        """Check bounds BEFORE the caller performs the additional native query."""
        self._world(world)
        if type(frame) is not int or not self.published < frame <= 0x7fffffff:
            raise ObservationError('diagnostic candidate predates confirmed state')
        if frame not in self.pending and len(self.pending) >= self.max_pending:
            raise ObservationError('diagnostic state pending-frame budget reached')

    def position_active(self, world, frame):
        self._world(world)
        if type(frame) is not int or not 0 <= frame <= 0x7fffffff:
            raise ObservationError('selected native frame is invalid')
        return self._positions is not None and self._positions.active(frame)

    def record(self, world, frame, state, *, context=None):
        self.prepare_frame(world, frame)
        if (type(state) is not dict or state.get('frame') != frame or state.get('viewer') != 31 or
                type(state.get('entities')) is not list):
            raise ObservationError('diagnostic state is not the actual full Spectator31 frame')
        value = state_digest(state)
        if frame in self.pending and self.pending[frame] != value:
            raise ObservationError('diagnostic candidate changed without checkpoint invalidation')
        if self._positions is not None:
            self._positions.record(frame, state, context)
        self.pending[frame] = value

    def invalidate_after(self, world, frame):
        self._world(world)
        if type(frame) is not int or frame < self.published:
            raise ObservationError('cannot invalidate published diagnostic native state')
        if self._positions is not None:
            self._positions.invalidate(frame)
        self.pending = {number: value for number, value in self.pending.items() if number <= frame}

    def promote(self, world, frontier, metrics):
        self._world(world)
        if type(frontier) is not int or not self.published <= frontier <= 0x7fffffff:
            raise ObservationError('diagnostic confirmed frontier is not monotonic')
        corrections, replayed = metrics['corrections'], metrics['replayed_frames']
        if (type(corrections) is not int or type(replayed) is not int or
                not self.last_corrections <= corrections <= 0xffffffffffffffff or
                not self.last_replayed <= replayed <= 0xffffffffffffffff):
            raise ObservationError('diagnostic replay metrics regressed')
        if frontier == self.published:
            return  # No C advance: no query,write,flush or lost replay delta.
        frames = range(self.published + 1, frontier + 1)
        if (frontier - self.published > self.max_pending or
                any(number not in self.pending for number in frames)):
            raise ObservationError('diagnostic confirmed native prefix has a missing candidate')
        if self.rows + frontier - self.published > self.max_rows:
            raise ObservationError('diagnostic state row budget reached')
        # Preflight the complete promotion before writing any rows. A failed
        # flush remains a failed diagnostic, with the partial file retained.
        for number in frames:
            tick = int(self.tick())
            if not 0 <= tick <= 0xffffffffffffffff:
                raise ObservationError('diagnostic Windows tick is invalid')
            row = dict(schema=1, event='confirmed_native_state', world=world, frame=number,
                parsed_state_sha256=self.pending[number], confirmed_frontier=frontier,
                corrections=corrections, corrections_delta=corrections-self.last_corrections,
                replayed_frames_total=replayed, replayed_frames_delta=replayed-self.last_replayed,
                tick_ms=tick)
            self.stream.write(json.dumps(row, separators=(',', ':'), allow_nan=False) + '\n')
            self.rows += 1
            self.published = number
            self.last_replayed, self.last_corrections = replayed, corrections
            del self.pending[number]
        self.stream.flush()

    def finish_world(self, world):
        self._owner()
        if self.world is None:
            return
        self._world(world)
        if self._positions is not None:
            self._positions.finish()
        self.pending.clear()  # Never publish unconfirmed physical/replay tails.
        self.world, self.published = None, -1

    def close(self):
        if self.closed:
            return
        self._owner()
        try:
            self.pending.clear()
            self.world = None
            self.stream.flush()
        finally:
            self.closed = True
            self.stream.close()
            if self._positions is not None:
                self._positions.close()
