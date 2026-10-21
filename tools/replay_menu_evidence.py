"""Original menu-to-replay API control; never equate API cleanup with a UI click."""
import re

from tools.replay_binding_evidence import require
from tools.replay_signal_evidence import validate as signal_inventory
from tools.replay_nody_evidence import validate as nody_inventory

COMPLETE = ('NATIVE REPLAY MENU API control passed: mainMenu=1 worldIdle=1 originalExitApi=1 '
            'probeRootsReleased=1 filePinReleased=1 buttonClicks=0 fsmWrites=0 helperTicks=0 '
            'BA_RESURRECTION_REPLAY_MENU_V1')


def validate(text, replay):
    require('Native replay menu control failed:' not in text, 'native menu/replay API control failed')
    require(text.count('Original replay runner update restored: primaryIntegration=1 originalPredicate=1 helperTicks=0') == 1 and
            'Original replay runner update failed:' not in text, 'original production replay pump was not observed')
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
    markers = [load[0], 'NATIVE REPLAY MENU loaded:', 'REPLAY BINDING inventory:', exit_api, returned, COMPLETE]
    positions = [text.find(marker) for marker in markers]
    require(all(text.count(marker) == 1 for marker in markers) and positions == sorted(positions) and
            positions[1] < world[0].start() < positions[3], 'replay load/observation/API exit/menu order differs')
    signal = signal_inventory(text, phase='healthy-replay')
    nody_receivers = [r for r in signal['binding_inventory']['inventory']['button_stream']['receivers'] if 'nody' in r]
    nody = nody_inventory(text, phase='healthy-replay') if len(nody_receivers) == 1 else None
    require('Practice requested:' not in text and 'NATIVE REPLAY playback armed:' not in text,
            'menu control used a practice match or developer replay batch')
    return dict(original_file_load_and_internal_play=True, original_in_game_owner=True, original_runner_update=True,
                frames=int(loaded[0][1]), game_data_sha256=loaded[0][2],
                presented_frame=int(world[0][2]), world=int(world[0][1]),
                original_exit_api=True, returned_to_menu=True, world_idle_after_exit=True,
                signal_inventory=signal, nody_listener_count=len(nody_receivers), nody_inventory=nody,
                button_clicks=0, helper_ticks=0, helper_fsm_writes=0,
                user_exposed_disk_selection_qualified=False, bound_button_exit_qualified=False,
                malformed_recovery_qualified=False)
