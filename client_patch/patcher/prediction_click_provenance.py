"""Original selection-operation edges used only by the movement experiment."""

CALL_HOOKS = [
    dict(name='OfflinePredictionPreviewClear', rva=0x3bf1375, offset=0x3bef975, before='e8d6580700'),
    dict(name='OfflinePredictionPreviewClear', rva=0x3bf2856, offset=0x3bf0e56, before='e8f5430700'),
    dict(name='OfflinePredictionSelectionAdd', rva=0x3bf253a, offset=0x3bf0b3a, before='e8713c0700'),
    dict(name='OfflinePredictionSelectionRemovePreview', rva=0x3bf25d0, offset=0x3bf0bd0, before='e83b400700'),
    dict(name='OfflinePredictionSelectionClear', rva=0x3bf2739, offset=0x3bf0d39, before='e812450700'),
]
# These are original E9 tail edges. Replacing one with CALL would return into
# the old function's padding, or use a stack frame already unwound by its owner.
TAIL_HOOKS = [
    dict(name='OfflinePredictionNaturalSelectionRemove', rva=0x3bf3316, offset=0x3bf1916, before='e9d5d9ffff'),
    dict(name='OfflinePredictionPreviewAdd', rva=0x3bf24f7, offset=0x3bf0af7, before='e9b43c0700'),
    dict(name='OfflinePredictionPreviewClear', rva=0x3bf2666, offset=0x3bf0c66, before='e9e5450700'),
    dict(name='OfflinePredictionSelectionRemoveCurrent', rva=0x3bf25f0, offset=0x3bf0bf0, before='e91b400700'),
    dict(name='OfflinePredictionSelectionClear', rva=0x3bf26a8, offset=0x3bf0ca8, before='e9a3450700'),
]
BODY_GUARDS = [
    # UnitsDying reads the original event's set and supplies null MethodInfo.
    dict(rva=0x3bf3310, before='498b104533c0'),
    # Original collection receivers, IDs, null MI, and pre-tail stack teardown.
    dict(rva=0x3bf24e0, before='4883ec28488b89880000004885c9740c4533c04883c428'),
    dict(rva=0x3bf2650, before='4883ec28488b89880000004885c9740b33d24883c428'),
    dict(rva=0x3bf2510, before='40534883ec20488b8180000000488bd94885c07429807810007429488b89900000004885c974174533c0'),
    dict(rva=0x3bf25a0, before='48895c2408574883ec20488b81800000008bfa488bd94885c0743a80781000743a488b89880000004885c974284533c0'),
    dict(rva=0x3bf25d5, before='488b8b900000004885c974144533c08bd7488b5c24304883c4205f'),
    dict(rva=0x3bf2680, before='4883ec28488b81800000004885c0741d80781000741d488b89900000004885c9740b33d24883c428'),
    dict(rva=0x3bf2710, before='40534883ec20488b8180000000488bd94885c07431807810007431488b89900000004885c9741f33d2'),
    dict(rva=0x3bf273e, before='488b8b880000004885c9740c33d24883c4205be9fa440700'),
]
