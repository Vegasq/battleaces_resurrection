"""Opt-in selected browser activation witnesses; never instantiate a web view.

Composes the retained metadata observer and its explicit 200ms self-termination
transport hold. No arguments/returns are modified, URLs read, or APIs invoked.
"""
import json
import re
from pathlib import PureWindowsPath
from tools.frida_attribution_exit import build_source as exit_source
from tools.frida_attribution_clock import replace_once
from tools.review_crash_policy170 import stream

ENTRIES = {
    'GameAssembly.dll': {'Survey.OpenURL': 0x3b76340,
                         'Canvas.Instantiate': 0x54ad180,
                         'Standalone.Init': 0x54c1fd0,
                         'Standalone.initializePlugin': 0x54c6a10,
                         'ThreadDispatcher.initialize': 0x54e9110,
                         'WindowsPlugin.register': 0x54ec860},
    'Battle Aces_Data/Plugins/x86_64/VuplexWebViewWindows.dll': {
        'Plugin.initialize': 0x13f20, 'Plugin.newView': 0x14780,
        'Plugin.lazyBridge': 0x1b030, 'Plugin.createBrowser': 0x1bbd0},
}
SHELL_APIS = ['ShellExecuteA', 'ShellExecuteW', 'ShellExecuteExA', 'ShellExecuteExW']
START_ENTRIES = {'Survey.OpenURL', 'Canvas.Instantiate', 'Standalone.Init',
                 'Plugin.newView', 'Plugin.lazyBridge', 'Plugin.createBrowser'}

WITNESSES = r'''
const activationConfig=__DESCRIPTORS__,activationInstalled=[],activationCounts={};
for(const group of activationConfig)for(const entry of group.entries)activationCounts[entry.name]=0;
function activationSnapshot(){return {installed:activationInstalled.slice(),counts:{...activationCounts}};}
function activationModule(module){
  emit('activation-module',{name:module.name.toLowerCase(),path:module.path});
  const group=activationConfig.find(group=>normalize(group.module)===normalize(module.path));
  if(!group)return;
  try{
    if(activationInstalled.includes(group.module))throw new Error('selected module reloaded');
    for(const entry of group.entries)
      if(Checksum.compute('sha256',module.base.add(entry.rva).readByteArray(16))!==entry.sha256)
        throw new Error('selected entry prefix differs: '+entry.name);
    for(const entry of group.entries)Interceptor.attach(module.base.add(entry.rva),{onEnter(){
      const count=++activationCounts[entry.name];
      if(count<=8)emit('activation-entry',{name:entry.name,count});
    }});
    activationInstalled.push(group.module);
    emit('activation-installed',{module:group.module,entries:group.entries});
  }catch(error){errors.push('activation: '+String(error));emit('decode-error',{api:'activation-install'});}
}
'''


def build_source(config, cwd, descriptors):
    image = PureWindowsPath(config['image'])
    expected = {str(image.parent / name): entries for name, entries in ENTRIES.items()}
    if not isinstance(descriptors, list) or len(descriptors) != len(expected):
        raise ValueError('Exact browser activation modules required')
    seen = set()
    for group in descriptors:
        if not isinstance(group, dict) or set(group) != {'module', 'entries'} or group['module'] not in expected or group['module'] in seen:
            raise ValueError('Exact unique browser module required')
        seen.add(group['module'])
        entries = group['entries']; wanted = expected[group['module']]
        if not isinstance(entries, list) or len(entries) != len(wanted) or any(
                not isinstance(e, dict) or set(e) != {'name', 'rva', 'sha256'} or
                e.get('name') not in wanted or type(e.get('rva')) is not int or
                e['rva'] != wanted[e['name']] or not isinstance(e.get('sha256'), str) or
                not re.fullmatch('[0-9a-f]{64}', e['sha256']) for e in entries) or len({e['name'] for e in entries}) != len(wanted):
            raise ValueError('Exact unique browser entries required')
    source = exit_source(config, cwd)
    start = source.index('function frames(context) {')
    end = source.index('function endpoint(', start)
    source = source[:start] + 'function frames(context){return null;}\n' + source[end:]
    start = source.index(', api=') + len(', api='); end = source.index(';', start)
    api = json.loads(source[start:end]); api['shell32.dll'] = SHELL_APIS
    source = source[:start] + json.dumps(api) + source[end:]
    source = replace_once(source, "if(name==='TerminateProcess') {",
        "if(name.startsWith('ShellExecute')) {emit('shell-entry',{api:key});return;} else if(name==='TerminateProcess') {")
    source = replace_once(source, 'Process.attachModuleObserver({onAdded(module){',
        WITNESSES.replace('__DESCRIPTORS__', json.dumps(descriptors)) +
        '\nProcess.attachModuleObserver({onAdded(module){\n  activationModule(module);')
    if source.count('resolvedCwdRoots,overflow') != 3:
        raise ValueError('Exit snapshot layout differs')
    return source.replace('resolvedCwdRoots,overflow', 'resolvedCwdRoots,activation:activationSnapshot(),overflow')


def review(normalized, owner):
    """Qualify recorded selected activation/lifetime coverage, never all privacy."""
    rows = stream(normalized, owner['pid'], owner['config']['runId'])
    if not owner.get('passed') or not owner.get('tracker', {}).get('complete') or \
            owner.get('launch', {}).get('forced_cleanup') is not False or \
            owner.get('exit_code') != 0 or owner['tracker']['final_accounting']['active'] != 0 or \
            owner['tracker']['final_accounting']['terminated'] != 0:
        raise ValueError('Owned natural lifetime/integrity proof missing')
    exits = [r for r in rows if r['kind'] == 'process-exit-entry']
    if len(exits) not in (1, 2) or rows[-len(exits):] != exits or any(
            r['tid'] != owner['thread'] or r['data'].get('exitStatus') != 0 or
            r['data'].get('currentProcessPseudoHandle') is not True or
            r['data'].get('transportHoldMs') != 200 for r in exits):
        raise ValueError('Final owned self-termination suffix required')
    apis = [r['data'].get('boundaryApi') for r in exits]
    if apis not in (['kernel32.dll:TerminateProcess'], ['kernelbase.dll:TerminateProcess'],
                    ['kernel32.dll:TerminateProcess', 'kernelbase.dll:TerminateProcess']):
        raise ValueError('Unknown self-termination boundary order')
    final = exits[-1]['data']; state = final.get('activation', {})
    if len(exits) == 2:
        first = exits[0]['data']
        if first['activation'] != state or first['installed'] != final['installed'] or \
                first['counts'].get('kernel32.dll:TerminateProcess') != 1 or \
                first['counts'].get('kernelbase.dll:TerminateProcess') != 0 or \
                final['counts'] != dict(first['counts'], **{'kernelbase.dll:TerminateProcess': 1}):
            raise ValueError('Forwarded exit snapshots disagree')
    expected = {e['name'] for group in owner['descriptors'] for e in group['entries']}
    if set(state.get('counts', {})) != expected or any(type(n) is not int or n < 0 for n in state['counts'].values()):
        raise ValueError('Complete activation counters required')
    loaded = {r['data']['path'].lower() for r in rows if r['kind'] == 'activation-module'}
    installed = state.get('installed', [])
    if len(installed) != len(set(installed)):
        raise ValueError('Duplicate activation installation')
    expected_installed = {g['module'] for g in owner['descriptors'] if g['module'].lower() in loaded}
    if set(installed) != expected_installed or owner['descriptors'][0]['module'] not in installed:
        raise ValueError('Loaded activation module lacks witnesses')
    seen = [r['data'] for r in rows if r['kind'] == 'activation-installed']
    if len(seen) != len(installed) or {g['module']: g for g in seen} != {g['module']: g for g in owner['descriptors'] if g['module'] in installed}:
        raise ValueError('Installed descriptor evidence differs')
    for name, count in state['counts'].items():
        actual = [r['data']['count'] for r in rows if r['kind'] == 'activation-entry' and r['data']['name'] == name]
        if actual != list(range(1, min(count, 8) + 1)):
            raise ValueError('Entry events and final counters differ')
    keys = {x['key'] for x in final.get('installed', [])}
    required = {'kernelbase.dll:CreateProcessW', 'kernelbase.dll:CreateProcessA', 'ntdll.dll:RtlExitUserProcess'}
    if any(p.endswith('\\shell32.dll') for p in loaded):
        required |= {'shell32.dll:' + name for name in SHELL_APIS}
    if not required <= keys:
        raise ValueError('Selected process/shell API coverage missing')
    boundary_counts = {k: n for k, n in final['counts'].items() if 'CreateProcess' in k or 'ShellExecute' in k}
    if any(type(n) is not int or n < 0 for n in boundary_counts.values()):
        raise ValueError('Invalid process/shell counter')
    if not required <= set(final['counts']) | {x['key'] for x in final['installed'] if 'aliasOf' in x}:
        raise ValueError('Selected API counter evidence missing')
    return dict(passed=True, scope='Selected startup/menu/Quit APIs through final self-termination entry; owned-job lifetime separately',
                events=len(rows), activation=state, process_shell_counts=boundary_counts,
                terminal_snapshots=len(exits), terminal_boundary=apis,
                modules=len(loaded), job=owner['tracker']['final_accounting'],
                no_selected_browser_activation=all(state['counts'][n] == 0 for n in START_ENTRIES),
                no_selected_process_or_shell_call=all(n == 0 for n in boundary_counts.values()),
                full_privacy_qualified=False)
