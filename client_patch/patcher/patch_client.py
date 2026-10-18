"""Apply or undo this build's verified offline patches; preserve the original DLL."""
from pathlib import Path
import argparse, hashlib, json, os, struct, uuid
from .pe_imports import extend_imports_with_thunks, pe_checksum
from . import telemetry
ROOT = Path(__file__).resolve().parents[2]
ORIGINAL_SHA256 = 'e59d08c01479b27404778048d7e13546dbf3771f6b3912744c7c2bdf80c4e758'
PATCHES = [
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
def digest(b): return hashlib.sha256(b).hexdigest()
def build_patch(original, *, include_telemetry=True, community=False):
    """Pure transformation; only a matching original may enter this routine."""
    if digest(original) != ORIGINAL_SHA256:
        raise ValueError('Original build SHA256 does not match.')
    patched = bytearray(telemetry.patch_component('GameAssembly.dll', original) if include_telemetry else original)
    call_hooks = CALL_HOOKS + (COMMUNITY_CALL_HOOKS if community else [])
    tail_hooks = TAIL_HOOKS + (COMMUNITY_TAIL_HOOKS if community else [])
    # Reject a future telemetry recipe that touches an existing startup hook.
    for site in PATCHES + HOOKS + tail_hooks + call_hooks:
        offset, size = site['offset'], len(bytes.fromhex(site['before']))
        if patched[offset:offset + size] != original[offset:offset + size]:
            raise ValueError('Telemetry/startup patch overlap: ' + site['name'])
    for p in PATCHES:
        before, after = bytes.fromhex(p['before']), bytes.fromhex(p['after'])
        o=p['offset']
        if len(before)!=len(after) or original[o:o+len(before)]!=before:
            raise SystemExit('Original bytes mismatch: '+p['name'])
        patched[o:o+len(after)]=after
    patched, iat, thunks = extend_imports_with_thunks(
        bytes(patched), 'BattleAcesOffline.dll',
        list(dict.fromkeys(h['name'] for h in HOOKS + tail_hooks + call_hooks)),
        thunk_exports=list(dict.fromkeys(h['name'] for h in tail_hooks + call_hooks)))
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


def install(game_dir, *, helper=None, original_path=None, restore=False, dry_run=False, community=False):
    game_dir = Path(game_dir).resolve()
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
        patched = build_patch(original, community=community) if name == 'GameAssembly.dll' else update_checksum(telemetry.patch_component(name, original))
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
                'patches': PATCHES, 'hooks': HOOKS, 'tail_hooks': TAIL_HOOKS + (COMMUNITY_TAIL_HOOKS if community else []),
                'call_hooks': CALL_HOOKS + (COMMUNITY_CALL_HOOKS if community else []),
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
    args = parser.parse_args()
    result = install(args.game_dir, helper=args.helper, original_path=args.original,
                     restore=args.restore, dry_run=args.dry_run, community=args.community_experimental)
    print(json.dumps(result, indent=2))


if __name__ == '__main__':
    main()
