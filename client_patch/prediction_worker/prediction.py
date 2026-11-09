"""Single-owner in-place checkpoint reconciliation; deliberately unintegrated.

Authority enqueueing only validates/retains bytes. The caller invokes
before_next_frame AFTER previous ordinary native queries, at a quiescent owner
boundary, then forwards its returned bytes exactly and reports the successful
ordinary step with after_native_frame. Only before_next_frame restores/replays.

Adapter methods are synchronous and raise on failure: capture(frame)->token,
restore(token), drop(token), process_frame(raw, 50), root_bindings()->immutable
tuple/scalars. Replay performs original native calls, never view-state copying
or presentation queries. Adapter/world lifetime, authoritative command/entity
admission, terminal draining, Unity rendering/UI and native completeness proofs
belong to the integration owner. close() releases snapshots, not the world.
"""
from __future__ import annotations

import struct
import time

MAX_FRAME_BYTES = 2 * 1024 * 1024
MAX_FRAME = 0x7fffffff


class PredictionError(RuntimeError): pass
class PredictionInputError(ValueError): pass
class PredictionBudgetError(PredictionError): pass
class PredictionBindingError(PredictionError): pass
class PredictionReplayError(PredictionError): pass
class PredictionCleanupError(PredictionError): pass


def frame_number(data):
    """Bounded InputActions envelope only; no nested command authorization.

    This local reader mirrors transport.prediction.frame_number without its
    async/server dependencies. Proto3 omitted GameFrame means frame0; players
    are repeated field6, exactly as server.game_data.encode_frame emits them.
    """
    if not isinstance(data, bytes) or not 1 <= len(data) <= MAX_FRAME_BYTES:
        raise PredictionInputError('prediction InputActions size/type limit')
    offset = 0

    def varint():
        nonlocal offset
        value = 0
        for index in range(10):
            if offset == len(data):
                raise PredictionInputError('truncated prediction varint')
            byte = data[offset]
            offset += 1
            if index == 9 and byte > 1:
                raise PredictionInputError('prediction varint exceeds uint64')
            value |= (byte & 127) << (index * 7)
            if byte < 128:
                return value
        raise PredictionInputError('overlong prediction varint')

    header, players, count = {}, 0, 0
    wire_types = {1: 0, 2: 0, 3: 0, 4: 5, 6: 2, 7: 0}
    while offset < len(data):
        count += 1
        if count > 32:
            raise PredictionInputError('prediction field count limit')
        key = varint()
        number, kind = key >> 3, key & 7
        if number not in wire_types or kind != wire_types[number]:
            raise PredictionInputError('unsupported prediction InputActions field')
        if kind == 0:
            value = varint()
        else:
            size = 4 if kind == 5 else varint()
            if size > len(data) - offset:
                raise PredictionInputError('truncated prediction field')
            value = data[offset:offset + size] if kind == 5 else None
            offset += size
        if number == 6:
            players += 1
            if players > 4:
                raise PredictionInputError('prediction player count limit')
        elif number in header:
            raise PredictionInputError('duplicate prediction frame header')
        else:
            header[number] = value
    frame = header.get(1, 0)
    if not 0 <= frame <= MAX_FRAME:
        raise PredictionInputError('prediction frame outside nonnegative int32')
    if (header.get(2) != 20 or header.get(3) != 50 or
            header.get(4) != struct.pack('<f', 1.0)):
        raise PredictionInputError('prediction requires20Hz,50ms and speed1')
    return frame


def _immutable(value):
    return type(value) in (int, bool, str, bytes, type(None)) or (
        isinstance(value, tuple) and all(_immutable(item) for item in value))


class Reconciler:
    def __init__(self, adapter, *, max_ahead=12, max_journal_bytes=16 * 1024 * 1024,
                 max_checkpoints=14):
        for name, value, maximum in (('max_ahead', max_ahead, 12),
                                     ('max_journal_bytes', max_journal_bytes, 64 * 1024 * 1024),
                                     ('max_checkpoints', max_checkpoints, 16)):
            if type(value) is not int or not 1 <= value <= maximum:
                raise ValueError('invalid native prediction ' + name)
        if any(not callable(getattr(adapter, name, None)) for name in
               ('capture', 'restore', 'drop', 'process_frame', 'root_bindings')):
            raise ValueError('native prediction requires a synchronous checkpoint adapter')
        self.adapter = adapter
        self.max_ahead, self.max_journal_bytes, self.max_checkpoints = max_ahead, max_journal_bytes, max_checkpoints
        self._head = self._confirmed = self._received = -1
        self._physical, self._authority, self._checkpoints = {}, {}, {}
        self._revisions, self._revision_bytes = {}, 0
        self._tokens, self._orphans = set(), []
        self._physical_bytes = self._authority_bytes = 0
        self._prepared = None
        self._failed = self._closed = False
        self._failure = None
        self._stats = dict(native_frames=0, enqueued_authority=0, confirmations=0, matched_frames=0,
                           mismatches=0, corrected_frames=0, corrections=0, restores=0,
                           replayed_frames=0, last_replay_frames=0, captures=0, drops=0,
                           cleanup_failures=0, terminal_failures=0, peak_checkpoints=0,
                           peak_pending=0, peak_journal_bytes=0, peak_ahead=0,
                           last_reconcile_ms=0.0, max_reconcile_ms=0.0)
        self._stats.update(revised_frames=0,revision_requests=0)

    @property
    def confirmed_frame(self): return self._confirmed
    @property
    def predicted_frame(self): return self._head
    @property
    def received_frame(self): return self._received
    @property
    def pending(self): return tuple(self._authority.items())
    @property
    def failed(self): return self._failed
    @property
    def closed(self): return self._closed
    @property
    def metrics(self):
        return dict(self._stats, confirmed_frame=self._confirmed, predicted_frame=self._head,
                    received_frame=self._received, journal_bytes=self._journal_bytes(),
                    physical_frames=len(self._physical), pending=len(self._authority),
                    revised_guesses=len(self._revisions),
                    checkpoints=len(self._checkpoints), prepared=self._prepared is not None,
                    failed=self._failed, closed=self._closed, failure=self._failure,
                    cleanup_complete=not self._checkpoints and not self._orphans)

    def _active(self):
        if self._failed or self._closed:
            raise PredictionError('native prediction match is terminal or retired')

    def prime(self):
        """Take the initial full checkpoint during loading,before READY."""
        self._active()
        if self._head != -1 or self._received != -1 or self._prepared is not None or self._checkpoints:
            raise PredictionInputError('initial prediction checkpoint already used')
        try:
            self._capture(-1)
        except BaseException as error:
            self._terminal(error, cleanup=True)
            raise

    def _capacity(self, extra=0):
        if self._journal_bytes() + extra > self.max_journal_bytes:
            raise PredictionBudgetError('native prediction journal byte budget reached')

    def _journal_bytes(self):
        return (self._physical_bytes + self._authority_bytes + self._revision_bytes +
                (len(self._prepared) if self._prepared is not None else 0))

    def _peaks(self):
        for name, value in (('peak_checkpoints', len(self._checkpoints)), ('peak_pending', len(self._authority)),
                            ('peak_journal_bytes', self._journal_bytes()),
                            ('peak_ahead', self._head - self._confirmed)):
            self._stats[name] = max(self._stats[name], value)

    def _bindings(self):
        value = self.adapter.root_bindings()
        if not _immutable(value):
            raise PredictionBindingError('native root binding token must be immutable tuple/scalars')
        return value

    def _capture(self, frame):
        if frame in self._checkpoints:
            return
        if len(self._checkpoints) >= self.max_checkpoints:
            raise PredictionBudgetError('native prediction checkpoint ring reached its limit')
        binding = self._bindings()
        token = self.adapter.capture(frame)
        if token is None or token is False or token == 0:
            raise PredictionReplayError('native checkpoint adapter returned an invalid token')
        self._orphans.append(token)
        try:
            duplicate = token in self._tokens
        except TypeError as error:
            raise PredictionReplayError('native checkpoint token must be hashable') from error
        if duplicate:
            self._orphans.pop()  # Already owned; never drop the same native handle twice.
            raise PredictionReplayError('native checkpoint adapter reused an owned token')
        self._checkpoints[frame] = token, binding
        self._tokens.add(token)
        self._orphans.pop()
        self._stats['captures'] += 1
        self._peaks()
        if self._bindings() != binding:
            raise PredictionBindingError('native root bindings changed during capture')

    def _drop(self, frame):
        token, _ = self._checkpoints[frame]
        try:
            self.adapter.drop(token)
        except BaseException:
            self._stats['cleanup_failures'] += 1
            raise
        del self._checkpoints[frame]
        self._tokens.discard(token)
        self._stats['drops'] += 1

    def _cleanup_owned(self):
        for frame in sorted(self._checkpoints, reverse=True):
            try:
                self._drop(frame)
            except BaseException:
                pass  # Ownership remains retained and cleanup failure is counted.
        for index in range(len(self._orphans) - 1, -1, -1):
            try:
                self.adapter.drop(self._orphans[index])
            except BaseException:
                self._stats['cleanup_failures'] += 1
            else:
                self._orphans.pop(index)
                self._stats['drops'] += 1
        return not self._checkpoints and not self._orphans

    def _terminal(self, error, *, cleanup):
        if not self._failed:
            self._stats['terminal_failures'] += 1
            self._failure = str(error)
        self._failed = True
        if cleanup:
            self._cleanup_owned()

    def _prune_confirmed(self):
        # after_native_frame can confirm F, but capture F after ordinary queries
        # before releasing its older base. No drops happen from record/enqueue.
        if self._confirmed in self._checkpoints:
            for frame in sorted(self._checkpoints):
                if frame < self._confirmed:
                    self._drop(frame)

    def _confirm_matches(self, corrected=()):
        while self._authority:
            frame = next(iter(self._authority))
            if frame > self._head:
                return
            if frame != self._confirmed + 1 or frame not in self._physical:
                raise PredictionReplayError('native prediction journal lost its contiguous prefix')
            raw = self._authority[frame]
            if raw != self._physical[frame]:
                return
            self._authority_bytes -= len(self._authority.pop(frame))
            self._physical_bytes -= len(self._physical.pop(frame))
            self._revision_bytes -= len(self._revisions.pop(frame,b''))
            self._confirmed = frame
            self._stats['confirmations'] += 1
            self._stats['corrected_frames' if frame in corrected else 'matched_frames'] += 1

    def enqueue_authority(self, raw):
        self._active()
        frame = frame_number(raw)
        if frame != self._received + 1:
            raise PredictionInputError('authority must be new and contiguous from frame0')
        try:
            if len(self._authority) >= self.max_checkpoints:
                raise PredictionBudgetError('native prediction authority queue reached its limit')
            self._capacity(len(raw))
        except PredictionBudgetError as error:
            self._terminal(error, cleanup=False)  # Control enqueue never calls any adapter method.
            raise
        self._authority[frame] = raw
        self._authority_bytes += len(raw)
        self._received = frame
        self._stats['enqueued_authority'] += 1
        self._peaks()

    def revise_unconfirmed(self, proposed):
        """Stage a COMPLETE replacement plan for earlier speculative guesses.

        An ordered command ledger uses this after authority retires/reanchors
        pending inputs. Authority is immutable and always wins. This method
        validates/stages bytes only;restore/replay waits for before_next_frame.
        """
        self._active()
        if type(proposed) is not dict or len(proposed) > self.max_ahead:
            raise PredictionInputError('invalid speculative revision plan')
        staged = {}
        for frame,raw in proposed.items():
            if (type(frame) is not int or not self._confirmed < frame <= self._head or
                    frame not in self._physical or frame in self._authority or frame_number(raw) != frame):
                raise PredictionInputError('revision must name an unconfirmed,unknown-authority physical frame')
            if raw != self._physical[frame]:staged[frame] = raw
        size = sum(map(len,staged.values()))
        try:
            self._capacity(size-self._revision_bytes)
        except PredictionBudgetError as error:
            self._terminal(error,cleanup=False)
            raise
        self._revisions,self._revision_bytes = staged,size
        self._stats['revision_requests'] += 1
        self._peaks()

    def after_native_frame(self, raw):
        self._active()
        try:
            frame = frame_number(raw)
            if frame != self._head + 1 or (self._prepared is not None and raw != self._prepared):
                raise PredictionInputError('ordinary native frame differs from the prepared contiguous input')
            if self._prepared is None and self._head != -1:
                raise PredictionInputError('ordinary native frame skipped its quiescent boundary')
            if frame - self._confirmed > self.max_ahead:
                raise PredictionBudgetError('native prediction exceeded its ahead limit')
            self._capacity(0 if self._prepared is not None else len(raw))
            self._physical[frame] = raw
            self._physical_bytes += len(raw)
            self._head = frame
            self._prepared = None
            self._stats['native_frames'] += 1
            self._peaks()
            self._confirm_matches()
        except PredictionInputError as cause:
            error = PredictionReplayError('invalid already-executed ordinary native frame')
            self._terminal(error, cleanup=False)
            raise error from cause
        except BaseException as error:
            self._terminal(error, cleanup=False)
            raise

    def _repair(self):
        self._confirm_matches()
        revisions = {frame:raw for frame,raw in self._revisions.items()
                     if frame > self._confirmed and frame not in self._authority}
        starts = list(revisions)
        if self._authority and next(iter(self._authority)) <= self._head:
            starts.append(next(iter(self._authority)))
        if not starts:
            self._revisions.clear();self._revision_bytes = 0
            return
        first = min(starts)
        if first - 1 not in self._checkpoints:
            raise PredictionReplayError('native correction lacks the preceding checkpoint')
        planned = dict(self._physical)
        planned.update(revisions)
        mismatches = set()
        for frame, raw in self._authority.items():
            if frame > self._head:
                break
            if frame not in planned:
                raise PredictionReplayError('native correction lost a recorded frame')
            if planned[frame] != raw:
                mismatches.add(frame)
            planned[frame] = raw
        replay = [(frame, planned[frame]) for frame in range(first, self._head + 1)]
        if len(replay) > self.max_ahead:
            raise PredictionBudgetError('native correction replay exceeded its ahead bound')
        for frame, raw in replay:
            if frame_number(raw) != frame:
                raise PredictionReplayError('native correction frame identity changed')
        bytes_after = sum(map(len, planned.values()))
        if bytes_after + self._authority_bytes + self._revision_bytes > self.max_journal_bytes:
            raise PredictionBudgetError('native correction journal byte budget reached')
        token, binding = self._checkpoints[first - 1]
        if self._bindings() != binding:
            raise PredictionBindingError('native FLS/TLS/owner bindings differ before restore')
        self._stats['mismatches'] += len(mismatches)
        self._stats['revised_frames'] += len(revisions)
        self.adapter.restore(token)
        self._stats['restores'] += 1
        if self._bindings() != binding:
            raise PredictionBindingError('native root bindings changed during restore')
        for frame in sorted(self._checkpoints, reverse=True):
            if frame >= first:
                self._drop(frame)
        for frame, raw in replay:
            self.adapter.process_frame(raw, 50)
            self._stats['last_replay_frames'] += 1
            self._stats['replayed_frames'] += 1
            self._capture(frame)  # Recapture internal boundaries, without querying presentation.
        self._physical, self._physical_bytes = planned, bytes_after
        self._revisions.clear();self._revision_bytes = 0
        self._stats['corrections'] += 1
        self._confirm_matches(mismatches)

    def before_next_frame(self, next_raw):
        self._active()
        frame = frame_number(next_raw)
        if frame != self._head + 1 or self._prepared is not None:
            raise PredictionInputError('next ordinary frame must follow the physical head exactly once')
        started = time.perf_counter()
        self._stats['last_replay_frames'] = 0
        try:
            self._capture(self._head)  # Includes initial-1 when called before ordinary frame0.
            self._prune_confirmed()
            self._repair()
            self._prune_confirmed()
            chosen = self._authority.get(frame, next_raw)
            if frame - self._confirmed > self.max_ahead:
                raise PredictionBudgetError('next ordinary frame would exceed prediction lead')
            self._capacity(len(chosen))
            self._prepared = chosen
            self._peaks()
            return chosen
        except PredictionError as error:
            self._terminal(error, cleanup=True)
            raise
        except BaseException as cause:
            error = PredictionReplayError('native reconciliation boundary failed')
            self._terminal(error, cleanup=True)
            raise error from cause
        finally:
            elapsed = (time.perf_counter() - started) * 1000
            self._stats['last_reconcile_ms'] = elapsed
            self._stats['max_reconcile_ms'] = max(self._stats['max_reconcile_ms'], elapsed)

    def close(self):
        """At an owned quiescent boundary, before caller destroys the world.

        One bounded drop attempt per retained handle per call. Failed handles
        remain owned for an explicit retry; no cleanup success is fabricated.
        """
        self._closed = True
        self._prepared = None
        self._physical.clear()
        self._authority.clear()
        self._revisions.clear();self._revision_bytes = 0
        self._physical_bytes = self._authority_bytes = 0
        if not self._cleanup_owned():
            error = PredictionCleanupError('native checkpoint cleanup incomplete')
            self._terminal(error, cleanup=False)
            raise error
