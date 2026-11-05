"""Validate recipe44-47 authored cached-report retention under genuine Client."""
from __future__ import annotations

import re


PATH = re.compile(r'^\[(\d+)\] TELEMETRY CACHEPATH probe passed: version=1 thread=(\d+) getters=4 originalBodies=1 scopedOwnedRoot=1 icallRestored=1 reportEnumeration=0 reportPayloadRead=0 wholeRunIsolation=0$', re.M)
CLIENT_BEGIN = re.compile(r'^\[(\d+)\] TELEMETRY CACHECLIENT begin: version=1 thread=(\d+) constructorGuards=6 callbackHeads=4$', re.M)
CLIENT_END = re.compile(r'^\[(\d+)\] TELEMETRY CACHECLIENT probe passed: version=1 thread=(\d+) nativeCtorCalls=1 clientCtorCalls=1 genuineNativeInterface=1 configurationRetained=1 coreFieldsPresent=14 dependencyGraphMatched=1 idleDelivery=1 globalCallbackHeadsUnchanged=4 reportingDisabled=1 wholeRunIsolation=0$', re.M)
PREEXISTING_BEGIN = re.compile(r'^\[(\d+)\] TELEMETRY PREEXISTING begin: version=1 thread=(\d+) ownedFilesBeforeClient=2$', re.M)
PREEXISTING_CTOR = re.compile(r'^\[(\d+)\] TELEMETRY PREEXISTING ctor passed: version=1 thread=(\d+) genuineClient=1 fileIdentitiesAndBytesUnchanged=2$', re.M)


def queue_patterns(version: int):
    delete = ' deleteEntriesReturned=2' if version == 2 else ''
    if version == 3:
        delete = ' deleteEntriesReturned=2'
    preexisting = ' preexistingBeforeClient=1' if version == 3 else ''
    return (
        re.compile(rf'^\[(\d+)\] TELEMETRY CURRENTQUEUE begin: version={version} thread=(\d+) genuineClient=1 authoredSeeds=2{preexisting}$', re.M),
        re.compile(rf'^\[(\d+)\] TELEMETRY CURRENTQUEUE probe passed: version={version} thread=(\d+) genuineClient=1 authoredSeeds=2{preexisting} eventFiles=0 sessionFiles=0 eventNull=1 sessionNull=1 cachedStartReturned=1{delete} deliveryFieldsUnchanged=1 clientFieldsUnchanged=1 seedIdentitiesAndBytesUnchanged=2 reportDelivered=0$', re.M),
        re.compile(rf'^\[(\d+)\] TELEMETRY CURRENTQUEUE scope restored: version={version} thread=(\d+) pathRestored=1$', re.M),
    )


def validate(text: str, quit_rows: list[dict], telemetry: dict, *, preexisting: bool = False) -> dict:
    recipe = telemetry.get('recipe_version')
    if telemetry.get('passed') is not True or recipe not in (44, 45, 46, 47) or (preexisting and recipe < 45):
        raise AssertionError('current recipe44-47 native audit required')
    version = 3 if preexisting else 2 if recipe >= 45 else 1
    patterns = [PATH]
    if preexisting:
        patterns.append(PREEXISTING_BEGIN)
    patterns.extend((CLIENT_BEGIN, CLIENT_END))
    if preexisting:
        patterns.append(PREEXISTING_CTOR)
    patterns.extend(queue_patterns(version))
    groups = [list(pattern.finditer(text)) for pattern in patterns]
    confirms = [row for row in quit_rows if row.get('event') == 'OnConfirm.dispatch']
    if any(len(group) != 1 for group in groups) or len(confirms) != 1:
        raise AssertionError('one complete current queue sequence and Quit required')
    sequence = [group[0] for group in groups]
    thread = int(sequence[0][2])
    ticks = [int(row[1]) for row in sequence]
    if (thread <= 0 or any(int(row[2]) != thread for row in sequence) or
            type(confirms[0].get('thread')) is not int or confirms[0]['thread'] != thread or
            type(confirms[0].get('tick')) is not int or ticks != sorted(ticks) or
            ticks[-1] > confirms[0]['tick'] or
            any(a.end() >= b.start() for a, b in zip(sequence, sequence[1:]))):
        raise AssertionError('current queue order, time or Quit thread differs')
    if any(marker in text for marker in ('TELEMETRY CACHE probe failed:',
            'TELEMETRY CACHEREAD ', 'TELEMETRY CACHEREADER',
            'TELEMETRY CACHETYPE', 'TELEMETRY CACHEDELIVERY',
            'TELEMETRY REPORTERROR')):
        raise AssertionError('obsolete disk reader, error or failure path appeared')
    return dict(passed=True, version=version, recipe=recipe, thread=thread,
                genuine_client=True, authored_seeds=2, event_files_returned=0,
                session_files_returned=0, event_lookup_null=True,
                session_lookup_null=True, cached_delivery_start_returned=True,
                seed_identity_and_bytes_unchanged=True, path_override_restored=True,
                guarded_delete_entries_returned=(version >= 2),
                preexisting_before_client=preexisting,
                report_delivered=False, whole_run_privacy_qualified=False,
                resumed_or_inflight_delivery_qualified=False)
