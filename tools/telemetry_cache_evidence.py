"""Validate scoped original cache getter/typed-constructor diagnostic evidence.

This does not qualify ordinary startup isolation, disk queues, report delivery,
or telemetry removal. Raw native logs and original Quit records remain required.
"""
import re


def validate(text, quit_rows):
    path = list(re.finditer(
        r'^\[(\d+)\] TELEMETRY CACHEPATH probe passed: version=1 thread=(\d+) getters=4 originalBodies=1 scopedOwnedRoot=1 icallRestored=1 reportEnumeration=0 reportPayloadRead=0 wholeRunIsolation=0$', text, re.M))
    typed = list(re.finditer(
        r'^\[(\d+)\] TELEMETRY CACHETYPE probe passed: version=1 thread=(\d+) parsed=4 constructed=2 errors=1 sessions=1 authoredFieldsRetained=1 missingKeyRejected=2 cacheManagerConstructed=0 reportDelivered=0 diskQueueRead=0$', text, re.M))
    confirm = [row for row in quit_rows if row.get('event') == 'OnConfirm.dispatch']
    if len(path) != 1 or len(typed) != 1 or len(confirm) != 1:
        raise AssertionError('one scoped cache-path/typed proof and original Quit dispatch required')
    if ('TELEMETRY CACHE probe failed:' in text or
        not (path[0].end() < typed[0].start() and
             int(path[0][1]) <= int(typed[0][1]) <= confirm[0]['tick']) or
        not (int(path[0][2]) == int(typed[0][2]) == confirm[0]['thread'])):
        raise AssertionError('scoped cache probe failed or thread/order does not precede original Quit')
    return dict(passed=True, version=1, thread=int(path[0][2]),
                path_tick=int(path[0][1]), typed_tick=int(typed[0][1]),
                original_path_getters=4, typed_reports=2, authored_errors=1,
                authored_sessions=1, missing_required_key_rejections=2,
                scoped_icall_restored=True, disk_queue_read=False,
                whole_run_cache_isolation=False, report_delivered=False)
