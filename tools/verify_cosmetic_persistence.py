"""Qualify cosmetic callbacks, full-map restart, isolation and retained bad saves.

Uses only a disposable patched game below ignored local/. Every profile key is
fresh and owned by this run. Server/network credentials are absent. The native
startup harness reaps each owned process forcibly; native Quit is not qualified.
Game-derived catalogs, selections, captures and detailed reports stay local.
"""
import argparse
from contextlib import contextmanager
import ctypes
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import secrets
from types import SimpleNamespace

from server.cosmetics import CosmeticCatalog
from tools import verify_unified_startup as startup
from tools.verify_custom_lobby import require

ROOT = Path(__file__).resolve().parents[1]


def encode(value):
    return (json.dumps(value, separators=(',', ':'), ensure_ascii=True)+'\n').encode('ascii')


def sources():
    return startup.source_hashes() | {Path(__file__).relative_to(ROOT).as_posix(): hashlib.sha256(Path(__file__).read_bytes()).hexdigest()}


@contextmanager
def writer_lock(path):
    kernel = ctypes.WinDLL('kernel32', use_last_error=True)
    kernel.CreateFileW.argtypes = (ctypes.c_wchar_p, ctypes.c_ulong, ctypes.c_ulong,
                                  ctypes.c_void_p, ctypes.c_ulong, ctypes.c_ulong, ctypes.c_void_p)
    kernel.CreateFileW.restype = ctypes.c_void_p
    kernel.CloseHandle.argtypes = (ctypes.c_void_p,)
    handle = kernel.CreateFileW(str(path), 0xc0000000, 1, None, 4, 0x80, None)
    require(handle not in (None, ctypes.c_void_p(-1).value), 'cannot hold the owned profile writer lock')
    try: yield
    finally: require(kernel.CloseHandle(handle), 'owned writer lock close failed')


def run(args):
    game, output = args.game.resolve(), args.output.resolve()
    require(os.name == 'nt' and game.is_relative_to(ROOT/'local') and output.is_relative_to(ROOT/'local'),
            'use an ignored disposable Windows game and evidence directory')
    require(60 <= args.timeout <= 300, 'bounded phase timeout required')
    output.mkdir(parents=True, exist_ok=False)
    report = dict(passed=False, utc=datetime.now(timezone.utc).isoformat(), scope=__doc__,
                  source_sha256_at_start=sources(), phases=[], native_quit_qualified=False)
    prefix = 'cosmeticstest_'+secrets.token_hex(6)
    folder = game/'.battleaces-resurrection/profiles'
    a, b = prefix+'_a', prefix+'_b'

    def state_path(key): return folder/(key+'.cosmetics.json')

    def seed(key, raw):
        require(not (folder/(key+'.cosmetics.lock')).exists(), 'test profile lock already exists')
        with state_path(key).open('xb') as stream: stream.write(raw)

    def phase(label, key=None, *, equip=False):
        print('Cosmetic phase: '+label, flush=True)
        startup.run(SimpleNamespace(game=game, output=output/label, timeout=args.timeout, visible=args.visible,
            local_profile=key, cosmetics_export=key is not None, cosmetics_unlock_smoke=False,
            cosmetics_ui_trace=False, cosmetics_picker_smoke=False, cosmetics_equip_smoke=equip,
            cosmetics_persistence_proof=key is not None))
        value = json.loads((output/label/'verification.json').read_bytes())
        require(value['passed'] and value['remote_connections'] == value['invite_reads'] == 0 and
                value['source_files_unchanged'] and value['owned_process_reaped'], 'native phase incomplete')
        require(all(value['ordinary_player_features'].values()),'ordinary startup omitted player features')
        proof = value.get('cosmetics_persistence_proof')
        if proof:
            catalog = CosmeticCatalog.from_bytes((output/label/'player-cosmetics-catalog.json').read_bytes())
            catalog.validate_selection(proof['state']['slots'])
            require(proof['state']['catalog_sha256'] == catalog.sha256, 'runtime state/catalog digest differs')
        report['phases'].append(dict(name=label, game_pid=value['game_pid'], passed=True,
            seconds=value['observed_menu_seconds'], report_sha256=hashlib.sha256((output/label/'verification.json').read_bytes()).hexdigest()))
        return proof

    try:
        require(not state_path(a).exists() and not (folder/(a+'.cosmetics.lock')).exists(), 'test profile already exists')
        first = phase('equip', a, equip=True)
        require(first['writable'] and not first['restored'] and not first['read_error'], 'fresh test profile not writable')
        saved_a = state_path(a).read_bytes()
        require(saved_a == encode(first['state']), 'native atomic file differs from effective full state')
        (output/'profile-a-saved.json').write_bytes(saved_a)
        second = phase('restart-a', a)
        require(second['restored'] and second['writable'] and not second['read_error'] and second['state'] == first['state'],
                'restart did not restore every slot')
        require(state_path(a).read_bytes() == saved_a, 'read-only restart rewrote profile A')

        catalog = CosmeticCatalog.from_bytes((output/'equip/player-cosmetics-catalog.json').read_bytes())
        baseline = dict(catalog.normalize_local({}).slots)
        alternate = baseline.copy()
        # Derive choices from installed compatibility, including non-wire slots.
        # Do not embed an item, slot or asset-name inventory in source.
        used = set(baseline.values())-{0}
        changed = []
        for slot_id in catalog.native_slot_order:
            for item in sorted(catalog.slots[slot_id].compatible_items):
                if item and item not in used:
                    alternate[slot_id] = item;used.add(item);changed.append(slot_id);break
        catalog.validate_selection(alternate)
        require(len(changed) >= 4, 'installed catalog has insufficient alternate categories')
        state_b = dict(first['state'], profile=b, slots=[[slot, alternate[slot]] for slot in catalog.native_slot_order])
        saved_b = encode(state_b);seed(b, saved_b)
        isolated = phase('restore-b', b)
        require(isolated['restored'] and isolated['writable'] and not isolated['read_error'] and isolated['state'] == state_b,
                'separate profile did not restore its full alternate selection')
        require(state_path(a).read_bytes() == saved_a and state_path(b).read_bytes() == saved_b, 'profiles interfered')
        after_b = phase('restart-a-after-b', a)
        require(after_b['restored'] and after_b['state'] == first['state'], 'profile B changed profile A restoration')
        report.update(profile_isolation=True, alternate_categories=len(changed), complete_slots=17)

        def invalid_case(label, mutate):
            key = prefix+'_'+label
            value = json.loads(saved_a);value['profile'] = key
            raw = mutate(value);seed(key, raw)
            proof = phase(label, key)
            require(proof['read_error'] and not proof['writable'] and not proof['restored'], 'invalid state not retained/rejected')
            require(dict(proof['state']['slots']) == baseline, 'invalid save partially changed native cosmetics')
            require(state_path(key).read_bytes() == raw, 'invalid input was overwritten')

        invalid_case('bad_catalog', lambda value: encode(dict(value, catalog_sha256='0'*64)))

        def wrong_slot(value):
            portrait = catalog.roles['portrait']
            compatible = catalog.slots[portrait].compatible_items
            equipped = {item for slot, item in value['slots'] if slot != portrait}
            unavailable = next(item for item in catalog.items if item not in compatible and item not in equipped)
            for pair in value['slots']:
                if pair[0] == portrait: pair[1] = unavailable
            return encode(value)

        invalid_case('wrong_slot', wrong_slot)
        def duplicate(value):
            value['slots'][1][1] = value['slots'][0][1]
            return encode(value)
        invalid_case('duplicate', duplicate)
        invalid_case('truncated', lambda value: encode(value)[:-7])

        lock_key = prefix+'_locked'
        locked_value = dict(first['state'], profile=lock_key);raw = encode(locked_value);seed(lock_key, raw)
        with writer_lock(folder/(lock_key+'.cosmetics.lock')):
            locked = phase('writer-locked', lock_key)
        require(locked['read_error'] and not locked['writable'] and not locked['restored'] and
                dict(locked['state']['slots']) == baseline and state_path(lock_key).read_bytes() == raw,
                'competing writer was not isolated without damaging state')
        phase('ordinary-startup')
        require(state_path(a).read_bytes() == saved_a and state_path(b).read_bytes() == saved_b, 'later probes changed saved profiles')
        report.update(passed=True, restart=True, retained_invalid_inputs=True, writer_lock=True,
                      ordinary_player_features_enabled=True, remote_connections=0, invite_reads=0)
    finally:
        report['source_sha256_at_finish'] = sources()
        report['source_files_unchanged'] = report['source_sha256_at_start'] == report['source_sha256_at_finish']
        report['passed'] &= report['source_files_unchanged']
        (output/'verification.json').write_text(json.dumps(report, indent=2)+'\n', encoding='utf-8')
        print('Evidence: '+str(output/'verification.json'), flush=True)
    require(report['passed'], 'cosmetic persistence qualification failed')


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    for field in ('game', 'output'): parser.add_argument('--'+field, type=Path, required=True)
    parser.add_argument('--timeout', type=int, default=240, help='per-process startup deadline')
    parser.add_argument('--visible', action='store_true')
    run(parser.parse_args())
