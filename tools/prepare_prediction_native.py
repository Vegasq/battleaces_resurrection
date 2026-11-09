"""Derive an ignored PRIVATE native DLL with early BAHeap heap imports.

This is a file-only experiment, never a launcher/runtime import. No DLL is
loaded, no code/TLS callback/initializer runs, and the original is never written.
Each KERNEL32 import run gets its own copied, null-terminated lookup table while
its FirstThunk still addresses the ORIGINAL IAT slots. Adjacent original IAT
ranges cannot gain extra terminators; loader qualification is a separate check.
"""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import struct

from client_patch.patcher.pe_imports import (
    PEFormatError, _align, _require, extend_imports, pe_checksum,
)

ROOT = Path(__file__).resolve().parents[1]
# Intentionally independent of any private child's runtime hash override.
SUPPORTED_ORIGINAL_SHA256 = '107bb83dc416a16492277392c50104660e34c48911345ae2e0d5afe3929a07fb'
HELPER_DLL = 'BAHeap.dll'
HEAP_IAT_RVAS = {
    'HeapAlloc': 0x3852D8, 'HeapFree': 0x3852E0,
    'HeapReAlloc': 0x385360, 'HeapSize': 0x3853B8,
}


def _sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


class _Image:
    """Bounded inspection after extend_imports has validated the PE layout."""
    def __init__(self, data: bytes):
        self.data = data
        self.pe = self.u32(0x3C)
        self.opt = self.pe + 24
        self.count = self.u16(self.pe + 6)
        self.table = self.opt + self.u16(self.pe + 20)
        self.sections = [struct.unpack_from('<8sIIIIIIHHI', data, self.table + index * 40)
                         for index in range(self.count)]

    def unpack(self, fmt: str, offset: int):
        size = struct.calcsize(fmt)
        _require(0 <= offset <= len(self.data) - size, 'Truncated PE field')
        return struct.unpack_from(fmt, self.data, offset)

    def u16(self, offset: int) -> int:
        return self.unpack('<H', offset)[0]

    def u32(self, offset: int) -> int:
        return self.unpack('<I', offset)[0]

    def mapped(self, rva: int, length: int) -> int:
        _require(0 <= rva <= 0xFFFFFFFF and 0 <= length <= 0xFFFFFFFF - rva,
                 'RVA range overflows')
        if rva + length <= self.u32(self.opt + 60):
            return rva
        for _, _, section_rva, raw_size, raw, *_ in self.sections:
            delta = rva - section_rva
            if delta >= 0 and delta + length <= raw_size:
                return raw + delta
        raise PEFormatError(f'RVA range 0x{rva:X}+0x{length:X} is not file-backed')

    def string(self, rva: int) -> str:
        offset = self.mapped(rva, 1)
        end = self.data.find(b'\0', offset, min(offset + 0x10000, len(self.data)))
        _require(end > offset, 'Empty or unterminated import name')
        self.mapped(rva, end - offset + 1)
        raw = self.data[offset:end]
        _require(all(0x21 <= value <= 0x7E for value in raw), 'Non-ASCII import name')
        return raw.decode('ascii')

    def directories(self) -> dict:
        return {str(index): dict(zip(('rva', 'size'), self.unpack('<II', self.opt + 112 + index * 8)))
                for index in range(self.u32(self.opt + 108))}

    def imports(self) -> list[dict]:
        directory = self.directories()['1']
        rows = []
        spans = []
        for index in range(directory['size'] // 20):
            offset = self.mapped(directory['rva'] + index * 20, 20)
            raw = self.data[offset:offset + 20]
            ilt, stamp, forwarder, name_rva, iat = struct.unpack('<5I', raw)
            if not any(raw):
                break
            _require(not stamp and not forwarder, 'Bound/forwarder imports are unsupported')
            _require(iat % 8 == 0 and (ilt or iat) % 8 == 0, 'Unaligned import thunks')
            entries = []
            for item in range(4097):
                lookup = self.unpack('<Q', self.mapped((ilt or iat) + item * 8, 8))[0]
                target = self.unpack('<Q', self.mapped(iat + item * 8, 8))[0]
                _require(lookup == target, 'Original IAT differs from unbound lookup table')
                if not lookup:
                    break
                _require(item < 4096, 'Import thunk count exceeds bounded limit')
                if lookup >> 63:
                    _require(not (lookup & ~((1 << 63) | 0xFFFF)), 'Invalid ordinal import bits')
                    entry = dict(lookup=lookup, ordinal=lookup & 0xFFFF, name=None, hint=None)
                else:
                    _require(lookup < (1 << 31), 'Invalid hint/name RVA bits')
                    hint = self.unpack('<H', self.mapped(lookup, 2))[0]
                    entry = dict(lookup=lookup, ordinal=None, name=self.string(lookup + 2), hint=hint)
                entries.append(entry)
            _require(bool(entries), 'Empty import descriptor')
            spans.append((iat, iat + (len(entries) + 1) * 8))
            rows.append(dict(raw=raw, dll=self.string(name_rva), ilt=ilt, iat=iat, entries=entries))
        ordered = sorted(spans)
        _require(all(left[1] <= right[0] for left, right in zip(ordered, ordered[1:])),
                 'Overlapping original IAT ranges')
        return rows


def _byte_patches(original: bytes, derived: bytes) -> list[dict]:
    patches = []
    offset = 0
    while offset < len(original):
        if original[offset] == derived[offset]:
            offset += 1
            continue
        start = offset
        while offset < len(original) and original[offset] != derived[offset]:
            offset += 1
        patches.append(dict(offset=start, before_hex=original[start:offset].hex(),
                            after_hex=derived[start:offset].hex()))
    if len(derived) > len(original):
        patches.append(dict(offset=len(original), before_hex='', after_hex=derived[len(original):].hex()))
    return patches


def _partition_heap_imports(original: bytes) -> tuple[bytes, dict]:
    """Generic private PE transform for authored fixtures; NOT the file API.

    Reuse the conservative appender's complete layout/signature/overlay checks
    and section-header allocation. Its temporary new imports are replaced in
    memory; their IAT is not present in the final section.
    """
    extended, _ = extend_imports(original, HELPER_DLL, HEAP_IAT_RVAS)
    image, staged = _Image(original), _Image(extended)
    imports = image.imports()
    kernels = [row for row in imports if row['dll'].lower() == 'kernel32.dll']
    _require(len(kernels) == 1, 'Exactly one original KERNEL32 descriptor is required')
    kernel = kernels[0]
    for name in HEAP_IAT_RVAS:
        _require(sum(entry['name'] == name for entry in kernel['entries']) == 1,
                 f'{name} must occur exactly once in KERNEL32 imports')
    runs = []
    for index, entry in enumerate(kernel['entries']):
        dll = HELPER_DLL if entry['name'] in HEAP_IAT_RVAS else kernel['dll']
        if not runs or runs[-1]['dll'] != dll:
            runs.append(dict(dll=dll, start=index, entries=[]))
        runs[-1]['entries'].append(entry)
    descriptor_count = len(imports) - 1 + len(runs)
    descriptor_size = (descriptor_count + 1) * 20
    payload = bytearray(descriptor_size)
    section = staged.sections[-1]
    new_rva, new_raw = section[2], section[4]
    dll_names = {}

    def append(raw: bytes, alignment: int = 1) -> int:
        payload.extend(bytes(_align(len(payload), alignment) - len(payload)))
        relative = len(payload)
        payload.extend(raw)
        return relative

    ranges = []
    slot = 0
    for row in imports:
        if row is not kernel:
            payload[slot * 20:(slot + 1) * 20] = row['raw']
            slot += 1
            continue
        for run in runs:
            dll = run['dll']
            if dll not in dll_names:
                dll_names[dll] = new_rva + append(dll.encode('ascii') + b'\0')
            int_relative = append(bytes((len(run['entries']) + 1) * 8), 8)
            for item, entry in enumerate(run['entries']):
                value = entry['lookup']
                if entry['name'] is not None:
                    value = new_rva + append(struct.pack('<H', entry['hint']) +
                                             entry['name'].encode('ascii') + b'\0', 2)
                    _require(value < (1 << 31), 'Copied hint/name RVA exceeds PE name limit')
                struct.pack_into('<Q', payload, int_relative + item * 8, value)
            iat = kernel['iat'] + run['start'] * 8
            struct.pack_into('<5I', payload, slot * 20,
                             new_rva + int_relative, 0, 0, dll_names[dll], iat)
            ranges.append(dict(dll=dll, start_index=run['start'], count=len(run['entries']),
                               first_thunk_rva=iat, int_rva=new_rva + int_relative,
                               imports=[entry['name'] if entry['name'] is not None else
                                        dict(ordinal=entry['ordinal']) for entry in run['entries']]))
            slot += 1
    _require(slot == descriptor_count, 'Internal descriptor count mismatch')
    section_alignment, file_alignment = image.unpack('<II', image.opt + 32)
    virtual_size = len(payload)
    raw_size = _align(virtual_size, file_alignment)
    image_size = _align(new_rva + max(virtual_size, raw_size), section_alignment)
    initialized_size = image.u32(image.opt + 8) + raw_size
    _require(max(new_raw + raw_size, image_size, initialized_size) <= 0xFFFFFFFF,
             'Partitioned PE size overflows')
    output = bytearray(extended[:new_raw])
    output.extend(payload)
    output.extend(bytes(raw_size - virtual_size))
    struct.pack_into('<8sIIIIIIHHI', output, image.table + image.count * 40,
                     b'.offline', virtual_size, new_rva, raw_size, new_raw,
                     0, 0, 0, 0, 0x40000040)  # READONLY initialized data; no new IAT.
    struct.pack_into('<I', output, image.opt + 8, initialized_size)
    struct.pack_into('<I', output, image.opt + 56, image_size)
    struct.pack_into('<II', output, image.opt + 120, new_rva, descriptor_size)
    struct.pack_into('<I', output, image.opt + 64, pe_checksum(output, image.opt + 64))
    derived = bytes(output)
    for row in imports:
        size = (len(row['entries']) + 1) * 8
        raw = image.mapped(row['iat'], size)
        _require(derived[raw:raw + size] == original[raw:raw + size],
                 'Original IAT bytes unexpectedly changed')
    preserved = []
    for name, virtual_size, rva, size, raw, *_ in image.sections:
        _require(derived[raw:raw + size] == original[raw:raw + size],
                 'Original section bytes unexpectedly changed')
        preserved.append(dict(name=name.rstrip(b'\0').decode('ascii'), rva=rva,
                              raw_offset=raw, raw_size=size,
                              sha256=_sha(original[raw:raw + size])))
    heap_iats = {entry['name']: kernel['iat'] + index * 8
                 for index, entry in enumerate(kernel['entries']) if entry['name'] in HEAP_IAT_RVAS}
    manifest = dict(experimental=True, private_only=True, status='DERIVED_NOT_LOADED',
                    original_sha256=_sha(original), derived_sha256=_sha(derived),
                    original_size=len(original), derived_size=len(derived), helper_dll=HELPER_DLL,
                    heap_iat_rvas=heap_iats, ranges=ranges,
                    directories_before=image.directories(), directories_after=_Image(derived).directories(),
                    appended_section=dict(name='.offline', rva=new_rva, raw_offset=new_raw,
                                          virtual_size=len(payload), raw_size=raw_size, characteristics=0x40000040),
                    preserved_original_sections=preserved, byte_patches=_byte_patches(original, derived),
                    original_iat_bytes_preserved=True, loader_qualified=False)
    return derived, manifest


def derive_native(original_bytes: bytes) -> tuple[bytes, dict]:
    """Pure exact-original derivation; no hash override or native execution."""
    if not isinstance(original_bytes, bytes) or _sha(original_bytes) != SUPPORTED_ORIGINAL_SHA256:
        raise ValueError('Unsupported original Simulation.dll SHA256')
    derived, manifest = _partition_heap_imports(original_bytes)
    _require(manifest['heap_iat_rvas'] == HEAP_IAT_RVAS, 'Exact original heap IAT RVAs differ')
    return derived, manifest


def prepare_native(input_path: str | Path, output_path: str | Path) -> dict:
    """Write a fresh private DLL and adjacent .derivation.json under local/."""
    source, output = Path(input_path).resolve(), Path(output_path).resolve()
    owned = (ROOT / 'local').resolve()
    try:
        owned.relative_to(ROOT.resolve())
        output.relative_to(owned)
    except ValueError as exc:
        raise ValueError('Derivative output must stay inside the ignored repository local/ tree') from exc
    if source == output or output.suffix.lower() != '.dll':
        raise ValueError('Choose a distinct private .dll output path')
    manifest_path = output.with_suffix('.derivation.json')
    if output.exists() or manifest_path.exists():
        raise FileExistsError('Choose fresh derivative and manifest paths')
    original = source.read_bytes()
    derived, manifest = derive_native(original)
    output.parent.mkdir(parents=True, exist_ok=True)
    with output.open('xb') as stream:
        stream.write(derived)
    if _sha(source.read_bytes()) != manifest['original_sha256']:
        raise RuntimeError('Original changed during derivation; derivative has no accepted manifest')
    manifest.update(input=str(source), output=str(output), manifest=str(manifest_path),
                    source_unchanged=True, tool_sha256=_sha(Path(__file__).read_bytes()),
                    pe_imports_sha256=_sha((ROOT / 'client_patch/patcher/pe_imports.py').read_bytes()))
    with manifest_path.open('x', encoding='utf-8') as stream:
        json.dump(manifest, stream, indent=2)
        stream.write('\n')
    return manifest


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('input', type=Path)
    parser.add_argument('output', type=Path)
    args = parser.parse_args()
    result = prepare_native(args.input, args.output)
    print(json.dumps({key: result[key] for key in (
        'status', 'output', 'manifest', 'original_sha256', 'derived_sha256', 'heap_iat_rvas')}, indent=2))


if __name__ == '__main__':
    main()
