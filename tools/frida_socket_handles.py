"""Count selected native socket calls by numeric handle, without payload access."""
from __future__ import annotations

from tools.frida_attribution_clock import replace_once
from tools.frida_attribution_source import build_source as base_source


def build_source(config):
    source = base_source(config)
    source = replace_once(source, 'const started=Date.now(), installed=[]',
                          'const socketHandles={send:{},recv:{}};\n'
                          'const started=Date.now(), installed=[]')
    source = replace_once(source, 'this.record=null;\n      try {',
                          '''this.record=null;
      try {
        if(name==='send' || name==='recv') {
          const handle=args[0].toString(),bucket=socketHandles[name];
          if(!(handle in bucket) && Object.keys(bucket).length>=32)
            throw new Error('socket handle budget exceeded');
          bucket[handle]=(bucket[handle]||0)+1;
        }''')
    source = replace_once(source,
                          "setInterval(()=>emit('heartbeat',{counts,installed:installed.slice(),errors:errors.slice(),unknownRelativeRoots,overflow}),5000);",
                          "setInterval(()=>emit('heartbeat',{counts,installed:installed.slice(),errors:errors.slice(),unknownRelativeRoots,overflow,socketHandles:{send:{...socketHandles.send},recv:{...socketHandles.recv}}}),5000);")
    return source
