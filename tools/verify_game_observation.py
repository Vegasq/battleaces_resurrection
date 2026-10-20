"""Review bounded REA game windows against canonical source and retained owner proof.

Never launch, attach, query or stop a process. A pass requires an observed original
OnDestroy return and the retained owner's natural Quit/empty job report. It does
not qualify continuous coverage, absence of analytics/traffic, descendants,
rendered movement or independent validation of the owner's OS observations.
"""
from __future__ import annotations
import argparse
import hashlib
import json
from pathlib import Path, PureWindowsPath
import re

from tools.frida_game_source import ENTRIES, matches_source, require, validate_config

ROOT = Path(__file__).resolve().parents[1]
UNITY_SHA = '3cca44b518abc803882c8d8ae0fff44e89c3f66f85ae9b1239e460ff14874e48'
GAME_SHAS = frozenset((
    'fd67ed32e434838118c669112f4b6c32522b26ad1b2877696555bbdda6bf1728',
    'f7d44daa146c2d75dc330a533092737e346a68784613ebe5ae3d9c171a98abe5'))
MAX_JSON = 8 * 1024 * 1024


def digest(raw):
    return hashlib.sha256(raw).hexdigest()


def integer(value, minimum=0):
    return type(value) is int and minimum <= value <= 2**53-1


def owner_proof(harness, native):
    """Cross-check retained owner records; this is not a fresh OS observation."""
    require(harness.get('passed') is True and native.get('passed') is True, 'owner report failed')
    require(type(harness.get('native_verifier_exit_code')) is int and harness['native_verifier_exit_code'] == 0,
            'native verifier did not exit successfully')
    require(harness.get('quit_gate_release', {}).get('native_hooks_ready') is True,
            'owner gate released without hook readiness')
    pid = native.get('pid')
    require(integer(pid, 1) and harness.get('pid') == pid, 'owner PID differs')
    require(harness.get('forced_cleanup') is False and native.get('forced_cleanup') is False and
            native.get('natural_exit') is True and native.get('owned_process_reaped') is True and
            type(native.get('exit_code')) is int and native['exit_code'] == 0, 'natural Quit required')
    require(harness.get('job_assigned') == dict(total_processes=1, active_processes=1, total_terminated_processes=0) and
            harness.get('job_before_close') == dict(total_processes=1, active_processes=0, total_terminated_processes=0) and
            all(type(value) is int for key in ('job_assigned', 'job_before_close') for value in harness[key].values()),
            'owned job did not settle naturally')
    require(native.get('source_files_unchanged') is True and
            native.get('source_sha256_at_start') == native.get('source_sha256_at_finish') and
            bool(native.get('source_sha256_at_start')) and native.get('shared_settings_unchanged') is True and
            native.get('shared_settings_before') == native.get('shared_settings_after'), 'owner input invariants failed')
    images = harness.get('game_components_before', {})
    require(images == harness.get('game_components_after') and set(images) == {'UnityPlayer.dll', 'GameAssembly.dll'} and
            images['UnityPlayer.dll'] == UNITY_SHA and images['GameAssembly.dll'] in GAME_SHAS and
            harness.get('source_unchanged') is True and harness.get('observer_unchanged') is True,
            'reviewed selected-file identities required')
    trace = native.get('trace', [])
    require([r.get('event') for r in trace] == ['armed', 'Show.dispatch', 'Show.return', 'OnConfirm.dispatch', 'OnConfirm.return'],
            'original Quit trace differs')
    thread = trace[0].get('thread')
    require(integer(thread, 1) and all(r.get('pid') == pid and r.get('thread') == thread and integer(r.get('tick')) for r in trace) and
            all(a['tick'] <= b['tick'] for a, b in zip(trace, trace[1:])), 'Quit thread/timing differs')
    dispatch, exit_tick = native.get('quit_dispatch_tick'), native.get('observed_exit_tick')
    require(dispatch == trace[-2]['tick'] and integer(exit_tick) and 0 <= exit_tick-dispatch < 60000 and
            native.get('native_quit_passed') is True, 'Quit exit boundary differs')
    return pid, thread


def prepared_root(harness, native, settings, source):
    """Bind the original preparation receipt to final owner metadata and script."""
    config = settings['config']
    validate_config(config)
    require(config == harness['config'] and settings.get('run_id') == harness.get('run_id') == config['runId'],
            'prepared owner run nonce differs')
    require(isinstance(native.get('profile'), str) and native['profile'].startswith('nativestest_') and
            settings.get('profile') == harness.get('profile') == native['profile'], 'prepared owner profile differs')
    require(settings.get('observer_sha256') == harness.get('observer_sha256') == digest(source),
            'prepared observer hash differs')
    owner_sha = harness.get('source_sha256')
    require(isinstance(owner_sha, str) and re.fullmatch('[0-9a-f]{64}', owner_sha) and
            settings.get('source_sha256') == owner_sha, 'prepared owner source hash differs')
    require(settings.get('game_components_before') == harness['game_components_before'],
            'prepared selected-file hashes differ')


def window(capture, journal, raw_source, config, *, pid, quit_thread):
    """Qualify only provider-corroborated journal rows, exposing any trailing rows."""
    validate_config(config)
    require(matches_source(raw_source, config), 'observer is not the canonical reviewed source')
    args = capture['arguments']
    require(set(args) == {'mode', 'device_id', 'pid', 'source_kind', 'path', 'duration_ms'} and
            args['mode'] == 'attach' and args['device_id'] == 'local' and args['pid'] == pid and
            args['source_kind'] == 'file' and integer(args['duration_ms'], 1) and args['duration_ms'] <= 60000,
            'bounded local attach request required')
    source_path = PureWindowsPath(args['path'])
    require(source_path.is_absolute() and source_path.name == 'observer.js' and
            PureWindowsPath(config['journal']) == source_path.parent/'events.jsonl', 'window paths differ')
    result = capture['result']
    evidence = result['structuredContent']
    texts = [c['text'] for c in result.get('content', []) if c.get('type') == 'text']
    require(not result.get('isError') and len(texts) == 1 and json.loads(texts[0]) == evidence,
            'ambiguous or failed provider evidence')
    require(evidence.get('confidence') == 'observed' and isinstance(evidence.get('evidence_id'), str) and
            re.fullmatch('ev_[0-9a-f]{64}', evidence['evidence_id']), 'observed provider Evidence identity required')
    observed = evidence['normalized_result']
    require(evidence.get('provider', {}).get('id') == 'frida' and
            evidence.get('operation') == 'instrument_with_frida' and
            evidence.get('predicate_type') == 'rea.frida.instrumentation-observation', 'wrong provider operation')
    session = observed.get('session_id')
    require(isinstance(session, str) and bool(session) and evidence['parameters'] ==
            dict(session_id=session, device_id='local', mode='attach', pid=pid), 'provider session differs')
    require(observed.get('pid') == pid and observed.get('mode') == 'attach' and observed.get('device_id') == 'local' and
            observed.get('state') in ('running', 'detached') and observed.get('messages_truncated') is False and
            observed.get('cleanup_error') is None and observed.get('source_kind') == 'file' and
            observed.get('source_path') == args['path'] and observed.get('source_sha256') == digest(raw_source),
            'provider identity/source/cleanup differs')
    scripts = observed['scripts']
    require(len(scripts) == 1 and isinstance(scripts[0].get('script_id'), str) and bool(scripts[0]['script_id']),
            'one nonempty script identity required')
    messages = observed['messages']
    require(messages and all(m.get('type') == 'send' and m.get('script_id') == scripts[0]['script_id'] for m in messages),
            'script errors or mismatched messages')
    rows = [m['payload'] for m in messages]
    require(len(journal) >= len(rows) and journal[:len(rows)] == rows, 'provider/journal prefix differs')
    return dict(evidence=evidence['evidence_id'], provider_state=observed['state'],
                **journal_summary(journal, rows, config, pid=pid, quit_thread=quit_thread))


def journal_summary(journal, rows, config, *, pid, quit_thread):
    """Validate canonical rows shared by real one-shot and persistent adapters."""
    validate_config(config)
    require(journal and rows and journal[:len(rows)] == rows, 'provider/journal prefix differs')
    expected = {f'{name}:{label}': dict(rva=rva, guard=guard)
                for name, entries in ENTRIES.items() for rva, label, guard in entries}
    before, installed_before, elapsed, ready_at = {}, {}, -1, None
    for sequence, row in enumerate(journal, 1):
        require(row.get('schema') == 2 and integer(row.get('sequence'), 1) and row['sequence'] == sequence and row.get('runId') == config['runId'] and
                row.get('pid') == pid and integer(row.get('thread'), 1) and row.get('architecture') == 'x64' and
                row.get('pointerSize') == 8 and row.get('errors') == [], 'journal identity/error differs')
        require(integer(row.get('elapsedMs')) and row['elapsedMs'] >= elapsed, 'journal timing regressed')
        elapsed = row['elapsedMs']
        counts = row['counts']
        require(set(before) <= set(counts) and all(integer(c) and c >= before.get(k, 0) for k, c in counts.items()),
                'counter missing, invalid or regressed')
        installed = {h['key']: h for h in row['installed']}
        require(len(installed) == len(row['installed']) and all(installed.get(k) == v for k, v in installed_before.items()),
                'installed guard/offset changed')
        guarded = {k: v for k, v in installed.items() if v.get('guarded') is True}
        require(set(guarded) <= set(expected), 'unreviewed native hook')
        for key, hook in guarded.items():
            require(hook.get('guardHex') == expected[key]['guard'] and int(hook['offset'], 16) == expected[key]['rva'],
                    'native guard/offset differs')
        ready = set(guarded) == set(expected)
        require(row.get('nativeReady') is ready, 'native readiness differs')
        loaded = {m['name']: m for m in row['loadedNative']}
        require(len(loaded) == len(row['loadedNative']) and set(loaded) <= set(config['native']), 'unreviewed loaded module')
        for name, module in loaded.items():
            cfg = config['native'][name]
            require(module == dict(name=name, path=cfg['path'], size=cfg['size']), 'loaded module path/size differs')
        if ready:
            require(set(loaded) == set(config['native']) and set(expected) <= set(counts), 'ready without modules/counters')
            if ready_at is None and sequence <= len(rows):
                ready_at = elapsed
        before, installed_before = counts, installed
    require(ready_at is not None, 'provider never observed all native hooks ready')
    lifecycle = [r for r in rows if r['kind'].startswith('lifecycle-')]
    positive = ([r['kind'] for r in lifecycle] == ['lifecycle-enter:RGameSingleton.OnDestroy', 'lifecycle-return:RGameSingleton.OnDestroy'] and
                all(r['nativeReady'] and r['thread'] == quit_thread and
                    r['counts']['gameassembly.dll:RGameSingleton.OnDestroy'] == 1 for r in lifecycle))
    return dict(pid=pid, run_id=config['runId'],
                provider_rows=len(rows), journal_rows=len(journal), trailing_journal_rows=len(journal)-len(rows),
                native_ready_ms=ready_at, last_provider_ms=rows[-1]['elapsedMs'], last_journal_ms=journal[-1]['elapsedMs'],
                original_destroy_return_observed=positive,
                native_entry_lower_bounds={k: rows[-1]['counts'][k] for k in expected})


def read(path):
    raw = path.read_bytes()
    require(len(raw) <= MAX_JSON, 'retained record exceeds review bound')
    return raw, json.loads(raw.decode('utf-8-sig'))


def review(folder, owner_source):
    folder = folder.resolve()
    require(folder.is_relative_to(ROOT/'local'), 'owned ignored evidence directory required')
    hraw, harness = read(folder/'harness-verification.json')
    nraw, native = read(folder/'native/verification.json')
    pid, thread = owner_proof(harness, native)
    owner_source = owner_source.resolve()
    require(owner_source.is_relative_to(ROOT/'local'), 'explicit retained owner source must be ignored/local')
    raw_owner_source = owner_source.read_bytes()
    require(len(raw_owner_source) <= 256*1024 and digest(raw_owner_source) == harness.get('source_sha256'),
            'retained owner source file differs')
    require(native.get('command', [None])[0] == harness['config']['image'] and
            native.get('profile') == harness.get('profile') and
            '-local-profile='+native['profile'] in native['command'], 'owner selected image/profile differs')
    summaries = []
    inputs = {}
    root_inputs_sha = digest((folder/'inputs.json').read_bytes())
    for base in [folder] + sorted(p for p in folder.glob('segment*') if p.is_dir()):
        paths = [base/name for name in ('inputs.json', 'observer.js', 'events.jsonl', 'rea-evidence.json', 'request.json')]
        require(all(p.resolve().is_relative_to(folder) for p in paths), 'window evidence escaped run folder')
        raw_settings, settings = read(paths[0]); raw_capture, capture = read(paths[3])
        raw_request, request = read(paths[4])
        require(capture['arguments'] == request, 'prepared attach request differs from provider request')
        source = paths[1].read_bytes(); raw_journal = paths[2].read_bytes()
        require(len(source) <= 256*1024 and len(raw_journal) <= MAX_JSON, 'source/journal exceeds review bound')
        config = settings['config']
        if base == folder:
            require(digest(raw_settings) == root_inputs_sha, 'root preparation changed during review')
            prepared_root(harness, native, settings, source)
        else:
            require(settings.get('parent_inputs_sha256') == root_inputs_sha and
                    settings.get('source_sha256') == digest(source) and settings.get('selected_pid_live') is True,
                    'prepared segment source/parent/live observation differs')
        require(PureWindowsPath(config['journal']) == PureWindowsPath(str(paths[2])) and
                capture['arguments']['path'] == str(paths[1]), 'retained window paths differ')
        require(config['image'] == harness['config']['image'] and config['native'] == harness['config']['native'],
                'window selected modules differ from owner input')
        rows = [json.loads(line) for line in raw_journal.splitlines()]
        summaries.append(window(capture, rows, source, config, pid=pid, quit_thread=thread))
        inputs.update({p.relative_to(folder).as_posix(): digest(raw) for p, raw in
                       zip(paths, (raw_settings, source, raw_journal, raw_capture, raw_request))})
    require(len({s['run_id'] for s in summaries}) == len(summaries), 'window run nonce reused')
    require(any(s['original_destroy_return_observed'] for s in summaries), 'no provider-observed original OnDestroy return')
    return dict(passed=True, scope=__doc__, owner_pid=pid, original_quit_thread=thread, windows=summaries,
                owner_report_sha256=dict(harness=digest(hraw), native=digest(nraw)), input_sha256=inputs,
                retained_owner_source_sha256=digest(raw_owner_source),
                continuous_lifecycle_coverage=False, analytics_removal_qualified=False,
                source_sha256={p.relative_to(ROOT).as_posix(): digest(p.read_bytes()) for p in
                               (Path(__file__), ROOT/'tools/frida_game_source.py', ROOT/'tools/frida_control_source.py')})


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--run', type=Path, required=True)
    parser.add_argument('--owner-source', type=Path, required=True, help='explicit retained owner harness source, read only')
    parser.add_argument('--report', type=Path, required=True)
    args = parser.parse_args()
    require(args.report.resolve().is_relative_to(ROOT/'local'), 'ignored report destination required')
    result = review(args.run, args.owner_source)
    with args.report.open('x', encoding='utf-8', newline='\n') as stream:
        stream.write(json.dumps(result, indent=2)+'\n')
    print(json.dumps(dict(passed=result['passed'], windows=len(result['windows']),
                         analytics_removal_qualified=False)))


if __name__ == '__main__':
    main()
