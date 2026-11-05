"""Review current-pair running recovery with prelaunch SDK-root notifications."""
from __future__ import annotations

import argparse
from datetime import datetime
import hashlib
import json
from pathlib import Path, PureWindowsPath

from client_patch.patcher.telemetry import RECIPE_VERSION, RUNTIME_VALIDATED
from tools.package_integrity import verify

ROOT=Path(__file__).resolve().parents[1]


def sha(path):return hashlib.sha256(path.read_bytes()).hexdigest()


def stamp(value):return datetime.fromisoformat(value.replace('Z','+00:00'))


def review(case,watch,control,packages,game,assets,helper_receipt):
    report=json.loads((case/'verification.json').read_text(encoding='utf-8'))
    run=json.loads((watch/'orchestration.json').read_text(encoding='utf-8'))
    observed=json.loads((watch/'watch.json').read_text(encoding='utf-8'))
    positive=json.loads((control/'observer/watch.json').read_text(encoding='utf-8'))
    build=json.loads((packages/'build-report.json').read_text(encoding='utf-8'))
    installed=json.loads((game/'.battleaces-resurrection/patch-manifest.json').read_text(encoding='utf-8'))
    receipt=json.loads(helper_receipt.read_text(encoding='utf-8'))
    bound=json.loads((ROOT/'local/privacy293-root-binding01/verification.json').read_text(encoding='utf-8'))
    source_root=json.loads((ROOT/'local/privacy269-startup01/verification.json').read_text(encoding='utf-8'))['sdk_cache_root']
    assert bound['passed'] and PureWindowsPath(observed['root'])==PureWindowsPath(source_root)
    assert RECIPE_VERSION==installed['telemetry']['recipe_version']==38
    assert RUNTIME_VALIDATED is installed['telemetry']['runtime_validated'] is False
    assert report['passed'] and not report['forced_cleanup'] and not report['rc_open']
    assert report['mode']==1 and report['humans']==2 and report['recover_stage']=='running'
    assert Path(report['packages']).resolve()==packages
    assert report['assets_manifest_sha256']==sha(assets/'asset-manifest.json')
    assert receipt['helper_sha256']==installed['helper_sha256']==sha(game/'BattleAcesOffline.dll')
    assert report['helper_build']['sha256']==sha(helper_receipt)
    assert sha(packages/'battleaces-client-win64/program/client-helper/BattleAcesOffline.dll')==receipt['helper_sha256']
    assert sha(game/'GameAssembly.dll')==installed['patched_sha256']
    for kind in ('client','server'):
        package=packages/f'battleaces-{kind}-win64'
        assert verify(package,kind)
        entry=build['packages'][kind]
        assert sha(packages/entry['archive'])==entry['sha256']
    assert build['versions']['game_build']==37822
    assert sha(ROOT/'client_patch/patcher/telemetry.py')==sha(packages/'battleaces-client-win64/program/app/client_patch/patcher/telemetry.py')
    for key in ('source_files_unchanged','shared_channels_unchanged','adapters_unchanged',
                'config_unchanged','package_files_unchanged','assets_unchanged',
                'fixture_tokens_not_logged','temporary_pki_removed'):
        assert report[key] is True,key
    fault,recovery,match=report['fault'],report['recovery'],report['match']
    assert fault['stage']=='running' and fault['room_state']=='running'
    assert fault['after_frame']==600 and fault['next_frame']>=601
    assert fault['loaded']==fault['peer_seats']==[0,1]
    assert report['fault_native_frames']==[600,600]
    assert recovery['aborted_match']==fault['match']
    assert recovery['replacement_match']==match['match']!=fault['match']
    assert recovery['same_native_processes'] and recovery['native_worlds_per_client']==2
    assert len(recovery['aborted_clients'])==2
    assert all(row['received_frames']>=600 for row in recovery['aborted_clients'])
    assert match['frames']>=1200 and match['result']['complete']
    assert len(report['clients'])==2
    assert all(row['driver_report']['passed'] and row['driver_report']['launcher_exit_code']==
               row['driver_report']['game_exit_code']==0 for row in report['clients'])
    server=report['server']
    assert server['passed'] and server['listener_closed'] and server['status_writer_drained']
    assert server['state_lock_released'] and len(server['workers'])==3
    assert all(row['exit_code']==0 and row['reaped'] and row['failure'] is None for row in server['workers'])
    assert all(server['final_state'][key]==0 for key in ('active_workers','rooms','retired','entries','offers','cleanup','sessions'))
    assert server['final_state']['lobbies']==[]
    assert [row['total_processes'] for row in report['jobs']]==[7,2,2]
    assert all(row['active_processes']==row['total_terminated_processes']==0 for row in report['jobs'])
    assert run['passed'] and run['verifier_exit_code']==0
    assert Path(run['case']).resolve()==case
    assert PureWindowsPath(run['sdk_root'])==PureWindowsPath(source_root)
    assert observed==run['watch_result'] and positive==run['control_result']
    assert observed['scope'].startswith('Read-only Windows FileSystemWatcher')
    assert observed['stopped_by_sentinel'] and observed['buffer_bytes']==65536
    assert set(observed['counts'])=={'Created','Changed','Deleted','Renamed','Error'}
    assert all(value==0 for value in observed['counts'].values())
    assert positive['stopped_by_sentinel'] and positive['counts']['Created']>=1
    assert positive['counts']['Changed']>=1 and positive['counts']['Deleted']>=1
    assert positive['counts']['Error']==0
    assert stamp(observed['started_utc'])<stamp(run['verifier_launched_utc'])
    assert stamp(run['verifier_finished_utc'])<stamp(observed['finished_utc'])
    assert (watch/'ready.txt').is_file() and (watch/'stop.txt').is_file()
    return dict(passed=True,scope='Current recipe38 isolated running disconnect/recovery and named SDK-root metadata notifications only; no queue read,all-I/O or wire proof',
                recipe=38,frames=match['frames'],aborted_frames=recovery['aborted_authoritative_frames'],
                same_native_processes=True,watch_counts=observed['counts'],
                report_sha256=sha(case/'verification.json'),orchestration_sha256=sha(watch/'orchestration.json'),
                watch_sha256=sha(watch/'watch.json'),positive_sha256=sha(control/'observer/watch.json'),
                watcher_source_sha256=sha(ROOT/'tools/watch_sdk_cache_events.ps1'),
                orchestrator_source_sha256=sha(ROOT/'tools/verify_d5_running_cache359.py'),
                full_d5_qualified=False)


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    for name in ('case','watch','control','packages','game','assets','helper-receipt'):
        parser.add_argument('--'+name,type=Path,required=True)
    args=parser.parse_args()
    paths={name.replace('-','_'):getattr(args,name.replace('-','_')).resolve()
           for name in ('case','watch','control','packages','game','assets','helper-receipt')}
    assert all(path.is_relative_to(ROOT/'local') for path in paths.values())
    result=review(**paths)
    output=paths['case']/'cache-review.json'
    output.write_text(json.dumps(result,indent=2)+'\n',encoding='utf-8')
    print(json.dumps({'passed':result['passed'],'frames':result['frames'],
                      'watch_counts':result['watch_counts']}))


if __name__=='__main__':main()
