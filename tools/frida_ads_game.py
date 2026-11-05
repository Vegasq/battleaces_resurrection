"""Close the isolated caller witness at original self-termination entry.

Diagnostic only:200ms transport hold, no API replacement or argument writes.
The owner must establish gameplay and OS termination separately. Observation
ends at the first self-TerminateProcess entry, not at OS process death.
"""
from tools.frida_ads_caller import build_source as caller_source, validate


EXIT_ADAPTER = r'''
// Explicit game182 boundary; never use the authored fixture's call-count stop.
const exitHooks=[],exitAddresses=new Set();let exitClaimed=false;
function exitEmit(kind,data){send({schema:1,kind,runId:config.runId,pid:Process.id,
  tid:Process.getCurrentThreadId(),elapsedMs:Date.now()-started,data});}
for(const name of ['kernelbase.dll','kernel32.dll']){
  const m=Process.getModuleByName(name),address=m.getExportByName('TerminateProcess');
  if(exitAddresses.has(address.toString()))continue;
  exitAddresses.add(address.toString());
  exitHooks.push(Interceptor.attach(address,{
    onEnter(args){
      this.claimed=false;
      if(exitClaimed||!args[0].equals(ptr('0xffffffffffffffff')))return;
      exitClaimed=true;this.claimed=true;
      const final=rpc.exports.finish();
      exitEmit('ads-exit-entry',{api:name+':TerminateProcess',exitStatus:args[1].toUInt32(),
        currentProcessPseudoHandle:true,transportHoldMs:200,callerFinished:final.finished});
      Thread.sleep(0.2);
    },
    onLeave(){if(this.claimed)exitEmit('ads-exit-returned',{});}
  }));
}
exitEmit('ads-exit-armed',{exports:2,uniqueHooks:exitHooks.length,transportHoldMs:200});
'''


def build_source(config):
    return caller_source(config) + EXIT_ADAPTER


def review_rows(rows, config):
    """Require closed caller interval and a matching nonreturning exit entry."""
    ads = [r for r in rows if not r.get('kind', '').startswith('ads-exit-')]
    result = validate(ads, config)
    exits = [r for r in rows if r.get('kind', '').startswith('ads-exit-')]
    if len(exits) != 2 or [r['kind'] for r in exits] != ['ads-exit-armed', 'ads-exit-entry']:
        raise ValueError('One armed boundary and nonreturning exit entry required')
    for row in exits:
        if set(row) != {'schema', 'kind', 'runId', 'pid', 'tid', 'elapsedMs', 'data'} or \
                type(row['schema']) is not int or row['schema'] != 1 or row['runId'] != config['runId'] or \
                type(row['pid']) is not int or row['pid'] != config['pid'] or \
                type(row['tid']) is not int or not 0 < row['tid'] < 2**32 or \
                type(row['elapsedMs']) is not int or row['elapsedMs'] < 0:
            raise ValueError('Exit boundary identity differs')
    armed, final = exits
    data = armed['data']
    if not isinstance(data, dict) or set(data) != {'exports', 'uniqueHooks', 'transportHoldMs'} or \
            any(type(v) is not int for v in data.values()) or data['exports'] != 2 or \
            data['uniqueHooks'] not in (1, 2) or data['transportHoldMs'] != 200:
        raise ValueError('Termination exports/hold differ')
    data = final['data']
    if not isinstance(data, dict) or set(data) != {'api', 'exitStatus', 'currentProcessPseudoHandle', 'transportHoldMs', 'callerFinished'} or \
            data['api'] not in ('kernelbase.dll:TerminateProcess', 'kernel32.dll:TerminateProcess') or \
            type(data['exitStatus']) is not int or data['exitStatus'] != 0 or \
            data['currentProcessPseudoHandle'] is not True or data['callerFinished'] is not True or \
            type(data['transportHoldMs']) is not int or data['transportHoldMs'] != 200 or \
            not armed['elapsedMs'] <= ads[-1]['elapsedMs'] <= final['elapsedMs'] or \
            final['tid'] != ads[-1]['tid'] or rows[-2:] != [ads[-1], final] or \
            rows.index(armed) >= rows.index(ads[-1]):
        raise ValueError('Original self-exit boundary differs')
    return result | dict(boundary=final, armed=armed,
                         scope='Instrumented callback interval ending at first original self-TerminateProcess entry; 200ms transport hold')
