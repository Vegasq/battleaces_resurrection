"""Apply or undo this build's verified offline patches; preserve the original DLL."""
from pathlib import Path
import argparse, hashlib, json, os, struct, uuid
from .pe_imports import extend_imports_with_thunks, pe_checksum
from . import telemetry
from . import startup_tasks
ROOT = Path(__file__).resolve().parents[2]
ORIGINAL_SHA256 = 'e59d08c01479b27404778048d7e13546dbf3771f6b3912744c7c2bdf80c4e758'
PATCHES = [
    # Entire original file-sync framework is local-only. This pure policy query
    # covers reference/fully-shared generic readers/writers and quota caller;
    # retain original functional objects, serialization and local bookkeeping.
    {'name': 'Original Steam file-sync policy local-only; preserve native backup operations',
     'offset': 0x3e91120, 'before': '4883ec28803df077fc0200754b488d0d', 'after': '31c0c390909090909090909090909090'},
    {'name': 'Tutorial proceeds after local setup without waiting for a backend channel',
     'offset': 0x3def547, 'before': 'e8d41952ff', 'after': '0f57c09090'},
    {'name': 'Front connection requirements false for this method only',
     'offset': 0x6d41cf0, 'before': '50156e8001000000', 'after': '80bf6e8001000000'},
    # Per-method codegen pointer for GameServerIntegration's virtual slot9.
    # Keep the shared true/false getters intact. Local AI and the replacement
    # transport do not need an original game-service gRPC channel.
    {'name': 'Game service connection requirements false for this method only',
     'offset': 0x6d42508, 'before': '50156e8001000000', 'after': '80bf6e8001000000'},
    {'name': 'Skip Steam restart and initialization in SubsystemRegistration',
     'offset': 0x3dfa9d7, 'before': '488b0d2272d102', 'after': 'e9880300009090'},
    # The paired startup call hook retains StopInitializationRecording. Pass
    # this exact Start coroutine's RGameInit owner as the helper's fourth arg;
    # the wrapper supplies the original null MethodInfo to the original call.
    {'name': 'Pass initialized startup owner to timing and intro completion hook',
     'offset': 0x3dfd95b, 'before': '4533c9', 'after': '4d89e9'},
    # The scoped Apply wrapper needs the invoking VM because native models may
    # be shared by multiple rows. Recover original MethodInfo from its vtable.
    {'name': 'Pass exact settings row to scoped difficulty selection hook',
     'offset': 0x3d17b0d, 'before': '4d8b8110020000', 'after': '4989d890909090'},
]
HOOKS = [
    {'name': 'OfflineDedicatedLeaveQueue', 'rva': 0x3e3e760, 'offset': 0x3e3cd60, 'before': '48895c2408574883ec20'},
    {'name': 'OfflineDedicatedJoinQueue', 'rva': 0x3e3c0d0, 'offset': 0x3e3a6d0, 'before': '48895c240848896c2410'},
    {'name': 'OfflineDedicatedSaveSelectedDeck', 'rva': 0x3e2e040, 'offset': 0x3e2c640, 'before': '4053554883ec38'},
    {'name': 'OfflineInitialUpdate', 'rva': 0x3dec5a0, 'offset': 0x3deaba0, 'before': '40534881eca0'},
    {'name': 'OfflineFrontUpdate', 'rva': 0x3e38240, 'offset': 0x3e36840, 'before': '40534883ec20'},
    {'name': 'OfflineBootstrapGameUpdate', 'rva': 0x3e4e020, 'offset': 0x3e4c620, 'before': '48895c240857'},
    {'name': 'OfflineEnqueueCommand', 'rva': 0x3e53530, 'offset': 0x3e51b30, 'before': '48895c240857'},
    {'name': 'OfflineEnqueueAction', 'rva': 0x3e53620, 'offset': 0x3e51c20, 'before': '48895c240857'},
    {'name': 'OfflineCreateGame', 'rva': 0x3e3bf00, 'offset': 0x3e3a500, 'before': '48895c240848896c2410'},
    {'name': 'OfflineSignalReadyToPlay', 'rva': 0x3e53d70, 'offset': 0x3e52370, 'before': '40574883ec20'},
]
TAIL_HOOKS = [
    # Restore this offline settings row's local presentation before native release.
    {'name': 'OfflinePracticeSettingsRelease', 'rva': 0x2273fcf,
     'offset': 0x22725cf, 'before': 'e97c5aaf01'},
    {'name': 'OfflineConsumeCreateRequest', 'rva': 0x3e4a00f,
     'offset': 0x3e4860f, 'before': 'e97c3f72fe'},
    {'name': 'OfflineDedicatedRetryLogin', 'rva': 0x3d06ffd,
     'offset': 0x3d055fd, 'before': 'e92e6a86fe'},
]
CALL_HOOKS = [
    # Concrete Tailored reference initializer; keep original read/JSON semantics.
    {'name': 'OfflineBackupInitialRead', 'rva': 0x26302be, 'offset': 0x262e8be, 'before': 'e83d0c0000'},
    # Both reviewed generic local writers serialize JSON before these calls.
    {'name': 'OfflineBackupWriteText', 'rva': 0x2631631, 'offset': 0x262fc31, 'before': 'e86a6cf100'},
    {'name': 'OfflineBackupWriteText', 'rva': 0x263362b, 'offset': 0x2631c2b, 'before': 'e8704cf100'},
    {'name': 'OfflineBackupStoragePath', 'rva': 0x3e92e22, 'offset': 0x3e91422, 'before': 'e869b26cff'},
    {'name': 'OfflineReplayStoragePath', 'rva': 0x3ddde36, 'offset': 0x3ddc436, 'before': 'e8f5a45aff'},
    {'name': 'OfflineReplayStoragePath', 'rva': 0x3ddde99, 'offset': 0x3ddc499, 'before': 'e892a45aff'},
    {'name': 'OfflineCleanupAutoSaveReplay', 'rva': 0x3e51d94, 'offset': 0x3e50394, 'before': 'e8d7e0ffff'},
    # All other confirmed direct callers, including HandleApplicationQuit.
    # Shutdown must share the nonfatal managed boundary.
    {'name': 'OfflineCleanupAutoSaveReplay', 'rva': 0x3e4dfe9, 'offset': 0x3e4c5e9, 'before': 'e8821e0000'},
    {'name': 'OfflineCleanupAutoSaveReplay', 'rva': 0x3e50db6, 'offset': 0x3e4f3b6, 'before': 'e8b5f0ffff'},
    {'name': 'OfflineCleanupAutoSaveReplay', 'rva': 0x3e57bbf, 'offset': 0x3e561bf, 'before': 'e8ac82ffff'},
    # Construct the native local-user TOML path before its first load/save.
    {'name': 'OfflineLocalUserConfigPath', 'rva': 0x379a38e, 'offset': 0x379898e, 'before': 'e89ddfbeff'},
    # Observe original results; do not replace TOML parsing/serialization.
    {'name': 'OfflineLocalUserLoadTable', 'rva': 0x379650c, 'offset': 0x3794b0c, 'before': 'e86f1a0000'},
    {'name': 'OfflineLocalUserSaveTable', 'rva': 0x3796a84, 'offset': 0x3795084, 'before': 'e8d7f5ffff'},
    {'name': 'OfflineLocalDeckStorageLoad', 'rva': 0x3de76a2, 'offset': 0x3de5ca2, 'before': 'e8094dfcff'},
    # Keep native Continue/navigation; public results have no service rewards.
    {'name': 'OfflineMatchResultContinue', 'rva': 0x3d61142, 'offset': 0x3d5f742, 'before': 'e8092949fd'},
    {'name': 'OfflineStartupReady', 'rva': 0x3dff36f, 'offset': 0x3dfd96f, 'before': 'e80cdeffff'},
    # Scoped enum settings presentation/actions. All other rows/modes forward.
    {'name': 'OfflinePracticeSettingsModel', 'rva': 0x3d19579, 'offset': 0x3d17b79, 'before': 'e852fdc9fe'},
    {'name': 'OfflinePracticeSettingsModel', 'rva': 0x3d1960b, 'offset': 0x3d17c0b, 'before': 'e8c0fcc9fe'},
    {'name': 'OfflinePracticeSettingsApply', 'rva': 0x3d19514, 'offset': 0x3d17b14, 'before': '41ff9108020000'},
    {'name': 'OfflinePracticeSettingsOptions', 'rva': 0x3c922f2, 'offset': 0x3c908f2, 'before': 'e849000000'},
    # AI entering-game coroutine only; all non-practice calls retain original JoinGame.
    {'name': 'OfflinePracticeAIJoin', 'rva': 0x37bdaee, 'offset': 0x37bc0ee, 'before': 'e84d5e6900'},
    {'name': 'OfflineAuditReadSimFrame', 'rva': 0x3e61faf, 'offset': 0x3e605af, 'before': 'e8dc600000'},
    {'name': 'OfflineAuditReadSimFrame', 'rva': 0x3e62160, 'offset': 0x3e60760, 'before': 'e82b5f0000'},
]
QUIT_CALL_HOOKS = [
    {'name': 'OfflineNativeQuitDispose', 'rva': 0x3de4968, 'offset': 0x3de2f68, 'before': 'e8c3e0ffff'},
    {'name': 'OfflineNativeQuitAIDispose', 'rva': 0x3de4a0f, 'offset': 0x3de300f, 'before': 'e89c39dbff'},
]
QUIT_POINTER_HOOKS = [
    {'name': 'OfflineNativeQuitOnDestroy', 'rva': 0x6d41a18, 'offset': 0x6d3f018,
     'before': '2048de8301000000', 'target_rva': 0x3de4820,
     'relocation_block_offset': 0x736cf50, 'relocation_block_before': '0010d40600040000',
     'relocation_entry_offset': 0x736d1d6, 'relocation_entry_before': '18aa'},
]
DLSS_PRIVACY_PATCHES = [
    {'name': 'Report optional DLSS unavailable before NGX telemetry initialization; preserve original renderer fallback and shutdown',
     'offset': 0x4b281e0, 'before': '40534883ec50', 'after': '31c0c3909090'},
]
COMMUNITY_CALL_HOOKS = [
    {'name': 'OfflineCommunityJoinGame', 'rva': 0x3e405e3, 'offset': 0x3e3ebe3, 'before': 'e858330100'},
    # Exact request enqueue callers; the shared generic entry remains original.
    # Experimental native lobby/invitation UI; not the normal-play recipe.
    {'name': 'OfflineCommunityEnqueue', 'rva': 0x3e46f3e, 'offset': 0x3e4553e, 'before': 'e84d7072fe'},
    {'name': 'OfflineCommunityEnqueue', 'rva': 0x3e472ce, 'offset': 0x3e458ce, 'before': 'e8bd6c72fe'},
    {'name': 'OfflineCommunityEnqueue', 'rva': 0x3e474e6, 'offset': 0x3e45ae6, 'before': 'e8a56a72fe'},
    {'name': 'OfflineCommunityForceFriends', 'rva': 0x3ca93b9, 'offset': 0x3ca79b9, 'before': 'e8e2a41c00'},
    {'name': 'OfflineCommunityFriendPresentation', 'rva': 0x3ca89eb, 'offset': 0x3ca6feb, 'before': '41ff9138020000'},
    {'name': 'OfflineCommunityInviteReason', 'rva': 0x3ca8e21, 'offset': 0x3ca7421, 'before': 'e89af5ffff'},
    {'name': 'OfflineCommunityCanInvite', 'rva': 0x3ca8e9d, 'offset': 0x3ca749d, 'before': 'e82ed858fc'},
    {'name': 'OfflineCommunityEnqueue', 'rva': 0x3cac066, 'offset': 0x3caa666, 'before': 'e8251f8cfe'},
    {'name': 'OfflineCommunityEnqueue', 'rva': 0x3e46968, 'offset': 0x3e44f68, 'before': 'e8237672fe'},
    {'name': 'OfflineCommunityEnqueue', 'rva': 0x3d24dad, 'offset': 0x3d233ad, 'before': 'e8de9184fe'},
    {'name': 'OfflineCommunityPopupLookup', 'rva': 0x3d25a10, 'offset': 0x3d24010, 'before': 'e81b977cfc'},
    {'name': 'OfflineCommunityPopupChild', 'rva': 0x3d25a38, 'offset': 0x3d24038, 'before': 'ff9038020000'},
    {'name': 'OfflineCommunityPopupChild', 'rva': 0x3d25a5d, 'offset': 0x3d2405d, 'before': 'ff9038020000'},
    {'name': 'OfflineCommunityPopupRefreshed', 'rva': 0x3d25b67, 'offset': 0x3d24167, 'before': 'e8140c51fc'},
    {'name': 'OfflineCommunityPopupRelease', 'rva': 0x3d59831, 'offset': 0x3d57e31, 'before': 'e8caa52bfc'},
    {'name': 'OfflineCommunityPopupRelease', 'rva': 0x3d5920c, 'offset': 0x3d5780c, 'before': 'e8efab2bfc'},
]
COMMUNITY_TAIL_HOOKS = [
    {'name': 'OfflineCommunityPopulate', 'rva': 0x3ca95cd, 'offset': 0x3ca7bcd, 'before': 'e95e050000'},
    {'name': 'OfflineCommunityPopulate', 'rva': 0x3ca983a, 'offset': 0x3ca7e3a, 'before': 'e9f1020000'},
    {'name': 'OfflineCommunityPopulate', 'rva': 0x3ca989f, 'offset': 0x3ca7e9f, 'before': 'e98c020000'},
    {'name': 'OfflineCommunityRosterRelease', 'rva': 0x3ca97f9, 'offset': 0x3ca7df9, 'before': 'e952020c00'},
    {'name': 'OfflineCommunityEnqueue', 'rva': 0x3e46b1d, 'offset': 0x3e4511d, 'before': 'e96e7472fe'},
]
COSMETIC_PATCHES = [
    {'name': 'Pass owning Front to scoped cosmetic presence hook', 'offset': 0x3e3d38f,
     'before': '4533c0', 'after': '4989f0'},
]
COSMETIC_CALL_HOOKS = [
    {'name': 'OfflineCosmeticVisibilityIndex', 'rva': 0x3ca50cc, 'offset': 0x3ca36cc, 'before': 'e80fe6fefe'},
    {'name': 'OfflineCosmeticOwned', 'rva': 0x3ca48d8, 'offset': 0x3ca2ed8, 'before': 'e843201e00'},
    {'name': 'OfflineCosmeticOwned', 'rva': 0x3ca5eb8, 'offset': 0x3ca44b8, 'before': 'e8630a1e00'},
    {'name': 'OfflineCosmeticOwned', 'rva': 0x3ca5d90, 'offset': 0x3ca4390, 'before': 'e88b0b1e00'},
    {'name': 'OfflineCosmeticOwned', 'rva': 0x3cbf80a, 'offset': 0x3cbde0a, 'before': 'e811711c00'},
    {'name': 'OfflineCosmeticOwned', 'rva': 0x3cc1f0d, 'offset': 0x3cc050d, 'before': 'e80e4a1c00'},
    {'name': 'OfflineCosmeticItemCache', 'rva': 0x3ca5166, 'offset': 0x3ca3766, 'before': 'e82546ecff'},
    {'name': 'OfflineCosmeticSaveDeckDeferred', 'rva': 0x3e3ec8b, 'offset': 0x3e3d28b, 'before': 'e8b0f3feff'},
    {'name': 'OfflineCosmeticPresence', 'rva': 0x3e3ed96, 'offset': 0x3e3d396, 'before': 'e835150500'},
]
COSMETIC_TAIL_HOOKS = [
    {'name': 'OfflineCosmeticOwned', 'rva': 0x3ca5dc8, 'offset': 0x3ca43c8, 'before': 'e9530b1e00'},
    {'name': 'OfflineCosmeticItemCache', 'rva': 0x3b69785, 'offset': 0x3b67d85, 'before': 'e906000000'},
    {'name': 'OfflineCosmeticSaveRequest', 'rva': 0x3e40f1d, 'offset': 0x3e3f51d, 'before': 'e96ed072fe'},
]
def digest(b): return hashlib.sha256(b).hexdigest()


def redirect_relocated_pointer(original, patched, hook, image_base, thunk_rva):
    """Rewrite one pinned method slot, retaining its original DIR64 relocation."""
    offset, block, entry = hook['offset'], hook['relocation_block_offset'], hook['relocation_entry_offset']
    before = bytes.fromhex(hook['before'])
    if len(before)!=8 or original[offset:offset+8]!=before or int.from_bytes(before,'little')!=image_base+hook['target_rva']:
        raise ValueError('Pointer original mismatch: '+hook['name'])
    for at, expected in ((block,hook['relocation_block_before']),(entry,hook['relocation_entry_before'])):
        expected = bytes.fromhex(expected)
        if original[at:at+len(expected)]!=expected or patched[at:at+len(expected)]!=expected:
            raise ValueError('Pointer relocation bytes mismatch: '+hook['name'])
    page, size = struct.unpack_from('<II',original,block)
    relocation = struct.unpack_from('<H',original,entry)[0]
    if not (size>=8 and size%2==0 and block+8<=entry<block+size and
            (entry-block)%2==0 and relocation>>12==10 and page+(relocation&0xfff)==hook['rva']):
        raise ValueError('Pointer DIR64 relocation mismatch: '+hook['name'])
    struct.pack_into('<Q',patched,offset,image_base+thunk_rva)


def build_patch(original, *, include_telemetry=True, community=False, cosmetics=False, quit_diagnostics=False, allow_dlss_diagnostics=False, startup_diagnostics=False):
    """Pure transformation; only a matching original may enter this routine."""
    if digest(original) != ORIGINAL_SHA256:
        raise ValueError('Original build SHA256 does not match.')
    patched = bytearray(telemetry.patch_component('GameAssembly.dll', original) if include_telemetry else original)
    patches = PATCHES + (COSMETIC_PATCHES if cosmetics else []) + ([] if allow_dlss_diagnostics else DLSS_PRIVACY_PATCHES)
    call_hooks = CALL_HOOKS + (COMMUNITY_CALL_HOOKS if community else []) + (COSMETIC_CALL_HOOKS if cosmetics else []) + (QUIT_CALL_HOOKS if quit_diagnostics else [])
    tail_hooks = TAIL_HOOKS + (COMMUNITY_TAIL_HOOKS if community else []) + (COSMETIC_TAIL_HOOKS if cosmetics else [])
    pointer_hooks = QUIT_POINTER_HOOKS if quit_diagnostics else []
    if startup_diagnostics:
        call_hooks += startup_tasks.CALL_HOOKS
        tail_hooks += startup_tasks.TAIL_HOOKS
    sites = sorted(patches + HOOKS + tail_hooks + call_hooks + pointer_hooks, key=lambda site: site['offset'])
    for left, right in zip(sites, sites[1:]):
        if left['offset'] + len(bytes.fromhex(left['before'])) > right['offset']:
            raise ValueError('Patch site overlap: ' + left['name'] + '/' + right['name'])
    # Reject a future telemetry recipe that touches an existing startup hook.
    for site in patches + HOOKS + tail_hooks + call_hooks + pointer_hooks:
        offset, size = site['offset'], len(bytes.fromhex(site['before']))
        if patched[offset:offset + size] != original[offset:offset + size]:
            raise ValueError('Telemetry/startup patch overlap: ' + site['name'])
    for p in patches:
        before, after = bytes.fromhex(p['before']), bytes.fromhex(p['after'])
        o=p['offset']
        if len(before)!=len(after) or original[o:o+len(before)]!=before:
            raise SystemExit('Original bytes mismatch: '+p['name'])
        patched[o:o+len(after)]=after
    patched, iat, thunks = extend_imports_with_thunks(
        bytes(patched), 'BattleAcesOffline.dll',
        list(dict.fromkeys(h['name'] for h in HOOKS + tail_hooks + call_hooks + pointer_hooks)),
        thunk_exports=list(dict.fromkeys(h['name'] for h in tail_hooks + call_hooks + pointer_hooks)))
    patched=bytearray(patched)
    for hook in HOOKS:
        before=bytes.fromhex(hook['before']);o=hook['offset']
        if original[o:o+len(before)] != before: raise SystemExit('Hook original mismatch: '+hook['name'])
        if len(before)<6: raise SystemExit('Hook site too short: '+hook['name'])
        patched[o:o+len(before)]=b'\xff\x25'+struct.pack('<i',iat[hook['name']]-(hook['rva']+6))+b'\x90'*(len(before)-6)
    for hook in tail_hooks:
        before=bytes.fromhex(hook['before']);o=hook['offset']
        if len(before)!=5 or original[o:o+5]!=before: raise SystemExit('Tail original mismatch: '+hook['name'])
        patched[o:o+5]=b'\xe9'+struct.pack('<i',thunks[hook['name']]-(hook['rva']+5))
    for hook in call_hooks:
        before=bytes.fromhex(hook['before']);o=hook['offset']
        if len(before)<5 or original[o:o+len(before)]!=before: raise SystemExit('Call original mismatch: '+hook['name'])
        patched[o:o+len(before)]=b'\xe8'+struct.pack('<i',thunks[hook['name']]-(hook['rva']+5))+b'\x90'*(len(before)-5)
    if pointer_hooks:
        pe = struct.unpack_from('<I',original,60)[0]
        image_base = struct.unpack_from('<Q',original,pe+24+24)[0]
        for hook in pointer_hooks:
            redirect_relocated_pointer(original,patched,hook,image_base,thunks[hook['name']])
    return update_checksum(patched)


def update_checksum(data):
    patched = bytearray(data)
    checksum_offset = struct.unpack_from('<I', patched, 60)[0] + 24 + 64
    struct.pack_into('<I', patched, checksum_offset, pe_checksum(patched, checksum_offset))
    return bytes(patched)


def atomic_write(path, data):
    temporary = path.with_name(path.name + '.' + uuid.uuid4().hex + '.tmp')
    try:
        with temporary.open('xb') as stream:
            stream.write(data)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)
    finally:
        temporary.unlink(missing_ok=True)


def contained_path(game_dir, relative):
    """Keep component, backup and state writes inside the selected installation."""
    relative = Path(relative)
    if relative.anchor or not relative.parts or '..' in relative.parts:
        raise ValueError('Patch paths must be relative children of the game directory.')
    resolved = (game_dir / relative).resolve()
    if resolved == game_dir or not resolved.is_relative_to(game_dir):
        raise ValueError('Patch path resolves outside the selected game directory.')
    return resolved


def install(game_dir, *, helper=None, original_path=None, restore=False, dry_run=False, community=False, cosmetics=False, quit_diagnostics=False, allow_dlss_diagnostics=False, startup_diagnostics=False):
    game_dir = Path(game_dir).resolve()
    if (quit_diagnostics or allow_dlss_diagnostics or startup_diagnostics) and not game_dir.is_relative_to(ROOT/'local'):
        raise ValueError('Native diagnostics require an owned ignored local test installation.')
    if game_dir.name.lower() == 'battleacesbeta_untouched':
        raise ValueError('The untouched recovery copy is read-only; choose a working game copy.')
    state_dir = contained_path(game_dir, '.battleaces-resurrection')
    manifest_path = contained_path(game_dir, '.battleaces-resurrection/patch-manifest.json')
    previous = json.loads(manifest_path.read_text()) if manifest_path.exists() else None
    components, replacements, originals = {}, {}, {}
    # Validate every input and backup before changing any installed file.
    for name, recipe in telemetry.COMPONENTS.items():
        target = contained_path(game_dir, name)
        backup = contained_path(game_dir, Path('.battleaces-resurrection/original') / name)
        if target.is_relative_to(state_dir) or not backup.is_relative_to(state_dir):
            raise ValueError('Installed components and original backups must be separate.')
        source = backup if backup.exists() else Path(original_path) if name == 'GameAssembly.dll' and original_path else target
        current, original = target.read_bytes(), source.read_bytes()
        if digest(original) != recipe.original_sha256:
            raise ValueError('Original build SHA256 does not match: ' + name)
        patched = build_patch(original, community=community, cosmetics=cosmetics, quit_diagnostics=quit_diagnostics,
                              allow_dlss_diagnostics=allow_dlss_diagnostics, startup_diagnostics=startup_diagnostics) if name == 'GameAssembly.dll' else update_checksum(telemetry.patch_component(name, original))
        known = {recipe.original_sha256, digest(patched)}
        if name == 'GameAssembly.dll':
            known.add(digest(build_patch(original, include_telemetry=False)))
        if previous:
            old = previous.get('components', {}).get(name)
            if old and old.get('original_sha256') == recipe.original_sha256:
                known.add(old['patched_sha256'])
            if name == 'GameAssembly.dll' and previous.get('original_sha256') == ORIGINAL_SHA256:
                known.add(previous['patched_sha256'])
        if digest(current) not in known:
            raise ValueError('Refusing to overwrite unexpected DLL changes: ' + name)
        originals[backup] = original
        replacements[target] = (current, original if restore else patched)
        components[name] = {'original_sha256': recipe.original_sha256, 'patched_sha256': digest(patched),
                            'installed_sha256': digest(original if restore else patched),
                            'telemetry_guards': len(recipe.patches)}
    helper_path = contained_path(game_dir, 'BattleAcesOffline.dll')
    helper_bytes = None if restore else Path(helper or ROOT / 'build/helper/BattleAcesOffline.dll').read_bytes()
    if helper_bytes is not None and not helper_bytes.startswith(b'MZ'):
        raise ValueError('Helper is not a PE DLL; build client_patch first.')
    if helper_bytes is not None and b'BA_RESURRECTION_RECOVERY_V1' not in helper_bytes:
        raise ValueError('Build the current helper supporting recovery ABI1 before installing this patch.')
    if helper_bytes is not None and b'OfflineMatchResultContinue\0' not in helper_bytes:
        raise ValueError('Build the current helper with the public result Continue hook before installing this patch.')
    if helper_bytes is not None and (b'BA_RESURRECTION_NATIVE_SETTINGS_V1' not in helper_bytes or b'OfflineLocalUserConfigPath\0' not in helper_bytes):
        raise ValueError('Build the current helper with native local-user settings isolation before installing this patch.')
    if helper_bytes is not None and any(marker not in helper_bytes for marker in
            (b'BA_RESURRECTION_NATIVE_SETTINGS_ERRORS_V1', b'OfflineLocalUserLoadTable\0', b'OfflineLocalUserSaveTable\0')):
        raise ValueError('Build the current helper with native local-user settings error hooks before installing this patch.')
    if helper_bytes is not None and any(marker not in helper_bytes for marker in
            (b'BA_RESURRECTION_NATIVE_DECK_INPUT_V1',b'OfflineLocalDeckStorageLoad\0')):
        raise ValueError('Build the current helper with native persisted deck validation before installing this patch.')
    if helper_bytes is not None and b'BA_RESURRECTION_NATIVE_SETTINGS_ATOMIC_V1' not in helper_bytes:
        raise ValueError('Build the current helper with native settings write publication before installing this patch.')
    if helper_bytes is not None and any(marker not in helper_bytes for marker in
            (b'BA_RESURRECTION_NATIVE_STORAGE_V1', b'OfflineBackupStoragePath\0',
             b'OfflineReplayStoragePath\0', b'OfflineCleanupAutoSaveReplay\0')):
        raise ValueError('Build the current helper with native replay and backup storage isolation before installing this patch.')
    if helper_bytes is not None and any(marker not in helper_bytes for marker in
            (b'BA_RESURRECTION_NATIVE_BACKUP_GUARD_V1', b'OfflineBackupInitialRead\0', b'OfflineBackupWriteText\0')):
        raise ValueError('Build the current helper with native backup input and publication protection before installing this patch.')
    if helper_bytes is not None and b'BA_RESURRECTION_NATIVE_REPLAY_LONG_PATH_V2' not in helper_bytes:
        raise ValueError('Build the current helper with ordinary extended replay paths before installing this patch.')
    if quit_diagnostics and helper_bytes is not None and any(marker not in helper_bytes for marker in
            (b'BA_RESURRECTION_NATIVE_QUIT_TRACE_V1',) + tuple(h['name'].encode()+b'\0' for h in QUIT_CALL_HOOKS+QUIT_POINTER_HOOKS)):
        raise ValueError('Build the owned native Quit diagnostic helper before installing this recipe.')
    if startup_diagnostics and helper_bytes is not None and any(marker not in helper_bytes for marker in
            (b'BA_RESURRECTION_STARTUP_TASKS_V1',) + tuple(h['name'].encode()+b'\0' for h in startup_tasks.CALL_HOOKS+startup_tasks.TAIL_HOOKS)):
        raise ValueError('Build the owned startup task diagnostic helper before installing this recipe.')
    if cosmetics and helper_bytes is not None and any(hook['name'].encode()+b'\0' not in helper_bytes
            for hook in COSMETIC_CALL_HOOKS + COSMETIC_TAIL_HOOKS):
        raise ValueError('Build the current helper with experimental cosmetic hooks before installing this patch.')
    if community and helper_bytes is not None and b'BA_RESURRECTION_COMMUNITY_V1' not in helper_bytes:
        raise ValueError('Build a helper supporting experimental community ABI1 before installing this patch.')
    if community and helper_bytes is not None and b'BA_RESURRECTION_COMMUNITY_ROSTER_V1' not in helper_bytes:
        raise ValueError('Build a helper supporting experimental community roster ABI1 before installing this patch.')
    if community and helper_bytes is not None and b'BA_RESURRECTION_COMMUNITY_INVITES_V1' not in helper_bytes:
        raise ValueError('Build a helper supporting experimental community invitation ABI1 before installing this patch.')
    if community and helper_bytes is not None and b'BA_RESURRECTION_COMMUNITY_MATCH_V1' not in helper_bytes:
        raise ValueError('Build a helper supporting experimental community match ABI1 before installing this patch.')
    manifest = {'schema': 2, 'game_build': 37822, 'patch_version': '0.2.0-dev',
                'original_sha256': ORIGINAL_SHA256, 'patched_sha256': components['GameAssembly.dll']['patched_sha256'],
                'helper_sha256': digest(helper_bytes) if helper_bytes is not None else None,
                'local_storage': {'isolated': not restore, 'scope': 'installation-and-profile',
                                  'replay_format': 'native-protobuf-deflate', 'backup_format': 'native-json',
                                  'steam_file_sync': 'original-restored' if restore else 'local-only',
                                  'autosave_exception_boundary': not restore, 'autosave_call_sites': 0 if restore else 4,
                                  'backup_input_guard': not restore,
                                  'replay_path_api': 'extended-local-drive' if not restore else None,
                                  'backup_publication': 'original-json-text-flush-handle-rename' if not restore else None},
                'local_settings': {'isolated': not restore, 'scope': 'installation-and-profile', 'format': 'native-toml',
                                   'error_hooks': not restore,
                                   'deck_input_guard': not restore,
                                   'write_publication': 'original-serializer-flush-handle-rename' if not restore else None,
                                   'save_notice': bool(helper_bytes and b'BA_RESURRECTION_NATIVE_SETTINGS_NOTICE_V1' in helper_bytes and not restore)},
                'patches': PATCHES + (COSMETIC_PATCHES if cosmetics else []) + ([] if allow_dlss_diagnostics else DLSS_PRIVACY_PATCHES), 'hooks': HOOKS,
                'tail_hooks': TAIL_HOOKS + (COMMUNITY_TAIL_HOOKS if community else []) + (COSMETIC_TAIL_HOOKS if cosmetics else []) + (startup_tasks.TAIL_HOOKS if startup_diagnostics else []),
                'call_hooks': CALL_HOOKS + (COMMUNITY_CALL_HOOKS if community else []) + (COSMETIC_CALL_HOOKS if cosmetics else []) + (QUIT_CALL_HOOKS if quit_diagnostics else []) + (startup_tasks.CALL_HOOKS if startup_diagnostics else []),
                'diagnostics': {'native_quit': bool(quit_diagnostics and not restore),
                                'startup_tasks': bool(startup_diagnostics and not restore),
                                'dlss_enabled': bool(allow_dlss_diagnostics and not restore)},
                'graphics': {'dlss_setup': 'original-restored' if restore else 'original-owned-diagnostic' if allow_dlss_diagnostics else 'unavailable-before-native-init',
                             'original_shutdown': True},
                'pointer_hooks': QUIT_POINTER_HOOKS if quit_diagnostics else [],
                'cosmetics': {'experimental': cosmetics,
                              'persistence': bool(cosmetics and helper_bytes is not None and b'BA_RESURRECTION_COSMETICS_PERSIST_V1' in helper_bytes),
                              'match_propagation': False},
                'community': {'experimental': community, 'native_scope': 'custom-match-prototype' if community else None},
                'practice': {'standalone': helper_bytes is not None and b'BA_RESURRECTION_OFFLINE_PRACTICE_V1' in helper_bytes,
                             'difficulty_settings': helper_bytes is not None and b'BA_RESURRECTION_PRACTICE_SETTINGS_V1' in helper_bytes},
                'ui': {'match_loading': helper_bytes is not None and b'BA_RESURRECTION_MATCH_LOADING_V1' in helper_bytes},
                'components': components,
                'telemetry': {'recipe_version': telemetry.RECIPE_VERSION, 'runtime_validated': telemetry.RUNTIME_VALIDATED,
                              'unresolved_components': telemetry.UNRESOLVED_COMPONENTS},
                'state': 'restored' if restore else 'dedicated-prototype-v2'}
    if dry_run:
        return manifest
    for backup, original in originals.items():
        backup.parent.mkdir(parents=True, exist_ok=True)
        if not backup.exists():
            atomic_write(backup, original)
    # Every installed file is replaced atomically. Retain prior bytes to roll back
    # if a later replacement fails (e.g. a running game has mapped its DLL).
    changes = {}
    if helper_bytes is not None:
        changes[helper_path] = (helper_path.read_bytes() if helper_path.exists() else None, helper_bytes)
    changes.update(replacements)
    changes[manifest_path] = (manifest_path.read_bytes() if manifest_path.exists() else None,
                              json.dumps(manifest, indent=2).encode())
    written = []
    try:
        for path, (_, content) in changes.items():
            atomic_write(path, content)
            written.append(path)
    except OSError:
        for path in reversed(written):
            prior = changes[path][0]
            if prior is None:
                path.unlink(missing_ok=True)
            else:
                atomic_write(path, prior)
        raise
    return manifest


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--game-dir', type=Path, required=True)
    parser.add_argument('--helper', type=Path)
    parser.add_argument('--original', type=Path, help='verified recovery DLL for an already-patched installation')
    parser.add_argument('--restore', action='store_true')
    parser.add_argument('--dry-run', action='store_true')
    parser.add_argument('--community-experimental', action='store_true', help='isolated experimental native Custom Game/invite/match adapter')
    parser.add_argument('--cosmetics-experimental', action='store_true', help='installed-catalog cosmetic unlock with isolated selection persistence')
    parser.add_argument('--quit-diagnostics', action='store_true', help='owned local-only original disposal trace; no cleanup changes')
    parser.add_argument('--startup-diagnostics', action='store_true', help='owned local-only original startup Task and Unity pump observation; runtime flag also required')
    parser.add_argument('--allow-dlss-diagnostics', action='store_true', help='owned local-only original NGX initialization comparison; ordinary installs report DLSS unavailable')
    args = parser.parse_args()
    result = install(args.game_dir, helper=args.helper, original_path=args.original,
                     restore=args.restore, dry_run=args.dry_run, community=args.community_experimental, cosmetics=args.cosmetics_experimental,
                     quit_diagnostics=args.quit_diagnostics, allow_dlss_diagnostics=args.allow_dlss_diagnostics,
                     startup_diagnostics=args.startup_diagnostics)
    print(json.dumps(result, indent=2))


if __name__ == '__main__':
    main()
