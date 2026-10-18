"""Opt-in native public1v1 AI button/combat/results/rematch verification.

Runs the real unified launcher with no server/CA/invite and explicit diagnostic
flags. Native Play, build, surrender and Continue are automated; window is hidden.
Forced owned teardown does not qualify native Quit, visible UI or online queues.
"""
from __future__ import annotations

import argparse
import csv
import ctypes
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import threading
import time
import traceback
from unittest import mock

from client_patch.transport import client, launcher
from server.worker_client import _WindowsJob
from tools.run_secure_match import read_native_log
from tools.verify_custom_lobby import require, source_hashes as core_hashes
from tools.verify_practice_ai import movement_evidence

ROOT = Path(__file__).resolve().parents[1]


def source_hashes():
    paths = [Path(__file__), ROOT/'tools/verify_practice_ai.py', ROOT/'tools/run_secure_match.py']
    paths += list((ROOT/'client_patch/transport').glob('*.py'))
    return core_hashes() | {p.relative_to(ROOT).as_posix(): hashlib.sha256(p.read_bytes()).hexdigest() for p in paths}


def run(args):
    require(os.name == 'nt' and 120 <= args.timeout <= 900, 'bounded Windows probe required')
    require(args.matches in (1, 2) and 1200 <= args.frames <= 3600, 'bounded match/frame count required')
    game, output = args.game.resolve(), args.output.resolve()
    require(output.is_relative_to(ROOT/'local'), 'evidence must remain under ignored local/')
    output.mkdir(parents=True, exist_ok=False)
    path = output/'client.json'
    settings = client.defaults(game); settings['display_name'] = 'Public AI Tester'
    path.write_text(json.dumps(settings, indent=2), encoding='utf-8')
    report = dict(passed=False, utc=datetime.now(timezone.utc).isoformat(), scope=__doc__,
                  source_sha256_at_start=source_hashes())
    process = job = monitor = None
    started, tick, log = time.monotonic(), None, ''

    def watch():
        nonlocal log
        try:
            while True:
                require(process.poll() is None, 'client exited before public AI completion')
                log = read_native_log(game, process.pid, since_tick=tick)
                require(not any(marker in log for marker in ('Client lifecycle invariant failed:',
                    'Local menu initialization failed:', 'Offline initialization failed:',
                    'Practice stopped in ', 'Dedicated native Play could not ready lobby:',
                    'Offline loop stopped in ')), 'native public AI failed; see logs')
                if f'Practice returned: completed={args.matches} mode=1 seat=-1 presenceRetained=0 standalone=1' in log:
                    report['native_lifecycle_complete'] = True
                    break
                require(time.monotonic()-started < args.timeout, 'native public AI deadline reached')
                time.sleep(.25)
        except BaseException as error:
            report.update(error=repr(error), traceback=traceback.format_exc())
        finally:
            if process.poll() is None: process.terminate()

    def spawn(config, remote, options, child):
        nonlocal process, job, monitor, tick
        command = launcher.game_arguments(config, None, child.fileno(), options)
        require(not any('smoke' in value or 'audit' in value for value in command), 'normal launcher added diagnostics')
        command[command.index('-logFile')+1] = str(output/'game.log')
        command += ['-public-ai-experimental', '-public-ai-smoke', '-practice-ai-smoke',
                    f'-practice-ai-smoke-matches={args.matches}', f'-practice-ai-smoke-frames={args.frames}',
                    '-lan-smoke', '-lan-audit']
        if args.matches == 2: command.append('-practice-ai-deck-smoke')
        if args.profile: command.append(f'-public-ai-smoke-profile={args.profile}')
        startup = subprocess.STARTUPINFO()
        startup.dwFlags |= subprocess.STARTF_USESHOWWINDOW
        startup.wShowWindow = 0
        startup.lpAttributeList = {'handle_list': [child.fileno()]}
        clock = ctypes.WinDLL('kernel32').GetTickCount64; clock.restype = ctypes.c_ulonglong
        tick = clock()
        try:
            child.set_inheritable(True)
            process = subprocess.Popen(command, cwd=game, startupinfo=startup,
                creationflags=subprocess.CREATE_NO_WINDOW, close_fds=True)
        finally: child.set_inheritable(False)
        job = _WindowsJob(process.pid)
        manifest = json.loads((game/'.battleaces-resurrection/patch-manifest.json').read_text())
        report.update(game_pid=process.pid, launch_tick=tick, client_arguments=command,
                      helper_sha256=manifest['helper_sha256'])
        (output/'process.json').write_text(json.dumps(report, indent=2), encoding='utf-8')
        monitor = threading.Thread(target=watch, name='public-ai-monitor')
        monitor.start()
        return process

    try:
        with (mock.patch.object(launcher, 'spawn_game', side_effect=spawn),
              mock.patch.object(launcher.tls, 'open_verified_connection', side_effect=AssertionError('unexpected remote connection')) as connect,
              mock.patch.object(launcher, 'read_credential_file', side_effect=AssertionError('unexpected invite read')) as invite):
            report['launcher_return_code'] = client.main(['--config', str(path)])
            if monitor is not None: monitor.join(timeout=15)
            require(report.get('native_lifecycle_complete') and 'error' not in report, report.get('error', 'public AI lifecycle incomplete'))
            require(connect.call_count == invite.call_count == 0, 'offline public AI required remote connection/invite')
        starts = list(re.finditer(r'Practice requested: match=([0-9a-f]{32}) mode=1 ', log))
        require(len(starts) == args.matches and len({s[1] for s in starts}) == args.matches, 'public match identities/count incorrect')
        for marker in ('PUBLIC AI SMOKE original mode1 OnMapSelected: owned=1 visible=1 interactable=1 preamble=1',
                       'Practice AI JoinedGame delivered:', 'Practice native EndOfGameResponse delivered;',
                       'PRACTICE SMOKE native Continue (automated)', 'owner=local-practice nativeIdle=1'):
            require(log.count(marker) == args.matches, 'native lifecycle count mismatch: ' + marker)
        report['matches'] = evidence = []
        for index, start in enumerate(starts):
            segment = log[start.start():starts[index+1].start() if index+1 < len(starts) else len(log)]
            armies = [json.loads(line.split('Practice army snapshot: ', 1)[1])
                      for line in segment.splitlines() if 'Practice army snapshot: ' in line]
            require(len(armies) == 2, 'expected one human and one bot army')
            human, bot = armies
            require(human['players'][0]['playerHandleWithName']['playerName'] == settings['display_name'], 'configured human name lost')
            bot_name = bot['players'][0]['playerHandleWithName']['playerName']
            profile = bot['players'][0]['aiProfileId']
            require(bot_name != 'Practice AI' and profile in (58, 62, 63, 64), 'public roster was replaced by practice opponent')
            if args.profile: require(profile == args.profile, 'forced qualification profile not used')
            require(bot.get('portraitId') and bot.get('bannerId'), 'public bot avatar missing')
            require(f'Practice effective AI profile: id={profile} expectedTableEntry=1' in segment, 'native AI did not use frozen public profile')
            require('Public AI identity binding: phase=result ' in segment, 'native result name/AI/cosmetic bindings not observed')
            moved, ordered = movement_evidence(segment, set(bot['deck']['units']))
            require(bool(moved & ordered), 'no produced bot unit both moved and received autonomous Move/Attack orders')
            resource_path = game/'investigation/runtime'/f'lan-resources-{process.pid}-{start[1]}.tsv'
            shutil.copy2(resource_path, output/resource_path.name)
            with resource_path.open(encoding='utf-8') as source:
                rows = [row for row in csv.DictReader(source, delimiter='\t') if row['viewer'] == '1' and row['army'] == '1']
            supply = max((int(row['current_supply']) for row in rows), default=0)
            require(supply > 0, 'bot produced no native unit supply')
            difficulty = re.search(r'Public AI difficulty snapshot: selected=(\w+) modifierProfile=(17|18|19) practiceSelectionUnchanged=1', segment)
            require(difficulty is not None, 'separate random public difficulty snapshot missing')
            evidence.append(dict(match=start[1], profile=profile, bot_name=bot_name, portrait=bot['portraitId'],
                banner=bot['bannerId'], human_deck=human['deck']['units'], bot_deck=bot['deck']['units'],
                difficulty=difficulty[1], bot_max_supply=supply, ordered_moving_units=sorted(moved & ordered),
                result_identity_binding=True, in_game_identity_binding='Public AI identity binding: phase=in-game ' in segment))
        if args.matches == 2:
            require(evidence[0]['human_deck'] != evidence[1]['human_deck'], 'edited human deck did not reach rematch')
            require(evidence[0]['bot_name'] != evidence[1]['bot_name'], 'public bot name did not vary')
        report.update(passed=True, remote_connections=0, invite_reads=0)
    except BaseException as error:
        report.update(passed=False, error=report.get('error', repr(error)))
        raise
    finally:
        if process is not None:
            if process.poll() is None: process.terminate()
            process.wait(timeout=15)
            (output/f'native-{process.pid}.log').write_text(read_native_log(game, process.pid, since_tick=tick), encoding='utf-8')
        if monitor is not None: monitor.join(timeout=15)
        if job is not None: job.close()
        report.update(elapsed_seconds=time.monotonic()-started, owned_process_reaped=process is None or process.poll() is not None,
                      source_sha256_at_finish=source_hashes())
        report['source_files_unchanged'] = report['source_sha256_at_start'] == report['source_sha256_at_finish']
        report['passed'] &= report['owned_process_reaped'] and report['source_files_unchanged']
        (output/'verification.json').write_text(json.dumps(report, indent=2), encoding='utf-8')
        print('Evidence: ' + str(output/'verification.json'))
    require(report['passed'], 'public AI qualification failed')


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    for key in ('game', 'output'): parser.add_argument('--'+key, type=Path, required=True)
    parser.add_argument('--timeout', type=int, default=600)
    parser.add_argument('--frames', type=int, default=3600)
    parser.add_argument('--matches', type=int, choices=(1, 2), default=2)
    parser.add_argument('--profile', type=int, choices=(58, 62, 63, 64))
    run(parser.parse_args())
