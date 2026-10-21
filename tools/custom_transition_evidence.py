"""Finite native lifecycle assertions for D2 T07/T08,with no UI mutation."""
import re

KINDS = ('C', 4, 'C', 1, 'C')


def require(value, message):
    if not value:
        raise AssertionError(message)


def segment(log, stage, role):
    marker = f'CUSTOM TRANSITION stage released: stage={stage} role={role}'
    require(log.count(marker) == 1, 'missing/duplicate transition stage release')
    left = log.index(marker)
    following = f'CUSTOM TRANSITION stage released: stage={stage+1} role={role}'
    right = log.index(following) if following in log else len(log)
    require(right > left, 'transition stages reordered')
    return log[left:right]


def ordered(log, markers):
    positions = []
    for marker in markers:
        require(log.count(marker) == 1, 'missing/duplicate transition evidence: '+marker)
        positions.append(log.index(marker))
    require(positions == sorted(positions), 'native transition lifecycle reordered')


def validate(log, role, matches):
    require(role in ('host', 'guest') and len(matches) == 4 and len(set(matches)) == 4, 'four distinct remote matches required')
    log = log.replace('\r\n', '\n').replace('\r', '\n')
    for marker in ('Public client failure:', 'Client lifecycle invariant failed:', 'Offline loop stopped in ',
                   'Public fallback accepted:', 'Cosmetic persistence unavailable:', 'Practice stopped in '):
        require(marker not in log, 'native transition failed: '+marker)
    require(log.count('Community native custom match joined:') == log.count('Community native match return:') ==
            log.count('Community native lobby restored:') == log.count('COMMUNITY MATCH SMOKE native Continue (NOT manual UI input)') == 3,
            'three original Custom joins/results/Continue required')
    for stage, match in zip((1, 3, 5), (matches[0], matches[1], matches[3])):
        tail = segment(log, stage, role)
        require(tail.count('Community native custom match joined:') == 1 and f'match={match} ' in tail,
                'Custom stage joined another or duplicate match')
        ordered(tail, [
            'Community native custom match joined:', 'Dedicated native EndOfGameResponse delivered;',
            'COMMUNITY MATCH SMOKE native Continue (NOT manual UI input)', 'Community native match return:',
            'Community native lobby restored:', f'CUSTOM TRANSITION Custom returned: stage={stage} role={role} ',
            f'CUSTOM TRANSITION original Leave dispatched: stage={stage} role={role}',
            f'CUSTOM TRANSITION departed: stage={stage} role={role} party=0 prediction=0 pending=0 nativeIdle=1'])
        action = 'host native picker Invite' if role == 'host' else 'guest native Accept'
        require(tail.count('COMMUNITY MATCH SMOKE '+action) == 1, 'original invitation action missing/duplicated')
        require('Public search intent:' not in tail and 'Practice requested:' not in tail, 'Custom stage leaked into public/local play')
    local = segment(log, 2, role)
    ordered(local, ['Practice requested:', 'PRACTICE SMOKE original EditDeck mode4 callback:',
        'Practice native EndOfGameResponse delivered;', 'PRACTICE SMOKE native Continue (automated)',
        'Practice returned: completed=1 mode=4 seat=-1 presenceRetained=0 standalone=1',
        f'CUSTOM TRANSITION local returned: stage=2 role={role} practiceCompleted=1 nativeIdle=1'])
    require('Community native custom match joined:' not in local and 'Public search intent:' not in local,
            'local stage replaced by a remote producer')
    public = segment(log, 4, role)
    ordered(public, ['Public search intent: ticket=1 mode=1 ', f'Public match assignment: ticket=1 match={matches[2]} ',
        'Public native match joined:', 'Practice native EndOfGameResponse delivered;',
        'DEDICATED REMATCH SMOKE automated original MatchResultVM.OnContinue;',
        'Public result Continue routed: mode=1 source=remote next=End', 'Public native return: ticket=1 ',
        'Public intent retired: ticket=1 reason=returned nativeIdle=1 disconnect=0',
        f'CUSTOM TRANSITION public returned: stage=4 role={role} publicCompleted=1 nativeIdle=1'])
    require(log.count('Public search intent:') == log.count('Public native match joined:') == 1,
            'extra/missing public intent')
    local_matches = re.findall(r'Practice requested: match=([0-9a-f]{32}) mode=4 ', log)
    require(len(local_matches) == 1, 'one independent local practice match required')
    expected = [('1', 'remote', matches[0]), ('2', 'local-practice', ''), ('3', 'remote', matches[1]),
                ('4', 'remote', matches[2]), ('5', 'remote', matches[3])]
    acquired = re.findall(r'Client world acquired: generation=(\d+) owner=([^ ]+) match=([0-9a-f]*)', log)
    released = re.findall(r'Client world released: generation=(\d+) owner=([^ ]+) nativeIdle=1', log)
    require(acquired == expected and released == [(generation, owner) for generation, owner, _ in expected],
            'transition world ownership/generations differ')
    require(log.count(f'CUSTOM TRANSITION complete: stages=C,local4,C,public1,C role={role} worlds=5 ') == 1,
            'final original Custom departure missing')
    return dict(role=role, stages=list(KINDS), remote_matches=matches, local_match=local_matches[0],
                original_continues=5, original_custom_invites=3, original_leaves=3,
                physical_native_quit_bundled_protected_or_lan_qualified=False)
