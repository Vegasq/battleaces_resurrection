"""Owned local-worker experiment hooks; excluded from the ordinary recipe."""

# Original LoadByPluginClassType's managed GetProcAddress wrapper CALL.
# Windows x64: uintptr(HMODULE, System.String*, MethodInfo*).
# The original loader/module stays untouched; the helper selects only the exact
# original Simulation image and routes its recovered exports to a local worker.
CALL_HOOKS = [
    dict(name='OfflinePredictionGetProcAddress',rva=0x379d260,
         offset=0x379b860,before='e8bbeaffff'),
]
