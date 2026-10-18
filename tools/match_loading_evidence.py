"""Check native loading-status ownership and retain owned Unity screenshots.

Readbacks establish component state; the retained PNGs still need visual review.
These checks do not establish physical mouse input or manual acceptance.
"""
from __future__ import annotations

import hashlib
from pathlib import Path
import re
import shutil

EVENT = re.compile(
    r'Match loading event=(\w+) source=(\w+) ticket=(\d+) identity=(\S+) '
    r'stage=(\w+) pending=([01]) visible=([01]) nativeVisible=([01]) rendererFailed=([01]) reason=([^\n]*)')
CAPTURE = re.compile(
    r'Match loading capture requested: file=(match-loading-\d+-\d+-\d+-\w+\.png) '
    r'ticket=(\d+) event=(\w+) nativeVisible=([01]) frame=(\d+)')


def check(log, game: Path, output: Path, pid: int, *, source: str, ready: int, minimum_errors=0,
          require_captures=False):
    def require(value, reason):
        if not value:
            raise AssertionError('match loading: ' + reason)

    require(not any(text in log for text in ('Match loading UI failed',
                'Match loading UI ignored an off-thread call')), 'native renderer/probe failed')
    require(log.count('Match loading UI created: privateCanvas=1 inputBlocked=0 ') == 1,
            'expected one private nonblocking canvas per process')
    rows, pending, terminal, shown = [], None, set(), set()
    for event in EVENT.finditer(log):
        kind, owner, ticket, identity, stage, busy, visible, native, failed, reason = event.groups()
        ticket = int(ticket)
        require(owner == source and failed == '0', 'wrong owner or failed renderer')
        require(visible == native, 'model/native visibility mismatch')
        if kind == 'show':
            require(ticket not in shown and pending is None, 'duplicate or overlapping start')
            require(busy == visible == '1', 'start did not show pending status')
            pending = ticket
            shown.add(ticket)
        elif kind == 'stage':
            require(ticket == pending and busy == visible == '1', 'stage has no pending owner')
        elif kind in ('ready', 'cancel', 'error'):
            require(ticket == pending and ticket not in terminal, 'stale or duplicate completion')
            require(busy == '0' and visible == ('1' if kind == 'error' else '0'), 'wrong completion state')
            terminal.add(ticket)
            pending = None
        elif kind == 'expired':
            require(ticket in terminal and busy == visible == '0', 'invalid notice expiry')
        else:
            require(False, 'unknown event ' + kind)
        rows.append(dict(event=kind, source=owner, ticket=ticket, identity=identity, stage=stage,
                         pending=int(busy), visible=int(visible), position=event.start(), reason=reason))
    require(rows and pending is None, 'missing events or status left pending after return')
    require(sum(row['event'] == 'ready' for row in rows) == ready, 'wrong successful readiness count')
    require(sum(row['event'] == 'error' for row in rows) >= minimum_errors, 'expected failure notice missing')
    gates = list(re.finditer(r'Match loading readiness: source=' + source + r' ticket=(\d+) nativeInGame=1 [^\n]+', log))
    for row in rows:
        if row['event'] == 'ready':
            require(any(int(gate[1]) == row['ticket'] and gate.start() < row['position'] for gate in gates),
                    'status hidden without native InGame/readiness evidence')
    captures, missing = [], []
    for record in CAPTURE.finditer(log):
        filename, ticket, event, visible, frame = record.groups()
        require(filename.startswith(f'match-loading-{pid}-'), 'screenshot belongs to another process')
        path = game / 'investigation/runtime' / filename
        if not path.is_file() or path.stat().st_size <= 1024:
            missing.append(filename)
            continue
        data = path.read_bytes()
        require(data.startswith(b'\x89PNG\r\n\x1a\n'), 'native screenshot is not PNG')
        shutil.copyfile(path, output / filename)
        captures.append(dict(file=filename, ticket=int(ticket), event=event, visible=int(visible),
                             frame=int(frame), sha256=hashlib.sha256(data).hexdigest()))
    capture_errors = [line for line in log.splitlines() if 'Match loading capture failed:' in line]
    if require_captures:
        require(not missing and not capture_errors, 'native screenshot request failed or file missing')
        require(any(row['visible'] for row in captures), 'no loading/notice screenshot')
        require(any(not row['visible'] and row['event'] == 'ready' for row in captures), 'no ready/hidden screenshot')
    return dict(events=rows, screenshots=captures, missing_screenshots=missing, capture_errors=capture_errors,
                visual_review='not established; hidden Unity windows can produce black/missing captures',
                qualification='native component state and readiness only; inspect pixels separately',
                input_blocking_readback=False)
