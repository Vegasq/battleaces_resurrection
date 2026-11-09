"""Owned native public-AI timing prefix over the real configured Internet route.

Creates an isolated test identity. Stops only its retained Popen/Job handles.
Records QPC presentation timing without the expensive -lan-audit state capture.
The exact first --frames prefix must pass the unchanged pacing limits.
The forced owned exit does not qualify natural result/Continue/Quit behavior.
"""
import argparse
import asyncio
import ctypes
import hashlib
import json
from pathlib import Path
import re
import shutil
import socket
import subprocess
import sys
import time
import traceback

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from client_patch.transport import launcher, bridge, rc_setup
from server.worker_client import _WindowsJob
from tools.run_secure_match import read_native_log
from tools.frame_timing import read_trace, matches, measure, qualify


async def run(args):
    game, output, helper = args.game.resolve(), args.output.resolve(), args.helper.resolve()
    assert game.is_relative_to(ROOT/'local') and output.is_relative_to(ROOT/'local')
    assert 600 <= args.frames <= 1800
    output.mkdir(exist_ok=False, parents=True)
    original_helper = (game/'BattleAcesOffline.dll').read_bytes()
    manifest_path = game/'.battleaces-resurrection/patch-manifest.json'
    original_manifest = manifest_path.read_bytes()
    manifest = json.loads(original_manifest)
    manifest['helper_sha256'] = hashlib.sha256(helper.read_bytes()).hexdigest()
    report = dict(passed=False, route='134.209.176.39:47623', target_frames=args.frames,
                  public_mode=args.mode,
                  probe_sha256=hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
                  helper_sha256=manifest['helper_sha256'], label=args.label,
                  cleanup='forced owned termination; no normal Quit/result claim')
    process = job = writer = parent = child = task = None
    started = time.monotonic()
    config = dict(schema=4, game_directory=str(game), display_name='Lag probe '+args.label,
                  local_profile='live_lag_probe', server_host='134.209.176.39',
                  server_port=47623, room='community', fullscreen=False)
    config_path = output/'client-config.json'
    config_path.write_text(json.dumps(config), encoding='utf-8')
    selected = rc_setup.settings(config, config_path)
    target = rc_setup.remote(selected, config_path)
    local = dict(selected, server_host='127.0.0.1')
    options = argparse.Namespace(run_name='live-lag-probe', unified_experimental=True,
                                 player_features=True, audit=False, smoke=True)
    try:
        (game/'BattleAcesOffline.dll').write_bytes(helper.read_bytes())
        manifest_path.write_text(json.dumps(manifest, indent=2), encoding='utf-8')
        launcher.verify_game(game, community=True, bridge_version=2, unified=True, player_features=True)
        parent, child = socket.socketpair(socket.AF_INET)
        parent.setblocking(False)
        reader, writer = await asyncio.open_connection(sock=parent)
        command = launcher.game_arguments(local, None, child.fileno(), options)
        command[command.index('-logFile')+1] = str(output/'game.log')
        command += ['-public-queue-smoke', f'-public-queue-smoke-mode={args.mode}', '-frame-timing',
                    f'-frame-timing-frames={args.frames}']
        startup = subprocess.STARTUPINFO()
        startup.dwFlags |= subprocess.STARTF_USESHOWWINDOW
        startup.wShowWindow = 0
        startup.lpAttributeList = {'handle_list':[child.fileno()]}
        clock = ctypes.WinDLL('kernel32').GetTickCount64
        clock.restype = ctypes.c_ulonglong
        launch_tick = clock()
        child.set_inheritable(True)
        try:
            process = subprocess.Popen(command, cwd=game, startupinfo=startup,
                                       close_fds=True, creationflags=subprocess.CREATE_NO_WINDOW)
        finally:
            child.set_inheritable(False)
        job = _WindowsJob(process.pid)
        child.close()
        task = asyncio.create_task(bridge.Bridge(reader, writer, target, version=2).run())
        report.update(pid=process.pid, player_id=target.player_id, launch_tick=launch_tick)
        (output/'process.json').write_text(json.dumps(report, indent=2))
        deadline = time.monotonic()+200
        while time.monotonic()<deadline:
            if process.poll() is not None:
                raise RuntimeError('owned client exited before target')
            log = await asyncio.to_thread(read_native_log, game, process.pid, since_tick=launch_tick)
            for failure in ('Offline loop stopped in ', 'Public client failure:', 'Client lifecycle invariant failed:',
                            'Frame timing capture stopped:'):
                if failure in log:
                    raise RuntimeError(next(line for line in log.splitlines() if failure in line))
            received = [int(frame) for frame in re.findall(r'LAN received frame (\d+),', log)]
            # Let the fixed prefix present fully and dump its in-memory trace
            # after measurement, before terminating the owned process.
            if received and max(received)>=args.frames+8:
                report['target_reached'] = max(received)
                report['match'] = re.search(r'Public match assignment: ticket=1 match=([0-9a-f]{32}) ',log)[1]
                break
            await asyncio.sleep(.25)
        else:
            raise TimeoutError('live match did not reach target')
    except BaseException as error:
        report.update(error=f'{type(error).__name__}: {error}', traceback=traceback.format_exc())
    finally:
        if process is not None:
            if process.poll() is None:
                process.terminate()
            await asyncio.to_thread(process.wait, timeout=15)
        if job is not None:
            job.close()
        if task is not None:
            task.cancel()
            await asyncio.gather(task, return_exceptions=True)
        if writer is not None:
            writer.close()
            try:
                await asyncio.wait_for(writer.wait_closed(), 3)
            except (OSError, TimeoutError):
                writer.transport.abort()
        if child is not None:
            child.close()
        if process is not None:
            log = read_native_log(game, process.pid, since_tick=launch_tick)
            (output/'native.log').write_text(log, encoding='utf-8')
            report['presentation_clock_active'] = 'BA_RESURRECTION_ONLINE_PRESENTATION_V1' in log
            trace = game/'investigation/runtime'/f'frame-timing-{process.pid}.tsv'
            if trace.is_file():
                shutil.copyfile(trace, output/trace.name)
                timing = matches(read_trace(trace))
                report['timing'] = [measure(part) for part in timing]
                prefix = [row for row in read_trace(trace) if (row['frame'] < args.frames if row['event'] in ('arrival','apply') else row['presented'] < args.frames)]
                report['timing_gate'] = qualify(prefix, [args.frames], max_short_gaps=2, max_gap_ms=100)
                publication = [dict(row, event='view') if row['event']=='publication' else row
                               for row in prefix if row['event']!='view']
                report['publication_gate'] = qualify(publication, [args.frames], max_short_gaps=0, max_gap_ms=100)
                report['passed'] = (not report.get('error') and report['presentation_clock_active'] and len(timing)==1 and
                                    report['timing'][0]['applied_frames']>=args.frames and
                                    report['timing_gate']['passed'] and report['publication_gate']['passed'])
        (game/'BattleAcesOffline.dll').write_bytes(original_helper)
        manifest_path.write_bytes(original_manifest)
        report['elapsed_seconds'] = round(time.monotonic()-started,3)
        (output/'report.json').write_text(json.dumps(report,indent=2),encoding='utf-8')
    print(json.dumps(report),flush=True)
    return not report['passed']


if __name__=='__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ('game','output','helper'):
        parser.add_argument('--'+name,type=Path,required=True)
    parser.add_argument('--label',choices=('baseline','candidate'),required=True)
    parser.add_argument('--frames',type=int,default=1200)
    parser.add_argument('--mode',type=int,choices=(1,2,5),default=5)
    raise SystemExit(asyncio.run(run(parser.parse_args())))
