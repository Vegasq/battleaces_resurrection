"""Opt-in observation of Unity's self-TerminateProcess shutdown route.

Legacy observers stay unchanged. This diagnostic pauses only a self-pseudo-
handle TerminateProcess entry for200ms so Frida's asynchronous message transport
can drain before the original API kills the process. No arguments, return values,
exit route or gameplay APIs are replaced. Entry is not completed termination;
the retained OS process/job handles must independently establish natural exit.
"""
import json
from tools.frida_attribution_clock import replace_once
from tools.frida_attribution_cwd import build_source as cwd_source
from tools.frida_cache_startup import build_source as cache_source

EXIT_APIS = {'kernelbase.dll:TerminateProcess', 'kernel32.dll:TerminateProcess'}
EXIT_HOLD_MS = 200

ENTRY = r'''if(name==='TerminateProcess') {
          const self=args[0].equals(ptr('0xffffffffffffffff'));
          if(!self) {
            emit('termination-request',{api:key,exitStatus:args[1].toUInt32(),
              currentProcessPseudoHandle:false,frames:frames(this.context)});
            return;
          }
          emit('process-exit-entry',{exitStatus:args[1].toUInt32(),counts,
            installed:installed.slice(),errors:errors.slice(),unknownRelativeRoots,
            resolvedCwdRoots,__CACHE__overflow,boundaryApi:key,
            currentProcessPseudoHandle:true,transportHoldMs:200,frames:frames(this.context)});
          // send() is asynchronous. This selected diagnostic deliberately delays
          // the original self-termination,not an external termination request.
          Thread.sleep(0.2);
          return;
        } else if(name==='NtCreateFile' || name==='NtOpenFile') {'''


def build_source(config, cwd, cache=None):
    source = cwd_source(config, cwd) if cache is None else cache_source(config, cwd, cache)
    # Modify only this new profile's generated API declaration,not legacy.API.
    start = source.index(', api=') + len(', api=')
    end = source.index(';', start)
    api = json.loads(source[start:end])
    for module in ('kernelbase.dll', 'kernel32.dll'):
        if 'TerminateProcess' in api.get(module, []):
            raise ValueError('Exit observer already installed')
        api.setdefault(module, []).append('TerminateProcess')
    source = source[:start] + json.dumps(api) + source[end:]
    source = replace_once(source, "if(name==='NtCreateFile' || name==='NtOpenFile') {",
                          ENTRY.replace('__CACHE__', 'cache:cacheSnapshot(),' if cache is not None else ''))
    return '// EXPLICIT EXIT DIAGNOSTIC:200ms self-termination transport hold.\n' + source
