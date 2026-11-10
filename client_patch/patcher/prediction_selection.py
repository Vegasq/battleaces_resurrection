"""Exact-original selection admission sites for the movement experiment only.

These descriptors are included by prediction_actor_repair, which build_patch
uses only with prediction_movement=True. They add no policy to the ordinary or
worker-only recipes. The helper must preserve the original dispatch when the
movement experiment has no active match.
"""
import hashlib


SUPPORTED_ORIGINAL_SHA256 = 'e59d08c01479b27404778048d7e13546dbf3771f6b3912744c7c2bdf80c4e758'

PATCHES = [
    # Only the scoped observer consumes this third bool argument. It forwards
    # ORIGINAL Actuate(selector, group, MethodInfo=null) exactly once.
    dict(name='Pass original repeat bit to scoped focus Actuate observer',
         rva=0x3bf305b, offset=0x3bf165b, before='4533c0', after='4588f0'),
]
CALL_HOOKS = [
    # SuspendedEventHelper.EndSuspend's virtual OnRaiseEvent dispatch. The
    # window starts BEFORE the MethodInfo load: RCX=helper, RDX=actual class,
    # RAX=original callback. void(helper*, actualIl2CppClass*), NOT MethodInfo.
    # The wrapper reloads target[class+0x188]/MethodInfo[class+0x190] and forwards
    # exactly once; original EndSuspend retains its state reset/end callback.
    dict(name='OfflinePredictionSelectionCommit', rva=0x3b02322,
         offset=0x3b00922, before='488b9290010000ffd0'),
    # Unit*(SelectionChangeHelper*, MethodInfo*). Original caller supplies null
    # MethodInfo. An inadmissible confirmer result becomes null, without
    # rewriting the helper's managed override or bypassing its cleanup.
    dict(name='OfflinePredictionSelectionConfirmer', rva=0x3bf9657,
         offset=0x3bf7c57, before='e8b4010000'),
    # UnitSelectionSet*(selector*, const Vector3*, sourceSet*, bool append,
    # MethodInfo*). Win64 passes the 12-byte Vector3 indirectly in RDX; the
    # MethodInfo is argument5. Both pointer and minimap callers share one shim.
    dict(name='OfflinePredictionCastingSet', rva=0x3bf416d,
         offset=0x3bf276d, before='e87ef4ffff'),
    dict(name='OfflinePredictionCastingSet', rva=0x3bf42e9,
         offset=0x3bf28e9, before='e802f3ffff'),
    # uint32(UnitSelectionSet*, const Vector3*, MethodInfo*). The original
    # chooser is 0x3c646a0; 0xffffffff declines focus through original TryGet.
    dict(name='OfflinePredictionControlGroupFocus', rva=0x3bf310f,
         offset=0x3bf170f, before='e88c150700'),
    # The same chooser in the ORIGINAL repeat-focus MoveNext fallback.
    dict(name='OfflinePredictionControlGroupFocus', rva=0x3bfa10b,
         offset=0x3bf870b, before='e890a50600'),
    dict(name='OfflinePredictionFocusActuate', rva=0x3bf306c,
         offset=0x3bf166c, before='e8dfe5ffff'),
    dict(name='OfflinePredictionStartRepeatFocus', rva=0x3bf322b,
         offset=0x3bf182b, before='e8c06570ff'),
    dict(name='OfflinePredictionControlGroupCamera', rva=0x3bf315d,
         offset=0x3bf175d, before='e8aeb12a00'),
    dict(name='OfflinePredictionControlGroupCamera', rva=0x3bfa027,
         offset=0x3bf8627, before='e8e4422a00'),
]

# Redirect the one codegen method-pointer slot, preserving its DIR64 fixup.
# The original MoveNext body remains callable for inactive delegation.
POINTER_HOOKS = [
    dict(name='OfflinePredictionRepeatFocusNext', rva=0x6d4dc48, offset=0x6d4b248,
         before='e09dbf8301000000', target_rva=0x3bf9de0,
         relocation_block_offset=0x736fbb4, relocation_block_before='00d0d40614030000',
         relocation_entry_offset=0x736fdd8, relocation_entry_before='48ac'),
]

# Pin the register/return contracts and original collection operations as well
# as the overwritten bytes. These are validation-only, never extra patches.
BODY_GUARDS = [
    dict(rva=0x3b022fd, before='488b4c2450807910000f8494000000807911007506807912007418488b11488b8288010000'),
    dict(rva=0x3b0232b, before='488b4c2450c6411000'),
    dict(rva=0x3bf95f0, before='40564883ec70803d50f9250300488bf1'),
    dict(rva=0x3bf9652, before='33d2488bce'),
    dict(rva=0x3bf965c, before='488b5620488bf8'),
    dict(rva=0x3bf9810, before='48895c2410488974242048894c240857'),
    dict(rva=0x3bf9886, before='488b7b18'),
    dict(rva=0x3bf25a0, before='48895c2408574883ec20488b8180000000'),
    dict(rva=0x3c66610, before='48895c24188954241048894c24085657'),
    dict(rva=0x3bf35f0, before='488bc4448848204c894018488950104889480853'),
    dict(rva=0x3bf4143, before='488d55b78b458f488bcb440fb68b180100004c8b8390000000f20f1145b78945bf48c744242000000000'),
    dict(rva=0x3bf42ba, before='f20f1006488d5424308b460833db440fb68f18010000488bcf4c8b8790000000f20f1144243048895c242089442438'),
    dict(rva=0x3c646a0, before='488954241048894c24085356574154'),
    dict(rva=0x3bf9de0, before='4053574883ec58803d64f1250300488bf9'),
    dict(rva=0x3bfa110, before='4d85f67460488d4c2470448b'),
    dict(rva=0x3bf1650, before='48895c24104889742418574883ec404863f2488bd9803db1'),
    dict(rva=0x3bf3067, before='8bd7488bcb'),
    dict(rva=0x3bf3071, before='84c00f84c7010000'),
    dict(rva=0x32f97f0, before='40574883ec50803de3a8b50300488bf9'),
    dict(rva=0x3bf3226, before='33d2488bcf'),
    dict(rva=0x3bf3230, before='8983b0000000'),
    dict(rva=0x3e9e310, before='48895c2408574883ec40803d50c0fb02'),
    dict(rva=0x3bf3155, before='488b5424304533c0'),
    dict(rva=0x3bfa021, before='488b164533c0'),
    dict(rva=0x3bfa02c, before='c74714000080ff'),
]


def validate_original(original, *, expected_sha256):
    """Validate the independent build pin and every file-backed ABI guard.

    Import the existing bounded PE mapper at call time: this module supplies
    descriptors to the actor module and must not create an import-time cycle.
    All checks precede any build_patch transformation or output publication.
    """
    if expected_sha256 != SUPPORTED_ORIGINAL_SHA256:
        raise ValueError('Prediction selection supported original SHA256 differs from patch recipe.')
    actual_sha256 = hashlib.sha256(original).hexdigest()
    if actual_sha256 != SUPPORTED_ORIGINAL_SHA256:
        raise ValueError('Prediction selection original SHA256 does not match.')
    from .prediction_actor_repair import rva_to_offset, validate_pointer_hooks, validate_byte_patches
    patches = validate_byte_patches(original, PATCHES)
    guarded = []
    for guard in BODY_GUARDS:
        before = bytes.fromhex(guard['before'])
        offset = rva_to_offset(original, guard['rva'], len(before))
        if original[offset:offset + len(before)] != before:
            raise ValueError(f"Prediction selection body guard mismatch: 0x{guard['rva']:x}")
        guarded.append(dict(rva=guard['rva'], offset=offset, before=guard['before']))
    calls = []
    for hook in CALL_HOOKS:
        before = bytes.fromhex(hook['before'])
        offset = rva_to_offset(original, hook['rva'], len(before))
        if (len(before) < 5 or offset != hook['offset'] or
                original[offset:offset + len(before)] != before):
            raise ValueError('Prediction selection call guard/mapping mismatch: ' + hook['name'])
        calls.append(dict(hook))
    pointers = validate_pointer_hooks(original, POINTER_HOOKS)
    return dict(original_sha256=actual_sha256,
                supported_original_sha256=SUPPORTED_ORIGINAL_SHA256,
                body_guards=guarded, call_hooks=calls,
                patches=patches,
                pointer_hooks=[dict(hook) for hook in POINTER_HOOKS], pointer_guards=pointers)
