"""Read original native lifecycle evidence for the finite D2 T05 sequence."""
import re

MODES = (1, 2, 5, 1)


def require(value, message):
    if not value:
        raise AssertionError(message)


def stage(log, ticket, mode, gate, match, seat, human_mask):
    """Check one completed stage before the next gate is released."""
    log = log.replace('\r\n', '\n').replace('\r', '\n')
    total = 2 if mode == 1 else 4
    markers = (
        f'PUBLIC MODE SEQUENCE gate released: key={gate} stage={ticket}',
        f'Public search intent: ticket={ticket} mode={mode} originalSearch=1 deadlineMs=30000',
        f'Public match assignment: ticket={ticket} match={match} mode={mode} count={total} seat={seat} humans={human_mask} ',
        f'Client world acquired: generation={ticket} owner=remote match={match}',
        f'Public native match joined: ticket={ticket} match={match} mode={mode} participants={total} seat={seat} remoteWorld=1',
        'Practice native EndOfGameResponse delivered;',
        'DEDICATED REMATCH SMOKE automated original MatchResultVM.OnContinue;',
        f'Public result Continue routed: mode={mode} source=remote next=End',
        f'Client world released: generation={ticket} owner=remote nativeIdle=1',
        f'Public native return: ticket={ticket} match={match} aborted=0 nativeIdle=1',
        f'PUBLIC QUEUE completed return: match={match} completed={ticket} seatReleased=1',
        f'Public intent retired: ticket={ticket} reason=returned nativeIdle=1 disconnect=0',
    )
    positions = []
    for marker in markers:
        require(log.count(marker) == 1, 'missing/duplicate stage lifecycle: ' + marker)
        positions.append(log.index(marker))
    require(positions == sorted(positions), 'stage lifecycle order differs')
    require(log.count('Public search intent:') == log.count('Public match assignment:') ==
            log.count('Public native match joined:') == log.count('Client world acquired:') ==
            log.count('Client world released:') == 1, 'stage created duplicate intent/world')
    for marker in ('Public client failure:', 'Client lifecycle invariant failed:', 'Public fallback accepted:',
                   'Offline loop stopped in ', 'owner=local-practice', 'Public result Continue routing failed:',
                   'Practice stopped in ', 'LAN normal-build smoke disabled', 'LAN normal-build smoke stopped'):
        require(marker not in log, 'native sequence failed: ' + marker)
    require(f'Native search joining signal: ticket={ticket} ' in log and
            f'Native search released: ticket={ticket} ' in log, 'stage search/loading ownership missing')
    return dict(ticket=ticket, mode=mode, match=match, seat=seat, original_continue=True,
                world_generation=ticket, idle_retirement=True)


def sequence(log, stages):
    require(len(stages) == 4 and tuple(row['mode'] for row in stages) == MODES and
            [row['ticket'] for row in stages] == [1, 2, 3, 4] and
            len({row['match'] for row in stages}) == 4, 'finite four-mode sequence differs')
    acquired = re.findall(r'Client world acquired: generation=(\d+) owner=([^ ]+) match=([0-9a-f]{32})', log)
    released = re.findall(r'Client world released: generation=(\d+) owner=([^ ]+) nativeIdle=1', log)
    require(acquired == [(str(row['ticket']), 'remote', row['match']) for row in stages] and
            released == [(str(row['ticket']), 'remote') for row in stages], 'sequence world lease set differs')
    require(log.count('Public search intent:') == log.count('Public native match joined:') ==
            log.count('Public result Continue routed:') == log.count('PUBLIC QUEUE completed return:') == 4,
            'sequence intent/join/Continue totals differ')
    return dict(modes=list(MODES), remote_worlds=4, original_continues=4,
                physical_native_quit_bundled_or_lan_qualified=False)
