"""Validate one bounded owned execution of guarded reporter callbacks."""
import re

ENTRIES={1:(0x3cc3600,0x3cc5440,0x3cc5df0),
         2:(0x3cc3600,0x3cc5440,0x3cc5df0,0x3cc6930,0x3cc6a70,0x3cc3700,0x3cc4aa0)}
BEGIN=re.compile(r'^\[(\d+)\] TELEMETRY REPORTCALLBACK begin: version=(1|2) thread=(\d+) guards=(3|7) borrowedUnreadable=1$',re.M)
CALL=re.compile(r'^\[(\d+)\] TELEMETRY REPORTCALLBACK call: version=(1|2) thread=(\d+) index=(\d+) rva=([0-9a-f]+) returnedFalse=1$',re.M)
END=re.compile(r'^\[(\d+)\] TELEMETRY REPORTCALLBACK probe passed: version=(1|2) thread=(\d+) calls=(3|7) guards=(3|7) borrowedUnreadable=1 returnedFalse=(3|7) payloadRead=0 callerRegistrationQualified=0 reportDelivered=0$',re.M)


def validate(text,quit_rows):
    begin=list(BEGIN.finditer(text));calls=list(CALL.finditer(text));end=list(END.finditer(text))
    confirm=[row for row in quit_rows if row.get('event')=='OnConfirm.dispatch']
    if len(begin)!=1 or len(end)!=1 or len(confirm)!=1:
        raise AssertionError('one complete guarded reporter callback sequence and original Quit required')
    version=int(begin[0][2]);entries=ENTRIES[version];count=len(entries)
    if (len(calls)!=count or text.count('TELEMETRY REPORTCALLBACK')!=count+2 or
            int(begin[0][4])!=count or int(end[0][2])!=version or
            any(int(row[2])!=version for row in calls) or
            any(int(end[0][field])!=count for field in (4,5,6))):
        raise AssertionError('reporter callback version or count differs')
    rows=[begin[0],*calls,end[0]]
    thread=int(rows[0][3]);ticks=[int(row[1]) for row in rows]
    if (thread<=0 or any(int(row[3])!=thread for row in rows) or
            [int(row[4]) for row in calls]!=list(range(1,count+1)) or
            tuple(int(row[5],16) for row in calls)!=entries or
            any(a.end()>=b.start() for a,b in zip(rows,rows[1:])) or
            ticks!=sorted(ticks) or type(confirm[0].get('thread')) is not int or
            confirm[0]['thread']!=thread or type(confirm[0].get('tick')) is not int or
            ticks[-1]>confirm[0]['tick']):
        raise AssertionError('guarded reporter callback order,entries,thread or Quit boundary differs')
    return dict(passed=True,version=version,thread=thread,calls=count,entries=list(entries),
                loaded_and_disk_guards=count,returned_false=count,borrowed_unreadable=True,
                callback_registration_qualified=False,report_delivered=False)
