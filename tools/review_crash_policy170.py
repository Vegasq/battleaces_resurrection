"""Fail-closed review of the bounded native crash observation, not full D5."""
import argparse
from collections import Counter
import hashlib
import json
from pathlib import Path

NETWORK = ('connect', 'WSAConnect', 'send', 'recv', 'sendto', 'WSASendTo',
           'getaddrinfo', 'GetAddrInfoW', 'GetAddrInfoExW')


def require(value, message):
    if not value:
        raise ValueError(message)


def stream(normalized, pid, run_id):
    require(normalized['messages_truncated'] is False, 'Provider capture truncated')
    require(normalized['pid'] == pid and normalized['state'] == 'detached', 'Wrong/live session')
    messages = normalized['messages']
    require(messages and all(m['type'] == 'send' for m in messages), 'Missing events or script error')
    events = [m['payload'] for m in messages]
    require([e['seq'] for e in events] == list(range(1, len(events) + 1)), 'Sequence gap/duplicate')
    require(all(e['pid'] == pid and e['runId'] == run_id and e['schema'] == 1 for e in events),
            'Foreign event identity')
    require(not any(e['kind'] in ('decode-error', 'budget-exceeded', 'unresolved-file-root',
                                 'crash-state-unavailable') for e in events), 'Incomplete observation')
    for event in events:
        data = event['data']
        require(not data.get('errors') and not data.get('overflow') and not data.get('unknownRelativeRoots'),
                'Observer error/overflow/unknown root')
    return events


def aggregate(events, final):
    require(final['data']['boundary'] == 'filter-return', 'Wrong crash boundary')
    totals = final['data']['fileAggregate']
    require(totals['overflow'] is False, 'File aggregate overflow')
    rows = []
    for event in events:
        if event['kind'] != 'policy-files':
            continue
        require(event['seq'] < final['seq'] and event['data']['boundary'] == 'filter-return' and
                event['data']['offset'] == len(rows), 'Missing/duplicate/reordered aggregate chunk')
        rows.extend(event['data']['rows'])
    require(len(rows) == totals['rows'] and 0 < len(rows) <= 8192, 'Aggregate row count differs')
    require(sum(r['count'] for r in rows) == totals['operations'], 'Aggregate operation count differs')
    require(min(r['firstOrdinal'] for r in rows) == 1 and
            max(r['lastOrdinal'] for r in rows) == totals['operations'], 'Aggregate extent differs')
    keys = []
    for row in rows:
        require(type(row['count']) is int and row['count'] > 0 and
                1 <= row['firstOrdinal'] <= row['lastOrdinal'] <= totals['operations'] and
                row['count'] <= row['lastOrdinal'] - row['firstOrdinal'] + 1 and
                row['firstMs'] <= row['lastMs'] <= final['elapsedMs'], 'Invalid aggregate row')
        require(row['frames'] is None and row['pending'] is False, 'Unexpected frames or asynchronous I/O')
        keys.append(json.dumps({k: v for k, v in row.items() if k not in
                               ('count', 'firstOrdinal', 'lastOrdinal', 'firstMs', 'lastMs')}, sort_keys=True))
    require(len(set(keys)) == len(keys), 'Duplicate aggregate key')
    return rows


def symbol_calls(events, expected):
    stacks = {}
    enters = Counter()
    leaves = Counter()
    for event in events:
        kind = event['kind']
        if kind not in ('crash-api-enter', 'crash-api-leave'):
            continue
        name = event['data']['name']
        stack = stacks.setdefault(event['tid'], [])
        if kind == 'crash-api-enter':
            stack.append(name)
            enters[name] += 1
        else:
            require(stack and stack.pop() == name, 'Symbol return thread/nesting differs')
            leaves[name] += 1
    require(not any(stacks.values()) and dict(enters) == dict(leaves) == expected,
            'Incomplete symbol API arguments/returns')


def review(folder):
    folder = Path(folder)
    owner = json.loads((folder / 'verification.json').read_bytes())
    require(owner['passed'] is True and owner['mode'] == 'crash' and owner['exit_code'] == 0xc0000005 and
            owner['launch']['forced_cleanup'] is False and owner['tracker']['complete'] is True and
            owner['tracker']['final_accounting'] == dict(total=1, active=0, terminated=0), 'Owned natural crash failed')
    for label in ('source', 'components', 'current166', 'shared', 'system_dbghelp'):
        require(owner[label + '_before'] == owner[label + '_after'], 'Changed ' + label)
    require(owner['components_before']['UnityPlayer.dll'] ==
            'a53b0c613a86c737b7caa7588c7c93ae20d5d5700f9321a406df9dcca8e32a7f', 'Wrong native image')
    digest = lambda p: hashlib.sha256(p.read_bytes()).hexdigest()
    require(digest(folder / 'observer.js') == owner['observer_sha256'], 'Observer bytes differ')
    session = json.loads((folder / 'rea-start.json').read_bytes())['structuredContent']['session_id']
    records = json.loads((folder / 'evidence.json').read_bytes())['records']
    def record(operation):
        matches = [r for r in records if r['operation'] == operation and r['parameters']['session_id'] == session]
        require(len(matches) == 1, 'One bound ' + operation + ' record required')
        return matches[0]
    loaded, final_record = record('load_frida_script'), record('frida_session_status')
    require(loaded['normalized_result']['source_sha256'] == owner['observer_sha256'], 'Loaded source differs')
    events = stream(final_record['normalized_result'], owner['pid'], owner['config']['runId'])
    finals = [e for e in events if e['kind'] == 'policy-final']
    require(len(finals) == 1 and events[-1] == finals[0], 'One complete final boundary required')
    final = finals[0]
    rows = aggregate(events, final)
    native = [(e['kind'], e['data']['label']) for e in events if e['kind'].startswith('crash-native-') and
              e['kind'] in ('crash-native-enter', 'crash-native-leave')]
    require(native == [('crash-native-enter', 'filter'), ('crash-native-enter', 'local-stack'),
                       ('crash-native-leave', 'local-stack'), ('crash-native-enter', 'handoff'),
                       ('crash-native-leave', 'handoff'), ('crash-native-leave', 'filter')], 'Native sequence differs')
    selected = [e for e in events if e['kind'] in ('crash-native-enter', 'crash-native-leave')]
    require(all(e['tid'] == owner['thread'] for e in selected) and
            selected[0]['data']['exceptionCode'] == 0xc0000005 and selected[-1]['data']['result'] == 0,
            'Native thread/exception/filter outcome differs')
    modules = [e['data'] for e in events if e['kind'] == 'crash-dbghelp-module']
    require(len(modules) == 1 and modules[0]['path'].lower() == r'c:\windows\system32\dbghelp.dll' and
            modules[0]['size'] == 2101248, 'Different DbgHelp path/build')
    expected = {k: v for k, v in final['data']['crashCounts'].items() if k.startswith('Sym') and v}
    symbol_calls(events, expected)
    require(expected.get('SymLoadModule64', 0) > 128, 'Expected complete uncapped module series')
    counters = final['data']['counts']
    require(all('ws2_32.dll:' + name in counters for name in NETWORK), 'Missing selected network hooks')
    network = {k: v for k, v in counters.items() if k.startswith(('ws2_32.dll:', 'winhttp.dll:', 'wininet.dll:'))}
    require(all(v == 0 for v in network.values()), 'Selected network operations observed')
    counts = Counter()
    for row in rows:
        counts[row['operation']] += row['count']
    return dict(passed=True, scope='instrumented original native filter through return; not complete privacy',
                pid=owner['pid'], thread=owner['thread'], events=len(events), file_operations=dict(counts),
                aggregate_operations=sum(counts.values()), aggregate_rows=len(rows), symbol_api_calls=expected,
                selected_network_counters=network, dbghelp=modules[0], dbghelp_disk_sha256=owner['system_dbghelp_before'],
                evidence_ids=[loaded['evidence_id'], final_record['evidence_id']],
                inputs={name: digest(folder / name) for name in ('verification.json', 'observer.js', 'evidence.json')},
                full_privacy_qualified=False, after_filter_os_handling_observed=False,
                clean_run_file_network_inferred=False)


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('folder', type=Path)
    args = parser.parse_args()
    result = review(args.folder)
    with (args.folder / 'observation-review.json').open('x', encoding='utf-8') as output:
        json.dump(result, output, indent=2)
        output.write('\n')
    print(json.dumps(result, indent=2))
