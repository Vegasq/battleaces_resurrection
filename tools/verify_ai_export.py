"""Opt-in original serializer/export probe on an isolated patched Windows client.

No match is started. The owned hidden process is terminated after the manifest;
this does not qualify native Quit, rendered UI or process-wide network absence.
"""
from __future__ import annotations

import argparse
import ctypes
import hashlib
import json
import os
from pathlib import Path, PureWindowsPath
import re
import secrets
import subprocess
import time
import traceback

from server.worker_client import _WindowsJob
from server.bot_catalog import BotCatalog
from server.cosmetics import CosmeticCatalog
from server.game_data import GameTemplate
from tools.import_assets import verify_export
from tools.verify_custom_lobby import require, source_hashes as core_hashes
from client_patch.transport import launcher
from tools import verify_native_quit as quit_probe
from tools import verify_unified_startup as startup_probe
from tools.verify_native_storage import snapshot
from tools.verify_packaged_play import job_accounting

ROOT = Path(__file__).resolve().parents[1]


def source_hashes():
    return core_hashes() | {p.relative_to(ROOT).as_posix(): hashlib.sha256(p.read_bytes()).hexdigest()
                           for p in (Path(__file__), ROOT/'tools/import_assets.py', ROOT/'tools/verify_native_quit.py',
                                     ROOT/'tools/verify_native_storage.py', ROOT/'tools/verify_packaged_play.py',
                                     ROOT/'tools/verify_unified_startup.py', ROOT/'client_patch/transport/launcher.py',
                                     ROOT/'client_patch/transport/client.py')}


def export_command(game, exported, profile, log):
    require(re.fullmatch(r'nativestest_export_[0-9a-f]{12}', profile), 'fresh owned export profile required')
    launcher.native_storage_preflight(dict(game_directory=game, local_profile=profile))
    return [str(game/'Battle Aces.exe'), '-offline-practice', '-export-server-assets',
            '-local-profile='+profile, '-server-assets-dir='+str(exported),
            '-screen-fullscreen', '0', '-screen-width', '960', '-screen-height', '540', '-logFile', str(log)]


def read_export_log(game, pid, since_tick):
    # Unlike match logs, export evidence includes isolation before native startup.
    path = game/'investigation/runtime'/f'dedicated-native-{pid}.log'
    raw = path.read_bytes() if path.exists() else b''
    complete = raw[:raw.rfind(b'\n')+1].decode('utf-8')
    return '\n'.join(line for line in complete.splitlines()
                     if (match := re.match(r'^\[(\d+)\] ', line)) and int(match[1]) >= since_tick)+'\n'


def export_log_evidence(text, game, profile):
    rows = re.findall(r'^\[\d+\] NATIVE SETTINGS path selected: (\{[^\n]*\}) BA_RESURRECTION_NATIVE_SETTINGS_V1$', text, re.M)
    expected = game/'.battleaces-resurrection/profiles'/profile/'gameconfig-localuser.toml'
    require(len(rows) == 1, 'isolated export settings path missing or ambiguous')
    for raw in rows:
        row = json.loads(raw)
        require(row.get('profile') == profile and PureWindowsPath(row.get('path', '')) == PureWindowsPath(str(expected)) and
                row.get('beforeNativeLoad') is True and row.get('isolated') is True and row.get('writerLock') is True,
                'export settings escaped its owned profile')
    backup = expected.parent/'StorageSyncBackup'
    backups = re.findall(r'^\[\d+\] NATIVE STORAGE path selected: kind=backup (.*)$', text, re.M)
    require(backups == [f'profile={profile} path={backup} isolated=1 rooted=1 BA_RESURRECTION_NATIVE_STORAGE_V1'],
            'isolated export backup path not observed')
    require('Network adapters and Play are disabled in export mode.' in text and
            'Server asset export: COMPLETE: three mode maps, unit/bot/cosmetic catalogs, AI rules and export.json written; no match started.' in text,
            'export mode/completion markers missing')
    require(not any(marker in text for marker in ('Practice requested:', 'Local AI all ready:',
                                                 'Native storage initialization refused:', 'Native local-user settings isolation failed:')),
            'export attempted play or failed storage initialization')
    return dict(settings_path_isolated=True, backup_path_isolated=True,
                export_mode_and_completion_observed=True, match_request_observed=False,
                scope='Native wrapper/control markers,not independent process-wide network evidence.')


def run(game, output, *, shared_settings, helper_build_receipt, timeout=300):
    game, output = game.resolve(), output.resolve()
    require(os.name == 'nt' and all(p.is_relative_to(ROOT/'local') for p in (game, output)) and 60 <= timeout <= 300,
            'owned Windows game/evidence directories and bounded timeout required')
    launcher.verify_game(game, community=True, bridge_version=2, unified=True, player_features=True)
    receipt = quit_probe.verify_build_receipt(game, helper_build_receipt.resolve())
    profile = 'nativestest_export_'+secrets.token_hex(6)
    profile_root = game/'.battleaces-resurrection/profiles'
    require(not (profile_root/profile).exists(), 'export profile already exists')
    def channels():
        shared = shared_settings.resolve()
        return dict(toml=startup_probe.shared_state(shared), replays=snapshot(shared.parent/'AutoSaveReplays'),
                    backup=snapshot(shared.parent/'StorageSyncBackup'), default_profile=snapshot(profile_root/'default'),
                    default_cosmetics=startup_probe.shared_state(profile_root/'default.cosmetics.json'))
    def components():
        manifest = json.loads((game/'.battleaces-resurrection/patch-manifest.json').read_bytes())
        names = list(manifest['components'])+['BattleAcesOffline.dll']
        return {name: hashlib.sha256((game/name).read_bytes()).hexdigest() for name in names}
    output.mkdir(parents=True, exist_ok=False)
    exported = output/'export'
    report = dict(passed=False, scope=__doc__, profile=profile, helper_build=receipt,
                  shared_before=channels(), components_before=components(),
                  source_sha256_at_start=source_hashes(), forced_cleanup=False, native_quit_qualified=False)
    process = job = None
    began, tick = time.monotonic(), None
    try:
        clock = ctypes.WinDLL('kernel32').GetTickCount64; clock.restype = ctypes.c_ulonglong
        tick = clock()
        command = export_command(game, exported, profile, output/'game.log')
        startup = subprocess.STARTUPINFO()
        startup.dwFlags |= subprocess.STARTF_USESHOWWINDOW; startup.wShowWindow = 0
        process = subprocess.Popen(command, cwd=game, startupinfo=startup,
                                   creationflags=subprocess.CREATE_NO_WINDOW)
        job = _WindowsJob(process.pid)
        manifest = json.loads((game/'.battleaces-resurrection/patch-manifest.json').read_text())
        report.update(game_pid=process.pid, launch_tick=tick, helper_sha256=manifest['helper_sha256'],
                      command=command, job_after_assignment=job_accounting(job.handle))
        (output/'process.json').write_text(json.dumps(report, indent=2), encoding='utf-8')
        while not (exported/'export.json').exists():
            require(process.poll() is None, 'client exited before completing export')
            if (exported/'export-error.json').exists():
                raise RuntimeError((exported/'export-error.json').read_text())
            require(time.monotonic()-began < timeout, 'asset export deadline reached')
            time.sleep(.25)
        completion = json.loads((exported/'export.json').read_bytes())
        require(completion.get('pid') == process.pid, 'export manifest belongs to another process')
        deadline = time.monotonic()+3
        while 'Server asset export: COMPLETE: three mode maps' not in read_export_log(game, process.pid, tick):
            require(time.monotonic()<deadline and process.poll() is None, 'export completion log missing')
            time.sleep(.05)
        report['native_control'] = export_log_evidence(read_export_log(game, process.pid, tick), game, profile)
        verify_export(exported)
        rules = json.loads((exported/'ai-rules.json').read_text())
        require(rules['repeatable'] and rules['manager_unchanged'], 'native exporter invariants failed')
        require(rules.get('repeatability_scope') == 'same_loaded_process', 'rule repeatability scope missing')
        profiles = rules['profiles']; ids = [p['profile'] for p in profiles]
        require(0 < len(ids) <= 256 and len(set(ids)) == len(ids) and rules['default_profile'] in ids,
                'invalid rule profile inventory')
        for entry in profiles:
            require(entry['file'] == f"ai-rules-{entry['profile']}.fb", 'invalid rule filename')
            data = (exported/entry['file']).read_bytes()
            require(len(data) == entry['bytes'] and hashlib.sha256(data).hexdigest() == entry['sha256'],
                    'rule size/hash mismatch')
        report.update(passed=True, default_profile=rules['default_profile'], profile_count=len(ids),
                      profiles=profiles, repeatable=True, manager_unchanged=True)
        templates = {}
        for name, mode in (('map-1v1.pb.gz', 1), ('map-2v2.pb.gz', 2), ('map-2vai.pb.gz', 5)):
            template = GameTemplate.load(exported/name, catalog_path=exported/'unit-catalog.json')
            require(template.game_mode == mode, 'original builder mode mismatch')
            templates[mode] = template
        bots = BotCatalog(exported, template=templates[1])
        cosmetics = CosmeticCatalog(exported)
        require(bots.cosmetic_ids == cosmetics.items.keys() and
                set(bots.portraits) <= cosmetics.slots[cosmetics.roles['portrait']].compatible_items and
                set(bots.banners) <= cosmetics.slots[cosmetics.roles['banner']].compatible_items,
                'exported bot and human cosmetic catalogs disagree')
        cosmetic_raw = (exported/'cosmetic-catalog.json').read_bytes()
        report['cosmetic_catalog'] = dict(items=len(cosmetics.items), slots=len(cosmetics.slots),
            sha256=cosmetics.sha256, bytes=len(cosmetic_raw), defaults=len(cosmetics.normalize_local().keys))
        report['maps'] = {mode: dict(armies=template.player_count, alliances=template.alliances,
                                    raw_sha256=template.raw_sha256) for mode, template in templates.items()}
        report['bot_catalog'] = dict(profiles=len(bots.profiles), names=len(bots.names), cosmetic_ids=len(bots.cosmetic_ids),
                                    decks=sum(len(decks) for _, decks in bots.profiles.values()),
                                    character_decks=sum(deck.kind == 1 for _, decks in bots.profiles.values() for deck in decks),
                                    strengths=dict(bots.strengths))
    except BaseException as error:
        report.update(passed=False, error=repr(error), traceback=traceback.format_exc())
    finally:
        if process is not None:
            if tick is not None:
                (output/f'native-{process.pid}.log').write_text(read_export_log(game, process.pid, tick), encoding='utf-8')
            if process.poll() is None:
                report['forced_cleanup']=True
                process.terminate()
            try: process.wait(timeout=10)
            except subprocess.TimeoutExpired: process.kill(); process.wait(timeout=5)
        if job is not None:
            deadline = time.monotonic()+5
            while job_accounting(job.handle)['active_processes'] and time.monotonic()<deadline:
                time.sleep(.05)
            report['job_before_close'] = job_accounting(job.handle)
            if report['job_before_close']['active_processes']:
                report.update(passed=False, forced_job_cleanup=True)
            job.close()
        report.update(elapsed_seconds=time.monotonic()-began, owned_process_reaped=process is None or process.poll() is not None,
                      source_sha256_at_finish=source_hashes(), shared_after=channels(), components_after=components())
        report['shared_channels_unchanged'] = report['shared_before'] == report['shared_after']
        report['components_unchanged'] = report['components_before'] == report['components_after']
        report['source_files_unchanged'] = report['source_sha256_at_start'] == report['source_sha256_at_finish']
        report['passed'] &= all(report[k] for k in ('source_files_unchanged', 'owned_process_reaped',
                                                   'shared_channels_unchanged', 'components_unchanged'))
        (output/'verification.json').write_text(json.dumps(report, indent=2)+'\n', encoding='utf-8')
    print(json.dumps({k: report[k] for k in ('passed', 'elapsed_seconds', 'profile_count', 'error') if k in report}))
    return 0 if report['passed'] else 1


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--game', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--shared-settings', type=Path, required=True)
    parser.add_argument('--helper-build-receipt', type=Path, required=True)
    parser.add_argument('--timeout', type=int, default=300)
    args = parser.parse_args()
    return run(args.game, args.output, shared_settings=args.shared_settings,
               helper_build_receipt=args.helper_build_receipt, timeout=args.timeout)


if __name__ == '__main__':
    raise SystemExit(main())
