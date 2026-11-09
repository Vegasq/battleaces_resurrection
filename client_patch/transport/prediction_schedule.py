"""Unintegrated numbered-input planner: only authoritative receipts mint credits.

One instance belongs to one match. The caller must first validate and route the
existing p.FRAME/public FRAME stream to that match, and call mark_confirmed only
after its world has reconciled that authority. This module neither predicts a
world nor authenticates/authorizes commands. It never creates JoinArmy or idle
inputs: startup bodies and every later input are supplied explicitly.

Observing F proves the server has completed F, so it safely permits input F+W.
Speculative progress, presentation progress and confirmation do not grant input
credits. Existing native/server/bridge code is not changed or imported here as
an active transport.
"""
from __future__ import annotations

from collections import deque
from dataclasses import dataclass
import struct

from server.protocol import validate_input_window, MAX_INPUT
from server.protobuf_wire import parse_fields, WireError

MAX_FRAME = 0x7fffffff


class InputCreditError(ValueError):
    pass


def _frame(value):
    if type(value) is not int or not 0 <= value <= MAX_FRAME:
        raise InputCreditError('input frame must be a nonnegative int32')
    return value


def _body(value, *, canonical=False):
    if not isinstance(value, bytes) or len(value) > MAX_INPUT:
        raise InputCreditError('input body must contain at most64 KiB of bytes')
    if not value:
        if canonical: raise InputCreditError('authoritative input requires its canonical identity')
        return 0
    try:
        fields = parse_fields(value, max_bytes=MAX_INPUT, max_fields=257)
    except WireError as error:
        raise InputCreditError('invalid input body envelope') from error
    identities, actions = 0, 0
    for field in fields:
        if field.wire_type != 2 or field.number not in (1, 2):
            raise InputCreditError('input body requires identity and action fields')
        if field.number == 1:
            identities += 1
            if not field.value: raise InputCreditError('input identity cannot be empty')
        else:
            actions += 1
    if identities != 1 or actions > 256:
        raise InputCreditError('input identity/action count limit')
    return actions


@dataclass(frozen=True)
class ScheduledInput:
    frame: int
    body: bytes

    @property
    def payload(self):
        """The unchanged p.INPUT payload, without its outer message framing."""
        return struct.pack('<I', self.frame) + self.body


@dataclass(frozen=True)
class AuthorityReceipt:
    frame: int
    submitted_body: bytes
    canonical_body: bytes
    submitted_action_count: int
    canonical_action_count: int

    @property
    def matched(self): return self.submitted_body == self.canonical_body
    @property
    def normalized(self):
        """Bytes changed by authority; this does not infer why an order changed."""
        return not self.matched
    @property
    def noop(self): return self.canonical_action_count == 0


class InputCreditPlanner:
    def __init__(self, input_window, *, max_prediction_ahead=12, max_authority_backlog=64,
                 max_buffered_bytes=16*1024*1024):
        self.input_window = validate_input_window(input_window)
        for name, value, maximum in (('max_prediction_ahead', max_prediction_ahead, 120),
                                     ('max_authority_backlog', max_authority_backlog, 64),
                                     ('max_buffered_bytes', max_buffered_bytes, 32*1024*1024)):
            if type(value) is not int or not 1 <= value <= maximum:
                raise InputCreditError('invalid input planner ' + name)
        self.max_prediction_ahead, self.max_authority_backlog = max_prediction_ahead, max_authority_backlog
        self.max_buffered_bytes = max_buffered_bytes
        self._next_input = 0
        self._received = self._confirmed = self._predicted = -1
        self._pending, self._authority = {}, deque()
        self._buffered_bytes = 0
        self._closed = False
        self._stats = dict(submissions=0, receipts=0, confirmations=0, matched=0, normalized=0,
                           peak_pending_inputs=0, peak_authority_backlog=0, peak_buffered_bytes=0)

    def _active(self):
        if self._closed: raise InputCreditError('input planner has retired its match')

    def _capacity(self, extra):
        if self._buffered_bytes + extra > self.max_buffered_bytes:
            raise InputCreditError('input planner byte capacity reached')

    def _peaks(self):
        self._stats['peak_pending_inputs'] = max(self._stats['peak_pending_inputs'], len(self._pending))
        self._stats['peak_authority_backlog'] = max(self._stats['peak_authority_backlog'], len(self._authority))
        self._stats['peak_buffered_bytes'] = max(self._stats['peak_buffered_bytes'], self._buffered_bytes)

    @property
    def next_input_frame(self): return self._next_input
    @property
    def received_frame(self): return self._received
    @property
    def confirmed_frame(self): return self._confirmed
    @property
    def predicted_frame(self): return self._predicted
    @property
    def buffered_bytes(self): return self._buffered_bytes
    @property
    def pending_inputs(self): return tuple(self._pending.values())
    @property
    def authority_backlog(self): return tuple(self._authority)
    @property
    def available_credits(self):
        if self._closed: return 0
        return min(self.input_window + self._received + 1 - self._next_input,
                   max(0, MAX_FRAME - self._next_input + 1))
    @property
    def metrics(self):
        return dict(self._stats, next_input_frame=self._next_input, received_frame=self._received,
                    confirmed_frame=self._confirmed, predicted_frame=self._predicted,
                    credits=self.available_credits, buffered_bytes=self._buffered_bytes,
                    pending_inputs=len(self._pending), authority_backlog=len(self._authority), retired=self._closed)

    def submit(self, body, *, frame=None):
        self._active()
        assigned = self._next_input if frame is None else _frame(frame)
        if assigned != self._next_input or assigned > MAX_FRAME:
            raise InputCreditError('submitted input must be the next contiguous frame')
        _body(body)
        if self.available_credits <= 0: raise InputCreditError('no authoritative input credit available')
        self._capacity(len(body))
        scheduled = ScheduledInput(assigned, body)
        self._pending[assigned] = scheduled
        self._next_input += 1; self._buffered_bytes += len(body)
        self._stats['submissions'] += 1; self._peaks()
        return scheduled

    def seed(self, bodies):
        self._active()
        if self._next_input != 0 or self._received != -1:
            raise InputCreditError('startup inputs may be seeded only once')
        # Consume at most W+1 values, so an accidental unbounded iterable is bounded.
        supplied, source = [], iter(bodies)
        for _ in range(self.input_window + 1):
            try: supplied.append(next(source))
            except StopIteration: break
        if len(supplied) != self.input_window:
            raise InputCreditError('startup requires exactly one supplied body per input credit')
        for value in supplied: _body(value)
        self._capacity(sum(map(len, supplied)))
        return tuple(self.submit(value) for value in supplied)

    def observe_authority(self, frame, canonical_body):
        self._active(); _frame(frame)
        if frame != self._received + 1 or frame not in self._pending:
            raise InputCreditError('authority must be new, contiguous and previously submitted')
        count = _body(canonical_body, canonical=True)
        if len(self._authority) >= self.max_authority_backlog:
            raise InputCreditError('unconfirmed authority backlog limit reached')
        self._capacity(len(canonical_body))
        submitted = self._pending[frame]
        receipt = AuthorityReceipt(frame, submitted.body, canonical_body, _body(submitted.body), count)
        self._authority.append(receipt)
        self._received = frame; self._buffered_bytes += len(canonical_body)
        self._stats['receipts'] += 1
        self._stats['matched' if receipt.matched else 'normalized'] += 1
        self._peaks()
        return receipt

    def mark_confirmed(self, frame):
        self._active(); _frame(frame)
        if frame != self._confirmed + 1 or not self._authority or self._authority[0].frame != frame:
            raise InputCreditError('confirmation requires the next received authority frame')
        receipt = self._authority.popleft()
        submitted = self._pending.pop(frame)
        self._buffered_bytes -= len(submitted.body) + len(receipt.canonical_body)
        self._confirmed = frame
        self._predicted = max(self._predicted, frame)
        self._stats['confirmations'] += 1
        return receipt

    def mark_predicted(self, frame):
        self._active(); _frame(frame)
        if frame != self._predicted + 1 or frame <= self._received:
            raise InputCreditError('prediction must be the next unknown frame')
        if frame - self._confirmed > self.max_prediction_ahead:
            raise InputCreditError('prediction lead limit reached')
        self._predicted = frame

    def rollback_prediction(self):
        """Bookkeeping after an actual world restore; never restores a world itself."""
        self._active()
        previous, self._predicted = self._predicted, self._confirmed
        return previous

    def retire(self):
        self._closed = True
        self._pending.clear(); self._authority.clear(); self._buffered_bytes = 0
