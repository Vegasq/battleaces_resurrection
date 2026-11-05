"""Independent bounded review of the owned two-client relay outage run."""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path

ROOT=Path(__file__).resolve().parents[1]

def check(value,message):
    if not value:raise AssertionError(message)

def review(folder:Path):
    folder=folder.resolve()
    check(folder.is_relative_to(ROOT/'local') and folder.name.startswith(('privacy439-outage','privacy440-outage-sdk')),
          'owned outage evidence required')
    raw=(folder/'verification.json').read_bytes();report=json.loads(raw)
    check(report['passed'] is True and report['forced_cleanup'] is False and
          report['outage_running'] is True and report['recover_stage']=='running' and
          report['mode']==1 and report['humans']==2,'outage verifier scope differs')
    check(report['source_files_unchanged'] and report['source_sha256_at_start']==report['source_sha256_at_finish'],
          'source changed during run')
    current_sources_match=all((ROOT/name).is_file() and
        hashlib.sha256((ROOT/name).read_bytes()).hexdigest()==digest
        for name,digest in report['source_sha256_at_start'].items())
    if folder.name.startswith('privacy440-outage-sdk'):
        check(current_sources_match,'current outage source differs')
    check(all(report[k] for k in ('adapters_unchanged','config_unchanged','package_files_unchanged',
              'assets_unchanged','shared_channels_unchanged','fixture_tokens_not_logged',
              'temporary_pki_removed')),'owned package/config/asset/shared preservation differs')
    outage=report['outage'];relay=report['stream_delay']['relay']
    check(outage['native_frames']==[600,600] and outage['before']['rooms']==1 and
          outage['before']['sessions']==2 and outage['control']['disconnected']==2 and
          outage['control']['port']==report['stream_delay']['route_port'] and
          outage['connect_ex']!=0 and outage['restored_seconds']-outage['started_seconds']>=2 and
          outage['before_retry']['sessions']==0 and outage['before_retry']['rooms']==0,
          'outage did not interrupt two running clients and refuse the same port')
    check(relay['accepted']==4 and relay['forwarded_bytes']>0 and
          relay['active_connections']==relay['rejected']==relay['failures']==0 and
          relay['listener_closed'] and relay['thread_stopped'],'relay did not drain')
    events=[json.loads(line) for path in sorted((folder/'host-data/logs').glob('events.jsonl*'),reverse=True)
            for line in path.read_text(encoding='utf-8').splitlines()]
    matches=[e['match'] for e in events if e['event']=='match_created']
    check(len(matches)==2 and matches==[report['recovery']['aborted_match'],
          report['recovery']['replacement_match']] and matches[0]!=matches[1],
          'raw match order differs')
    check(sum(e['event']=='match_aborted' and e.get('match')==matches[0] for e in events)==1 and
          sum(e['event']=='match_completed' and e.get('match')==matches[1] for e in events)==1 and
          report['match']['match']==matches[1] and report['match']['frames']==1220,
          'raw abort/completion differs')
    check(report['server']['recovery_sessions']==dict(both_replaced=True) and
          report['server']['listener_closed'] and report['server']['state_lock_released'] and
          report['server']['status_writer_drained'],'host sessions or shutdown differ')
    check(len(report['jobs'])==3 and all(j['active_processes']==j['total_terminated_processes']==0
          and j['launch']['job_attached_before_resume'] for j in report['jobs']),
          'owned jobs not naturally drained')
    check(len(report['clients'])==2 and len(report['worker_cleanup'])==3 and
          all(w['exit_code']==0 and w['reaped'] for w in report['worker_cleanup']),
          'native clients or workers differ')
    for index,client in enumerate(report['clients']):
        log=(folder/f'client-{index}/native.log').read_text(encoding='utf-8')
        check(client['driver_report']['game_exit_code']==client['driver_report']['launcher_exit_code']==0 and
              client['driver_report']['tls_connections']==2 and
              [event['event'] for event in client['trace']]==[
                  'armed','Show.dispatch','Show.return','OnConfirm.dispatch','OnConfirm.return'],
              'client TLS/Quit flow differs')
        check(log.count('RECOVERY SMOKE invoking original disconnected modal OnConfirm')==1 and
              log.count('Public native match joined: ticket=1 ')==1 and
              log.count('Public native match joined: ticket=2 ')==1 and
              'NATIVE QUIT owned menu verified:' in log,'native recovery/Quit log differs')
    return dict(passed=True,scope='owned recipe38 two-client loopback relay outage',
                verifier_sha256=hashlib.sha256(raw).hexdigest(),
                clients=2,aborted_matches=1,completed_matches=1,
                old_native_frames=report['outage']['native_frames'],
                replacement_frames=report['match']['frames'],
                quit_exits=[0,0],natural_job_cleanup=True,
                current_sources_match=current_sources_match,
                sdk_queue_retry_observed=False,whole_wire_observed=False,final_installed=False)

def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--folder',type=Path,required=True)
    parser.add_argument('--output',type=Path,required=True)
    args=parser.parse_args()
    output=args.output.resolve()
    check(output.is_relative_to(ROOT/'local') and not output.exists(),'fresh owned review output required')
    result=review(args.folder)
    output.parent.mkdir(parents=True,exist_ok=True)
    output.write_text(json.dumps(result,indent=2)+'\n',encoding='utf-8')
    print(json.dumps(result))

if __name__=='__main__':main()
