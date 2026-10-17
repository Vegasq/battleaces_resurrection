"""Conservatively append named DLL imports to an unsigned AMD64 PE32+ image.

No code is executed and no existing section is moved.  The function is pure;
the command-line interface writes only the caller-selected derivative file.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import struct
import sys
from pathlib import Path
from typing import Iterable


class PEFormatError(ValueError):
    """The input is malformed or uses a deliberately unsupported PE layout."""


def _align(value: int, alignment: int) -> int:
    return (value + alignment - 1) & -alignment


def _require(condition: bool, message: str) -> None:
    if not condition:
        raise PEFormatError(message)


def _ascii_z(value: str, label: str) -> bytes:
    _require(isinstance(value, str) and bool(value), f"{label} must be nonempty text")
    try:
        encoded = value.encode("ascii")
    except UnicodeEncodeError as exc:
        raise PEFormatError(f"{label} must be ASCII") from exc
    _require(all(0x21 <= c <= 0x7E for c in encoded),
             f"{label} must contain printable ASCII without spaces or NUL")
    return encoded + b"\0"


def pe_checksum(data: bytes | bytearray, checksum_offset: int) -> int:
    """Return the PE checksum with the existing CheckSum DWORD excluded."""
    _require(checksum_offset % 2 == 0 and checksum_offset + 4 <= len(data),
             "Invalid checksum field offset")
    view = memoryview(data)
    even_end = len(data) & ~1
    if sys.byteorder == "little":
        total = sum(view[:even_end].cast("H"))
    else:
        total = sum(x[0] for x in struct.iter_unpack("<H", view[:even_end]))
    if len(data) & 1:
        total += data[-1]
    total -= sum(struct.unpack_from("<HH", data, checksum_offset))
    while total >> 16:
        total = (total & 0xFFFF) + (total >> 16)
    return (total + len(data)) & 0xFFFFFFFF


def extend_imports(
    original_bytes: bytes,
    dll_name: str,
    export_names: Iterable[str],
) -> tuple[bytes, dict[str, int]]:
    """Return ``(new_image_bytes, {export_name: IAT_RVA})``.

    Adds one RW/non-executable ``.offline`` section containing a copy of all
    original import descriptors, a new descriptor, its terminating descriptor,
    the DLL name, an ILT, an IAT, and hint/name records. Existing sections and
    original import descriptors remain byte-for-byte unchanged.

    Supports AMD64 PE32+ with normal section/file alignment and spare zeroed
    section-header space. Rejects signatures, overlays, COFF symbol tables,
    bound imports, overlapping sections, repeated DLLs, repeated exports, and
    images already containing .offline. No ordinal imports can be added.

    The existing IAT data directory is preserved: the new IAT is discontiguous
    and explicitly writable. The Windows loader discovers it through the new
    descriptor's FirstThunk, not through an expanded IAT directory range.
    """
    _require(isinstance(original_bytes, bytes), "original_bytes must be bytes")
    data = original_bytes
    dll_z = _ascii_z(dll_name, "DLL name")
    _require(not any(c in dll_name for c in '/\\:'), "DLL name must be a basename")
    _require(not isinstance(export_names, (str, bytes)), "export_names must be an iterable of names")
    names = list(export_names)
    _require(bool(names), "At least one export name is required")
    name_z = [_ascii_z(name, "Export name") for name in names]
    _require(len(set(names)) == len(names), "Duplicate export names")

    def u16(offset: int) -> int:
        _require(0 <= offset <= len(data) - 2, "Truncated WORD")
        return struct.unpack_from("<H", data, offset)[0]

    def u32(offset: int) -> int:
        _require(0 <= offset <= len(data) - 4, "Truncated DWORD")
        return struct.unpack_from("<I", data, offset)[0]

    _require(len(data) >= 0x40 and data[:2] == b"MZ", "Missing DOS header")
    pe = u32(0x3C)
    _require(pe >= 0x40 and pe + 24 <= len(data) and data[pe:pe + 4] == b"PE\0\0",
             "Missing or truncated PE header")
    _require(u16(pe + 4) == 0x8664, "Only AMD64 is supported")
    count = u16(pe + 6)
    _require(1 <= count < 96, "Unsupported section count")
    _require(u32(pe + 12) == 0 and u32(pe + 16) == 0,
             "COFF symbol tables are unsupported")
    optional_size = u16(pe + 20)
    opt = pe + 24
    _require(optional_size >= 128 and opt + optional_size <= len(data),
             "Truncated PE32+ optional header")
    _require(u16(opt) == 0x20B, "Only PE32+ is supported")
    section_alignment = u32(opt + 32)
    file_alignment = u32(opt + 36)
    _require(0x200 <= file_alignment <= 0x10000 and
             file_alignment & (file_alignment - 1) == 0,
             "Unsupported FileAlignment")
    _require(section_alignment >= 0x1000 and section_alignment >= file_alignment and
             section_alignment & (section_alignment - 1) == 0,
             "Unsupported SectionAlignment")
    header_size = u32(opt + 60)
    _require(header_size <= len(data) and header_size % file_alignment == 0,
             "Invalid SizeOfHeaders")
    directory_count = u32(opt + 108)
    _require(2 <= directory_count <= (optional_size - 112) // 8,
             "Invalid NumberOfRvaAndSizes")

    def directory(index: int) -> tuple[int, int]:
        if index >= directory_count:
            return (0, 0)
        return struct.unpack_from("<II", data, opt + 112 + index * 8)

    _require(directory(4) == (0, 0),
             "Authenticode certificate directory present; refusing to invalidate a signature")
    _require(directory(11) == (0, 0), "Bound-import directory is unsupported")
    section_table = opt + optional_size
    new_header = section_table + count * 40
    _require(new_header + 40 <= header_size, "Insufficient section-header room")
    _require(data[new_header:new_header + 40] == bytes(40),
             "New section-header slot is not zero-filled")
    sections = []
    raw_ranges = []
    virtual_ranges = []
    for index in range(count):
        fields = struct.unpack_from("<8sIIIIIIHHI", data, section_table + index * 40)
        name, virtual_size, rva, raw_size, raw_offset = fields[:5]
        _require(name.rstrip(b"\0") != b".offline", ".offline section already exists")
        _require(rva % section_alignment == 0 and rva >= _align(header_size, section_alignment),
                 "Invalid section RVA")
        _require(raw_size % file_alignment == 0, "Unaligned section raw size")
        if raw_size:
            _require(raw_offset >= header_size and raw_offset % file_alignment == 0,
                     "Invalid section raw offset")
            _require(raw_offset + raw_size <= len(data), "Truncated section")
            raw_ranges.append((raw_offset, raw_offset + raw_size))
        extent = max(virtual_size, raw_size)
        _require(rva + extent <= 0xFFFFFFFF, "Section virtual extent overflows")
        if extent:
            virtual_ranges.append((rva, _align(rva + extent, section_alignment)))
        sections.append((rva, virtual_size, raw_offset, raw_size))
    for ranges in (raw_ranges, virtual_ranges):
        ordered = sorted(ranges)
        _require(all(left[1] <= right[0] for left, right in zip(ordered, ordered[1:])),
                 "Overlapping sections are unsupported")
    raw_end = max([header_size] + [end for _, end in raw_ranges])
    _require(raw_end == len(data), "File overlay/trailing data present; refusing to relocate it")
    image_end = max([_align(header_size, section_alignment)] + [end for _, end in virtual_ranges])
    _require(u32(opt + 56) == image_end, "SizeOfImage does not match section extents")

    def mapped(rva: int, length: int) -> int:
        if 0 <= rva and rva + length <= header_size:
            return rva
        for section_rva, _, raw_offset, raw_size in sections:
            delta = rva - section_rva
            if delta >= 0 and delta + length <= raw_size:
                return raw_offset + delta
        raise PEFormatError(f"RVA range 0x{rva:X}+0x{length:X} is not file-backed")

    def string_at(rva: int) -> bytes:
        offset = mapped(rva, 1)
        end = data.find(b"\0", offset, min(offset + 0x10000, len(data)))
        _require(end >= 0, "Unterminated import DLL name")
        mapped(rva, end - offset + 1)
        return data[offset:end]

    import_rva, import_size = directory(1)
    descriptors = []
    if import_rva or import_size:
        _require(import_rva != 0 and import_size >= 20, "Invalid import directory")
        terminated = False
        for index in range(import_size // 20):
            offset = mapped(import_rva + index * 20, 20)
            descriptor = data[offset:offset + 20]
            ilt, timestamp, forwarder, name_rva, iat = struct.unpack("<5I", descriptor)
            if not any(descriptor):
                terminated = True
                break
            _require(timestamp == 0, "Bound/timestamped import descriptors are unsupported")
            _require(name_rva != 0 and iat != 0, "Incomplete import descriptor")
            mapped(iat, 8)
            if ilt:
                mapped(ilt, 8)
            _require(string_at(name_rva).lower() != dll_z[:-1].lower(),
                     "The requested DLL is already imported")
            descriptors.append(descriptor)
        _require(terminated, "Import descriptors have no terminator within the directory")

    new_rva = image_end
    new_raw = _align(len(data), file_alignment)
    descriptor_size = (len(descriptors) + 2) * 20
    payload = bytearray(descriptor_size)

    def append(value: bytes, alignment: int = 1) -> int:
        payload.extend(bytes(_align(len(payload), alignment) - len(payload)))
        relative = len(payload)
        payload.extend(value)
        return relative

    dll_relative = append(dll_z)
    table_size = (len(names) + 1) * 8
    ilt_relative = append(bytes(table_size), 8)
    iat_relative = append(bytes(table_size), 8)
    result_iat = {}
    for index, (name, encoded) in enumerate(zip(names, name_z)):
        hint_name_relative = append(b"\0\0" + encoded, 2)
        hint_name_rva = new_rva + hint_name_relative
        _require(hint_name_rva <= 0xFFFFFFFF, "New import RVA overflows")
        struct.pack_into("<Q", payload, ilt_relative + index * 8, hint_name_rva)
        struct.pack_into("<Q", payload, iat_relative + index * 8, hint_name_rva)
        result_iat[name] = new_rva + iat_relative + index * 8
    for index, descriptor in enumerate(descriptors):
        payload[index * 20:(index + 1) * 20] = descriptor
    struct.pack_into("<5I", payload, len(descriptors) * 20,
                     new_rva + ilt_relative, 0, 0, new_rva + dll_relative, new_rva + iat_relative)
    virtual_size = len(payload)
    raw_size = _align(virtual_size, file_alignment)
    new_image_size = _align(new_rva + max(virtual_size, raw_size), section_alignment)
    initialized_size = u32(opt + 8) + raw_size
    _require(max(new_raw + raw_size, new_image_size, initialized_size) <= 0xFFFFFFFF,
             "Extended PE exceeds 32-bit size fields")
    output = bytearray(data)
    output.extend(bytes(new_raw - len(output)))
    output.extend(payload)
    output.extend(bytes(raw_size - virtual_size))
    struct.pack_into("<8sIIIIIIHHI", output, new_header,
                     b".offline", virtual_size, new_rva, raw_size, new_raw,
                     0, 0, 0, 0, 0xC0000040)  # initialized data, READ | WRITE
    struct.pack_into("<H", output, pe + 6, count + 1)
    struct.pack_into("<I", output, opt + 8, initialized_size)
    struct.pack_into("<I", output, opt + 56, new_image_size)
    struct.pack_into("<II", output, opt + 120, new_rva, descriptor_size)
    struct.pack_into("<I", output, opt + 64, pe_checksum(output, opt + 64))
    return bytes(output), result_iat


def extend_imports_with_thunks(
    original_bytes: bytes,
    dll_name: str,
    export_names: Iterable[str],
    thunk_exports: Iterable[str] | None = None,
) -> tuple[bytes, dict[str, int], dict[str, int]]:
    """Add imports and optional RX tail-jump thunks; return bytes, IATs, thunks.

    ``thunk_exports=None`` selects all requested imports. An empty iterable
    adds no code section. Other selections must be a unique subset of the
    imported export names. Thunk RVAs name 16-byte-aligned ``FF 25 disp32``
    indirect jumps through the IAT, padded with INT3 bytes to 16 bytes.

    This retains the original two-result ``extend_imports`` API and its
    refusal checks. Nonempty thunk selections require one additional spare
    section-header slot. ``.offline`` remains RW/non-executable; ``.ofcode``
    is RX/non-writable. All thunk references are RIP-relative, so no absolute
    relocations are added. The caller must separately check that any 5-byte
    ``E9 disp32`` patch site can reach its selected thunk.
    """
    _require(not isinstance(export_names, (str, bytes)),
             "export_names must be an iterable of names")
    names = list(export_names)
    _require(thunk_exports is None or not isinstance(thunk_exports, (str, bytes)),
             "thunk_exports must be an iterable of names")
    selected = list(names if thunk_exports is None else thunk_exports)
    for name in selected:
        _ascii_z(name, "Thunk export name")
    _require(len(set(selected)) == len(selected), "Duplicate thunk export names")
    _require(all(name in names for name in selected),
             "Every thunk export must be included in export_names")
    imported, iat_rvas = extend_imports(original_bytes, dll_name, names)
    if not selected:
        return imported, iat_rvas, {}

    pe = struct.unpack_from("<I", imported, 0x3C)[0]
    opt = pe + 24
    count = struct.unpack_from("<H", imported, pe + 6)[0]
    _require(count < 96, "No section-count capacity for thunk section")
    section_table = opt + struct.unpack_from("<H", imported, pe + 20)[0]
    new_header = section_table + count * 40
    header_size = struct.unpack_from("<I", imported, opt + 60)[0]
    _require(new_header + 40 <= header_size,
             "Insufficient section-header room for .ofcode")
    _require(imported[new_header:new_header + 40] == bytes(40),
             "Thunk section-header slot is not zero-filled")
    _require(all(imported[section_table + index * 40:section_table + index * 40 + 8]
                 .rstrip(b"\0") != b".ofcode" for index in range(count)),
             ".ofcode section already exists")
    section_alignment, file_alignment = struct.unpack_from("<II", imported, opt + 32)
    new_rva = struct.unpack_from("<I", imported, opt + 56)[0]
    new_raw = _align(len(imported), file_alignment)
    virtual_size = len(selected) * 16
    raw_size = _align(virtual_size, file_alignment)
    new_image_size = _align(new_rva + raw_size, section_alignment)
    code_size = struct.unpack_from("<I", imported, opt + 4)[0] + raw_size
    _require(max(new_raw + raw_size, new_image_size, code_size) <= 0xFFFFFFFF,
             "Thunk section exceeds 32-bit size fields")
    payload = bytearray(b"\xCC" * raw_size)
    thunk_rvas = {}
    for index, name in enumerate(selected):
        thunk_rva = new_rva + index * 16
        displacement = iat_rvas[name] - (thunk_rva + 6)
        _require(-(1 << 31) <= displacement < (1 << 31),
                 "IAT is outside thunk RIP-relative displacement range")
        payload[index * 16:index * 16 + 6] = b"\xFF\x25" + struct.pack("<i", displacement)
        thunk_rvas[name] = thunk_rva
    output = bytearray(imported)
    output.extend(bytes(new_raw - len(output)))
    output.extend(payload)
    struct.pack_into("<8sIIIIIIHHI", output, new_header,
                     b".ofcode\0", virtual_size, new_rva, raw_size, new_raw,
                     0, 0, 0, 0, 0x60000020)  # code, READ | EXECUTE
    struct.pack_into("<H", output, pe + 6, count + 1)
    struct.pack_into("<I", output, opt + 4, code_size)
    struct.pack_into("<I", output, opt + 56, new_image_size)
    struct.pack_into("<I", output, opt + 64, pe_checksum(output, opt + 64))
    return bytes(output), iat_rvas, thunk_rvas


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("input", type=Path)
    parser.add_argument("output", type=Path)
    parser.add_argument("dll_name")
    parser.add_argument("export_names", nargs="+")
    args = parser.parse_args()
    if args.input.resolve() == args.output.resolve():
        parser.error("Input and output must be different paths")
    if args.output.exists():
        parser.error("Output already exists; choose a fresh derivative path")
    original = args.input.read_bytes()
    extended, imports = extend_imports(original, args.dll_name, args.export_names)
    with args.output.open("xb") as stream:
        stream.write(extended)
    print(json.dumps({"input_sha256": hashlib.sha256(original).hexdigest(),
                      "output_sha256": hashlib.sha256(extended).hexdigest(),
                      "output": str(args.output.resolve()),
                      "iat_rvas": {key: hex(value) for key, value in imports.items()}}, indent=2))


if __name__ == "__main__":
    main()
