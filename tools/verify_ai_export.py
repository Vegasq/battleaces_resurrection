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
from pathlib import Path
import subprocess
import time
import traceback

from server.worker_client import _WindowsJob
from server.bot_catalog import BotCatalog
from server.game_data import GameTemplate
from tools.import_assets import verify_export
from tools.run_secure_match import read_native_log
from tools.verify_custom_lobby import require, source_hashes as core_hashes

ROOT = Path(__file__).resolve().parents[1]


def source_hashes():
    return core_hashes() | {p.relative_to(ROOT).as_posix(): hashlib.sha256(p.read_bytes()).hexdigest()
                           for p in (Path(__file__), ROOT/'tools/import_assets.py')}


def run(game, output):
    game, output = game.resolve(), output.resolve()
    require(os.name == 'nt' and output.is_relative_to(ROOT/'local'), 'Windows/ignored evidence directory required')
    output.mkdir(parents=True, exist_ok=False)
    exported = output/'export'
    report = dict(passed=False, scope=__doc__, source_sha256_at_start=source_hashes())
    process = job = None
    began, tick = time.monotonic(), None
    try:
        clock = ctypes.WinDLL('kernel32').GetTickCount64; clock.restype = ctypes.c_ulonglong
        tick = clock()
        command = [str(game/'Battle Aces.exe'), '-export-server-assets', f'-server-assets-dir={exported}',
                   '-screen-fullscreen', '0', '-screen-width', '960', '-screen-height', '540',
                   '-logFile', str(output/'game.log')]
        startup = subprocess.STARTUPINFO()
        startup.dwFlags |= subprocess.STARTF_USESHOWWINDOW; startup.wShowWindow = 0
        process = subprocess.Popen(command, cwd=game, startupinfo=startup,
                                   creationflags=subprocess.CREATE_NO_WINDOW)
        job = _WindowsJob(process.pid)
        manifest = json.loads((game/'.battleaces-resurrection/patch-manifest.json').read_text())
        report.update(game_pid=process.pid, launch_tick=tick, helper_sha256=manifest['helper_sha256'])
        (output/'process.json').write_text(json.dumps(report, indent=2), encoding='utf-8')
        while not (exported/'export.json').exists():
            require(process.poll() is None, 'client exited before completing export')
            if (exported/'export-error.json').exists():
                raise RuntimeError((exported/'export-error.json').read_text())
            require(time.monotonic()-began < 180, 'asset export deadline reached')
            time.sleep(.25)
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
        report['maps'] = {mode: dict(armies=template.player_count, alliances=template.alliances,
                                    raw_sha256=template.raw_sha256) for mode, template in templates.items()}
        report['bot_catalog'] = dict(profiles=len(bots.profiles), names=len(bots.names), cosmetic_ids=len(bots.cosmetic_ids),
                                    decks=sum(len(decks) for _, decks in bots.profiles.values()),
                                    character_decks=sum(deck.kind == 1 for _, decks in bots.profiles.values() for deck in decks),
                                    strengths=dict(bots.strengths))
    except BaseException as error:
        report.update(error=repr(error), traceback=traceback.format_exc())
    finally:
        if process is not None:
            if tick is not None:
                (output/f'native-{process.pid}.log').write_text(read_native_log(game, process.pid, since_tick=tick), encoding='utf-8')
            if process.poll() is None: process.terminate()
            try: process.wait(timeout=10)
            except subprocess.TimeoutExpired: process.kill(); process.wait(timeout=5)
        if job is not None: job.close()
        report.update(elapsed_seconds=time.monotonic()-began, owned_process_reaped=process is None or process.poll() is not None,
                      source_sha256_at_finish=source_hashes())
        report['source_files_unchanged'] = report['source_sha256_at_start'] == report['source_sha256_at_finish']
        report['passed'] &= report['source_files_unchanged'] and report['owned_process_reaped']
        (output/'verification.json').write_text(json.dumps(report, indent=2)+'\n', encoding='utf-8')
    print(json.dumps({k: report[k] for k in ('passed', 'elapsed_seconds', 'profile_count', 'error') if k in report}))
    return 0 if report['passed'] else 1


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--game', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    return run(args.game, args.output)


if __name__ == '__main__':
    raise SystemExit(main())
