"""Strict evidence for genuine pending-owner cleanup/disabled-ID fixture126.

This is not operational-client,in-flight network or whole-process isolation proof.
"""
import re
from tools.telemetry_cache_evidence import validate as delivery_validate

FIELDS='cases=8 matchedCases=4 missCases=4 removedMatches=8 unmatchedRetained=24 clearedArrayRefs=8 cleanupVersionUpdates=4 missListUnchanged=4 pendingAfter=0 genuinePendingOwners=32 typedFailureBranches=2 cacheHandlers=2 cacheLimitsZero=1 configLimitsRestored=1 reportFieldsUnchanged=2 payloadManagerFieldsUnchanged=1 listIdentityRetained=1 devicePositiveRead=1 deviceEmpty=1 deviceSeedUnchanged=1 configRestored=1 retainedFilenameUnchanged=1 reportDelivered=0 operationalClient=0 wholeRunIsolation=0'


def validate(text,quit_rows):
    base=delivery_validate(text,quit_rows,disk_probe=True,delivery_probe=True)
    begin=list(re.finditer(r'^\[(\d+)\] TELEMETRY CACHEFAILURE begin: version=1 thread=(\d+) genuinePendingOwners=1 activeClientConstructed=0$',text,re.M))
    end=list(re.finditer(r'^\[(\d+)\] TELEMETRY CACHEFAILURE probe passed: version=1 thread=(\d+) '+FIELDS+'$',text,re.M))
    boundaries=list(re.finditer(r'^\[(\d+)\] TELEMETRY CACHEFAILURE device boundary: version=1 thread=(\d+) phase=(read-begin|read-end|id-begin|id-end)$',text,re.M))
    if len(begin)!=1 or len(end)!=1 or len(boundaries)!=4 or text.count('TELEMETRY CACHEFAILURE')!=6:
        raise AssertionError('one complete pending-owner/disabled-ID fixture with four device boundaries required')
    phases=['read-begin','read-end','id-begin','id-end']
    if [m[3] for m in boundaries]!=phases:raise AssertionError('device control/guard call order differs')
    marks=[begin[0],*boundaries,end[0]];ticks=[int(m[1]) for m in marks]
    if ticks!=sorted(ticks) or any(int(m[2])!=base['thread'] for m in marks) or \
            not base['guard_end_tick']<=ticks[0]<=ticks[-1]<=base['reader_tick'] or \
            [m.start() for m in marks]!=sorted(m.start() for m in marks):
        raise AssertionError('pending fixture must remain within genuine owned cache lifetime and original Quit thread')
    return dict(passed=True,version=1,thread=base['thread'],begin_tick=ticks[0],end_tick=ticks[-1],
        pending_cases=8,matched_cases=4,id_miss_cases=4,matches_removed=8,unmatched_retained=24,
        cleared_array_refs=8,version_updates=4,genuine_pending_owners=32,pending_after=0,
        typed_failure_branches=2,cache_handlers=2,device_positive_read=True,genuine_empty_string=True,
        device_seed_unchanged=True,configuration_restored=True,retained_filename_unchanged=True,
        device_boundaries=[dict(tick=int(m[1]),phase=m[3]) for m in boundaries],
        operational_client_qualified=False,resumed_network_request_qualified=False,
        whole_run_cache_isolation=False,analytics_removal_qualified=False)
