"""Original menu-to-replay API control; never equate API cleanup with a UI click."""
import json
import re

from tools.replay_binding_evidence import require
from tools.replay_signal_evidence import validate as signal_inventory
from tools.replay_nody_evidence import validate as nody_inventory

COMPLETE = ('NATIVE REPLAY MENU API control passed: mainMenu=1 worldIdle=1 originalExitApi=1 '
            'probeRootsReleased=1 filePinReleased=1 buttonClicks=0 fsmWrites=0 helperTicks=0 '
            'BA_RESURRECTION_REPLAY_MENU_V1')
BUTTON_COMPLETE = ('NATIVE REPLAY MENU BUTTON control passed: mainMenu=1 worldIdle=1 originalExitApi=0 '
                   'probeRootsReleased=1 filePinReleased=1 buttonClicks=1 fsmWrites=0 helperTicks=0 '
                   'BA_RESURRECTION_REPLAY_MENU_BUTTON_V2')
CANCEL_COMPLETE = ('NATIVE REPLAY MENU CANCEL control passed: mainMenu=1 worldIdle=1 originalExitApi=0 '
                   'probeRootsReleased=1 filePinReleased=1 buttonClicks=2 cancelCallbacks=1 fsmWrites=0 helperTicks=0 '
                   'BA_RESURRECTION_REPLAY_MENU_CANCEL_V1')
INVALID_COMPLETE = ('NATIVE REPLAY MENU INVALID control passed: originalBadFileRefused=1 subsequentHealthyPlayback=1 '
                    'mainMenu=1 worldIdle=1 originalExitApi=0 probeRootsReleased=1 filePinReleased=1 buttonClicks=2 '
                    'cancelCallbacks=1 originalStopCalls=0 fsmWrites=0 helperTicks=0 BA_RESURRECTION_REPLAY_MENU_INVALID_V1')
SEMANTIC_COMPLETE = ('NATIVE REPLAY MENU SEMANTIC control passed: originalBadFilesRefused=3 semanticCases=2 '
                     'subsequentHealthyPlayback=1 mainMenu=1 worldIdle=1 originalExitApi=0 probeRootsReleased=1 '
                     'filePinReleased=1 buttonClicks=2 cancelCallbacks=1 originalStopCalls=0 fsmWrites=0 helperTicks=0 '
                     'BA_RESURRECTION_REPLAY_MENU_SEMANTIC_V1')
PARTIAL_COMPLETE = ('NATIVE REPLAY MENU PARTIAL control passed: originalRunnerFailureObserved=1 subsequentHealthyPlayback=1 '
                    'mainMenu=1 worldIdle=1 originalExitApi=0 probeRootsReleased=1 filePinReleased=1 buttonClicks=2 '
                    'cancelCallbacks=1 originalStopCalls=0 fsmWrites=0 helperTicks=0 BA_RESURRECTION_REPLAY_MENU_PARTIAL_V1')


def validate(text, replay, *, button_exit=False, cancel_first=False, invalid_first=False, semantic_first=False, partial_first=False):
    require(not partial_first or (button_exit and cancel_first and not invalid_first and not semantic_first),
            'Partial initialization requires a separate healthy replacement sequence')
    require(not cancel_first or button_exit,'Cancel requires the authored leave route')
    require(not invalid_first or cancel_first,'Invalid-file control requires subsequent healthy Cancel/reopen/exit')
    require(not semantic_first or invalid_first,'Semantic controls require the invalid-file/healthy sequence')
    cycles=2 if cancel_first else 1
    require('Native replay menu control failed:' not in text, 'native menu/replay API control failed')
    require(text.count('Original replay runner update restored: primaryIntegration=1 originalPredicate=1 helperTicks=0') == 1 and
            text.count('Original replay runner update failed:')==int(partial_first), 'original production replay pump was not observed')
    load = ('NATIVE REPLAY MENU load dispatch: profile=', 'mainMenu=1 worldIdle=1 '
            'originalLoadReplayFromFile=1 extraPlayCalls=0 fsmWrites=0 helperTicks=0')
    require(text.count(load[0]) == 1 and text.count(load[1]) == 1,
            'one original file load from idle menu required')
    loaded = list(re.finditer(r'NATIVE REPLAY MENU loaded: frames=(\d+) gameDataSha256=([0-9a-f]{64}) '
                              r'loadReturned=1 originalPlayInternal=1', text))
    world = list(re.finditer(r'NATIVE REPLAY MENU in-game: world=(\d+) presented=(\d+) '
                             r'originalMainFsm=1 practiceActive=0 frames=(\d+)', text))
    require(len(loaded) == len(world) == 1 and int(loaded[0][1]) == replay['input_action_messages'] and
            loaded[0][2] == replay['game_data_sha256'] and int(world[0][1]) > 0 and
            30 <= int(world[0][2]) < replay['input_action_messages'] and
            int(world[0][3]) == replay['input_action_messages'],
            'original replay metadata/world/presentation differs')
    exit_api = 'NATIVE REPLAY MENU exit API dispatch: originalReplayEndGame=1 buttonClicks=0 fsmWrites=0 helperTicks=0'
    returned = 'NATIVE REPLAY MENU exit API returned: originalCallbackReturned=1'
    completed=PARTIAL_COMPLETE if partial_first else SEMANTIC_COMPLETE if semantic_first else INVALID_COMPLETE if invalid_first else CANCEL_COMPLETE if cancel_first else BUTTON_COMPLETE if button_exit else COMPLETE
    require(partial_first or 'NATIVE REPLAY PARTIAL ' not in text and PARTIAL_COMPLETE not in text,
            'unexpected partial initialization evidence')
    if partial_first:
        partial_markers=[
            'NATIVE REPLAY PARTIAL dispatch: case=missing-version-build mainMenu=1 worldIdle=1 originalLoadReplayFromFile=1 fsmWrites=0 helperTicks=0',
            'NATIVE REPLAY PARTIAL accepted: originalLoadReturned=1 decodedDataApplied=1 missingVersionBuild=1 originalPlayInternal=1 fsmWrites=0 helperTicks=0',
            'Original replay runner update failed:',
            'NATIVE REPLAY PARTIAL failure observed: sameOwner=1 mainMenu=1 worldIdle=1 decodedDataRetained=1 originalRunnerFailures=1 sameDataRetries=0 originalFileReleased=1 originalStopCalls=0 fsmWrites=0 helperTicks=0',
            load[0],
            'Original replay runner recovery allowed: sameOwner=1 newDecodedData=1 fsmWrites=0 helperTicks=0',
            'Original replay runner update restored: primaryIntegration=1 originalPredicate=1 helperTicks=0']
        partial_positions=[text.find(m) for m in partial_markers]
        require(all(text.count(m)==1 for m in partial_markers) and partial_positions==sorted(partial_positions),
                'partial failure containment/replacement/original pump recovery order differs')
    require(cancel_first or 'NATIVE REPLAY BUTTON cancel ' not in text and CANCEL_COMPLETE not in text,
            'unexpected Cancel control evidence')
    require(invalid_first or 'NATIVE REPLAY INVALID ' not in text and INVALID_COMPLETE not in text,
            'unexpected invalid-file control evidence')
    require(semantic_first or 'NATIVE REPLAY SEMANTIC ' not in text and SEMANTIC_COMPLETE not in text,
            'unexpected semantic-file control evidence')
    if invalid_first:
        invalid_markers=[
            'NATIVE REPLAY INVALID dispatch: case=invalid-deflate-07 bytes=1 mainMenu=1 worldIdle=1 originalLoadReplayFromFile=1 fsmWrites=0 helperTicks=0',
            'NATIVE REPLAY INVALID refused: originalLoadReturned=0 originalStopCalls=0 fsmWrites=0 helperTicks=0',
            'NATIVE REPLAY INVALID settled: sameOwner=1 mainMenu=1 worldIdle=1 decodedDataAbsent=1 navigationCount=0 filePinReleased=1 originalFileReleased=1 originalStopCalls=0 fsmWrites=0 helperTicks=0']
        invalid_positions=[text.find(m) for m in invalid_markers]
        require(all(text.count(m)==1 for m in invalid_markers) and invalid_positions==sorted(invalid_positions) and
                invalid_positions[-1]<text.index(load[0]),
                'original invalid Deflate refusal/owner/file cleanup did not precede healthy playback')
    if semantic_first:
        prior=invalid_positions[-1]
        for name,size in (('empty-replay',2),('missing-game-config',4)):
            semantic_markers=[
                f'NATIVE REPLAY SEMANTIC dispatch: case={name} bytes={size} mainMenu=1 worldIdle=1 originalLoadReplayFromFile=1 fsmWrites=0 helperTicks=0',
                f'NATIVE REPLAY SEMANTIC refused: case={name} originalLoadReturned=0 originalStopCalls=0 fsmWrites=0 helperTicks=0',
                f'NATIVE REPLAY SEMANTIC settled: case={name} sameOwner=1 mainMenu=1 worldIdle=1 decodedDataAbsent=1 navigationCount=0 originalFileReleased=1 originalStopCalls=0 fsmWrites=0 helperTicks=0']
            semantic_positions=[text.find(m) for m in semantic_markers]
            require(all(text.count(m)==1 for m in semantic_markers) and semantic_positions==sorted(semantic_positions) and
                    prior<semantic_positions[0] and semantic_positions[-1]<text.index(load[0]),
                    'parsed empty/missing-config refusal/owner/file cleanup did not precede healthy playback')
            prior=semantic_positions[-1]
    if button_exit:
        require('NATIVE REPLAY MENU exit API dispatch:' not in text and COMPLETE not in text and
                'NATIVE REPLAY BUTTON failure cleanup:' not in text,'button control used exit API cleanup')
        exit_api='NATIVE REPLAY BUTTON authored dispatch: originalBindClickButton=1 active=1 interactable=1 originalExitApi=0 buttonClicks=1 fsmWrites=0 helperTicks=0'
        returned='NATIVE REPLAY BUTTON authored returned: originalCallbackReturned=1'
    else:
        require('NATIVE REPLAY BUTTON authored dispatch:' not in text and BUTTON_COMPLETE not in text,
                'API control contains button exit evidence')
    markers = [load[0], 'NATIVE REPLAY MENU loaded:', 'REPLAY BINDING inventory:', exit_api, returned, completed]
    positions = [text.rfind(marker) if cancel_first and marker==exit_api else text.find(marker) for marker in markers]
    require(all(text.count(marker) == (cycles if button_exit and marker==exit_api else 1) for marker in markers) and positions == sorted(positions) and
            positions[1] < world[0].start() < positions[3], 'replay load/observation/API exit/menu order differs')
    signal = signal_inventory(text, phase='healthy-replay')
    visible=None
    if button_exit:
        opened='NATIVE REPLAY BUTTON options dispatch: originalTryShowOptionsConcedeView=1 buttonInitiallyHidden=1 fsmWrites=0'
        inventories=list(re.finditer(r'^\[\d+\] NATIVE REPLAY BUTTON visible inventory: (.+)$',text,re.M))
        openings=[m.start() for m in re.finditer(re.escape(opened),text)]
        dispatches=[m.start() for m in re.finditer(re.escape(exit_api),text)]
        require(len(openings)==len(inventories)==cycles and world[0].start()<openings[0],
                'original options/visible button count differs')
        hidden=signal['binding_inventory']['inventory']
        bindings=list(re.finditer(r'^\[\d+\] NATIVE REPLAY BUTTON authored binding: (.+)$',text,re.M))
        require(len(bindings)==cycles,'existing authored binding count differs')
        for i in range(cycles):
            require(openings[i]<inventories[i].start()<inventories[i].end()<bindings[i].start()<dispatches[i],
                    'original options/visible binding/leave dispatch order differs')
            if i:require(dispatches[i-1]<openings[i],'reopened options precede first leave')
            visible=json.loads(inventories[i][1])
            require(all(visible[k] is True for k in ('active','active_self','initialized')) and
                    all(visible[k]==hidden[k] for k in ('controller','button','path','signal_category','signal_name','signal_custom')) and
                    visible['signal_category']=='Game' and visible['signal_name']=='Quit' and visible['signal_custom'] is False,
                    'visible original button ownership/activation differs')
            authored=json.loads(bindings[i][1]);calls=authored['confirm_event']['persistent']
            clicks=authored['click_event']['persistent']
            require(authored['same_game_object'] is True and
                authored['binder']['class']=='Uncapped.BindUISelectableToInputAction' and
                authored['show']['class']=='Uncapped.UI.ShowUIObjectComponent' and
                authored['view']['class']=='Doozy.Runtime.UIManager.Containers.UIView' and
                len(clicks)==2 and clicks[0]['target']==authored['show'] and clicks[0]['method']=='Show' and
                clicks[1]['target']==authored['view'] and clicks[1]['method']=='Hide' and
                all(c['mode']==1 and c['state']==2 and c['method_name_present'] is True for c in clicks) and
                authored['click_event']['runtime']==[] and authored['confirm_event']['runtime']==[] and
                len(calls)==1 and calls[0]['target']==visible['controller'] and
                calls[0]['method']=='ReplayEndGame' and calls[0]['method_name_present'] is True and
                    calls[0]['state']==2 and calls[0]['mode']==1, 'existing authored callbacks do not own replay confirmation/exit')
        confirm='NATIVE REPLAY BUTTON confirmation dispatch: originalModalOnConfirm=1 currentNavigation=1 nativeModel=1 persistentReplayEndGame=1 originalExitApi=0 fsmWrites=0 helperTicks=0'
        require(text.count(confirm)==1 and positions[3]<text.index(confirm)<positions[4],
                'original current confirmation was not invoked after the authored leave action')
        if cancel_first:
            cancel=list(re.finditer(r'NATIVE REPLAY BUTTON cancel dispatch: originalModalOnCancel=1 currentNavigation=1 '
                r'emptyCancelEvent=1 closeOnCancel=1 world=(\d+) presented=(\d+) originalExitApi=0 fsmWrites=0 helperTicks=0',text))
            settled=list(re.finditer(r'NATIVE REPLAY BUTTON cancel settled: world=(\d+) presentedBefore=(\d+) presentedAfter=(\d+) '
                r'sameReplay=1 nativeRelease=1 navigationCount=0 optionsHidden=1 fsmWrites=0 helperTicks=0',text))
            returned_cancel='NATIVE REPLAY BUTTON cancel returned: originalCallbackReturned=1'
            require(len(cancel)==len(settled)==1 and text.count(returned_cancel)==1 and
                    dispatches[0]<cancel[0].start()<text.index(returned_cancel)<settled[0].start()<openings[1] and
                    int(cancel[0][1])==int(settled[0][1])==int(world[0][1]) and
                    int(cancel[0][2])==int(settled[0][2])>=int(world[0][2]) and
                    int(settled[0][3])>=int(settled[0][2])+3 and int(settled[0][3])<replay['input_action_messages'],
                    'Cancel did not preserve an advancing replay before original reopen/Confirm')
    nody_receivers = [r for r in signal['binding_inventory']['inventory']['button_stream']['receivers'] if 'nody' in r]
    nody = nody_inventory(text, phase='healthy-replay') if len(nody_receivers) == 1 else None
    require('Practice requested:' not in text and 'NATIVE REPLAY playback armed:' not in text,
            'menu control used a practice match or developer replay batch')
    return dict(original_file_load_and_internal_play=True, original_in_game_owner=True, original_runner_update=True,
                frames=int(loaded[0][1]), game_data_sha256=loaded[0][2],
                presented_frame=int(world[0][2]), world=int(world[0][1]),
                original_exit_api=not button_exit, returned_to_menu=True, world_idle_after_exit=True,
                signal_inventory=signal, nody_listener_count=len(nody_receivers), nody_inventory=nody,
                button_clicks=cycles if button_exit else 0, helper_ticks=0, helper_fsm_writes=0,
                user_exposed_disk_selection_qualified=False, bound_button_exit_qualified=button_exit,
                original_options_opened=button_exit,visible_button=visible,physical_ui_input_qualified=False,
                confirmation_cancel_qualified=cancel_first,invalid_deflate_refusal_qualified=invalid_first,
                semantic_refusal_cases=['empty-replay','missing-game-config'] if semantic_first else [],
                partial_initialization_replacement_qualified=partial_first,
                malformed_recovery_qualified=False)
