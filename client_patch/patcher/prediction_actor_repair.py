"""Optional movement-experiment actor hook; never part of the normal recipe.

Apply only with the exact original admission/recipe checks already required by
the patcher. BODY_GUARDS describe additional untouched original call targets;
the helper also validates their runtime bytes before enabling ownership work.
"""
import hashlib
import struct
from . import prediction_selection
from . import prediction_click_provenance

SUPPORTED_ORIGINAL_SHA256 = 'e59d08c01479b27404778048d7e13546dbf3771f6b3912744c7c2bdf80c4e758'
CALL_HOOKS = [
    # Exact original Trigger -> EventContext.get_EventOwner edge. Observe its
    # actual result without an additional lookup or a fabricated EventContext.
    dict(name='OfflinePredictionTimelineEventOwner', rva=0x3be43be,
         offset=0x3be29be, before='e8bdd4feff'),
    dict(name='OfflinePredictionTimelineEventOwner', rva=0x3be4661,
         offset=0x3be2c61, before='e81ad2feff'),
    dict(name='OfflinePredictionTimelineEventOwner', rva=0x3be47b5,
         offset=0x3be2db5, before='e8c6d0feff'),
    dict(name='OfflinePredictionTimelineAnimator', rva=0x3be46a9,
         offset=0x3be2ca9, before='e862a77dfd'),
    dict(name='OfflinePredictionTimelineBinding', rva=0x3be468c,
         offset=0x3be2c8c, before='e84f954f01'),
    dict(name='OfflinePredictionTimelineBinding', rva=0x3be46bd,
         offset=0x3be2cbd, before='e81e954f01'),
    dict(name='OfflinePredictionTimelinePlay', rva=0x3be478a,
         offset=0x3be2d8a, before='e8e1904f01'),
    dict(name='OfflinePredictionActorUpdate', rva=0x3e6608b,
         offset=0x3e6468b, before='e8801fdaff'),
    # bool(UnitSelectionSet*, uint32 entity, MethodInfo*=null). The ORIGINAL
    # false-Contains branch has already removed trackedReleasedUnits. Decline
    # only the complete typed membership operation; the return is ignored.
    dict(name='OfflinePredictionGroupReleaseRemove', rva=0x3ea625a,
         offset=0x3ea485a, before='e8b103dcff'),
] + prediction_selection.CALL_HOOKS + prediction_click_provenance.CALL_HOOKS
TAIL_HOOKS = list(prediction_click_provenance.TAIL_HOOKS)
POINTER_HOOKS = list(prediction_selection.POINTER_HOOKS) + [
    # Passive terminal diagnostic. The helper forwards the original Trigger
    # once with the actual EventContext/MethodInfo; it never consumes failures.
    dict(name='OfflinePredictionTimelineTrigger', rva=0x6d4ced0, offset=0x6d4a4d0,
         before='9042be8301000000', target_rva=0x3be4290,
         relocation_block_offset=0x736f880, relocation_block_before='00c0d40634030000',
         relocation_entry_offset=0x736fb74, relocation_entry_before='d0ae'),
]
PATCHES = list(prediction_selection.PATCHES)
BODY_GUARDS = [
    dict(rva=0x3c699b0, before='48895c2408574883ec20488bd98bfa48'),
    dict(rva=0x3c63de0, before='c74154ffffffffc3'),
    dict(rva=0x3c08010, before='488bc44889501048894808535657415441'),
    dict(rva=0x3c0913c, before='e8afe8ffff'),
    dict(rva=0x3c08655, before='e8f68650ff'),
    dict(rva=0x3be9770, before='48896c2420574883ec20803d71f72603'),
    dict(rva=0x3bf0cf0, before='48895c241048894c2408565741544156'),
    dict(rva=0x3c6c660, before='40534883ec20488bd94885d20f84fa00'),
    dict(rva=0x3c54b2d, before='e80e150000'),
    dict(rva=0x3e66151, before='ff5718'),
    dict(rva=0x3ea6236, before='8b974c0100004533c0e82cc38dff498b4d204885c90f84f40000008b974c0100004533c0'),
    dict(rva=0x3ea625f, before='eb660fb7c84803c9'),
    dict(rva=0x3ea62df, before='498b4d204885c9745d33d2e8112cdcff3bc3741f498b4d404885c9744980791000753d'),
    dict(rva=0x3c66610, before='48895c24188954241048894c2408565741574881ec800000008bf2488bf9'),
    dict(rva=0x3b02170, before='807910007511488b01488b909001000048ffa088010000c6411201c3'),
    dict(rva=0x3ea5790, before='4883ec28488b49404885c9740c4533c04883c428e9e7c9c5ff'),
    dict(rva=0x3b02160, before='33d2e979010000'),
] + prediction_click_provenance.BODY_GUARDS


def _pe_sections(data):
    """Read bounded AMD64 PE32+ section mappings without assuming an RVA delta."""
    def require(condition, message):
        if not condition:
            raise ValueError('Prediction actor PE: ' + message)

    require(len(data) >= 0x40 and data[:2] == b'MZ', 'missing DOS header')
    pe = struct.unpack_from('<I', data, 0x3c)[0]
    require(0x40 <= pe <= len(data) - 24 and data[pe:pe + 4] == b'PE\0\0',
            'missing or truncated PE header')
    machine, count = struct.unpack_from('<HH', data, pe + 4)
    require(machine == 0x8664 and 1 <= count <= 96, 'unsupported machine/section count')
    optional_size = struct.unpack_from('<H', data, pe + 20)[0]
    opt = pe + 24
    require(optional_size >= 112 and opt + optional_size <= len(data),
            'truncated PE32+ optional header')
    require(struct.unpack_from('<H', data, opt)[0] == 0x20b, 'unsupported optional header')
    headers = struct.unpack_from('<I', data, opt + 60)[0]
    table = opt + optional_size
    require(table + count * 40 <= headers <= len(data), 'truncated section table/headers')
    sections, raw_ranges, virtual_ranges = [], [], []
    for index in range(count):
        virtual_size, rva, raw_size, raw_offset = struct.unpack_from(
            '<IIII', data, table + index * 40 + 8)
        extent = max(virtual_size, raw_size)
        require(rva + extent <= 0x100000000, 'section RVA extent overflows')
        if extent:
            require(rva >= headers, 'section overlaps headers')
            virtual_ranges.append((rva, rva + extent))
        if raw_size:
            require(raw_offset >= headers and raw_offset + raw_size <= len(data),
                    'section raw bytes outside file/overlap headers')
            raw_ranges.append((raw_offset, raw_offset + raw_size))
        sections.append((rva, raw_offset, raw_size))
    for ranges in (raw_ranges, virtual_ranges):
        ordered = sorted(ranges)
        require(all(a[1] <= b[0] for a, b in zip(ordered, ordered[1:])),
                'overlapping section ranges')
    return headers, sections


def _mapped_offset(headers, sections, rva, length):
    if (type(rva) is not int or type(length) is not int or rva < 0 or
            length <= 0 or rva + length > 0x100000000):
        raise ValueError('Prediction actor PE: invalid RVA range')
    if rva + length <= headers:
        return rva
    for section_rva, raw_offset, raw_size in sections:
        delta = rva - section_rva
        if delta >= 0 and delta + length <= raw_size:
            return raw_offset + delta
    raise ValueError(f'Prediction actor PE: RVA 0x{rva:x}+0x{length:x} is not file-backed')


def rva_to_offset(original, rva, length):
    """Map a complete file-backed range; reject gaps, zero-fill and malformed PE."""
    return _mapped_offset(*_pe_sections(original), rva, length)


def validate_pointer_hooks(original, hooks):
    """Validate exact method slots and their unique, file-backed DIR64 entries."""
    if not hooks:
        return []

    def require(condition, message):
        if not condition:
            raise ValueError('Prediction actor pointer: ' + message)

    headers, sections = _pe_sections(original)
    pe = struct.unpack_from('<I', original, 0x3c)[0]
    opt = pe + 24
    require(struct.unpack_from('<H', original, pe + 20)[0] >= 160 and
            struct.unpack_from('<I', original, opt + 108)[0] >= 6,
            'base relocation directory is missing')
    image_base = struct.unpack_from('<Q', original, opt + 24)[0]
    directory_rva, directory_size = struct.unpack_from('<II', original, opt + 112 + 5 * 8)
    require(directory_size >= 8, 'base relocation directory is empty')
    directory = _mapped_offset(headers, sections, directory_rva, directory_size)
    wanted = set()
    for hook in hooks:
        for key in ('rva', 'offset', 'target_rva', 'relocation_block_offset', 'relocation_entry_offset'):
            require(type(hook.get(key)) is int and hook[key] >= 0, 'invalid descriptor ' + key)
        require(hook['rva'] not in wanted, 'duplicate method-pointer slot')
        wanted.add(hook['rva'])
    matches = {rva: 0 for rva in wanted}
    blocks = {}
    at, end = directory, directory + directory_size
    while at < end:
        require(at + 8 <= end, 'truncated relocation block header')
        page, size = struct.unpack_from('<II', original, at)
        require(page % 4096 == 0 and size >= 8 and size % 2 == 0 and at + size <= end,
                'malformed relocation block')
        blocks[at] = (page, size)
        for entry in range(at + 8, at + size, 2):
            value = struct.unpack_from('<H', original, entry)[0]
            target = page + (value & 0xfff)
            if value >> 12 == 10 and target in matches:
                matches[target] += 1
        at += size
    guarded = []
    for hook in hooks:
        offset = _mapped_offset(headers, sections, hook['rva'], 8)
        before = bytes.fromhex(hook['before'])
        require(offset == hook['offset'] and len(before) == 8 and original[offset:offset + 8] == before,
                'method-pointer bytes/mapping mismatch: ' + hook['name'])
        _mapped_offset(headers, sections, hook['target_rva'], 1)
        require(image_base + hook['target_rva'] < 1 << 64 and
                int.from_bytes(before, 'little') == image_base + hook['target_rva'],
                'original target mismatch: ' + hook['name'])
        block, entry = hook['relocation_block_offset'], hook['relocation_entry_offset']
        require(block in blocks, 'relocation block is not in the PE directory')
        page, size = blocks[block]
        block_bytes, entry_bytes = (bytes.fromhex(hook[key]) for key in
                                   ('relocation_block_before', 'relocation_entry_before'))
        require(len(block_bytes) == 8 and len(entry_bytes) == 2 and
                original[block:block + 8] == block_bytes and
                block + 8 <= entry < block + size and (entry - block) % 2 == 0 and
                original[entry:entry + 2] == entry_bytes,
                'relocation bytes/entry mismatch: ' + hook['name'])
        relocation = struct.unpack_from('<H', original, entry)[0]
        require(relocation >> 12 == 10 and page + (relocation & 0xfff) == hook['rva'] and
                matches[hook['rva']] == 1, 'unique DIR64 target mismatch: ' + hook['name'])
        guarded.append(dict(hook, image_base=image_base,
                            relocation_directory_rva=directory_rva,
                            relocation_directory_size=directory_size))
    return guarded


def validate_byte_patches(original, patches):
    guarded = []
    for item in patches:
        before, after = bytes.fromhex(item['before']), bytes.fromhex(item['after'])
        offset = rva_to_offset(original, item['rva'], len(before))
        if not before or len(before) != len(after) or offset != item['offset'] or original[offset:offset + len(before)] != before:
            raise ValueError('Prediction actor byte patch guard/mapping mismatch: ' + item['name'])
        guarded.append(dict(item))
    return guarded


def validate_original(original, *, expected_sha256):
    """Return guard provenance only after independent recipe and original checks.

    The caller supplies its own supported-build constant, so drift between the
    ordinary recipe and this optional descriptor fails before patching. No
    original target bytes are changed by these additional guards.
    """
    if expected_sha256 != SUPPORTED_ORIGINAL_SHA256:
        raise ValueError('Prediction actor supported original SHA256 differs from patch recipe.')
    actual_sha256 = hashlib.sha256(original).hexdigest()
    if actual_sha256 != SUPPORTED_ORIGINAL_SHA256:
        raise ValueError('Prediction actor original SHA256 does not match.')
    selection = prediction_selection.validate_original(
        original, expected_sha256=expected_sha256)
    headers, sections = _pe_sections(original)
    guarded = []
    for guard in BODY_GUARDS:
        before = bytes.fromhex(guard['before'])
        offset = _mapped_offset(headers, sections, guard['rva'], len(before))
        if original[offset:offset + len(before)] != before:
            raise ValueError(f"Prediction actor body guard mismatch: 0x{guard['rva']:x}")
        guarded.append(dict(rva=guard['rva'], offset=offset, before=guard['before']))
    calls = []
    for hook in CALL_HOOKS:
        before = bytes.fromhex(hook['before'])
        offset = _mapped_offset(headers, sections, hook['rva'], len(before))
        if offset != hook['offset'] or original[offset:offset + len(before)] != before:
            raise ValueError('Prediction actor call guard/mapping mismatch: ' + hook['name'])
        calls.append(dict(hook))
    pointers = validate_pointer_hooks(original, POINTER_HOOKS)
    tails = []
    for hook in TAIL_HOOKS:
        before = bytes.fromhex(hook['before'])
        offset = _mapped_offset(headers, sections, hook['rva'], len(before))
        if (len(before) != 5 or before[0] != 0xe9 or offset != hook['offset'] or
                original[offset:offset + len(before)] != before):
            raise ValueError('Prediction actor tail guard/mapping mismatch: ' + hook['name'])
        tails.append(dict(hook))
    patches = validate_byte_patches(original, PATCHES)
    return dict(original_sha256=actual_sha256,
                supported_original_sha256=SUPPORTED_ORIGINAL_SHA256,
                body_guards=guarded, call_hooks=calls, tail_hooks=tails,
                pointer_hooks=[dict(hook) for hook in POINTER_HOOKS], pointer_guards=pointers,
                patches=patches,
                selection_admission=selection)
