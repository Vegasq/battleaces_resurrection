"""Opt-in original startup callsites, scoped to owned diagnostic installations.

Original PE SHA256 is enforced by patch_client. Contracts were independently
checked against original LLVM disassembly and IL2CPP metadata (review38).
The shared generic factory receives its exact original inflated MethodInfo.
"""

TABLES = (
    ('PlayerInputActionTable', 0x3e19e4a, 'e8813240fd'),
    ('InputActionPanelMappingTable', 0x3e19eb3, 'e8183240fd'),
    ('OptionSettingTable', 0x3e19f1a, 'e8b13140fd'),
    ('CursorTable', 0x3e19f7e, 'e84d3140fd'),
    ('UIButtonAudioTable', 0x3e19fe5, 'e8e63040fd'),
    ('UIContainerAudioTable', 0x3e1a04c, 'e87f3040fd'),
    ('UIDragAndDropAudioTable', 0x3e1a0b3, 'e8183040fd'),
    ('UIAnimatorAudioTable', 0x3e1a11a, 'e8b12f40fd'),
    ('PlaySoundNodeAudioTable', 0x3e1a181, 'e84a2f40fd'),
    ('UIPrefabTable', 0x3e1a1e8, 'e8e32e40fd'),
    ('MenuUIStateTable', 0x3e1a24f, 'e87c2e40fd'),
    ('IngameMusicTrackTable', 0x3e1a2b6, 'e8152e40fd'),
)

CALL_HOOKS = [dict(name='OfflineStartupTable'+str(i), rva=rva,
                   offset=rva-0x1a00, before=before)
              for i, (_, rva, before) in enumerate(TABLES)] + [
    dict(name='OfflineStartupPreMenu', rva=0x3dfea6e, offset=0x3dfd06e, before='e85db20100'),
    dict(name='OfflineStartupOther', rva=0x3dfea85, offset=0x3dfd085, before='e8b6b80100'),
    dict(name='OfflineStartupWhenAll', rva=0x3dfebf9, offset=0x3dfd1f9, before='e8f2f683ff'),
]
TAIL_HOOKS = [dict(name='OfflineStartupPump', rva=0x509359c,
                   offset=0x5091b9c, before='e9bffaffff')]
