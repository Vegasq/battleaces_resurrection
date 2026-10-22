"""Validate scoped original cache getter/typed-constructor diagnostic evidence.

The explicit disk mode qualifies two authored SDK reader calls, not ordinary
startup isolation, report delivery, or telemetry removal. Raw native logs and
original Quit records remain required. Legacy120 proof retains its narrow scope.
"""
import re


def validate(text, quit_rows, *, disk_probe=False):
    path = list(re.finditer(
        r'^\[(\d+)\] TELEMETRY CACHEPATH probe passed: version=1 thread=(\d+) getters=4 originalBodies=1 scopedOwnedRoot=1 icallRestored=1 reportEnumeration=0 reportPayloadRead=0 wholeRunIsolation=0$', text, re.M))
    suffix=(r'version=2 thread=(\d+) parsed=4 constructed=2 errors=1 sessions=1 authoredFieldsRetained=1 missingKeyRejected=2 cacheManagerConstructed=1 reportDelivered=0 diskQueueRead=1 fromDisk=2'
            if disk_probe else
            r'version=1 thread=(\d+) parsed=4 constructed=2 errors=1 sessions=1 authoredFieldsRetained=1 missingKeyRejected=2 cacheManagerConstructed=0 reportDelivered=0 diskQueueRead=0')
    typed = list(re.finditer(r'^\[(\d+)\] TELEMETRY CACHETYPE probe passed: '+suffix+'$',text,re.M))
    confirm = [row for row in quit_rows if row.get('event') == 'OnConfirm.dispatch']
    if (len(path) != 1 or len(typed) != 1 or len(confirm) != 1 or
        text.count('TELEMETRY CACHEPATH probe passed:') != 1 or text.count('TELEMETRY CACHETYPE probe passed:') != 1):
        raise AssertionError('one scoped cache-path/typed proof and original Quit dispatch required')
    if ('TELEMETRY CACHE probe failed:' in text or
        not (path[0].end() < typed[0].start() and
             int(path[0][1]) <= int(typed[0][1]) <= confirm[0]['tick']) or
        not (int(path[0][2]) == int(typed[0][2]) == confirm[0]['thread'])):
        raise AssertionError('scoped cache probe failed or thread/order does not precede original Quit')
    result=dict(passed=True, version=2 if disk_probe else 1, thread=int(path[0][2]),
                path_tick=int(path[0][1]), typed_tick=int(typed[0][1]),
                original_path_getters=4, typed_reports=2, authored_errors=1,
                authored_sessions=1, missing_required_key_rejections=2,
                scoped_icall_restored=True, disk_queue_read=disk_probe,
                whole_run_cache_isolation=False, report_delivered=False)
    if not disk_probe:
        if 'TELEMETRY CACHEREAD' in text:raise AssertionError('disk reader proof requires explicit disk mode')
        return result
    readers=list(re.finditer(
        r'^\[(\d+)\] TELEMETRY CACHEREADER probe passed: version=1 thread=(\d+) instanceCtor=1 emptyBeforeCtor=1 emptyAfterCtor=1 seeds=2 enumerated=2 reads=2 rawBytesMatched=2 missingIdNull=2 fileIdentityBytesUnchanged=2 staticConfigRestored=1 deviceFilenameUnchanged=1 icallRestored=1 wholeRunIsolation=0$',text,re.M))
    boundaries=list(re.finditer(r'^\[(\d+)\] TELEMETRY CACHEREAD (begin|end): version=1 thread=(\d+) kind=(event|session)$',text,re.M))
    if (len(readers)!=1 or text.count('TELEMETRY CACHEREADER probe passed:')!=1 or len(boundaries)!=4 or
        text.count('TELEMETRY CACHEREAD begin:')!=2 or text.count('TELEMETRY CACHEREAD end:')!=2 or
        [(row[2],row[4]) for row in boundaries]!=[('begin','event'),('end','event'),('begin','session'),('end','session')]):
        raise AssertionError('one real cache reader proof and four ordered reader boundaries required')
    ticks=[int(path[0][1]),*[int(row[1]) for row in boundaries],int(readers[0][1]),int(typed[0][1]),confirm[0]['tick']]
    if (not(path[0].end()<boundaries[0].start() and boundaries[-1].end()<readers[0].start()<readers[0].end()<typed[0].start()) or
        ticks!=sorted(ticks) or int(readers[0][2])!=result['thread'] or any(int(row[3])!=result['thread'] for row in boundaries)):
        raise AssertionError('original cache read boundaries do not match typed proof/confirmed Quit order and thread')
    result.update(real_cache_manager_initialized=True,empty_constructor_before_seed=True,
                  seeded_files=2,original_disk_reads=2,missing_ids_returned_null=2,
                  file_identity_bytes_unchanged=True,static_configuration_restored=True,
                  device_filename_pointer_unchanged=True,reader_tick=int(readers[0][1]),
                  reader_boundaries=[dict(tick=int(row[1]),phase=row[2],kind=row[4]) for row in boundaries])
    return result
