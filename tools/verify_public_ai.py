"""Opt-in native local AI combat/results/rematch and mode-switch verification.

Runs the real unified launcher with no server/CA/invite and explicit diagnostic
flags. Native Play, build, surrender and Continue are automated; hidden by default.
Forced owned teardown does not qualify native Quit, visible UI or online queues.
Optional --search-smoke cancels before building and at the original map callback,
then retries successfully. It retains original Unity UI screenshots for review.
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


def search_evidence(log, game, output, pid, matches):
    starts = list(re.finditer(r'Native search began: ticket=(\d+) mode=1 nativeStatus=5 originalPanel=1', log))
    tickets = [int(row[1]) for row in starts]
    require(len(tickets) == matches+2 and tickets == sorted(set(tickets)), 'search generation count/order')
    cancelled = [int(row[1]) for row in re.finditer(r'Public search cancelled: ticket=(\d+) builderReturned=[01] nativeWorld=0', log)]
    found = [int(row[1]) for row in re.finditer(r'Native search match accepted: ticket=(\d+) status=7', log)]
    joined = [int(row[1]) for row in re.finditer(r'Native search joining signal: ticket=(\d+) mode=1 activeConnection=1 originalRouter=1', log)]
    require(cancelled == tickets[:2] and found == joined == tickets[2:], 'cancelled or stale search started a world')
    require(log.count('Public map callback discarded: ') == 1, 'pending builder cancellation not exercised')
    require(log.count('Native search original Cancel invoked: ') == 2, 'original Cancel callback count')
    require(log.count('Native search button: ') == len(tickets), 'original Searching button not observed')
    require(log.count('Native search stale ticket rejected: ') == len(tickets)-1, 'stale generation guard not exercised')
    require('Match loading UI created:' not in log, 'public search used the replacement overlay')
    timers = {}
    for ticket in tickets:
        seconds = [int(row[1]) for row in re.finditer(rf'Native search timer: ticket={ticket} seconds=(\d+)', log)]
        require(seconds and seconds[0] == 0 and seconds[-1] >= 1 and seconds == sorted(set(seconds)), 'native elapsed timer did not advance')
        timers[str(ticket)] = seconds
    captures = []
    for row in re.finditer(r'Native search capture requested: file=(match-search-\d+-\d+-\d+-\w+\.png) ticket=(\d+) event=(\w+) frame=(\d+)', log):
        filename, ticket, event, frame = row.groups()
        require(filename.startswith(f'match-search-{pid}-') and int(ticket) in tickets, 'foreign search screenshot')
        source = game/'investigation/runtime'/filename
        require(source.is_file() and source.stat().st_size > 1024, 'missing native search screenshot: '+filename)
        data = source.read_bytes()
        require(data.startswith(b'\x89PNG\r\n\x1a\n'), 'search screenshot is not PNG')
        shutil.copyfile(source, output/filename)
        captures.append(dict(file=filename, ticket=int(ticket), event=event, frame=int(frame), sha256=hashlib.sha256(data).hexdigest()))
    for ticket in tickets:
        require(any(row['ticket'] == ticket and row['event'] == 'searching' for row in captures), 'missing search-state capture')
    require(any(row['event'] == 'joining' for row in captures), 'missing joining-state capture')
    return dict(tickets=tickets, cancelled=cancelled, accepted=found, elapsed_seconds=timers,
        screenshots=captures, native_cancel='automated callback, not mouse input',
        visual_review='pending pixel inspection; hidden Unity windows may produce black captures',
        limits='local 1v1 only; no online queue, timeout or remote late-response qualification')


def run(args):
    require(os.name == 'nt' and 120 <= args.timeout <= 1800, 'bounded Windows probe required')
    modes=[int(value) for value in args.modes.split(',')] if args.modes else [args.mode]*args.matches
    require(1 <= len(modes) <= 8 and all(mode in (1,2,4,5) for mode in modes), 'unsupported mode sequence')
    matches=len(modes)
    require(1200 <= args.frames <= 3600, 'bounded frame count required')
    require(not args.search_smoke or (not args.modes and args.mode == 1), 'cancellation probe currently covers repeated mode1')
    require(not args.profile or 1 in modes, 'profile override applies only to mode1')
    game, output = args.game.resolve(), args.output.resolve()
    require(output.is_relative_to(ROOT/'local'), 'evidence must remain under ignored local/')
    output.mkdir(parents=True, exist_ok=False)
    path = output/'client.json'
    settings = client.defaults(game); settings['display_name'] = 'Public AI Tester'
    path.write_text(json.dumps(settings, indent=2), encoding='utf-8')
    report = dict(passed=False, utc=datetime.now(timezone.utc).isoformat(), scope=__doc__, requested_modes=modes,
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
                    'Offline loop stopped in ', 'Offline status: native search',
                    'Native search failure cleanup:')), 'native public AI failed; see logs')
                if f'Practice returned: completed={matches} mode={modes[-1]} seat=-1 presenceRetained=0 standalone=1' in log:
                    report['native_lifecycle_complete'] = True
                    break
                require(time.monotonic()-started < args.timeout, 'native public AI deadline reached')
                time.sleep(.25)
        except BaseException as error:
            report.update(error=f'{type(error).__name__}: {error}', traceback=traceback.format_exc())
        finally:
            if process.poll() is None: process.terminate()

    def spawn(config, remote, options, child):
        nonlocal process, job, monitor, tick
        command = launcher.game_arguments(config, None, child.fileno(), options)
        require(not any('smoke' in value or 'audit' in value for value in command), 'normal launcher added diagnostics')
        command[command.index('-logFile')+1] = str(output/'game.log')
        command += ['-public-ai-experimental', '-public-ai-smoke', '-practice-ai-smoke',
                    f'-public-ai-smoke-mode={args.mode}',
                    f'-practice-ai-smoke-matches={matches}', f'-practice-ai-smoke-frames={args.frames}',
                    '-lan-smoke', '-lan-audit']
        if matches > 1: command.append('-practice-ai-deck-smoke')
        if args.modes: command.append('-practice-ai-smoke-modes='+','.join(map(str,modes)))
        if args.profile: command.append(f'-public-ai-smoke-profile={args.profile}')
        if args.natural: command.append('-practice-ai-smoke-natural')
        if args.search_smoke: command.append('-match-search-smoke')
        startup = subprocess.STARTUPINFO()
        startup.dwFlags |= subprocess.STARTF_USESHOWWINDOW
        startup.wShowWindow = 5 if args.visible else 0
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
                      helper_sha256=manifest['helper_sha256'], visible_window=args.visible)
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
        starts = list(re.finditer(r'Practice requested: match=([0-9a-f]{32}) mode=([1245]) ', log))
        attempts = matches + (2 if args.search_smoke else 0)
        require(len(starts) == attempts and len({s[1] for s in starts}) == attempts, 'public match identities/count incorrect')
        require(log.count('owner=local-practice nativeIdle=1') == attempts, 'native world ownership release count mismatch')
        for mode in (1,2,4,5):
            marker=('PRACTICE SMOKE original EditDeck mode4 callback: owned=1 visible=1 interactable=1 preamble=1' if mode==4 else
                    f'PUBLIC AI SMOKE original mode{mode} OnMapSelected: owned=1 visible=1 interactable=1 preamble=1')
            expected=modes.count(mode)+(2 if args.search_smoke and mode==1 else 0)
            require(log.count(marker)==expected, 'native intent count mismatch: '+marker)
        if args.search_smoke:
            report['native_search'] = search_evidence(log, game, output, process.pid, matches)
            starts = starts[2:]
        require([int(start[2]) for start in starts]==modes,'native mode order differs from requested sequence')
        require(log.count('Practice AI JoinedGame delivered:') == sum(1 if mode in (1,4) else 3 for mode in modes), 'not every bot joined exactly once')
        for marker in ('Practice native EndOfGameResponse delivered;',
                       'PRACTICE SMOKE native Continue (automated)'):
            require(log.count(marker) == matches, 'native lifecycle count mismatch: ' + marker)
        report['matches'] = evidence = []; practice_settings=[]
        for index, start in enumerate(starts):
            mode=modes[index];bots_per_match=1 if mode in (1,4) else 3
            segment = log[start.start():starts[index+1].start() if index+1 < len(starts) else len(log)]
            if mode==4:
                difficulty=re.search(r'Practice difficulty snapshot: selected=(\w+) modifierProfile=(17|18|19) tuningProfile=(18|19)',segment)
                require(difficulty is not None,'practice difficulty/tactics snapshot missing')
                practice_settings.append(difficulty.groups())
            else:
                difficulty=re.search(r'Public AI difficulty snapshot: selected=(\w+) modifierProfile=(17|18|19) practiceSelectionUnchanged=1',segment)
                require(difficulty is not None,'separate random public difficulty snapshot missing')
            armies = [json.loads(line.split('Practice army snapshot: ', 1)[1])
                      for line in segment.splitlines() if 'Practice army snapshot: ' in line]
            require(len(armies) == bots_per_match+1, 'local roster size mismatch')
            require([army.get('armyId', 0) for army in armies] == list(range(len(armies))), 'local army order mismatch')
            require([army.get('allianceId', 0) for army in armies] == [index%2 for index in range(len(armies))], 'authored team alliances changed')
            human = armies[0]
            require(human['players'][0]['playerHandleWithName']['playerName'] == settings['display_name'], 'configured human name lost')
            resource_path = game/'investigation/runtime'/f'lan-resources-{process.pid}-{start[1]}.tsv'
            shutil.copy2(resource_path, output/resource_path.name)
            with resource_path.open(encoding='utf-8') as source:
                rows = list(csv.DictReader(source, delimiter='\t'))
            bot_evidence = []
            names = {settings['display_name']}
            for seat, bot in enumerate(armies[1:], 1):
                bot_name = bot['players'][0]['playerHandleWithName']['playerName']
                profile = bot['players'][0]['aiProfileId']
                expected_profiles = (int(difficulty[3]),) if mode==4 else (58,62,63,64) if mode==1 else (59,) if mode==2 or seat==2 else (60,)
                require((bot_name=='Practice AI') == (mode==4) and bot_name not in names and profile in expected_profiles, 'local roster identity/pool mismatch')
                names.add(bot_name)
                if args.profile and mode==1: require(profile == args.profile, 'forced qualification profile not used')
                if mode!=4: require(bot.get('portraitId') and bot.get('bannerId'), 'public bot avatar missing')
                require(f'Practice effective AI profile: id={profile} expectedTableEntry=1' in segment, 'native AI did not use frozen public profile')
                bindings = [line for line in segment.splitlines() if 'Public AI identity binding: phase=result ' in line and line.endswith(f'army={seat}')]
                if mode!=4: require(bindings, 'native result name/AI/cosmetic bindings not observed for seat '+str(seat))
                moved, ordered = movement_evidence(segment, set(bot['deck']['units']), seat)
                require(bool(moved & ordered), 'bot did not produce and autonomously move units: '+str(seat))
                supply = max((int(row['current_supply']) for row in rows if row['viewer'] == str(seat%2) and row['army'] == str(seat)), default=0)
                require(supply > 0, 'bot produced no native unit supply: '+str(seat))
                require(segment.count(f'Practice native JoinArmy validated: army={seat} ') == 1, 'bot deck/army join not validated exactly once')
                bot_evidence.append(dict(seat=seat, profile=profile, bot_name=bot_name, portrait=bot.get('portraitId',0), banner=bot.get('bannerId',0),
                    bot_deck=bot['deck']['units'], bot_max_supply=supply, ordered_moving_units=sorted(moved & ordered), result_identity_binding=bool(bindings)))
            require(f'Local AI all ready: bots={bots_per_match} sharedSimulation=1 producers={bots_per_match+1}' in segment, 'all-bot readiness gate not observed')
            evidence.append(dict(match=start[1], mode=mode, human_deck=human['deck']['units'], bots=bot_evidence,
                difficulty=difficulty[1], **bot_evidence[0],
                in_game_identity_binding='Public AI identity binding: phase=in-game ' in segment))
        if args.natural: require('PRACTICE SMOKE native ConcedeGame' not in log, 'natural probe surrendered')
        for previous,current in zip(evidence,evidence[1:]):
            require(previous['human_deck']!=current['human_deck'],'edited human deck did not reach next mode/rematch')
            if previous['mode']==current['mode']==1: require(previous['bot_name']!=current['bot_name'],'public1v1 bot name did not vary')
        require(len(set(practice_settings))<=1,'public play changed the practice difficulty selection')
        report['practice_difficulty_snapshots']=practice_settings
        report.update(passed=True, remote_connections=0, invite_reads=0)
    except BaseException as error:
        report.update(passed=False, error=report.get('error', f'{type(error).__name__}: {error}'))
        raise
    finally:
        if process is not None:
            if process.poll() is None: process.terminate()
            process.wait(timeout=15)
            try:
                (output/f'native-{process.pid}.log').write_text(read_native_log(game, process.pid, since_tick=tick), encoding='utf-8')
            except Exception as error:
                report.update(passed=False, evidence_error=f'{type(error).__name__}: {error}')
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
    parser.add_argument('--mode', type=int, choices=(1, 2, 5), default=1)
    parser.add_argument('--modes', help='explicit sequence of up to eight modes1,2,4,5; includes original Edit Deck for mode4')
    parser.add_argument('--natural', action='store_true', help='wait for a natural result; never surrender automatically')
    parser.add_argument('--search-smoke', action='store_true')
    parser.add_argument('--visible', action='store_true', help='show the owned window for native UI capture/review')
    run(parser.parse_args())
