"""Optional movement-experiment actor hook; never part of the normal recipe.

Apply only with the exact original admission/recipe checks already required by
the patcher. BODY_GUARDS describe additional untouched original call targets;
the helper also validates their runtime bytes before enabling ownership work.
"""
import hashlib
import struct
from . import prediction_selection

SUPPORTED_ORIGINAL_SHA256 = 'e59d08c01479b27404778048d7e13546dbf3771f6b3912744c7c2bdf80c4e758'
CALL_HOOKS = [
    dict(name='OfflinePredictionActorUpdate', rva=0x3e6608b,
         offset=0x3e6468b, before='e8801fdaff'),
] + prediction_selection.CALL_HOOKS
BODY_GUARDS = [
    dict(rva=0x3c08010, before='488bc44889501048894808535657415441'),
    dict(rva=0x3c0913c, before='e8afe8ffff'),
    dict(rva=0x3c08655, before='e8f68650ff'),
    dict(rva=0x3be9770, before='48896c2420574883ec20803d71f72603'),
    dict(rva=0x3bf0cf0, before='48895c241048894c2408565741544156'),
    dict(rva=0x3c6c660, before='40534883ec20488bd94885d20f84fa00'),
    dict(rva=0x3c54b2d, before='e80e150000'),
    dict(rva=0x3e66151, before='ff5718'),
]


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
    return dict(original_sha256=actual_sha256,
                supported_original_sha256=SUPPORTED_ORIGINAL_SHA256,
                body_guards=guarded, call_hooks=calls,
                selection_admission=selection)
