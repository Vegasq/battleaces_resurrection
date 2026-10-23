"""Strict bounded guarded-error evidence; never whole-run privacy acceptance."""
import re

ENTRIES=(0x814ef0,0x815100,0x815390,0x8153e0,0x8154e0,0x8157d0,0x815ba0)


def validate(text,quit_rows):
    begin=list(re.finditer(r'^\[(\d+)\] TELEMETRY REPORTERROR begin: version=1 thread=(\d+) genuineClient=1 genuineException=1$',text,re.M))
    calls=list(re.finditer(r'^\[(\d+)\] TELEMETRY REPORTERROR call: version=1 thread=(\d+) index=(\d+) rva=([0-9a-f]+) returned=1 clientStable=1 exceptionStable=1$',text,re.M))
    end=list(re.finditer(r'^\[(\d+)\] TELEMETRY REPORTERROR probe passed: version=1 thread=(\d+) calls=7 genuineClient=1 genuineException=1 nullOptionalInputs=1 clientFieldsUnchanged=1 globalCallbackHeadsUnchanged=4 originalUnityExceptionLog=1 reportDelivered=0 wholeRunIsolation=0$',text,re.M))
    confirm=[row for row in quit_rows if row.get('event')=='OnConfirm.dispatch']
    if len(begin)!=1 or len(end)!=1 or len(calls)!=7 or len(confirm)!=1 or text.count('TELEMETRY REPORTERROR')!=9:
        raise AssertionError('one complete guarded-report sequence and original Quit required')
    sequence=[begin[0],*calls,end[0]];thread=int(begin[0][2])
    if (thread<=0 or any(int(row[2])!=thread for row in sequence) or type(confirm[0].get('thread')) is not int or confirm[0].get('thread')!=thread or
            [int(row[3]) for row in calls]!=list(range(1,8)) or
            tuple(int(row[4],16) for row in calls)!=ENTRIES or
            any(a.end()>=b.start() for a,b in zip(sequence,sequence[1:]))):
        raise AssertionError('guarded-report order, entries or thread differs')
    ticks=[int(row[1]) for row in sequence]
    if type(confirm[0].get('tick')) is not int or ticks!=sorted(ticks) or ticks[-1]>confirm[0]['tick']:
        raise AssertionError('guarded-report interval does not precede Quit')
    return dict(passed=True,version=1,thread=thread,begin_tick=ticks[0],end_tick=ticks[-1],
                calls=7,entries=list(ENTRIES),genuine_client=True,genuine_exception=True,
                original_local_exception_logging=True,whole_run_privacy_qualified=False,
                resumed_or_inflight_delivery_qualified=False)
