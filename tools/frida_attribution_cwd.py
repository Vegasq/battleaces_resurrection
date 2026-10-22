"""Opt-in passive current-directory root resolution from an owned PEB anchor.

The owner establishes the address through its process handle. Read current
parameters/root/string at each entry,with a stability recheck;never call a target
API,guess a launch cwd or convert an unmatched root into a resolved path.
"""
import json
import re
from tools.frida_attribution_paths import build_source as path_source,control_request as path_request
from tools.frida_attribution_clock import replace_once

PROFILE='cwd-v4'
CWD_READER=r'''
function cwdRoot(root,context,key,operation,relativePath) {
  const parameters=ptr(cwdProbe.pebAddress).add(0x20).readPointer();
  if(parameters.isNull())throw new Error('null current process parameters');
  const entry=parameters.add(0x38),handle=entry.add(16).readPointer();
  if(!handle.equals(root))return null;
  const size=entry.readU16(),maximum=entry.add(2).readU16(),buffer=entry.add(8).readPointer();
  if(!size || size>maximum || maximum>32768 || size%2 || buffer.isNull())throw new Error('current directory layout differs');
  let rootPath=buffer.readUtf16String(size/2);
  if(!/^[a-zA-Z]:\\/.test(rootPath) || rootPath.indexOf('\u0000')>=0)throw new Error('absolute local current directory required');
  if(!ptr(cwdProbe.pebAddress).add(0x20).readPointer().equals(parameters) ||
     !entry.add(16).readPointer().equals(handle) || entry.readU16()!==size ||
     entry.add(2).readU16()!==maximum || !entry.add(8).readPointer().equals(buffer) ||
     buffer.readUtf16String(size/2)!==rootPath)throw new Error('current directory changed during observation');
  const parentPath=rootPath.replace(/\\+$/,'');
  resolvedCwdRoots++;
  emit('resolved-cwd-root',{api:key,operation,phase:'entry',rootHandle:root.toString(),relativePath,frames:frames(context),
    rootPath,pebAddress:cwdProbe.pebAddress,parametersAddress:parameters.toString(),resolution:'process-current-directory'});
  return {path:parentPath,tracked:relevant(rootPath)};
}
'''


def build_source(config,cwd):
    if not isinstance(cwd,dict) or set(cwd)!={'pid','pebAddress'} or type(cwd['pid']) is not int or not 0<cwd['pid']<2**32 or \
            not isinstance(cwd['pebAddress'],str) or not re.fullmatch('0x[0-9a-f]{1,16}',cwd['pebAddress']) or int(cwd['pebAddress'],16)==0:
        raise ValueError('Owned process/address descriptor required')
    source=path_source(config)
    source=replace_once(source,'const started=Date.now()',
        'const cwdProbe='+json.dumps(cwd)+";if(Process.id!==cwdProbe.pid)throw new Error('owned PID differs');\nconst started=Date.now()")
    source=replace_once(source,'lastClock=-250, clockReady=false;','lastClock=-250, clockReady=false, resolvedCwdRoots=0;')
    source=replace_once(source,'function objectPath(p,context,key,operation) {',CWD_READER+'\nfunction objectPath(p,context,key,operation) {')
    source=replace_once(source,'const parent=files.get(root.toString());',
        'const parent=cwdRoot(root,context,key,operation,path) || files.get(root.toString());')
    # Match both heartbeat and process-exit snapshots,without changing old profiles.
    if source.count('errors:errors.slice(),unknownRelativeRoots,overflow')!=2:raise ValueError('Observer snapshots changed')
    return source.replace('errors:errors.slice(),unknownRelativeRoots,overflow',
                          'errors:errors.slice(),unknownRelativeRoots,resolvedCwdRoots,overflow')


CWD_CONTROL=r'''assert pathlib.Path.cwd()==queue
assert pathlib.Path('cwd-control.json').read_bytes()==b'authored cwd control\n'
cwdPaths=[str(pathlib.Path.cwd())]
os.chdir(queue/'moved')
assert pathlib.Path('cwd-control.json').read_bytes()==b'authored cwd control\n'
cwdPaths.append(str(pathlib.Path.cwd()))
os.chdir(queue)
'''


def control_request(image,folder,run_id):
    config,request=path_request(image,folder,run_id)
    code=replace_once(request['argv'][3],'temp=queue/"owned.tmp";',CWD_CONTROL+'temp=queue/"owned.tmp";')
    request['argv'][3]=replace_once(code,'receipt["clockTicks"]=clockTicks',
                                  'receipt["cwdPaths"]=cwdPaths\nreceipt["clockTicks"]=clockTicks')
    return config,request
