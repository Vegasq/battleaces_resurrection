"""Check exact recipe3 through40 and44-47 native-field samples and ordered lifecycle coverage.

This verifies the bounded read-only helper log, not collection/network absence.
No game files or processes are accessed. Original log lines are never emitted.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path
import re

from client_patch.patcher.telemetry import COMPONENTS,RECIPE_VERSION

STAGES = frozenset(('startup-after-engine-init', 'menu', 'ingame', 'postgame', 'tutorial','pre-quit-confirm'))
DEFAULT_STAGES = ('startup-after-engine-init', 'menu', 'ingame', 'postgame',
                  'menu', 'ingame', 'postgame')
FIELDS = {
    'main': ('state_8', 'init_e10_nonzero', 'archiveFlush_480_nonzero',
             'worker_4e0_present', 'registered_15c0', 'registered_1650',
             'enabled_1651', 'deviceStats_15c3', 'preinitQueueCount'),
    'session': ('registered_8', 'state_c_nonzero', 'value_10_nonzero', 'value_20_nonzero'),
    'performance': ('registered_0', 'enabled_9'),
}
LINE = re.compile(r'^\[(\d+)\] Telemetry audit (.*)$')
BUILD = re.compile(r'build verified: UnityPlayer sha256=([0-9a-f]{64}) '
                   r'normalized=([0-9a-f]{64}) crashSignatures=(\d+)/(?:3|4) '
                   r'coreCandidateSignatures=(\d+)/(12|14|15|16|18|21|25|27|28|31|40|48|53|56|57|58|59) performanceCandidateSignatures=(\d+)/3(?: cacheFailureSignatures=(\d+)/5)?(?: serviceIdentitySignatures=(\d+)/2)?(?: serviceProfileSignatures=(\d+)/2)?(?: recipeVersion=(\d+))?(?: automaticCollectorSignatures=(\d+)/1)?(?: sdkInitializationSignatures=(\d+)/6)?(?: reportErrorSignatures=(\d+)/7)?(?: reporterCallbackSignatures=(\d+)/(3|7))?(?: reporterEnabledSignatures=(\d+)/2)?(?: reporterRegistrationSignatures=(\d+)/1)?(?: networkBreadcrumbSignatures=(\d+)/1)?(?: breadcrumbCollectorSignatures=(\d+)/3)?(?: breadcrumbFacadeSignatures=(\d+)/2)?(?: sdkDataIngressSignatures=(\d+)/10)?(?: sdkContextSignatures=(\d+)/2)?(?: sdkMetadataMergeSignatures=(\d+)/2)?(?: sdkConfigurationIngressSignatures=(\d+)/6)?(?: sdkSceneMetadataSignatures=(\d+)/1)?(?: sdkUserCacheSignatures=(\d+)/1)?(?: sdkSessionCacheSignatures=(\d+)/1)?(?: sdkCacheReaderSignatures=(\d+)/(4|5))?(?: sdkCacheDirectorySignatures=(\d+)/1)?; '
                   r'READ ONLY, no qualification claim')
BEGIN = re.compile(r'(\d+)/17 stage=([a-z-]+) retained main=(\d+) session=(\d+) '
                   r'performance=(\d+) callbackHooks main=(\d+) performance=(\d+)')
COMPONENT = re.compile(r'(\d+) (main|session|performance): (.*)')
END = re.compile(r'(\d+) snapshotEnd singletonPointersStable=(\d+); '
                 r'scalar observations are not atomic or network evidence')


def verify_lines(lines, *, expected_sha256, required_stages=DEFAULT_STAGES,recipe_version=RECIPE_VERSION):
    """Fail on missing, partial, unavailable, changed or out-of-order evidence."""
    if not re.fullmatch('[0-9a-f]{64}', expected_sha256):
        raise ValueError('Expected UnityPlayer SHA256 must be 64 lowercase hexadecimal digits.')
    if type(recipe_version) is not int or recipe_version not in (*range(3,41),44,45,46,47):
        raise ValueError('Only explicit telemetry recipes3 through40 and44-47 are supported.')
    core_guards={3:12,4:14,5:15,6:16,7:18,8:21,9:25,10:27,11:28,12:31,13:40,14:48,15:53,16:53,17:56,18:56,19:56,20:56,21:56,22:56,23:56,24:56,25:56,26:56,27:56,28:56,29:56,30:56,31:56,32:56,33:56,34:56,35:56,36:56,37:56,38:56,39:57,40:58,41:58,42:58,43:58,44:58,45:58,46:58,47:59}[recipe_version]
    crash_guards=4 if recipe_version>=23 else 3
    required_stages = tuple(required_stages)
    if (not required_stages or len(required_stages) > 17
            or required_stages[0] != 'startup-after-engine-init'
            or any(stage not in STAGES for stage in required_stages)
            or any(a == b for a, b in zip(required_stages, required_stages[1:]))):
        raise ValueError('Require a bounded stage-entry path beginning with startup; no adjacent duplicates.')
    errors, stages = [], []
    active = None
    builds = snapshots = rows = 0
    previous_tick = -1

    def fail(code, line=0):
        errors.append({'code': code, 'line': line})

    for number, line in enumerate(lines, 1):
        if 'Telemetry audit' not in line:
            continue
        rows += 1
        if rows > 128:
            fail('audit_row_limit', number)
            break
        if len(line) > 2048:
            fail('audit_line_limit', number)
            break
        match = LINE.fullmatch(line.rstrip('\r\n'))
        if not match:
            fail('malformed_audit_line', number)
            continue
        tick, body = int(match[1]), match[2]
        if tick < previous_tick:
            fail('timestamp_regression', number)
        previous_tick = tick
        if match := BUILD.fullmatch(body):
            builds += 1
            if builds != 1 or active is not None or snapshots:
                fail('duplicate_or_late_build', number)
            if (match[1] != expected_sha256
                    or match[2] != COMPONENTS['UnityPlayer.dll'].original_sha256
                    or match.groups()[2:6] != (str(crash_guards), str(core_guards),str(core_guards), '3') or
                    f' crashSignatures={crash_guards}/{crash_guards} ' not in body or
                    match[7] != ('5' if recipe_version>=16 else None) or
                    match[8] != ('2' if recipe_version==18 else None) or
                    match[9] != ('2' if recipe_version>=19 else None) or
                    match[10] != (str(recipe_version) if recipe_version>=19 else None) or
                    match[11] != ('1' if recipe_version>=20 else None) or
                    match[12] != ('6' if recipe_version>=21 else None) or
                    match[13] != ('7' if recipe_version>=22 else None) or
                    match[14] != ('7' if recipe_version>=26 else '3' if recipe_version>=25 else None) or
                    match[15] != ('7' if recipe_version>=26 else '3' if recipe_version>=25 else None) or
                    match[16] != ('2' if recipe_version>=27 else None) or
                    match[17] != ('1' if recipe_version>=28 else None) or
                    match[18] != ('1' if recipe_version>=29 else None) or
                    match[19] != ('3' if recipe_version>=30 else None) or
                    match[20] != ('2' if recipe_version>=31 else None) or
                    match[21] != ('10' if recipe_version>=32 else None) or
                    match[22] != ('2' if recipe_version>=33 else None) or
                    match[23] != ('2' if recipe_version>=34 else None) or
                    match[24] != ('6' if recipe_version>=35 else None) or
                    match[25] != ('1' if recipe_version>=36 else None) or
                    match[26] != ('1' if recipe_version>=37 else None) or
                    match[27] != ('1' if recipe_version>=38 else None) or
                    match[28] != ('5' if recipe_version>=45 else '4' if recipe_version==44 else None) or
                    match[29] != ('5' if recipe_version>=45 else '4' if recipe_version==44 else None) or
                    match[30] != ('1' if recipe_version>=46 else None)):
                fail('unsupported_or_partial_build', number)
        elif match := BEGIN.fullmatch(body):
            if active is not None:
                fail('unfinished_snapshot', number)
            sequence = int(match[1])
            if builds != 1 or sequence != snapshots + 1 or not 1 <= sequence <= 17:
                fail('snapshot_order_or_budget', number)
            if match[2] not in STAGES or (sequence == 1) != (match[2] == 'startup-after-engine-init'):
                fail('invalid_stage', number)
            if match.groups()[2:] != ('1', '1', '1', '0', '0'):
                fail('missing_object_or_active_hook', number)
            active = {'sequence': sequence, 'stage': match[2], 'components': set()}
        elif match := COMPONENT.fullmatch(body):
            component = match[2]
            if active is None or int(match[1]) != active['sequence']:
                fail('orphan_component', number)
                continue
            if component in active['components']:
                fail('duplicate_component', number)
            active['components'].add(component)
            # Exact keys, no duplicates, and all constructor-default values.
            expected = ' '.join(name + '=0' for name in FIELDS[component])
            if match[3] != expected:
                fail('unavailable_or_nondefault_' + component, number)
        elif match := END.fullmatch(body):
            if active is None or int(match[1]) != active['sequence']:
                fail('orphan_snapshot_end', number)
                continue
            if active['components'] != set(FIELDS):
                fail('missing_component', number)
            if match[2] != '1':
                fail('unstable_singletons', number)
            stages.append(active['stage'])
            snapshots += 1
            active = None
        else:
            fail('disabled_or_unrecognized_audit', number)
    if builds != 1:
        fail('missing_or_multiple_builds')
    if active is not None:
        fail('incomplete_final_snapshot')
    if 'pre-quit-confirm' in stages and (stages.count('pre-quit-confirm')!=1 or stages[-1]!='pre-quit-confirm'):
        fail('duplicate_or_nonfinal_quit_boundary')
    # Repeated samples in one state must not count as distinct result entries.
    entries = [stage for i, stage in enumerate(stages) if not i or stage != stages[i - 1]]
    cursor = 0
    for stage in entries:
        if cursor < len(required_stages) and stage == required_stages[cursor]:
            cursor += 1
    if cursor != len(required_stages):
        fail('missing_ordered_stage_coverage')
    return {'schema': 1, 'passed': not errors, 'recipe_version': recipe_version,
            'scope': 'Read-only sampled native fields and stage coverage; not network/removal qualification.',
            'expected_unity_sha256': expected_sha256, 'complete_snapshots': snapshots,
            'observed_stages': stages, 'observed_entries': entries,
            'required_stages': list(required_stages), 'errors': errors}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--log', type=Path, required=True, help='One client process log from a fresh run.')
    parser.add_argument('--expected-unity-sha256', required=True, help='Installed UnityPlayer hash from that run manifest.')
    parser.add_argument('--recipe-version',type=int,choices=(*range(3,41),44,45),default=RECIPE_VERSION,help='older reports require explicit older recipe; never qualify current guards from legacy samples')
    parser.add_argument('--stages', nargs='+', choices=sorted(STAGES), default=DEFAULT_STAGES)
    parser.add_argument('--output', type=Path, help='Optional new JSON report; existing files are never overwritten.')
    args = parser.parse_args()
    try:
        if args.log.stat().st_size > 64 * 1024 * 1024:
            raise ValueError('Input log exceeds the 64 MiB review bound.')
        with args.log.open(encoding='utf-8-sig', errors='strict') as stream:
            result = verify_lines(stream, expected_sha256=args.expected_unity_sha256, required_stages=args.stages,recipe_version=args.recipe_version)
        encoded = json.dumps(result, indent=2) + '\n'
        if args.output:
            with args.output.open('x', encoding='utf-8') as stream:
                stream.write(encoded)
        print(encoded, end='')
        return 0 if result['passed'] else 1
    except (OSError, UnicodeError, ValueError) as exc:
        parser.error(str(exc))


if __name__ == '__main__':
    raise SystemExit(main())
