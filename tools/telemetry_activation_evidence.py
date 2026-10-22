"""Selected guarded calls on real retained owners;not all-mode privacy proof."""
import re

FIELDS='transitionCalls=3 initializationDeclined=1 busyRejected=1 sameStateDeclined=1 configPreparationCalls=1 configDeclined=1 borrowedUnreadable=2 mainStable=1 busyRestored=1 cloudGetterCalls=1 retainedStringAddress=1 emptySsoMetadataUnchanged=1 identityPayloadRead=0 originalAcquisitionInvoked=0 originalInitializerInvoked=0 wholeRunIsolation=0'

def validate(text,quit_rows):
    begin=list(re.finditer(r'^\[(\d+)\] TELEMETRY ACTIVATION begin: version=1 thread=(\d+) retainedMain=1 retainedSession=1 originalInitializerInvoked=0$',text,re.M))
    end=list(re.finditer(r'^\[(\d+)\] TELEMETRY ACTIVATION probe passed: version=1 thread=(\d+) '+FIELDS+'$',text,re.M))
    confirm=[r for r in quit_rows if r.get('event')=='OnConfirm.dispatch']
    if len(begin)!=1 or len(end)!=1 or len(confirm)!=1 or text.count('TELEMETRY ACTIVATION')!=2 or \
            not begin[0].end()<end[0].start() or not int(begin[0][1])<=int(end[0][1])<=confirm[0]['tick'] or \
            not int(begin[0][2])==int(end[0][2])==confirm[0]['thread']:
        raise AssertionError('one complete same-thread retained-owner activation proof before original Quit required')
    return dict(passed=True,version=1,thread=int(begin[0][2]),begin_tick=int(begin[0][1]),end_tick=int(end[0][1]),
        transition_calls=3,initialization_declined=True,busy_rejection_preserved=True,same_state_decline_preserved=True,
        configuration_preparation_calls=1,configuration_declined_before_borrowed_inputs=True,unreadable_borrowed_inputs=2,
        sampled_main_unchanged=True,busy_restored=True,cloud_getter_calls=1,retained_native_string_address=True,
        empty_string_metadata_unchanged=True,identity_payload_read=False,original_acquisition_invoked=False,
        original_initializer_invoked=False,nonempty_retained_value_runtime_qualified=False,
        other_transition_runtime_qualified=False,analytics_removal_qualified=False)
