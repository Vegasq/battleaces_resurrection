"""Validate only the opt-in pipe extension; preserve every original input row.

Passing means typed pipe metadata, not complete capture, P8, privacy, ordinary
execution or a completed handshake. Entered calls can remain pending and alias
callbacks can complete out of entry order. No projection/resequencing is done.
"""
import re
from pathlib import PureWindowsPath
from tools.frida_webview_pipe import descriptor

BASE = {'schema', 'seq', 'runId', 'pid', 'tid', 'elapsedMs', 'kind', 'data'}
OPS = {'parent': ('CreateNamedPipeA', 'ConnectNamedPipe', 'WaitForSingleObject'), 'child': ('CreateFileA',)}
CALLERS = {'CreateNamedPipeA': ('vuplexwebviewwindows.dll', '0x1b6af'),
           'ConnectNamedPipe': ('vuplexwebviewwindows.dll', '0x1b73f'),
           'WaitForSingleObject': ('vuplexwebviewwindows.dll', '0x1b772'),
           'CreateFileA': ('vuplex webview.vuplex', '0x840e8')}
COMMON = {'api', 'operation', 'frames', 'nameLength', 'nameSha256', 'fixedPrefixMatched', 'call', 'lastError'}
ARGUMENTS = {
    'CreateNamedPipeA': dict(openMode=0x40000003, pipeMode=6, maxInstances=255,
                           outBuffer=1048576, inBuffer=1048576, defaultTimeout=0, securityAttributesNull=True),
    'ConnectNamedPipe': dict(overlappedNull=False),
    'WaitForSingleObject': dict(timeout=0xffffffff),
    'CreateFileA': dict(desiredAccess=0xc0000000, shareMode=0, securityAttributesNull=True,
                       creationDisposition=3, flags=0x40000000, templateHandleNull=True),
}
RESULT = {'CreateNamedPipeA': 'handleValid', 'CreateFileA': 'handleValid',
          'ConnectNamedPipe': 'returned', 'WaitForSingleObject': 'waitResult'}


def _require(ok, message):
    if not ok:
        raise AssertionError(message)


def _integer(value, low=0, high=2**53-1):
    return type(value) is int and low <= value <= high


def _witness(value, role):
    _require(type(value) is dict and set(value) == {'role', 'module', 'prefixRva', 'sha256', 'nonce'}, 'pipe witness fields differ')
    _require(role in OPS and value['role'] == role and type(value['prefixRva']) is int and
             isinstance(value['module'], str) and 0 < len(value['module']) <= 32768 and '\0' not in value['module'], 'pipe witness identity differs')
    path = PureWindowsPath(value['module'])
    try:
        image = path.parents[3] / 'Battle Aces.exe' if role == 'parent' else path
        expected = descriptor(role, str(image), value['nonce'])
    except (ValueError, IndexError, TypeError) as error:
        raise AssertionError('pipe witness descriptor invalid') from error
    _require(value == expected, 'pipe witness is not the original exact descriptor')


def _frames(value, operation):
    _require(type(value) is list and 1 <= len(value) <= 8, 'pipe frames budget differs')
    for frame in value:
        _require(type(frame) is dict and set(frame) == {'module', 'rva'}, 'pipe frame fields differ')
        if frame['module'] is None:
            _require(frame['rva'] is None, 'pipe unresolved frame differs')
        else:
            module, rva = frame['module'], frame['rva']
            _require(isinstance(module, str) and 1 <= len(module) <= 256 and module == module.lower() and
                     not any(c in module for c in ('/', '\\', '\0')) and isinstance(rva, str) and
                     re.fullmatch('0x[0-9a-f]{1,16}', rva) is not None, 'pipe frame identity differs')
    module, rva = CALLERS[operation]
    _require(any(f == dict(module=module, rva=rva) for f in value), 'original pipe caller stack membership absent')


def validate(rows, *, pid, run_id, role, witness):
    """Return a JSON summary or raise AssertionError; never modify input rows.

    All envelopes are checked, unrelated kinds/data/annotations are retained and
    otherwise outside this validator's scope. A pending count is not a failure.
    """
    _require(_integer(pid, 1, 0xffffffff) and isinstance(run_id, str) and
             re.fullmatch('[0-9a-f]{32}', run_id) is not None, 'pipe PID/run identity required')
    _require(isinstance(role, str) and role in OPS, 'pipe role differs')
    _witness(witness, role)
    _require(type(rows) is list and bool(rows), 'original complete row list required')
    names = OPS[role]
    labels = {module+':'+name for module in ('kernel32.dll', 'kernelbase.dll') for name in names}
    ready = None
    bindings = []
    last_elapsed = -1
    previous_counts = {name: 0 for name in names}
    completed = {name: set() for name in names}
    maximum = {name: 0 for name in names}
    last_snapshot = None
    last_operation = None
    snapshots = 0
    operations = []
    digests = set()
    for sequence, row in enumerate(rows, 1):
        _require(type(row) is dict and BASE <= set(row), 'pipe original row envelope differs')
        _require(type(row['schema']) is int and row['schema'] == 1 and type(row['seq']) is int and row['seq'] == sequence and
                 type(row['pid']) is int and row['pid'] == pid and row['runId'] == run_id and
                 _integer(row['tid'], 1, 0xffffffff) and _integer(row['elapsedMs']) and row['elapsedMs'] >= last_elapsed and
                 isinstance(row['kind'], str) and bool(row['kind']) and type(row['data']) is dict, 'pipe row identity/order/time differs')
        last_elapsed = row['elapsedMs']
        kind, data = row['kind'], row['data']
        if not kind.startswith('pipe-'):
            continue
        _require(kind in ('pipe-probe-ready', 'pipe-probe-snapshot', 'pipe-operation', 'pipe-probe-error'), 'unknown pipe extension kind')
        _require(kind != 'pipe-probe-error', 'pipe probe error retained; metadata not qualified')
        if kind == 'pipe-probe-ready':
            _require(ready is None and set(data) == {'role', 'descriptor', 'bindings', 'errors', 'nameValuesRetained', 'apiResultsReplaced'}, 'pipe ready schema/repeat differs')
            _require(data['role'] == role and type(data['descriptor']) is dict and data['descriptor'] == witness and
                     data['errors'] == [] and data['nameValuesRetained'] is False and data['apiResultsReplaced'] is False, 'pipe ready descriptor/redaction/errors differ')
            bindings = data['bindings']
            _require(type(bindings) is list and 1 <= len(bindings) <= len(labels) and all(type(v) is str and v in labels for v in bindings) and
                     len(set(bindings)) == len(bindings) and {v.split(':', 1)[1] for v in bindings} == set(names), 'pipe binding inventory differs')
            ready = sequence
            continue
        _require(ready is not None, 'pipe metadata precedes ready')
        if kind == 'pipe-probe-snapshot':
            _require(set(data) == {'role', 'counts', 'errors', 'nameValuesRetained'} and data['role'] == role and
                     data['errors'] == [] and data['nameValuesRetained'] is False, 'pipe snapshot schema/redaction/errors differ')
            counts = data['counts']
            _require(type(counts) is dict and set(counts) == set(names) and all(_integer(counts[n], 0, 32) for n in names), 'pipe role counters/types differ')
            _require(all(counts[n] >= previous_counts[n] and counts[n] >= maximum[n] for n in names), 'pipe counters backward/below completed ID')
            previous_counts = dict(counts)
            last_snapshot = sequence
            snapshots += 1
            continue
        operation = data.get('operation')
        _require(type(operation) is str and operation in names, 'pipe operation role differs')
        _require(set(data) == COMMON | set(ARGUMENTS[operation]) | {RESULT[operation]}, 'pipe operation keys differ')
        _require(type(data['api']) is str and data['api'] in bindings and data['api'].split(':', 1)[1] == operation, 'pipe operation binding differs')
        _require(type(data['nameLength']) is int and data['nameLength'] == 64 and data['fixedPrefixMatched'] is True and
                 isinstance(data['nameSha256'], str) and re.fullmatch('[0-9a-f]{64}', data['nameSha256']) is not None, 'pipe name redaction facts differ')
        _frames(data['frames'], operation)
        for key, expected in ARGUMENTS[operation].items():
            _require(type(data[key]) is type(expected) and data[key] == expected, 'original Win64 pipe argument metadata differs: '+key)
        call = data['call']
        _require(_integer(call, 1, 32) and call not in completed[operation], 'pipe call ID invalid/duplicate')
        result = data[RESULT[operation]]
        if operation == 'WaitForSingleObject':
            _require(type(result) is int and result in (0, 0x80, 0x102, 0xffffffff), 'pipe wait result differs')
            failure = result == 0xffffffff
        else:
            _require(type(result) is bool, 'pipe handle/BOOL result differs')
            failure = not result
        _require(_integer(data['lastError'], 0, 0xffffffff) if failure else data['lastError'] is None, 'pipe failure/stale last-error semantics differ')
        completed[operation].add(call)
        maximum[operation] = max(maximum[operation], call)
        digests.add(data['nameSha256'])
        last_operation = sequence
        operations.append(dict(seq=sequence, operation=operation, api=data['api'], call=call,
                               nameSha256=data['nameSha256'], result=result, lastError=data['lastError']))
    _require(ready is not None, 'pipe ready absent')
    lower = {n: max(previous_counts[n], maximum[n]) for n in names}
    pending = {n: sorted(set(range(1, lower[n]+1))-completed[n]) for n in names}
    return dict(passed=True, scope='typed pipe extension only; original rows unchanged', role=role,
                pid=pid, run_id=run_id, rows=len(rows), ready_seq=ready, bindings=list(bindings),
                binding_scope='unique address first-label inventory; shared export aliases not enumerated',
                snapshots=snapshots, last_snapshot_seq=last_snapshot, last_operation_seq=last_operation,
                last_snapshot_after_operations=last_snapshot is not None and (last_operation is None or last_snapshot > last_operation),
                last_snapshot_entered=dict(previous_counts) if last_snapshot is not None else None,
                entered_lower_bound=lower, completed_counts={n: len(completed[n]) for n in names},
                completed_call_ids={n: sorted(completed[n]) for n in names}, pending_entered_call_ids=pending,
                pending_scope='only entries evidenced by snapshots or completed IDs; unseen entries not inferred absent',
                digests=sorted(digests), operations=operations, caller_scope='exact original RVA stack membership, not direct caller',
                rows_projected=False, full_P8_qualified=False, full_privacy_qualified=False, ordinary_execution_qualified=False)
