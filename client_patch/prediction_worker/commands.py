"""Pure ordered action ledger for the exact arrival-command V1 Custom path.

ASSUMPTIONS: server accepts contiguous batches over one ordered connection,
preserves per-player action FIFO and whole batches, only normalizes empty-ID
Execute groups and the initial frozen Join deck, and aborts on rejection or
disconnect. No server/AI injected own actions or nonterminal rejection is allowed.
Canonical actions acknowledge the next normalized action PREFIX, never a content
search, set or deduplication. Identical commands retain distinct ordinals.

This module performs no native calls/imports and restores no world. Forecasts
are only guesses. The integration must stage changed guesses for quiescent native
replay; changing this ledger cannot retroactively change an executed simulation.
All transmitted bytes remain the caller's original immutable player body.
"""
from __future__ import annotations

from dataclasses import dataclass
from types import MappingProxyType

from server.protobuf_wire import (field_bytes, field_float, field_uint, get_bytes,
                                  get_repeated_bytes, get_repeated_uint, get_uint,
                                  parse_fields, replace_fields)

MAX_FRAME = 0x7fffffff
MAX_BODY = 65536
MAX_ACTIONS = 256


class CommandLedgerError(ValueError):
    pass


def require(condition, message):
    if not condition:
        raise CommandLedgerError(message)


def _integer(value, minimum, maximum, label):
    require(type(value) is int and minimum <= value <= maximum, label)


def _identity_role(raw, slot, *, human):
    named = get_bytes(raw, 1, required=True)
    handle = get_bytes(named, 1, required=True)
    require(get_uint(handle, 1, required=True) == slot + 1 and get_uint(handle, 2) == 1 and
            ((get_uint(raw, 2) == 0) if human else (0 < get_uint(raw, 2) <= 0xffffffff)),
            'player identity differs from assigned slot/role')
    for number in (2, 4):
        name = get_bytes(named, number, required=True)
        require(0 < len(name) <= 96 and not any(ord(ch) < 32 for ch in name.decode('utf-8')),
                'invalid player display identity')
    return raw


def _identity(raw, slot):
    return _identity_role(raw, slot, human=True)


def _player_shape(raw):
    require(type(raw) is bytes and 1 <= len(raw) <= MAX_BODY, 'player body byte limit')
    fields = parse_fields(raw)
    require(all(field.number in (1, 2) and field.wire_type == 2 for field in fields),
            'player body may contain only identity and actions')
    identity = get_bytes(raw, 1, required=True)
    actions = get_repeated_bytes(raw, 2)
    require(len(actions) <= MAX_ACTIONS, 'player action count limit')
    return identity, actions


def _player(raw, slot):
    identity, actions = _player_shape(raw)
    _identity(identity, slot)
    return identity, actions


@dataclass(frozen=True)
class CanonicalRoster:
    """Exact server-AI identities from this world's original CreateWorld bytes.

    Canonical opponent AI input is replayed, never registered as local input.
    Only the explicit two-army public mode1 human0/bot1 route is supported.
    """
    identities: tuple[bytes, bytes]

    @classmethod
    def from_game_data(cls, raw):
        config = get_bytes(raw, 1, required=True)
        require(get_uint(config, 36) == 1, 'canonical AI roster requires public mode1')
        armies = get_repeated_bytes(config, 2)
        require(len(armies) == 2, 'canonical AI roster requires two armies')
        identities = []
        for slot, army in enumerate(armies):
            require(get_uint(army, 1) == slot and get_uint(army, 4) == slot,
                    'canonical AI roster army/alliance differs from assigned slot')
            players = get_repeated_bytes(army, 2)
            require(len(players) == 1 and len(players[0]) <= MAX_BODY,
                    'canonical AI roster requires one bounded identity per army')
            identities.append(_identity_role(players[0], slot, human=(slot == 0)))
        return cls(tuple(identities))

    def player_slot(self, raw):
        identity, _ = _player_shape(raw)
        require(identity in self.identities, 'canonical identity differs from frozen bootstrap roster')
        return self.identities.index(identity)


def player_slot(raw):
    """Strict Custom human identity, never infer a slot from player ordering."""
    require(type(raw) is bytes and 1 <= len(raw) <= MAX_BODY, 'player body byte limit')
    identity = get_bytes(raw, 1, required=True)
    named = get_bytes(identity, 1, required=True)
    handle = get_bytes(named, 1, required=True)
    player_id = get_uint(handle, 1, required=True)
    require(player_id in (1, 2), 'Custom human player ID must be1/2')
    slot = player_id - 1
    _player(raw, slot)
    return slot


def own_player_body(raw_frame, slot, *, roster=None):
    """Extract own canonical body; reject ambiguous/foreign human identities."""
    _integer(slot, 0, 1, 'Custom human slot must be0/1')
    require(roster is None or (type(roster) is CanonicalRoster and slot == 0),
            'canonical AI roster requires own human slot0')
    bodies = get_repeated_bytes(raw_frame, 6)
    require(len(bodies) <= 2, 'Custom authority may contain at most two human players')
    seen, own = set(), b''
    for raw in bodies:
        current = player_slot(raw) if roster is None else roster.player_slot(raw)
        require(current not in seen, 'duplicate canonical player identity')
        seen.add(current)
        if current == slot:
            own = raw
    return own


def admit_entities(raw_player_body, slot, lookup):
    """Prototype admission for every Execute, using only confirmed identities.

    The original server still validates abilities, payloads and startup actions.
    Known dead IDs remain valid; speculative/new IDs cannot be rebound here.
    """
    _, actions = _player(raw_player_body, slot)
    for action in actions:
        normalized, _, _ = _action(action, slot)
        if normalized is None:
            continue
        value = parse_fields(normalized)[0]
        if value.number == 1:
            for group in get_repeated_bytes(value.value, 1):
                kind = get_uint(group, 1)
                for entity in get_repeated_uint(group, 3, max_values=4096):
                    require(lookup(entity) == (slot, kind), 'Execute entity identity is not confirmed for own army/type')


def _action(raw, slot):
    """Return normalized bytes or None, prediction eligibility, Join flag."""
    fields = parse_fields(raw)
    require(len(fields) == 1 and fields[0].wire_type == 2, 'action requires one message case')
    kind, payload = fields[0].number, fields[0].value
    require(kind in (1, 3, 5), 'unsupported client action case')
    if kind == 3:
        require(get_uint(payload, 1) == slot, 'Join army differs from assigned slot')
        get_bytes(payload, 2, required=True)
        return raw, False, True
    if kind == 5:
        ui = parse_fields(payload)
        # Match server _action's structural rule only. Original ToProto and the
        # real server descriptor validator own variant/type validation. These
        # opaque cosmetic/UI bytes are never executed speculatively here.
        require(len(ui) == 1, 'UI action requires one command case')
        return raw, False, False
    groups = get_repeated_bytes(payload, 1)
    require(1 <= len(groups) <= MAX_ACTIONS, 'Execute entity group count limit')
    target = parse_fields(get_bytes(payload, 3, required=True))
    require(len(target) == 1, 'Execute target requires one command case')
    retained = []
    eligible = True
    for group in groups:
        ids = get_repeated_uint(group, 3, max_values=4096)
        require(len(ids) == len(set(ids)) and all(entity <= 0xffffffff for entity in ids), 'invalid Execute entity IDs')
        if ids:
            retained.append(group)
            eligible &= get_uint(group, 2) in (12, 14)
    if not retained:
        return None, False, False
    if len(retained) != len(groups):
        raw = field_bytes(1, replace_fields(payload, {1: [field_bytes(1, group) for group in retained]}))
    return raw, bool(eligible), False


def _join_matches(submitted, canonical):
    first = parse_fields(submitted)[0].value
    second = parse_fields(canonical)[0].value
    # Server _join changes only field2 after validating the entire frozen intent.
    # Do not extend this exception to other Join fields or later commands.
    return replace_fields(first, {2: []}) == replace_fields(second, {2: []})


@dataclass(frozen=True)
class PendingAction:
    sequence: int
    action_index: int
    first_speculative_frame: int
    body: bytes
    predictive: bool
    join: bool

    @property
    def ordinal(self):
        return self.sequence, self.action_index


@dataclass(frozen=True)
class Registration:
    sequence: int
    send_body: bytes
    normalized_actions: tuple[PendingAction, ...]
    locally_elided_noops: int


@dataclass(frozen=True)
class AuthorityObservation:
    frame: int
    retired: tuple[PendingAction, ...]
    reanchored: tuple[tuple[int, int], ...]


class CommandLedger:
    def __init__(self, slot, *, max_pending_actions=4096, max_pending_bytes=1024 * 1024):
        _integer(slot, 0, 1, 'Custom human slot must be0/1')
        _integer(max_pending_actions, 1, 16384, 'pending action budget outside bound')
        _integer(max_pending_bytes, 1, 32 * 1024 * 1024, 'pending byte budget outside bound')
        self.slot = slot
        self.max_pending_actions, self.max_pending_bytes = max_pending_actions, max_pending_bytes
        self._next_sequence, self._received, self._identity = 1, -1, None
        self._last_speculative_frame = -1
        self._pending, self._pending_bytes = (), 0
        self._finished = False
        self._stats = dict(registered_batches=0, registered_actions=0, locally_elided_noops=0,
                           canonical_actions=0, authority_frames=0, reanchors=0,
                           peak_pending_actions=0, peak_pending_bytes=0)

    @property
    def next_sequence(self): return self._next_sequence

    @property
    def received_frame(self): return self._received

    @property
    def canonical_identity(self): return self._identity

    @property
    def pending(self): return self._pending

    @property
    def finished(self): return self._finished

    @property
    def metrics(self):
        return dict(self._stats, pending_actions=len(self._pending), pending_bytes=self._pending_bytes,
                    next_sequence=self._next_sequence, received_frame=self._received, finished=self._finished)

    def register(self, sequence, raw_player_body, first_speculative_frame):
        require(not self._finished, 'command ledger has finished')
        _integer(sequence, 1, 2**64 - 1, 'batch sequence outside uint64')
        _integer(first_speculative_frame, 0, MAX_FRAME, 'speculative frame outside nonnegative int32')
        require(sequence == self._next_sequence, 'batch sequence must be new and contiguous')
        require(first_speculative_frame >= self._last_speculative_frame, 'local batch frame order moved backwards')
        _, actions = _player(raw_player_body, self.slot)
        staged, joins, noops = [], [], 0
        for index, action in enumerate(actions):
            normalized, predictive, join = _action(action, self.slot)
            if join: joins.append(index)
            if normalized is None:
                noops += 1
            else:
                staged.append(PendingAction(sequence, index, first_speculative_frame, normalized, predictive, join))
        require(joins == ([0] if sequence == 1 else []), 'only first action of batch1 may Join')
        pending = self._pending + tuple(staged)
        size = self._pending_bytes + sum(len(item.body) for item in staged)
        require(len(pending) <= self.max_pending_actions and size <= self.max_pending_bytes, 'pending ledger budget reached')
        stats = dict(self._stats)
        stats.update(registered_batches=stats['registered_batches'] + 1,
                     registered_actions=stats['registered_actions'] + len(actions),
                     locally_elided_noops=stats['locally_elided_noops'] + noops,
                     peak_pending_actions=max(stats['peak_pending_actions'], len(pending)),
                     peak_pending_bytes=max(stats['peak_pending_bytes'], size))
        result = Registration(sequence, raw_player_body, tuple(staged), noops)
        # No mutation until every validation/allocation above has succeeded.
        self._pending, self._pending_bytes = pending, size
        self._next_sequence, self._stats = sequence + 1, stats
        self._last_speculative_frame = first_speculative_frame
        return result

    def observe_authority(self, frame, canonical_own_player_body):
        require(not self._finished, 'command ledger has finished')
        _integer(frame, 0, MAX_FRAME, 'authority frame outside nonnegative int32')
        require(frame == self._received + 1, 'authority must be new and contiguous from0')
        if canonical_own_player_body == b'' and self._identity is not None:
            identity, actions = self._identity, ()
        else:
            identity, actions = _player(canonical_own_player_body, self.slot)
        require(self._identity is None or identity == self._identity, 'canonical own identity changed within match')
        require(len(actions) <= len(self._pending), 'canonical own action has no pending ordinal')
        for index, action in enumerate(actions):
            normalized, _, join = _action(action, self.slot)
            require(normalized == action, 'canonical action is not already server normalized')
            pending = self._pending[index]
            if join:
                require(frame == 0 and index == 0 and pending.sequence == 1 and pending.action_index == 0 and
                        pending.join and _join_matches(pending.body, action), 'unexpected or changed canonical Join')
            else:
                require(not pending.join and pending.body == action, 'canonical own action differs from pending prefix')
        require(frame != 0 or (actions and self._pending[0].join and parse_fields(actions[0])[0].number == 3),
                'canonical0 must confirm the initial owned Join')
        count = len(actions)
        require(not count or count == len(self._pending) or self._pending[count - 1].sequence != self._pending[count].sequence,
                'canonical frame split a server whole batch')
        retired, remaining = self._pending[:count], self._pending[count:]
        reanchored = tuple(item.ordinal for item in remaining if item.predictive and
                           max(item.first_speculative_frame, self._received + 1) != max(item.first_speculative_frame, frame + 1))
        size = self._pending_bytes - sum(len(item.body) for item in retired)
        stats = dict(self._stats)
        stats.update(canonical_actions=stats['canonical_actions'] + count,
                     authority_frames=stats['authority_frames'] + 1,
                     reanchors=stats['reanchors'] + len(reanchored))
        result = AuthorityObservation(frame, retired, reanchored)
        self._pending, self._pending_bytes = remaining, size
        self._received, self._identity, self._stats = frame, identity, stats
        return result

    def finish(self, frame):
        require(not self._finished, 'command ledger has already finished')
        _integer(frame, 0, MAX_FRAME, 'final authority frame must follow canonical startup')
        require(frame == self._received, 'final frame differs from latest received authority')
        count = len(self._pending)
        stats = dict(self._stats, canceled_actions=count)
        self._pending, self._pending_bytes, self._stats = (), 0, stats
        self._finished = True
        return count

    def forecast(self, frame):
        _integer(frame, 0, MAX_FRAME, 'forecast frame outside nonnegative int32')
        require(self._identity is not None and frame > self._received, 'forecast requires startup identity and an unknown frame')
        actions = tuple(item.body for item in self._pending if item.predictive and
                        max(item.first_speculative_frame, self._received + 1) == frame)
        require(len(actions) <= MAX_ACTIONS, 'forecast exceeds original per-player action cap')
        raw = (field_uint(1, frame) if frame else b'') + field_uint(2, 20) + field_uint(3, 50) + field_float(4, 1.)
        if actions:
            player = field_bytes(1, self._identity) + b''.join(field_bytes(2, action) for action in actions)
            require(len(player) <= MAX_BODY, 'forecast player body exceeds original byte cap')
            raw += field_bytes(6, player)
        return raw  # Empty remote/own lists are omitted exactly as original serialization.

    def revision_plan(self, first, last):
        _integer(first, 0, MAX_FRAME, 'revision start outside frame range')
        _integer(last, first, min(MAX_FRAME, first + 11), 'revision plan must contain1..12 frames')
        return MappingProxyType({frame: self.forecast(frame) for frame in range(first, last + 1)})
