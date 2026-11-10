"""Explicit diagnostic-only confirmed native-state journal.

Candidates must come from an actual quiescent original Spectator31 Make/Get
pair. Confirmation publishes cached hashes only; it never queries or invents
native state. This is an observable parsed-state witness, not a checkpoint or
complete hidden-world fingerprint.
"""
from __future__ import annotations

import _thread
import ctypes as C
import hashlib
import json
from pathlib import Path


class ObservationError(ValueError):
    pass


def state_digest(state):
    # Exactly tools.verify_high_latency_clients.state_digest's normalization.
    canonical = {key: value for key, value in state.items() if key != 'raw_sha256'}
    return hashlib.sha256(json.dumps(canonical, sort_keys=True, separators=(',', ':')).encode()).hexdigest()


def windows_tick():
    clock = C.WinDLL('kernel32').GetTickCount64
    clock.argtypes, clock.restype = [], C.c_uint64
    return clock


class CanonicalStateObserver:
    def __init__(self, path, *, tick=None, max_pending=32, max_rows=4096):
        if (type(max_pending) is not int or not 1 <= max_pending <= 32 or
                type(max_rows) is not int or not 1 <= max_rows <= 4096):
            raise ObservationError('invalid diagnostic state observation budget')
        self.path = Path(path).resolve()
        self.tick = tick if tick is not None else windows_tick()
        self.max_pending, self.max_rows = max_pending, max_rows
        self.owner = _thread.get_ident()
        self.stream = self.path.open('x', encoding='utf-8')
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

    def record(self, world, frame, state):
        self.prepare_frame(world, frame)
        if (type(state) is not dict or state.get('frame') != frame or state.get('viewer') != 31 or
                type(state.get('entities')) is not list):
            raise ObservationError('diagnostic state is not the actual full Spectator31 frame')
        value = state_digest(state)
        if frame in self.pending and self.pending[frame] != value:
            raise ObservationError('diagnostic candidate changed without checkpoint invalidation')
        self.pending[frame] = value

    def invalidate_after(self, world, frame):
        self._world(world)
        if type(frame) is not int or frame < self.published:
            raise ObservationError('cannot invalidate published diagnostic native state')
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
