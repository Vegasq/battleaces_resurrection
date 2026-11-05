"""Add a passive self-TerminateProcess boundary to the selected API observer."""
from __future__ import annotations

from tools.frida_attribution_source import build_source as base_source

EXIT_ADAPTER = r'''
// Opt-in owned diagnostic: record the final selected counters at the game's
// original self-TerminateProcess entry. No API replacement or argument writes.
const exitHooks=[],exitAddresses=new Set();let selfExitClaimed=false;
for(const name of ['kernelbase.dll','kernel32.dll']) {
  const module=Process.getModuleByName(name),address=module.getExportByName('TerminateProcess');
  if(exitAddresses.has(address.toString()))continue;
  exitAddresses.add(address.toString());
  exitHooks.push(Interceptor.attach(address,{
    onEnter(args) {
      this.claimed=false;
      if(selfExitClaimed || !args[0].equals(ptr('0xffffffffffffffff')))return;
      selfExitClaimed=true;this.claimed=true;
      emit('self-terminate-entry',{api:name+':TerminateProcess',exitStatus:args[1].toUInt32(),
        counts:Object.assign({},counts),installed:installed.slice(),errors:errors.slice(),
        unknownRelativeRoots,overflow,transportHoldMs:200});
      Thread.sleep(0.2);
    },
    onLeave() {if(this.claimed)emit('self-terminate-returned',{});}
  }));
}
emit('exit-boundary-armed',{exports:2,uniqueHooks:exitHooks.length,transportHoldMs:200});
'''


def build_source(config: dict) -> str:
    return base_source(config) + EXIT_ADAPTER
