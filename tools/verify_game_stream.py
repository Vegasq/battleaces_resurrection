"""Read-only persistent REA Frida evidence and retained native AI/Quit owner proof.

One script may cover a pre-practice menu through OnDestroy return. This does not
prove pre-attachment startup, descendant/network/collection completeness, or that
silent hooks were exercised. Never launch, attach, query, or stop a process.
"""
from __future__ import annotations
import argparse
import json
from pathlib import Path, PureWindowsPath
import re

from tools.frida_game_source import matches_source, require
from tools.verify_game_observation import (
    ROOT, MAX_JSON, digest, integer, journal_summary, owner_proof, prepared_root, read,
)


def envelope(call):
    result = call['result']
    texts = [c['text'] for c in result.get('content', []) if c.get('type') == 'text']
    value = result.get('structuredContent')
    require(not result.get('isError') and isinstance(value, dict) and len(texts) == 1 and
            json.loads(texts[0]) == value, 'ambiguous or failed provider response')
    return value


def evidence(call, operation, session):
    value = envelope(call)
    require(value.get('confidence') == 'observed' and
            isinstance(value.get('evidence_id'), str) and
            re.fullmatch('ev_[0-9a-f]{64}', value['evidence_id']) and
            value.get('provider', {}).get('id') == 'frida' and
            value.get('operation') == operation and
            value.get('predicate_type') == 'rea.frida.instrumentation-observation' and
            value.get('parameters') == dict(session_id=session),
            'observed persistent provider operation/session required')
    return value


def payloads(value, script):
    require(value.get('messages_truncated') is False, 'provider message history truncated')
    messages = value['messages']
    require(messages and all(m.get('type') == 'send' and m.get('script_id') == script for m in messages),
            'script errors or mismatched messages')
    return [m['payload'] for m in messages]


def stream(start, load, statuses, close, journal, source, config, *, pid, quit_thread):
    require(matches_source(source, config), 'observer is not the canonical reviewed source')
    require(start['arguments'] == dict(mode='attach', device_id='local', pid=pid),
            'explicit local owned PID attach required')
    begun = envelope(start)
    session = begun.get('session_id')
    require(isinstance(session, str) and bool(session) and begun == dict(
        session_id=session, mode='attach', device_id='local', pid=pid,
        state='running', target=f'Battle Aces.exe (pid {pid})'), 'start session identity differs')
    args = load['arguments']
    require(set(args) == {'session_id', 'source_kind', 'path'} and args['session_id'] == session and
            args['source_kind'] == 'file' and PureWindowsPath(args['path']).name == 'observer.js' and
            PureWindowsPath(args['path']).is_absolute() and
            PureWindowsPath(config['journal']) == PureWindowsPath(args['path']).parent/'events.jsonl',
            'one selected file script required')
    loaded = evidence(load, 'load_frida_script', session)
    value = loaded['normalized_result']
    script = value.get('script_id')
    require(isinstance(script, str) and bool(script) and value.get('source_kind') == 'file' and
            value.get('source_path') == args['path'] and value.get('source_sha256') == digest(source),
            'loaded script identity/source differs')
    previous = payloads(value, script)
    require(isinstance(statuses, list) and 2 <= len(statuses) <= 64, 'bounded persistent status history required')
    ids = [loaded['evidence_id']]
    states = []
    for call in statuses:
        require(call['arguments'] == dict(session_id=session), 'status request session differs')
        item = evidence(call, 'frida_session_status', session)
        ids.append(item['evidence_id'])
        current = item['normalized_result']
        require(current.get('session_id') == session and current.get('device_id') == 'local' and
                current.get('pid') == pid and current.get('mode') == 'attach' and
                current.get('target') == begun['target'] and current.get('state') in ('running', 'detached') and
                current.get('scripts') == [dict(script_id=script, name='rea-'+script)],
                'persistent session/script identity differs')
        rows = payloads(current, script)
        require(rows[:len(previous)] == previous, 'cumulative provider history regressed or changed')
        previous = rows
        states.append(current['state'])
    require(states[-1] == 'detached' and all(s == 'running' for s in states[:-1]),
            'one running attachment followed by detached final observation required')
    require(close['arguments'] == dict(session_id=session) and envelope(close) == dict(target_state='unknown'),
            'explicit session cleanup response required')
    require(journal == previous, 'complete final provider/journal equality required')
    summary = journal_summary(journal, previous, config, pid=pid, quit_thread=quit_thread)
    require(summary['original_destroy_return_observed'], 'original same-thread OnDestroy return required')
    ready = next(i for i, row in enumerate(journal) if row['nativeReady'])
    require(all(row['nativeReady'] for row in journal[ready:]), 'native readiness lost')
    finish = next(i for i, row in enumerate(journal) if row['kind'] == 'lifecycle-return:RGameSingleton.OnDestroy')
    require(finish == len(journal)-1, 'unexpected records after original OnDestroy return')
    times = [journal[ready]['elapsedMs']] + [r['elapsedMs'] for r in journal[ready:finish]
        if r['kind'] == 'heartbeat'] + [journal[finish]['elapsedMs']]
    require(len(times) >= 3, 'heartbeat coverage required')
    max_gap = max(b-a for a, b in zip(times, times[1:]))
    require(max_gap <= 10000, 'observer heartbeat gap exceeds ten seconds')
    return dict(**summary, session_id=session, script_id=script, evidence_ids=ids,
                max_heartbeat_gap_ms=max_gap, single_script_ready_through_destroy=True,
                continuous_lifecycle_coverage=False, analytics_removal_qualified=False,
                close_target_state='unknown')


def practice_anchor(text, profile, native):
    patterns = [r'Local menu ready: .* BA_RESURRECTION_LOCAL_MENU_V1',
        r'NATIVE QUIT owned gate released: profile='+re.escape(profile)+r' BA_RESURRECTION_NATIVE_QUIT_GATE_V1',
        r'PRACTICE SMOKE original EditDeck mode4 callback: .*',
        r'Practice native EndOfGameResponse delivered; .*',
        r'PRACTICE SMOKE native Continue \(automated\)',
        r'NATIVE QUIT original confirmation dispatch: thread=(\d+) worldIdle=1 assetLoadingCount=0 naturalExitDeadlineSeconds=60']
    markers = []
    for pattern in patterns:
        found = list(re.finditer(r'^\[(\d+)\] '+pattern+r'$', text, re.M))
        require(len(found) == 1, 'one menu/gate/practice/result/Continue/Quit anchor required')
        markers.append(found[0])
    ticks = [int(m[1]) for m in markers]
    require(ticks == sorted(ticks) and [m.start() for m in markers] == sorted(m.start() for m in markers) and
            ticks[0] < ticks[1] < ticks[2], 'pre-practice native gate ordering differs')
    practice = native.get('practice', {})
    require(native.get('after_practice') is True and integer(native.get('launch_tick')) and
            integer(native.get('quit_dispatch_tick')) and integer(native.get('observed_exit_tick')),
            'post-practice owned timing required')
    trace = native.get('trace', [])
    require(len(trace) == 5 and trace[-2].get('event') == 'OnConfirm.dispatch' and
            trace[-1].get('event') == 'OnConfirm.return' and
            native['launch_tick'] <= ticks[0] and ticks[-2] <= native['quit_dispatch_tick'] == trace[-2].get('tick') <=
            ticks[-1] <= trace[-1].get('tick', -1) <= native['observed_exit_tick'] and
            int(markers[-1][2]) == trace[-2].get('thread') == trace[-1].get('thread'),
            'native anchor outside original owner callback/thread bounds')
    requested = list(re.finditer(r'^\[(\d+)\] Practice requested: match=([0-9a-f]{32}) '
        r'mode=4 selectedDeckSnapshot=1 standalone=1$', text, re.M))
    require(len(requested) == 1 and requested[0][2] == practice.get('match') and
            ticks[1] < int(requested[0][1]) <= ticks[2] and
            markers[1].start() < requested[0].start() < markers[2].start(),
            'native practice match/ready ordering differs')
    require(all(practice.get(key) is True for key in ('native_result', 'native_continue', 'returned_to_menu')) and
            integer(practice.get('bot_max_supply'), 1) and integer(practice.get('autonomous_action_records'), 5),
            'retained owner AI/result/Continue proof incomplete')
    return dict(menu_tick=ticks[0], ready_gate_tick=ticks[1], practice_callback_tick=ticks[2],
                result_tick=ticks[3], continue_tick=ticks[4], quit_tick=ticks[5],
                original_confirmation_dispatch_tick=native['quit_dispatch_tick'],
                readiness_before_practice=True, startup_before_attachment_covered=False,
                bot_movement_qualified=False)


def review(folder, owner_source):
    folder = folder.resolve(); owner_source = owner_source.resolve()
    require(folder.is_relative_to(ROOT/'local') and owner_source.is_relative_to(ROOT/'local'),
            'explicit ignored retained run and owner source required')
    files = {}
    def record(name):
        path = folder/name
        require(path.resolve().is_relative_to(folder), 'evidence path escaped run folder')
        raw, value = read(path); files[name] = digest(raw)
        return value
    harness = record('harness-verification.json'); native = record('native/verification.json')
    pid, thread = owner_proof(harness, native)
    owner = owner_source.read_bytes()
    require(len(owner) <= 256*1024 and digest(owner) == harness.get('source_sha256'), 'retained owner source differs')
    config = harness['config']
    source = (folder/'observer.js').read_bytes()
    require(len(source) <= 256*1024, 'observer source exceeds bound')
    files['observer.js'] = digest(source)
    prepared_root(harness, native, record('inputs.json'), source)
    require(native.get('command', [None])[0] == config['image'] and
            '-local-profile='+harness['profile'] in native['command'], 'selected owner image/profile differs')
    raw = (folder/'events.jsonl').read_bytes()
    require(0 < len(raw) <= MAX_JSON and raw.endswith(b'\n'), 'bounded complete journal lines required')
    files['events.jsonl'] = digest(raw)
    journal = [json.loads(line) for line in raw.splitlines()]
    start = record('rea-start.json')
    require(record('request.json') == start['arguments'], 'prepared attach request differs')
    load = record('rea-load.json')
    require(load['arguments']['path'] == str(folder/'observer.js') and
            config['journal'] == str(folder/'events.jsonl'), 'selected retained script/journal paths differ')
    summary = stream(start, load, record('rea-statuses.json'), record('rea-close.json'),
                     journal, source, config, pid=pid, quit_thread=thread)
    log = (folder/'native/native.log').read_bytes()
    require(len(log) <= MAX_JSON, 'retained native log exceeds bound')
    files['native/native.log'] = digest(log)
    anchor = practice_anchor(log.decode('utf-8').replace('\r\n', '\n'), harness['profile'], native)
    return dict(passed=True, scope=__doc__, stream=summary, native_anchor=anchor,
                retained_owner_source_sha256=digest(owner), input_sha256=files,
                source_sha256={p.relative_to(ROOT).as_posix(): digest(p.read_bytes()) for p in
                    (Path(__file__), ROOT/'tools/verify_game_observation.py',
                     ROOT/'tools/frida_game_source.py', ROOT/'tools/frida_control_source.py')})


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--run', type=Path, required=True)
    parser.add_argument('--owner-source', type=Path, required=True)
    parser.add_argument('--report', type=Path, required=True)
    args = parser.parse_args()
    require(args.report.resolve().is_relative_to(ROOT/'local'), 'ignored report destination required')
    result = review(args.run, args.owner_source)
    with args.report.open('x', encoding='utf-8', newline='\n') as target:
        target.write(json.dumps(result, indent=2)+'\n')
    print(json.dumps(dict(passed=True, rows=result['stream']['provider_rows'], analytics_removal_qualified=False)))


if __name__ == '__main__':
    main()
