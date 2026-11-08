"""Measure displayed simulation frame pacing from opt-in -lan-audit traces.

The game runs simulation and presentation on different threads.  Only `view`
rows sample what Unity actually displayed; `arrival` and `apply` rows explain
whether the network and native simulation were still advancing.
"""

import argparse
import csv
import json
from pathlib import Path


def read_trace(path):
    with Path(path).open(newline="", encoding="utf-8") as stream:
        rows = list(csv.DictReader(stream, delimiter="\t"))
    required = {"ms", "event", "update", "frame", "sim", "presented", "queued"}
    if not rows or not required.issubset(rows[0]):
        raise ValueError(f"{path}: empty or invalid timing trace")
    return [{key: int(value) if key != "event" else value for key, value in row.items()}
            for row in rows]


def matches(rows):
    """Split a multi-match trace at each authoritative frame-zero arrival."""
    starts = [i for i, row in enumerate(rows)
              if row["event"] == "arrival" and row["frame"] == 0]
    if not starts:
        return [rows]
    return [rows[start:end] for start, end in zip(starts, starts[1:] + [len(rows)])]


def measure(rows, warmup_frame=10):
    views = [row for row in rows if row["event"] == "view"
             and row["presented"] > warmup_frame]
    changes = [row for i, row in enumerate(views)
               if i == 0 or row["presented"] != views[i-1]["presented"]]
    gaps = [b["ms"]-a["ms"] for a, b in zip(changes, changes[1:])]
    steps = [b["presented"]-a["presented"] for a, b in zip(changes, changes[1:])]
    if any(gap < 0 for gap in gaps) or any(step <= 0 for step in steps):
        raise ValueError("nonmonotonic presentation trace")
    applied = [row["frame"] for row in rows if row["event"] == "apply"]
    arrivals = [row["frame"] for row in rows if row["event"] == "arrival"]
    for name, frames in (("apply", applied), ("arrival", arrivals)):
        if any(b != a+1 for a, b in zip(frames, frames[1:])):
            raise ValueError(f"noncontiguous {name} frames")
    ordered = sorted(gaps)
    return {
        "presented_changes": len(changes),
        "first_presented": changes[0]["presented"] if changes else None,
        "last_presented": changes[-1]["presented"] if changes else None,
        "median_gap_ms": ordered[len(ordered)//2] if ordered else None,
        "p95_gap_ms": ordered[(95*(len(ordered)-1))//100] if ordered else None,
        "max_gap_ms": max(gaps, default=None),
        "gaps_over_100_ms": sum(gap > 100 for gap in gaps),
        "skipped_presented_updates": sum(step > 1 for step in steps),
        "skipped_presented_frames": sum(step-1 for step in steps),
        "arrival_frames": len(arrivals),
        "applied_frames": len(applied),
        "first_arrived": arrivals[0] if arrivals else None,
        "first_applied": applied[0] if applied else None,
        "last_arrived": arrivals[-1] if arrivals else None,
        "last_applied": applied[-1] if applied else None,
        "effective_presented_hz": round(1000 * (changes[-1]["presented"]-changes[0]["presented"])
                                        / sum(gaps), 3) if gaps and sum(gaps) else None,
        "max_receive_queue": max((row["queued"] for row in rows if row["event"] == "arrival"), default=0),
    }


def qualify(rows, expected_frames, max_skips=1, max_p95_ms=80, min_hz=19, max_hz=21):
    """Require every completed match to remain complete, paced and near 20 Hz."""
    parts = matches(rows)
    errors = []
    measured = []
    if len(parts) != len(expected_frames):
        errors.append("timing match count differs from completed authoritative matches")
    for index, part in enumerate(parts):
        try:
            result = measure(part)
        except ValueError as error:
            errors.append(f"match {index+1}: {error}")
            continue
        measured.append(result)
        if index >= len(expected_frames):
            continue
        expected = expected_frames[index]
        if (result["arrival_frames"] != expected or result["applied_frames"] != expected
                or result["first_arrived"] != 0 or result["first_applied"] != 0
                or result["last_arrived"] != expected-1 or result["last_applied"] != expected-1):
            errors.append(f"match {index+1}: authoritative frames missing or incomplete")
        if (result["last_presented"] is None or result["last_presented"] < expected-1
                or result["presented_changes"] < expected-11-max_skips):
            errors.append(f"match {index+1}: presentation did not cover the completed match")
        if result["skipped_presented_frames"] > max_skips:
            errors.append(f"match {index+1}: displayed frame skips exceed {max_skips}")
        if result["p95_gap_ms"] is None or result["p95_gap_ms"] > max_p95_ms:
            errors.append(f"match {index+1}: p95 presentation gap exceeds {max_p95_ms} ms")
        if result["effective_presented_hz"] is None or result["effective_presented_hz"] < min_hz:
            errors.append(f"match {index+1}: presentation rate is below {min_hz} Hz")
        elif result["effective_presented_hz"] > max_hz:
            errors.append(f"match {index+1}: presentation rate exceeds {max_hz} Hz")
    return dict(passed=not errors, matches=measured, errors=errors)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("traces", nargs="+", type=Path)
    parser.add_argument("--max-skips", type=int, help="fail if any match exceeds this number of skipped presented frames")
    parser.add_argument("--max-p95-ms", type=int, help="fail if the 95th percentile presentation gap exceeds this")
    parser.add_argument("--expected-frames", type=int, help="require this many contiguous arrived and applied frames per match")
    parser.add_argument("--min-changes", type=int, default=100)
    args = parser.parse_args()
    reports = [{"trace": str(path), "matches": [measure(part) for part in matches(read_trace(path))]}
               for path in args.traces]
    print(json.dumps(reports, indent=2))
    for report in reports:
        for match in report["matches"]:
            if match["presented_changes"] < args.min_changes:
                return 2
            if args.expected_frames is not None and (match["arrival_frames"] != args.expected_frames
                                                       or match["applied_frames"] != args.expected_frames):
                return 2
            if args.max_skips is not None and match["skipped_presented_frames"] > args.max_skips:
                return 1
            if args.max_p95_ms is not None and match["p95_gap_ms"] > args.max_p95_ms:
                return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
