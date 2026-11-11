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
    # Original Down has accepted the ordinary no-drag/no-caster path.
    # void(UnitSelector*, MethodInfo*=null); call original 0x3bf4a60 once,
    # then observe pending Single only inside the actual Down callback.
    dict(name='OfflinePredictionClickDownAccepted', rva=0x3bf7e64,
         offset=0x3bf6464, before='e8f7cbffff'),
]

# Redirect exact codegen method-pointer slots, preserving their DIR64 fixups.
# Original bodies remain callable for unchanged inactive delegation.
# Input callbacks: void(UnitSelector*, const CallbackContext*, MethodInfo*).
# CallbackContext is the original nested InputAction value type (16 bytes),
# passed indirectly in RDX on Win64. Never fabricate it or infer selector from
# saved registers. Subscribe/Unsubscribe pass callback MethodInfo to ctor
# 0x018d00, which reads MethodInfo+8. Require a positive runtime witness that
# actual callback MethodInfo+0/+8 resolve to this loaded thunk before capture.
# A constructor CALL observer alone would not observe later input invocations.
POINTER_HOOKS = [
    dict(name='OfflinePredictionRepeatFocusNext', rva=0x6d4dc48, offset=0x6d4b248,
         before='e09dbf8301000000', target_rva=0x3bf9de0,
         relocation_block_offset=0x736fbb4, relocation_block_before='00d0d40614030000',
         relocation_entry_offset=0x736fdd8, relocation_entry_before='48ac'),
    dict(name='OfflinePredictionInputFocusCancel0', rva=0x6d4db50, offset=0x6d4b150,
         before='6077bf8301000000', target_rva=0x3bf7760,
         relocation_block_offset=0x736fbb4, relocation_block_before='00d0d40614030000',
         relocation_entry_offset=0x736fd9a, relocation_entry_before='50ab'),
    dict(name='OfflinePredictionInputFocusCancel1', rva=0x6d4db58, offset=0x6d4b158,
         before='d077bf8301000000', target_rva=0x3bf77d0,
         relocation_block_offset=0x736fbb4, relocation_block_before='00d0d40614030000',
         relocation_entry_offset=0x736fd9c, relocation_entry_before='58ab'),
    dict(name='OfflinePredictionInputFocusCancel2', rva=0x6d4db60, offset=0x6d4b160,
         before='4078bf8301000000', target_rva=0x3bf7840,
         relocation_block_offset=0x736fbb4, relocation_block_before='00d0d40614030000',
         relocation_entry_offset=0x736fd9e, relocation_entry_before='60ab'),
    dict(name='OfflinePredictionInputFocusCancel3', rva=0x6d4db68, offset=0x6d4b168,
         before='b078bf8301000000', target_rva=0x3bf78b0,
         relocation_block_offset=0x736fbb4, relocation_block_before='00d0d40614030000',
         relocation_entry_offset=0x736fda0, relocation_entry_before='68ab'),
    dict(name='OfflinePredictionInputFocusCancel4', rva=0x6d4db70, offset=0x6d4b170,
         before='2079bf8301000000', target_rva=0x3bf7920,
         relocation_block_offset=0x736fbb4, relocation_block_before='00d0d40614030000',
         relocation_entry_offset=0x736fda2, relocation_entry_before='70ab'),
    dict(name='OfflinePredictionInputCancelAbility', rva=0x6d4db78, offset=0x6d4b178,
         before='9079bf8301000000', target_rva=0x3bf7990,
         relocation_block_offset=0x736fbb4, relocation_block_before='00d0d40614030000',
         relocation_entry_offset=0x736fda4, relocation_entry_before='78ab'),
    dict(name='OfflinePredictionInputQueueModifier', rva=0x6d4db80, offset=0x6d4b180,
         before='a079bf8301000000', target_rva=0x3bf79a0,
         relocation_block_offset=0x736fbb4, relocation_block_before='00d0d40614030000',
         relocation_entry_offset=0x736fda6, relocation_entry_before='80ab'),
    dict(name='OfflinePredictionInputForceModifier', rva=0x6d4db88, offset=0x6d4b188,
         before='707abf8301000000', target_rva=0x3bf7a70,
         relocation_block_offset=0x736fbb4, relocation_block_before='00d0d40614030000',
         relocation_entry_offset=0x736fda8, relocation_entry_before='88ab'),
    dict(name='OfflinePredictionInputPosition', rva=0x6d4db90, offset=0x6d4b190,
         before='d07abf8301000000', target_rva=0x3bf7ad0,
         relocation_block_offset=0x736fbb4, relocation_block_before='00d0d40614030000',
         relocation_entry_offset=0x736fdaa, relocation_entry_before='90ab'),
    dict(name='OfflinePredictionInputDown', rva=0x6d4db98, offset=0x6d4b198,
         before='207dbf8301000000', target_rva=0x3bf7d20,
         relocation_block_offset=0x736fbb4, relocation_block_before='00d0d40614030000',
         relocation_entry_offset=0x736fdac, relocation_entry_before='98ab'),
    dict(name='OfflinePredictionInputUp', rva=0x6d4dba0, offset=0x6d4b1a0,
         before='607fbf8301000000', target_rva=0x3bf7f60,
         relocation_block_offset=0x736fbb4, relocation_block_before='00d0d40614030000',
         relocation_entry_offset=0x736fdae, relocation_entry_before='a0ab'),
    dict(name='OfflinePredictionInputContextDown', rva=0x6d4dba8, offset=0x6d4b1a8,
         before='f080bf8301000000', target_rva=0x3bf80f0,
         relocation_block_offset=0x736fbb4, relocation_block_before='00d0d40614030000',
         relocation_entry_offset=0x736fdb0, relocation_entry_before='a8ab'),
    dict(name='OfflinePredictionInputContextUp', rva=0x6d4dbb0, offset=0x6d4b1b0,
         before='9082bf8301000000', target_rva=0x3bf8290,
         relocation_block_offset=0x736fbb4, relocation_block_before='00d0d40614030000',
         relocation_entry_offset=0x736fdb2, relocation_entry_before='b0ab'),
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
    # Original input bodies and accepted Down call context remain untouched.
    dict(rva=0x3bf7760, before='83b9a0000000007558833dd8ec240300488d91a800000048c70200000000c781'),
    dict(rva=0x3bf77d0, before='83b9a0000000017558833d68ec240300488d91a800000048c70200000000c781'),
    dict(rva=0x3bf7840, before='83b9a0000000027558833df8eb240300488d91a800000048c70200000000c781'),
    dict(rva=0x3bf78b0, before='83b9a0000000037558833d88eb240300488d91a800000048c70200000000c781'),
    dict(rva=0x3bf7920, before='83b9a0000000047558833d18eb240300488d91a800000048c70200000000c781'),
    dict(rva=0x3bf7990, before='33d2e989e9ffffcccccccccccccccccc48895c2408574883ec20803d8d152603'),
    dict(rva=0x3bf79a0, before='48895c2408574883ec20803d8d15260300488bfa488bd97518488d0d80d3f102'),
    dict(rva=0x3bf7a70, before='48895c2408574883ec20803dbe14260300488bda488bf97518488d0db0d2f102'),
    dict(rva=0x3bf7ad0, before='48895c2410574883ec50803d5f14260300488bfa488bd9753a488d0da065f602'),
    dict(rva=0x3bf7d20, before='48895c24104889742418574883ec30803d0b12260300488bf2488bd9754b488d'),
    dict(rva=0x3bf7f60, before='40534883ec20488bc2488bd9488bc833d2e8aa3aa40080bb190100000088836c'),
    dict(rva=0x3bf80f0, before='48895c2410574883ec70803d410e260300488bfa488bd97518488d0dc8d1f102'),
    dict(rva=0x3bf8290, before='40534883ec20488bc2488bd9488bc833d2e87a37a40088836d0100004883c420'),
    dict(rva=0x3bf7e5f, before='33d2488bcb'),
    dict(rva=0x3bf7e69, before='488b5c2448488b7424504883c4305fc3'),
    dict(rva=0x3bf4a60, before='40534883ec60803dc044260300488bd97518488d0d67c9f102e88281a2fcf083'),
    dict(rva=0x3bf8e0f, before='488b742430898328010000c7837001000001000000488b5c24384883c4205fc3'),
    # Special delegate ctor retains the actual callback MI and reads its +8
    # dispatch pointer. Both subscription and removal use the same original
    # MI cells; no delegate or MethodInfo layout is rewritten by these hooks.
    dict(rva=0x18d00, before='40534883ec20833d3bd7e20600488bda498b40084c8bc9488941104c89412848895120'),
    # Subscribe: original callback MI load / selector / delegate / ctor.
    dict(rva=0x3bee820, before='4c8b05796bf202488bd7488bc8488be8e8cba442fc'),
    dict(rva=0x3bee991, before='4c8b05186af202488bd7488bc8488be8e85aa342fc'),
    dict(rva=0x3beeb02, before='4c8b059f68f202488bd7488bc8488be8e8e9a142fc'),
    dict(rva=0x3beec73, before='4c8b054667f202488bd7488bc8488be8e878a042fc'),
    dict(rva=0x3beede4, before='4c8b05cd65f202488bd7488bc8488be8e8079f42fc'),
    dict(rva=0x3beee5f, before='4c8b05e262f202488bd7488bc8488be8e88c9e42fc'),
    dict(rva=0x3beeeda, before='4c8b05af61f202488bd7488bc8488be8e8119e42fc'),
    dict(rva=0x3beef55, before='4c8b053461f202488bd7488bc8488be8e8969d42fc'),
    dict(rva=0x3beefd0, before='4c8b056160f202488bd7488bc8488be8e81b9d42fc'),
    dict(rva=0x3bef04b, before='4c8b05e65ff202488bd7488bc8488be8e8a09c42fc'),
    dict(rva=0x3bef0c6, before='4c8b059b5ff202488bd7488bc8488be8e8259c42fc'),
    dict(rva=0x3bef141, before='4c8b05005ff202488bd7488bc8488be8e8aa9b42fc'),
    dict(rva=0x3bef1bc, before='4c8b059d5ef202488bd7488bc8488be8e82f9b42fc'),
    dict(rva=0x3bef237, before='4c8b05ea5df202488bd7488bc8488be8e8b49a42fc'),
    dict(rva=0x3bef2ae, before='4c8b05a35df202488bd7488bc8488bf0e83d9a42fc'),
    # Unsubscribe: original callback MI load / selector / delegate / ctor.
    dict(rva=0x3befb80, before='4c8b051958f202488bd7488bc8488be8e86b9142fc'),
    dict(rva=0x3befcf1, before='4c8b05b856f202488bd7488bc8488be8e8fa8f42fc'),
    dict(rva=0x3befe62, before='4c8b053f55f202488bd7488bc8488be8e8898e42fc'),
    dict(rva=0x3beffd3, before='4c8b05e653f202488bd7488bc8488be8e8188d42fc'),
    dict(rva=0x3bf0144, before='4c8b056d52f202488bd7488bc8488be8e8a78b42fc'),
    dict(rva=0x3bf01bf, before='4c8b05824ff202488bd7488bc8488be8e82c8b42fc'),
    dict(rva=0x3bf023a, before='4c8b054f4ef202488bd7488bc8488be8e8b18a42fc'),
    dict(rva=0x3bf02b5, before='4c8b05d44df202488bd7488bc8488be8e8368a42fc'),
    dict(rva=0x3bf0330, before='4c8b05014df202488bd7488bc8488be8e8bb8942fc'),
    dict(rva=0x3bf03ab, before='4c8b05864cf202488bd7488bc8488be8e8408942fc'),
    dict(rva=0x3bf0426, before='4c8b053b4cf202488bd7488bc8488be8e8c58842fc'),
    dict(rva=0x3bf04a1, before='4c8b05a04bf202488bd7488bc8488be8e84a8842fc'),
    dict(rva=0x3bf051c, before='4c8b053d4bf202488bd7488bc8488be8e8cf8742fc'),
    dict(rva=0x3bf0597, before='4c8b058a4af202488bd7488bc8488be8e8548742fc'),
    dict(rva=0x3bf060e, before='4c8b05434af202488bd7488bc8488bf0e8dd8642fc'),
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
