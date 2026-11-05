"""Record bounded metadata for file API calls whose preexisting handle has no path."""
from __future__ import annotations

from tools.frida_attribution_clock import replace_once
from tools.frida_preexisting_file_source372 import build_source as base_source


def build_source(config: dict) -> str:
    source = base_source(config)
    source = replace_once(source, 'this.record=null;\n      try {',
                          'this.record=null;this.unresolvedFileOp=null;\n      try {')
    source = replace_once(source,
                          "if(file && file.nonDisk)nonDiskFileOps++;\n          if(file && file.tracked && name!=='NtClose')",
                          "if(file && file.nonDisk)nonDiskFileOps++;\n          if(!file && name!=='NtClose')this.unresolvedFileOp={operation:name,handle:this.handle,fileType:getFileType(args[0])};\n          if(file && file.tracked && name!=='NtClose')")
    source = replace_once(source,
                          "if(this.record) {\n          this.record.api=key;",
                          "if(this.unresolvedFileOp){this.unresolvedFileOp.api=key;this.unresolvedFileOp.returnValue=status;emit('unresolved-file-operation',this.unresolvedFileOp);}\n        if(this.record) {\n          this.record.api=key;")
    return source
