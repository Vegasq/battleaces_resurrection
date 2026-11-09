"""Choose a frozen input window from authenticated HELLO feedback, not a claimed RTT."""
from __future__ import annotations

import math

from . import protocol as p

FRAME_MS = 50.0
HEADROOM_MS = 100.0


def feedback_sample(value):
    """Return finite nonnegative milliseconds; missing/invalid measurements stay unknown."""
    if type(value) not in (int, float):
        return None
    try:
        measured = float(value)
    except OverflowError:
        return None
    return measured if math.isfinite(measured) and measured >= 0 else None


def select_input_window(configured_min, feedback_samples):
    """Cover the slowest measured human plus two ticks, within the existing wire bounds."""
    minimum = p.validate_input_window(configured_min)
    measured = [sample for value in feedback_samples if (sample := feedback_sample(value)) is not None]
    if not measured:
        return minimum
    required = math.ceil((min(max(measured), p.MAX_INPUT_WINDOW * FRAME_MS) + HEADROOM_MS) / FRAME_MS)
    return min(p.MAX_INPUT_WINDOW, max(minimum, required))
