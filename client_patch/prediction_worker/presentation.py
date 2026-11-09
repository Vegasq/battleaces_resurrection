"""Confirmed terminal-event admission for COPIED native presentation buffers."""
from __future__ import annotations

from server.native_simulation import _Buffer

from .native import HostError


def confirmed_terminal_view(raw, *, confirmed_frame, physical_frame):
    """Leave native physics untouched;defer Unity's irreversible complete event.

    GameState.game_over_frame identifies the original native terminal tick.
    Reconciliation has already executed all authority through confirmed_frame.
    A completion no later than that frontier is therefore authoritative. Only
    the complete scalar in this private output copy may change;positions and
    all actual simulation data remain original. Return (bytes,masked,key).
    """
    if type(raw) is not bytes or not 8 <= len(raw) <= 16 * 1024 * 1024:
        raise HostError('terminal presentation buffer exceeds bounds')
    b = _Buffer(raw)
    root = b.read('I', 0)
    b.bounds(root, 4)
    state = b.table(root, 23)
    field = b.field(state, 0)
    complete = b.read('B', field) if field else 0
    if complete not in (0, 1):
        raise HostError('native completion scalar differs from boolean ABI')
    if not complete:
        return raw, False, None
    frame = b.scalar(root, 0, 'I')
    terminal = b.scalar(state, 1, 'i')
    if frame != physical_frame or not -1 <= confirmed_frame <= physical_frame or not 0 <= terminal <= frame:
        raise HostError('native terminal frame is outside prediction frontiers')
    key = (terminal, b.scalar(state, 2, 'I'), b.scalar(state, 3, 'I'), b.scalar(state, 4, 'Q'))
    if terminal <= confirmed_frame:
        return raw, False, key
    result = bytearray(raw)
    result[field] = 0
    return bytes(result), True, key
