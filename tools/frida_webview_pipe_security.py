"""Opt-in returned server-handle witness for query-only security inspection.

The old pipe profile remains unchanged. This wrapper additionally retains the
numeric handle returned by the source-anchored creation call, never its name.
The external owner must independently pin process/job identity and verify the
duplicated object type/server PID. A historical numeric handle alone cannot
prove that the object remained alive or that its value was not reused.
"""
import re
from tools.frida_attribution_clock import replace_once
from tools.frida_webview_pipe import parent_build_source as old_parent_source
from tools.webview_pipe_evidence import validate as validate_pipe

PROFILE = 'owned-pipe-security-handle-v1'
OLD = "if(name==='CreateNamedPipeA' && d.handleValid)pipeHandles.set(value.toString(),{nameLength:d.nameLength,nameSha256:d.nameSha256,fixedPrefixMatched:true});"
NEW = """if(name==='CreateNamedPipeA' && d.handleValid){
              pipeHandles.set(value.toString(),{nameLength:d.nameLength,nameSha256:d.nameSha256,fixedPrefixMatched:true});
              emit('owned-pipe-handle',{schema:1,role:'parent',operation:name,api:d.api,call:d.call,
                nameLength:d.nameLength,nameSha256:d.nameSha256,fixedPrefixMatched:true,
                handle:value.toString(),frames:d.frames});
            }"""
READY = "\nemit('owned-pipe-handle-ready',{schema:1,profile:'"+PROFILE+"',role:'parent',handleValuesRetained:true,nameValuesRetained:false,apiResultsReplaced:false});\n"


def parent_build_source(config, cwd, sdk, *, cache_path, gate, pipe_nonce):
    source = old_parent_source(config, cwd, sdk, cache_path=cache_path,
                               gate=gate, pipe_nonce=pipe_nonce)
    return replace_once(source, OLD, NEW) + READY


def select_handle(rows, *, pid, run_id, witness):
    """Validate original rows and return one observed value, not live identity.

    Does not project/resequence input or qualify the actual OS security query.
    Callers must also validate the actual REA session/script/source envelope.
    """
    pipe = validate_pipe(rows, pid=pid, run_id=run_id, role='parent', witness=witness)
    ready = None
    handles = []
    expected_ready = dict(schema=1, profile=PROFILE, role='parent',
                          handleValuesRetained=True, nameValuesRetained=False,
                          apiResultsReplaced=False)
    expected_keys = {'schema', 'role', 'operation', 'api', 'call', 'nameLength',
                     'nameSha256', 'fixedPrefixMatched', 'handle', 'frames'}
    for row in rows:
        kind, data = row['kind'], row['data']
        if not kind.startswith('owned-pipe-'):
            continue
        if kind == 'owned-pipe-handle-ready':
            if (ready is not None or data != expected_ready or
                    any(type(data.get(k)) is not type(v) for k, v in expected_ready.items())):
                raise AssertionError('owned pipe handle ready differs')
            ready = row['seq']
            continue
        if kind != 'owned-pipe-handle' or ready is None or set(data) != expected_keys:
            raise AssertionError('owned pipe handle event schema/order differs')
        handle = data['handle']
        if (type(data['schema']) is not int or data['schema'] != 1 or
                data['role'] != 'parent' or data['operation'] != 'CreateNamedPipeA' or
                not isinstance(handle, str) or not re.fullmatch('0x[1-9a-f][0-9a-f]{0,15}', handle) or
                not 0 < int(handle, 16) < 0xffffffffffffffff):
            raise AssertionError('owned pipe handle value/role differs')
        # Correlate to the later original success record, including the exact
        # calling thread, binding/call ID, frame list and salted name fingerprint.
        matches = [r for r in rows if r['seq'] > row['seq'] and
                   r['tid'] == row['tid'] and r['kind'] == 'pipe-operation' and
                   r['data'].get('operation') == 'CreateNamedPipeA' and
                   all(type(data[k]) is type(r['data'].get(k)) and data[k] == r['data'][k]
                       for k in ('operation', 'api', 'call', 'nameLength', 'nameSha256',
                                 'fixedPrefixMatched', 'frames'))]
        if len(matches) != 1 or matches[0]['data']['handleValid'] is not True:
            raise AssertionError('owned pipe handle original success correlation absent')
        handles.append(dict(seq=row['seq'], creation_seq=matches[0]['seq'],
                            tid=row['tid'], handle=handle,
                            name_sha256=data['nameSha256']))
    if ready is None or len(handles) != 1:
        raise AssertionError('one owned source-anchored server handle required')
    return dict(passed=True, profile=PROFILE, pid=pid, run_id=run_id,
                observation=handles[0], pipe_metadata=pipe,
                scope='returned numeric server handle only; live object identity requires OS query',
                live_object_identity_qualified=False, access_cause_qualified=False,
                full_P8_qualified=False)
