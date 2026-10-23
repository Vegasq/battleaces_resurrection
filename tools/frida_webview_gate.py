"""Explicit controlled-replay gate for one owned original Vuplex child only.

This profile MUTATES CreateProcessW creation flags to add CREATE_SUSPENDED.
It is not passive, never enabled by ordinary launchers, and never resumes a
thread. The external owner validates/pins the actual job process/thread first.
Legacy metadata profiles are unchanged; argv values remain transient/redacted.
"""
import json,re
from pathlib import PureWindowsPath
from tools.frida_webview_process import build_source as metadata_source
from tools.frida_attribution_clock import replace_once

PROFILE='owned-webview-gate-v1'
GATE=r'''const webviewGate=__GATE__;let webviewGateTaken=false;
function webviewHoldBrowser(args,record) {
  if(record.processMetadata.expectedChildImageMatches!==true ||
     record.processMetadata.ownedCacheMatches!==true || record.processMetadata.processType!==null ||
     !record.frames.some(f=>f.module==='vuplexwebviewwindows.dll' && f.rva==='0x'+webviewGate.returnRva.toString(16)))return;
  if(webviewGateTaken)throw new Error('second owned browser creation refused');
  if(args[5].toUInt32()!==0)throw new Error('owned browser original creation flags differ');
  const module=Process.findModuleByName('VuplexWebViewWindows.dll');
  if(!module || module.path.toLowerCase()!==webviewGate.module.toLowerCase() ||
     Checksum.compute('sha256',module.base.add(webviewGate.entryRva).readByteArray(16))!==webviewGate.sha256)
    throw new Error('owned browser callsite module differs');
  record.ownedChildGate={schema:1,rootPid:Process.id,originalCreationFlags:0,effectiveCreationFlags:4,
    externalResumeRequired:true,entryRva:webviewGate.entryRva,returnRva:webviewGate.returnRva};
  args[5]=ptr(4);webviewGateTaken=true;
}
'''

def build_source(config,cwd,sdk,*,cache_path,gate):
    image=PureWindowsPath(config['image']);plugin=image.parent/'Battle Aces_Data/Plugins/x86_64/VuplexWebViewWindows.dll'
    child=plugin.parent/'VuplexWebViewChromium/Vuplex WebView.vuplex'
    if not isinstance(gate,dict) or set(gate)!={'module','childImage','entryRva','returnRva','sha256'} or \
        gate['module']!=str(plugin) or gate['childImage']!=str(child) or \
        type(gate['entryRva']) is not int or gate['entryRva']!=0x1bbd0 or \
        type(gate['returnRva']) is not int or gate['returnRva']!=0x1c1d4 or \
        not isinstance(gate['sha256'],str) or not re.fullmatch('[0-9a-f]{64}',gate['sha256']):
        raise ValueError('Exact owned original browser callsite descriptor required')
    source=metadata_source(config,cwd,sdk,cache_path=cache_path)
    source=replace_once(source,'function hook(module,name,address) {',GATE.replace('__GATE__',json.dumps(gate))+'\nfunction hook(module,name,address) {')
    source=replace_once(source,'return {schema:1,argumentCount:args.length,optionNames:',
        'return {schema:1,expectedChildImageMatches:normalize(args[0] || "")===normalize('+json.dumps(str(child))+'),argumentCount:args.length,optionNames:')
    source=replace_once(source,'this.record.processMetadata.directoryInherited=args[user?8:7].isNull();',
        "this.record.processMetadata.directoryInherited=args[user?8:7].isNull();\n          if(name==='CreateProcessW')webviewHoldBrowser(args,this.record);")
    source=replace_once(source,"emit(name.startsWith('Nt')?'file-operation':name.startsWith('CreateProcess')?'process-create':'network-operation',this.record);",
        "if(this.record.ownedChildGate){this.record.ownedChildGate.created=status!==0;if(status!==0){this.record.ownedChildGate.childPid=this.processInfo.add(16).readU32();this.record.ownedChildGate.childTid=this.processInfo.add(20).readU32();}}\n          emit(name.startsWith('Nt')?'file-operation':name.startsWith('CreateProcess')?'process-create':'network-operation',this.record);")
    source=replace_once(source,'// Metadata only; no NativeFunction, replacements, return/argument writes,',
        '// Controlled replay: one owned browser CreateProcessW flags argument is changed to CREATE_SUSPENDED. No NativeFunction/replacement,')
    return source
