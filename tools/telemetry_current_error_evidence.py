"""Bind the recipe44/45 in-memory SDK error fixture to the owned Quit interval."""
from __future__ import annotations

import re


PATH = re.compile(r'^\[(\d+)\] TELEMETRY CACHEPATH probe passed: version=1 thread=(\d+) getters=4 originalBodies=1 scopedOwnedRoot=1 icallRestored=1 reportEnumeration=0 reportPayloadRead=0 wholeRunIsolation=0$', re.M)
CLIENT_BEGIN = re.compile(r'^\[(\d+)\] TELEMETRY CACHECLIENT begin: version=1 thread=(\d+) constructorGuards=6 callbackHeads=4$', re.M)
CLIENT_END = re.compile(r'^\[(\d+)\] TELEMETRY CACHECLIENT probe passed: version=1 thread=(\d+) nativeCtorCalls=1 clientCtorCalls=1 genuineNativeInterface=1 configurationRetained=1 coreFieldsPresent=14 dependencyGraphMatched=1 idleDelivery=1 globalCallbackHeadsUnchanged=4 reportingDisabled=1 wholeRunIsolation=0$', re.M)
ERROR_BEGIN = re.compile(r'^\[(\d+)\] TELEMETRY REPORTERROR begin: version=1 thread=(\d+) genuineClient=1 genuineException=1$', re.M)
ERROR_END = re.compile(r'^\[(\d+)\] TELEMETRY REPORTERROR probe passed: version=1 thread=(\d+) calls=7 genuineClient=1 genuineException=1 nullOptionalInputs=1 clientFieldsUnchanged=1 globalCallbackHeadsUnchanged=4 originalUnityExceptionLog=1 reportDelivered=0 wholeRunIsolation=0$', re.M)
CURRENT = re.compile(r'^\[(\d+)\] TELEMETRY CURRENTERROR probe passed: version=1 thread=(\d+) genuineClient=1 inMemoryInputs=1 originalCacheReads=0 pathRestored=1 reportDelivered=0$', re.M)


def validate(text: str, quit_rows: list[dict], telemetry: dict, report_errors: dict) -> dict:
    if (telemetry.get('passed') is not True or telemetry.get('recipe_version') not in (44, 45, 46) or
            report_errors.get('passed') is not True or report_errors.get('calls') != 7 or
            report_errors.get('local_exception_log_retained') is not True):
        raise AssertionError('recipe44/45 audit and local seven-entry error proof required')
    patterns = (PATH, CLIENT_BEGIN, CLIENT_END, ERROR_BEGIN, ERROR_END, CURRENT)
    matches = [list(pattern.finditer(text)) for pattern in patterns]
    confirms = [row for row in quit_rows if row.get('event') == 'OnConfirm.dispatch']
    if any(len(group) != 1 for group in matches) or len(confirms) != 1:
        raise AssertionError('one complete current Client/error sequence and Quit required')
    sequence = [group[0] for group in matches]
    thread = int(sequence[0][2])
    ticks = [int(row[1]) for row in sequence]
    if (thread <= 0 or any(int(row[2]) != thread for row in sequence) or
            type(confirms[0].get('thread')) is not int or confirms[0]['thread'] != thread or
            type(confirms[0].get('tick')) is not int or ticks != sorted(ticks) or
            ticks[-1] > confirms[0]['tick'] or
            any(a.end() >= b.start() for a, b in zip(sequence, sequence[1:])) or
            thread != report_errors.get('thread')):
        raise AssertionError('current Client/error path order or Quit thread differs')
    if any(marker in text for marker in ('TELEMETRY CACHE probe failed:',
            'TELEMETRY CACHEREAD ', 'TELEMETRY CACHEREADER',
            'TELEMETRY CACHETYPE', 'TELEMETRY CACHEDELIVERY',
            'TELEMETRY CACHEFAILURE')):
        raise AssertionError('obsolete disk-reader path or failure appeared')
    return dict(passed=True, version=1, recipe=telemetry['recipe_version'], thread=thread,
                in_memory_inputs=True, genuine_client=True,
                original_cache_reads=0, guarded_error_calls=7,
                local_exception_log_retained=True, path_override_restored=True,
                report_delivered=False, whole_run_privacy_qualified=False,
                resumed_or_inflight_delivery_qualified=False)
