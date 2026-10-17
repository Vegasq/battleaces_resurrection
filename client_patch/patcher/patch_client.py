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
    {'name': 'Skip Steam restart and initialization in SubsystemRegistration',
     'offset': 0x3dfa9d7, 'before': '488b0d2272d102', 'after': 'e9880300009090'},
    {'name': 'Start initial state after assets load, without intro UI input',
     'offset': 0x3dfd963, 'before': '488d542470488b0d617ccf02e80cdeffff',
     'after': '4c89e931d2e863dbffff90909090909090'},
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
    {'name': 'OfflineConsumeCreateRequest', 'rva': 0x3e4a00f,
     'offset': 0x3e4860f, 'before': 'e97c3f72fe'},
]
CALL_HOOKS = [
    {'name': 'OfflineAuditReadSimFrame', 'rva': 0x3e61faf, 'offset': 0x3e605af, 'before': 'e8dc600000'},
    {'name': 'OfflineAuditReadSimFrame', 'rva': 0x3e62160, 'offset': 0x3e60760, 'before': 'e82b5f0000'},
]
def digest(b): return hashlib.sha256(b).hexdigest()
def build_patch(original, *, include_telemetry=True):
    """Pure transformation; only a matching original may enter this routine."""
    if digest(original) != ORIGINAL_SHA256:
        raise ValueError('Original build SHA256 does not match.')
    patched = bytearray(telemetry.patch_component('GameAssembly.dll', original) if include_telemetry else original)
    # Reject a future telemetry recipe that touches an existing startup hook.
    for site in PATCHES + HOOKS + TAIL_HOOKS + CALL_HOOKS:
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
        list(dict.fromkeys(h['name'] for h in HOOKS + TAIL_HOOKS + CALL_HOOKS)),
        thunk_exports=list(dict.fromkeys(h['name'] for h in TAIL_HOOKS + CALL_HOOKS)))
    patched=bytearray(patched)
    for hook in HOOKS:
        before=bytes.fromhex(hook['before']);o=hook['offset']
        if original[o:o+len(before)] != before: raise SystemExit('Hook original mismatch: '+hook['name'])
        if len(before)<6: raise SystemExit('Hook site too short: '+hook['name'])
        patched[o:o+len(before)]=b'\xff\x25'+struct.pack('<i',iat[hook['name']]-(hook['rva']+6))+b'\x90'*(len(before)-6)
    for hook in TAIL_HOOKS:
        before=bytes.fromhex(hook['before']);o=hook['offset']
        if len(before)!=5 or original[o:o+5]!=before: raise SystemExit('Tail original mismatch: '+hook['name'])
        patched[o:o+5]=b'\xe9'+struct.pack('<i',thunks[hook['name']]-(hook['rva']+5))
    for hook in CALL_HOOKS:
        before=bytes.fromhex(hook['before']);o=hook['offset']
        if len(before)!=5 or original[o:o+5]!=before: raise SystemExit('Call original mismatch: '+hook['name'])
        patched[o:o+5]=b'\xe8'+struct.pack('<i',thunks[hook['name']]-(hook['rva']+5))
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


def install(game_dir, *, helper=None, original_path=None, restore=False, dry_run=False):
    game_dir = Path(game_dir).resolve()
    if game_dir.name.lower() == 'battleacesbeta_untouched':
        raise ValueError('The untouched recovery copy is read-only; choose a working game copy.')
    state_dir = game_dir / '.battleaces-resurrection'
    manifest_path = state_dir / 'patch-manifest.json'
    previous = json.loads(manifest_path.read_text()) if manifest_path.exists() else None
    components, replacements, originals = {}, {}, {}
    # Validate every input and backup before changing any installed file.
    for name, recipe in telemetry.COMPONENTS.items():
        target, backup = game_dir / name, state_dir / 'original' / name
        source = backup if backup.exists() else Path(original_path) if name == 'GameAssembly.dll' and original_path else target
        current, original = target.read_bytes(), source.read_bytes()
        if digest(original) != recipe.original_sha256:
            raise ValueError('Original build SHA256 does not match: ' + name)
        patched = build_patch(original) if name == 'GameAssembly.dll' else update_checksum(telemetry.patch_component(name, original))
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
    helper_path = game_dir / 'BattleAcesOffline.dll'
    helper_bytes = None if restore else Path(helper or ROOT / 'build/helper/BattleAcesOffline.dll').read_bytes()
    if helper_bytes is not None and not helper_bytes.startswith(b'MZ'):
        raise ValueError('Helper is not a PE DLL; build client_patch first.')
    manifest = {'schema': 2, 'game_build': 37822, 'patch_version': '0.2.0-dev',
                'original_sha256': ORIGINAL_SHA256, 'patched_sha256': components['GameAssembly.dll']['patched_sha256'],
                'helper_sha256': digest(helper_bytes) if helper_bytes is not None else None,
                'patches': PATCHES, 'hooks': HOOKS, 'tail_hooks': TAIL_HOOKS, 'call_hooks': CALL_HOOKS,
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
    args = parser.parse_args()
    result = install(args.game_dir, helper=args.helper, original_path=args.original,
                     restore=args.restore, dry_run=args.dry_run)
    print(json.dumps(result, indent=2))


if __name__ == '__main__':
    main()
