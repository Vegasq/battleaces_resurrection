"""Real imported-catalog profiles and protected backup/restore, without mocks.

Uses fresh owned ignored output only. No server, game or socket is started.
An explicit loopback-development host config omits credentials and TLS keys;
production backup privacy creation/readback still runs unmodified. A restricted
token failure is a failure, not a reason to weaken ACLs or declare a pass.
"""
import argparse
import hashlib
import json
import os
from pathlib import Path
import traceback

from server.assets import verify_assets
from server.configuration import load_config
from server.cosmetics import CosmeticCatalog
from server.game_data import GameTemplate
from server.profiles import ProfileStore
from server import state_backup as backup
from tools.verify_custom_lobby import source_hashes as core_hashes, require

ROOT = Path(__file__).resolve().parents[1]


def source_hashes():
    return core_hashes() | {Path(__file__).relative_to(ROOT).as_posix(): hashlib.sha256(Path(__file__).read_bytes()).hexdigest()}


def run(args):
    assets, output = args.assets.resolve(), args.output.resolve()
    require(os.name == 'nt' and output.is_relative_to(ROOT/'local'), 'fresh ignored Windows evidence required')
    output.mkdir(parents=True, exist_ok=False)
    report = dict(passed=False, scope=__doc__, source_sha256_at_start=source_hashes())
    try:
        manifest = verify_assets(assets)
        require('cosmetic-catalog.json' in manifest['files'], 'import current native cosmetic catalog first')
        catalog = CosmeticCatalog(assets)
        template = GameTemplate.load(assets/'map-1v1.pb.gz', catalog_path=assets/'unit-catalog.json', descriptors_path=assets/'descriptors')
        from client_patch.transport.launcher import read_json
        value = read_json(args.selection, 4096)
        state = value.get('state', value)
        require(state['schema'] == 1 and state['build'] == 37822 and state['catalog_sha256'] == catalog.sha256,
                'native local selection has a different catalog/build')
        selection = catalog.validate_selection(state['slots'])
        require(selection != catalog.normalize_local(), 'use an actual changed native selection')
        data = output/'data'
        legacy = ProfileStore(data/'profiles', template)
        legacy.save('native_a', template.default_decks[0])
        legacy_raw = (data/'profiles/native_a.json').read_bytes()
        profiles = ProfileStore(data/'profiles', template, catalog=catalog)
        require(profiles.load_state('native_a', []).cosmetics == catalog.normalize_local(), 'legacy defaults not migrated')
        require((data/'profiles/native_a.json').read_bytes() == legacy_raw, 'legacy read rewrote original profile')
        profiles.save('native_a', template.default_decks[0], cosmetics=selection)
        profiles.save('native_a', template.default_decks[1])
        profiles.save('native_b', template.default_decks[0])
        expected = profiles.load_state('native_a', [])
        require(expected.cosmetics == selection and profiles.load_state('native_b', []).cosmetics == catalog.normalize_local(),
                'deck-only save or separate profile lost full state')
        before = {path.name:path.read_bytes() for path in (data/'profiles').iterdir()}
        report.update(profile_storage_passed=True, catalog_sha256=catalog.sha256, complete_slots=len(selection.slots),
            imported_files=len(manifest['files']), profile_bytes_sha256={key:hashlib.sha256(raw).hexdigest() for key, raw in before.items()})
        settings = dict(schema=1, listen_host='127.0.0.1', listen_port=47623, assets_directory=str(assets),
            data_directory=str(data), certificate_file=None, private_key_file=None, credential_directory=None,
            max_rooms=1, input_window=6, diagnostic_audit=False, log_max_bytes=65536, log_backups=1, allow_insecure_loopback=True)
        config_path = output/'host.json';config_path.write_text(json.dumps(settings, indent=2)+'\n', encoding='utf-8')
        config = load_config(config_path)
        destination = output/'snapshots/full-loadout.backup.json'
        saved = backup.backup(config, destination)
        require(backup.verify_snapshot(config, destination)['verified'], 'protected backup verification failed')
        restored = backup.restore(config, destination, output/'restored')
        restored_config = load_config(restored['config'])
        copied = ProfileStore(restored_config.data_directory/'profiles', template, catalog=catalog)
        require(copied.load_state('native_a', []) == expected and copied.load_state('native_b', []).cosmetics == catalog.normalize_local(),
                'full actual profile restore differs')
        require({path.name:path.read_bytes() for path in (data/'profiles').iterdir()} == before, 'restore changed live profiles')
        report.update(passed=True, protected_backup_passed=True, full_restore_passed=True,
            snapshot_sha256=saved['sha256'], snapshot_bytes=saved['bytes'], snapshot_schema=json.loads(destination.read_bytes())['schema'])
    except BaseException as error:
        report.update(passed=False, error=repr(error), traceback=traceback.format_exc())
    finally:
        report['source_sha256_at_finish'] = source_hashes()
        report['source_files_unchanged'] = report['source_sha256_at_start'] == report['source_sha256_at_finish']
        report['passed'] &= report['source_files_unchanged']
        (output/'verification.json').write_text(json.dumps(report, indent=2)+'\n', encoding='utf-8')
        print(json.dumps({key:report[key] for key in ('passed', 'profile_storage_passed', 'protected_backup_passed', 'full_restore_passed', 'error') if key in report}))
    return 0 if report['passed'] else 1


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    for key in ('assets', 'output', 'selection'): parser.add_argument('--'+key, type=Path, required=True)
    raise SystemExit(run(parser.parse_args()))
