"""Unintegrated prediction experiment using fresh-world replay, never view restoration.

Callers supply complete, already command-validated canonical InputActions. Only
their frame/timing envelope is checked here. Factories and worlds retain the
existing cancellable async create/process_frame/owned-close contract. Parsed
state fingerprints detect observed prefix divergence; they are not checkpoints
or proof of equality of hidden native state.
"""
from __future__ import annotations

import asyncio
from dataclasses import dataclass
import hashlib
import json
import math
import struct
import time

from server.profile_io import _await_owned
from server.protobuf_wire import parse_fields, WireError

MAX_FRAME_BYTES = 2 * 1024 * 1024


class PredictionError(RuntimeError): pass
class PredictionInputError(ValueError): pass
class PredictionLimitError(PredictionInputError): pass
class PredictionBudgetError(PredictionError): pass
class PredictionReplayError(PredictionError): pass
class PredictionCleanupError(PredictionError): pass


@dataclass(frozen=True)
class Confirmation:
    frame: int
    status: str
    replayed_frames: int = 0


def frame_number(data):
    if not isinstance(data, bytes) or not 1 <= len(data) <= MAX_FRAME_BYTES:
        raise PredictionInputError('prediction InputActions size/type limit')
    try:
        fields = parse_fields(data, max_bytes=MAX_FRAME_BYTES, max_fields=32)
        header, players = {}, 0
        wire_types = {1: 0, 2: 0, 3: 0, 4: 5, 6: 2, 7: 0}
        for field in fields:
            if field.number not in wire_types or field.wire_type != wire_types[field.number]:
                raise PredictionInputError('unsupported prediction InputActions field')
            if field.number == 6:
                players += 1
                if players > 4: raise PredictionInputError('prediction player count limit')
            else:
                if field.number in header: raise PredictionInputError('duplicate prediction frame header')
                header[field.number] = field.value
        frame = header.get(1, 0)
        if not 0 <= frame <= 0x7fffffff:
            raise PredictionInputError('prediction frame outside nonnegative int32')
        if header.get(2) != 20 or header.get(3) != 50 or 4 not in header or struct.unpack('<f', header[4])[0] != 1.0:
            raise PredictionInputError('prediction requires 20 Hz, 50 ms and speed 1')
        return frame
    except (WireError, struct.error) as error:
        raise PredictionInputError('invalid prediction InputActions envelope') from error


def _fingerprint(result, world, expected):
    if (type(getattr(result, 'frame', None)) is not int or result.frame != expected or
            type(getattr(world, 'frame', None)) is not int or world.frame != expected or
            not isinstance(getattr(result, 'state', None), dict) or
            type(result.state.get('frame')) is not int or result.state['frame'] != expected):
        raise PredictionReplayError('prediction world returned an invalid completed frame')
    state = {key: value for key, value in result.state.items() if key != 'raw_sha256'}
    try:
        raw = json.dumps(dict(frame=expected, seconds=getattr(result, 'game_time_seconds', None), state=state),
                         sort_keys=True, separators=(',', ':'), allow_nan=False).encode('utf-8')
    except (TypeError, ValueError) as error:
        raise PredictionReplayError('prediction world returned an invalid parsed state') from error
    return hashlib.sha256(raw).hexdigest()


class PredictionController:
    def __init__(self, bootstrap, create_world, *, max_ahead=12, max_replay_frames=1200,
                 cleanup_timeout=2.0, operation_timeout=30.0, max_history_bytes=64*1024*1024):
        if not isinstance(bootstrap, bytes) or not 1 <= len(bootstrap) <= 32*1024*1024 or not callable(create_world):
            raise ValueError('prediction requires bounded bootstrap bytes and an async world factory')
        for name, value, maximum in (('max_ahead', max_ahead, 120), ('max_replay_frames', max_replay_frames, 100000),
                                     ('max_history_bytes', max_history_bytes, 256*1024*1024)):
            if type(value) is not int or not 1 <= value <= maximum: raise ValueError('invalid prediction ' + name)
        for name, value in (('cleanup_timeout', cleanup_timeout), ('operation_timeout', operation_timeout)):
            if type(value) not in (int, float) or not math.isfinite(value) or not 0 < value <= 600:
                raise ValueError('invalid prediction ' + name)
        self._bootstrap, self._factory = bootstrap, create_world
        self.max_ahead, self.max_replay_frames = max_ahead, max_replay_frames
        self.cleanup_timeout, self.operation_timeout, self.max_history_bytes = cleanup_timeout, operation_timeout, max_history_bytes
        self._world, self._result, self._head = None, None, -1
        self._confirmed, self._confirmed_keys, self._speculative, self._speculative_keys = [], [], [], []
        self._pending_authoritative = None
        self._owned = []
        self._failed = self._closed = False
        self._lock, self._close_task = asyncio.Lock(), None
        self._stats = dict(predicted_frames=0, authoritative_frames=0, matched_frames=0, mismatches=0,
                           corrections=0, rebuilds=0, replayed_frames=0, last_replay_frames=0,
                           last_rebuild_ms=0.0, max_rebuild_ms=0.0, last_factory_create_seconds=0.0,
                           last_replay_seconds=0.0, last_cleanup_seconds=0.0, cleanup_failures=0, terminal_failures=0)

    @classmethod
    async def create(cls, bootstrap, create_world, **kwargs):
        owner = cls(bootstrap, create_world, **kwargs)
        async with owner._lock:
            await owner._guarded(owner._initialize)
        return owner

    def _active(self):
        if self._failed or self._closed: raise PredictionError('prediction controller is terminal or closed')

    @property
    def world(self): self._active(); return self._world
    @property
    def current_result(self): self._active(); return self._result
    @property
    def confirmed_frame(self): return len(self._confirmed) - 1
    @property
    def predicted_frame(self): return self._head
    @property
    def confirmed_inputs(self): return tuple(self._confirmed)
    @property
    def speculative_inputs(self): return tuple(self._speculative)
    @property
    def pending_authoritative(self): return self._pending_authoritative
    @property
    def failed(self): return self._failed
    @property
    def closed(self): return self._closed
    @property
    def metrics(self):
        return dict(self._stats, confirmed_frame=self.confirmed_frame, predicted_frame=self._head,
                    speculative_frames=len(self._speculative), failed=self._failed, closed=self._closed,
                    cleanup_complete=not self._owned)

    async def _new_world(self):
        started = time.perf_counter()
        try: world = await self._factory(self._bootstrap)
        finally: self._stats['last_factory_create_seconds'] = time.perf_counter() - started
        if any(world is item for item in self._owned): raise PredictionReplayError('factory reused an owned prediction world')
        self._owned.append(world)
        self._active()
        if type(getattr(world, 'frame', None)) is not int or world.frame != -1:
            raise PredictionReplayError('fresh prediction world must start at frame -1')
        return world

    async def _initialize(self): self._world = await self._new_world()

    async def _step(self, world, data):
        expected = frame_number(data)
        if world.frame + 1 != expected: raise PredictionReplayError('prediction replay frame order changed')
        result = await world.process_frame(data, dt_ms=50)
        self._active()
        return result, _fingerprint(result, world, expected)

    async def _close_one(self, world):
        started = time.perf_counter()
        try:
            await asyncio.wait_for(world.close(), self.cleanup_timeout)
        except BaseException as error:
            self._stats['cleanup_failures'] += 1
            raise PredictionCleanupError('owned prediction world cleanup failed or timed out') from error
        finally: self._stats['last_cleanup_seconds'] = time.perf_counter() - started
        self._owned = [item for item in self._owned if item is not world]

    async def _cleanup(self):
        errors = []
        for world in tuple(self._owned):
            try: await self._close_one(world)
            except PredictionCleanupError as error: errors.append(error)
        return not errors

    @staticmethod
    async def _drain(task):
        while not task.done():
            try: await _await_owned(task)
            except asyncio.CancelledError: pass
        return task.result()

    async def _guarded(self, operation):
        self._active()
        try:
            return await asyncio.wait_for(operation(), self.operation_timeout)
        except BaseException as error:
            self._failed = True; self._world = None
            self._stats['terminal_failures'] += 1
            await self._drain(asyncio.create_task(self._cleanup()))
            if isinstance(error, (asyncio.CancelledError, PredictionError)): raise
            raise PredictionError('prediction world operation failed or timed out') from error

    def _history_budget(self, extra):
        if sum(map(len, self._confirmed)) + sum(map(len, self._speculative)) + extra > self.max_history_bytes:
            raise PredictionBudgetError('prediction input journal byte budget exceeded')

    async def predict(self, data):
        async with self._lock:
            self._active(); frame = frame_number(data)
            if frame != self._head + 1: raise PredictionInputError('predictions must be contiguous and new')
            if frame - self.confirmed_frame > self.max_ahead: raise PredictionLimitError('prediction ahead limit reached')
            async def apply():
                self._history_budget(len(data))
                result, key = await self._step(self._world, data)
                self._head, self._result = frame, result
                self._speculative.append(data); self._speculative_keys.append(key)
                self._stats['predicted_frames'] += 1
                return result
            return await self._guarded(apply)

    async def confirm(self, data):
        async with self._lock:
            self._active(); frame = frame_number(data)
            if frame != self.confirmed_frame + 1: raise PredictionInputError('authority must be contiguous and new')
            self._pending_authoritative = data  # Retained if reconciliation becomes terminal.
            return await self._guarded(lambda: self._confirm(data, frame))

    async def _confirm(self, data, frame):
        if not self._speculative:
            self._history_budget(len(data))
            result, key = await self._step(self._world, data)
            self._head, self._result = frame, result
            status, replayed = 'authoritative', 0
        elif self._speculative[0] == data:
            key = self._speculative_keys.pop(0); self._speculative.pop(0)
            self._stats['matched_frames'] += 1
            status, replayed = 'matched', 0
        else:
            self._stats['mismatches'] += 1
            return await self._reconcile(data, frame)
        self._confirmed.append(data); self._confirmed_keys.append(key)
        self._pending_authoritative = None; self._stats['authoritative_frames'] += 1
        return Confirmation(frame, status, replayed)

    async def _reconcile(self, data, frame):
        started = time.perf_counter()
        trailing = self._speculative[1:]
        replay = [*self._confirmed, data, *trailing]
        self._stats['last_replay_frames'] = len(replay)
        if len(replay) > self.max_replay_frames:
            raise PredictionBudgetError('full prediction reconstruction exceeds replay frame budget')
        if sum(map(len, replay)) > self.max_history_bytes:
            raise PredictionBudgetError('corrected prediction journal byte budget exceeded')
        self._stats['rebuilds'] += 1
        try:
            candidate = await self._new_world()
            keys, result = [], None
            replay_started = time.perf_counter()
            try:
                for index, payload in enumerate(replay):
                    result, key = await self._step(candidate, payload)
                    self._stats['replayed_frames'] += 1
                    if index < len(self._confirmed_keys) and key != self._confirmed_keys[index]:
                        raise PredictionReplayError('confirmed parsed-state replay diverged')
                    keys.append(key)
            finally: self._stats['last_replay_seconds'] = time.perf_counter() - replay_started
            old = self._world
            # Publish only a completely rebuilt world and immutable-input journals.
            self._world, self._result = candidate, result
            self._confirmed.append(data); self._confirmed_keys.append(keys[frame])
            self._speculative, self._speculative_keys = trailing, keys[frame+1:]
            self._pending_authoritative = None
            await self._close_one(old)
            self._stats['corrections'] += 1; self._stats['authoritative_frames'] += 1
            return Confirmation(frame, 'corrected', len(replay))
        finally:
            elapsed = (time.perf_counter() - started) * 1000
            self._stats['last_rebuild_ms'] = elapsed
            self._stats['max_rebuild_ms'] = max(self._stats['max_rebuild_ms'], elapsed)

    async def _close(self):
        async with self._lock:
            self._world = None
            if not await self._cleanup():
                self._failed = True
                raise PredictionCleanupError('prediction controller could not close every owned world')

    async def close(self):
        if self._close_task is None:
            self._closed = True
            self._close_task = asyncio.create_task(self._close())
        try: await _await_owned(self._close_task)
        except asyncio.CancelledError:
            try: await self._drain(self._close_task)
            except PredictionError: pass
            raise
