"""Native positive root control only; external early-shim/queue proof required."""
import re


def validate(text,quit_rows):
    matches=list(re.finditer(r'^\[(\d+)\] TELEMETRY CACHESTARTUP probe passed: version=1 thread=(\d+) originalGetters=3 sdkRootMatched=1 deviceFilenameMatched=1 staticConfigNull=1 generalUnityPathUnchanged=1 cacheInstanceConstructed=0 reportPayloadRead=0 expiryCalled=0 scopedIcallOverride=0 externalEarlyRootShimRequired=1$',text,re.M))
    confirm=[row for row in quit_rows if row.get('event')=='OnConfirm.dispatch']
    if (len(matches)!=1 or text.count('TELEMETRY CACHESTARTUP probe passed:')!=1 or
        'TELEMETRY CACHESTARTUP probe failed:' in text or len(confirm)!=1 or
        int(matches[0][1])>confirm[0]['tick'] or int(matches[0][2])!=confirm[0]['thread'] or
        'TELEMETRY CACHEPATH' in text or 'TELEMETRY CACHEREADER' in text):
        raise AssertionError('one new startup root control before same-thread original Quit required')
    return dict(passed=True,version=1,thread=int(matches[0][2]),tick=int(matches[0][1]),
                original_path_getters=3,sdk_root_matched=True,device_filename_matched=True,
                static_configuration_null=True,general_unity_path_unchanged=True,
                cache_instance_constructed=False,report_payload_read=False,expiry_called=False,
                scoped_icall_override=False,external_early_root_shim_required=True,
                startup_queue_isolation_qualified=False,analytics_removal_qualified=False)
