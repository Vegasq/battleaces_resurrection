"""Recover build 37822 protobuf descriptors from locally supplied original files.

Standard library only. No game data, native-method dump, disassembler, Unity, or
running client is bundled or required. Input hashes deliberately restrict this
small IL2CPP/x64 reader to the researched build. Checkout outputs stay under
ignored local/; deployment outputs stay outside program files. This is static
extraction, not execution.
"""
from __future__ import annotations

import argparse
import base64
import hashlib
import json
import pathlib
import re
import struct
import sys

ROOT = pathlib.Path(__file__).resolve().parents[1]
GAME_ASSEMBLY_SHA256 = "e59d08c01479b27404778048d7e13546dbf3771f6b3912744c7c2bdf80c4e758"
METADATA_SHA256 = "b760be9190309b14174cd272e1f83b730181b299bc7a0cdca66985c69dcdc57d"
EXPECTED_DESCRIPTOR_COUNT = 50


class ExtractionError(ValueError):
    pass


def require(condition, message):
    if not condition:
        raise ExtractionError(message)


def unpack(data, fmt, offset):
    size = struct.calcsize(fmt)
    require(0 <= offset <= len(data) and size <= len(data) - offset, "truncated binary structure")
    return struct.unpack_from(fmt, data, offset)


def checked_input(path, expected):
    data = pathlib.Path(path).read_bytes()
    actual = hashlib.sha256(data).hexdigest()
    require(actual == expected, f"unsupported original input {pathlib.Path(path).name}: SHA256 {actual}")
    return data


class PE:
    def __init__(self, data):
        self.data = data
        require(data[:2] == b"MZ", "input is not a PE file")
        header = unpack(data, "<I", 60)[0]
        require(data[header:header + 4] == b"PE\0\0", "invalid PE signature")
        machine, count = unpack(data, "<HH", header + 4)
        require(machine == 0x8664 and 0 < count < 128, "expected x64 PE")
        optional = header + 24
        require(unpack(data, "<H", optional)[0] == 0x20B, "expected PE32+ optional header")
        self.base = unpack(data, "<Q", optional + 24)[0]
        optional_size = unpack(data, "<H", header + 20)[0]
        self.sections = []
        for index in range(count):
            section = optional + optional_size + index * 40
            _, rva, size, start = unpack(data, "<4I", section + 8)
            require(start <= len(data) and size <= len(data) - start, "PE section exceeds file")
            self.sections.append((self.base + rva, size, start))
        exception_rva, exception_size = unpack(data, "<II", optional + 112 + 3 * 8)
        require(exception_size % 12 == 0, "invalid PE exception table")
        start = self.offset(self.base + exception_rva, exception_size)
        runtime_functions = {}
        for entry in range(start, start + exception_size, 12):
            begin, end, unwind = unpack(data, "<III", entry)
            require(begin < end, "invalid native function bounds")
            runtime_functions[begin] = (end, unwind)
        self.function_ends = {}
        for begin, (end, unwind) in runtime_functions.items():
            root = begin
            visited = {begin}
            # MSVC can split one function's unwind description into chained
            # ranges. Follow UNW_FLAG_CHAININFO to the original entry, rather
            # than mistaking the end of its prologue range for the whole method.
            for _ in range(32):
                unwind_offset = self.offset(self.base + unwind, 4)
                flags, _, code_count, _ = unpack(data, "<4B", unwind_offset)
                if not (flags >> 3) & 4:
                    break
                tail = unwind_offset + 4 + ((code_count + 1) // 2) * 4
                parent, parent_end, parent_unwind = unpack(data, "<III", tail)
                require(runtime_functions.get(parent) == (parent_end, parent_unwind), "unresolved chained unwind parent")
                require(parent not in visited, "cyclic chained unwind parent")
                visited.add(parent)
                root, unwind = parent, parent_unwind
            else:
                raise ExtractionError("chained unwind depth exceeds bound")
            address = self.base + root
            self.function_ends[address] = max(self.function_ends.get(address, 0), self.base + end)

    def offset(self, address, length=1):
        for start, size, file_offset in self.sections:
            relative = address - start
            if 0 <= relative <= size and length <= size - relative:
                return file_offset + relative
        raise ExtractionError(f"PE address is not backed by file bytes: {address:#x}")

    def address(self, offset):
        for start, size, file_offset in self.sections:
            if file_offset <= offset < file_offset + size:
                return start + offset - file_offset
        raise ExtractionError("PE file offset is outside sections")

    def module(self, name, minimum_methods):
        """Locate Il2CppCodeGenModule by its name pointer, count and method table."""
        needle = name.encode("utf-8") + b"\0"
        candidates = set()
        cursor = 0
        while (cursor := self.data.find(needle, cursor)) >= 0:
            try:
                pointer = struct.pack("<Q", self.address(cursor))
            except ExtractionError:
                cursor += 1
                continue
            ref = 0
            while (ref := self.data.find(pointer, ref)) >= 0:
                try:
                    count, table = unpack(self.data, "<QQ", ref + 8)
                    if minimum_methods <= count <= 1_000_000:
                        self.offset(table, count * 8)
                        candidates.add((count, table))
                except ExtractionError:
                    pass
                ref += 1
            cursor += 1
        require(len(candidates) == 1, f"ambiguous or missing IL2CPP module: {name}")
        return next(iter(candidates))


class Metadata:
    def __init__(self, data):
        self.data = data
        self.header = unpack(data, "<64I", 0)
        require(self.header[:2] == (0xFAB11BAF, 31), "expected IL2CPP metadata version 31")
        for index, row_size in ((2, 8), (12, 36), (40, 88), (42, 40)):
            start, size = self.header[index:index + 2]
            require(size % row_size == 0 and start <= len(data) and size <= len(data) - start,
                    "invalid IL2CPP metadata table bounds")
        for index in (4, 6):
            start, size = self.header[index:index + 2]
            require(start <= len(data) and size <= len(data) - start, "invalid metadata string heap")
        self.types = [unpack(data, "<16i8H2I", self.header[40] + index * 88)
                      for index in range(self.header[41] // 88)]
        self.methods = [unpack(data, "<6iI4H", self.header[12] + index * 36)
                        for index in range(self.header[13] // 36)]
        self.images = [unpack(data, "<10i", self.header[42] + index * 40)
                       for index in range(self.header[43] // 40)]

    def string(self, index):
        require(0 <= index < self.header[7], "metadata name index outside heap")
        start = self.header[6] + index
        end = self.data.find(b"\0", start, self.header[6] + self.header[7])
        require(end >= start, "unterminated metadata name")
        return self.data[start:end].decode("utf-8")

    def literal(self, index):
        require(0 <= index < self.header[3] // 8, "string literal index outside table")
        size, start = unpack(self.data, "<II", self.header[2] + index * 8)
        require(start <= self.header[5] and size <= self.header[5] - start, "literal outside metadata heap")
        begin = self.header[4] + start
        return self.data[begin:begin + size].decode("utf-8")

    def methods_for_type(self, record):
        start, count = record[9], record[16]
        require(0 <= start <= len(self.methods) and count <= len(self.methods) - start,
                "type method range outside metadata")
        return self.methods[start:start + count]

    def selected_native_methods(self, pe):
        modules, constructors, concat = {}, [], {}
        for index, record in enumerate(self.types):
            name, namespace = self.string(record[0]), self.string(record[1])
            reflection = name.endswith("Reflection") and ("Pb" in namespace or
                namespace == "Google.Protobuf.WellKnownTypes" or
                namespace == "Google.Protobuf.Reflection" and name == "DescriptorReflection")
            string_type = namespace == "System" and name == "String"
            if not (reflection or string_type):
                continue
            selected = [method for method in self.methods_for_type(record)
                        if self.string(method[0]) == (".cctor" if reflection else "Concat")]
            if not selected:
                continue
            images = [image for image in self.images if image[2] <= index < image[2] + image[3]]
            require(len(images) == 1, "type has ambiguous metadata image")
            image = images[0]
            module_name = self.string(image[0])
            if module_name not in modules:
                minimum = max((method[6] & 0xFFFFFF) for method in selected)
                modules[module_name] = pe.module(module_name, minimum)
            count, table = modules[module_name]
            for method in selected:
                method_index = (method[6] & 0xFFFFFF) - 1
                require(0 <= method_index < count, "method token outside native table")
                address = unpack(pe.data, "<Q", pe.offset(table + method_index * 8, 8))[0]
                if string_type:
                    if address:
                        require(address not in concat or concat[address] == method[-1], "ambiguous Concat parameter count")
                        concat[address] = method[-1]  # Generic overloads can have no direct method pointer.
                else:
                    require(address != 0, f"descriptor method has no native implementation: {namespace}.{name}")
                    constructors.append((address, f"{namespace}.{name}::.cctor"))
        require(concat, "System.String.Concat was not resolved")
        require(len(constructors) == EXPECTED_DESCRIPTOR_COUNT, "unexpected reflection constructor count")
        return sorted(constructors), concat


def ordered_fragments(code, start_address, pe, metadata, concat_targets):
    """Read exact-build RIP-relative MOV literal loads before the first Concat.

    This is deliberately a small signature reader, not a general x64 decoder.
    LEA initialization references are excluded. A whole-input hash gate plus the
    resolved function bounds, call target and literal-token checks constrain it.
    """
    end, argument_count = None, None
    for index in range(len(code) - 4):
        if code[index] == 0xE8:
            target = start_address + index + 5 + struct.unpack_from("<i", code, index + 1)[0]
            if target in concat_targets:
                end, argument_count = index, concat_targets[target]
                break
    require(end is not None, "descriptor constructor has no resolved String.Concat call")
    result = []
    for index in range(max(0, end - 6)):
        if code[index] not in (0x48, 0x4C) or code[index + 1] != 0x8B or code[index + 2] & 0xC7 != 0x05:
            continue
        address = start_address + index + 7 + struct.unpack_from("<i", code, index + 3)[0]
        try:
            token = unpack(pe.data, "<Q", pe.offset(address, 8))[0]
        except ExtractionError:
            continue
        if token > 0xFFFFFFFF or not token & 1 or token >> 29 != 5:
            continue
        literal = metadata.literal((token & 0x1FFFFFFE) >> 1)
        require(len(literal) >= 4 and re.fullmatch(r"[A-Za-z0-9+/=]+", literal),
                "unexpected non-base64 literal before descriptor concat")
        register = ((code[index + 2] >> 3) & 7) + (8 if code[index] & 4 else 0)
        result.append((register, literal))
    require(result, "no ordered descriptor fragments found")
    if argument_count == 1:
        return [literal for register, literal in result]  # String[] array stores preserve this order.
    require(argument_count in (2, 3, 4), "unsupported Concat overload")
    # Fixed-arity overloads use the Windows x64 argument registers; the compiler
    # may load those registers in reverse order. Sort by argument, not instruction.
    registers = (1, 2, 8, 9)[:argument_count]  # RCX, RDX, R8, R9.
    by_register = dict(result)
    require(len(result) == argument_count and set(by_register) == set(registers),
            "ambiguous fixed-arity Concat arguments")
    return [by_register[register] for register in registers]


def varint(data, offset):
    value = 0
    for shift in range(0, 70, 7):
        require(offset < len(data), "truncated descriptor varint")
        byte = data[offset]; offset += 1
        require(shift < 63 or byte <= 1, "descriptor varint exceeds uint64")
        value |= (byte & 127) << shift
        if not byte & 128:
            return value, offset
    raise ExtractionError("overlong descriptor varint")


def wire_fields(data):
    offset = 0
    while offset < len(data):
        tag, offset = varint(data, offset)
        number, wire_type = tag >> 3, tag & 7
        require(number != 0, "descriptor field number is zero")
        if wire_type == 0:
            value, offset = varint(data, offset)
        elif wire_type in (1, 2, 5):
            if wire_type == 2:
                size, offset = varint(data, offset)
            else:
                size = 8 if wire_type == 1 else 4
            require(size <= len(data) - offset, "truncated descriptor field")
            value = data[offset:offset + size]; offset += size
        else:
            raise ExtractionError("unsupported descriptor wire type")
        yield number, wire_type, value


# Public protobuf descriptor schema, projected into the server's readable JSON
# form. Unknown options are intentionally omitted; this is not a proto compiler.
SCHEMAS = {
    "file": {1: ("name", "s"), 2: ("package", "s"), 3: ("dependencies", "s", True), 4: ("messages", "message", True), 5: ("enums", "enum", True), 6: ("services", "service", True), 7: ("extensions", "field", True), 8: ("options", "fileopts"), 12: ("syntax", "s")},
    "fileopts": {1: ("java_package", "s"), 8: ("java_outer_classname", "s"), 11: ("go_package", "s"), 37: ("csharp_namespace", "s")},
    "message": {1: ("name", "s"), 2: ("fields", "field", True), 3: ("nested_messages", "message", True), 4: ("enums", "enum", True), 6: ("extensions", "field", True), 7: ("options", "msgopts"), 8: ("oneofs", "oneof", True)},
    "msgopts": {7: ("map_entry", "i")},
    "field": {1: ("name", "s"), 2: ("extendee", "s"), 3: ("number", "i"), 4: ("label", "i"), 5: ("type", "i"), 6: ("type_name", "s"), 7: ("default_value", "s"), 9: ("oneof_index", "i"), 10: ("json_name", "s"), 17: ("proto3_optional", "i")},
    "enum": {1: ("name", "s"), 2: ("values", "enumvalue", True)},
    "enumvalue": {1: ("name", "s"), 2: ("number", "i")},
    "oneof": {1: ("name", "s")},
    "service": {1: ("name", "s"), 2: ("methods", "method", True)},
    "method": {1: ("name", "s"), 2: ("input_type", "s"), 3: ("output_type", "s"), 5: ("client_streaming", "i"), 6: ("server_streaming", "i")},
}


def decode_descriptor(data, schema="file", depth=0):
    require(depth <= 32, "descriptor nesting exceeds bound")
    result = {}
    for number, wire_type, value in wire_fields(data):
        spec = SCHEMAS[schema].get(number)
        if spec is None:
            continue
        name, kind = spec[:2]
        require(wire_type == (0 if kind == "i" else 2), "descriptor field has wrong wire type")
        decoded = value if kind == "i" else value.decode("utf-8") if kind == "s" else decode_descriptor(value, kind, depth + 1)
        if len(spec) == 3:
            result.setdefault(name, []).append(decoded)
        else:
            require(name not in result, "duplicate singular descriptor field")
            result[name] = decoded
    return result


def validate_output_directory(output):
    output = pathlib.Path(output).resolve()
    local = (ROOT / "local").resolve()
    if ROOT.name == 'app' and ROOT.parent.name == 'program':
        require(not output.is_relative_to(ROOT.parent), 'generated assets must be outside bundled program files')
    elif output.is_relative_to(ROOT):
        require(output != local and output.is_relative_to(local), 'generated assets in this checkout must be under the ignored local/ directory')
    return output


def extract(game_assembly, metadata_path, output):
    output = validate_output_directory(output)
    pe = PE(checked_input(game_assembly, GAME_ASSEMBLY_SHA256))
    metadata = Metadata(checked_input(metadata_path, METADATA_SHA256))
    constructors, concat = metadata.selected_native_methods(pe)
    descriptors, inventory = {}, []
    for start, name in constructors:
        end = pe.function_ends.get(start)
        require(end is not None, f"native constructor has no PE unwind bounds: {name}")
        offset = pe.offset(start, end - start)
        try:
            fragments = ordered_fragments(pe.data[offset:offset + end - start], start, pe, metadata, concat)
        except ExtractionError as error:
            raise ExtractionError(f"{name}: {error}") from error
        try:
            raw = base64.b64decode("".join(fragments), validate=True)
        except ValueError as error:
            raise ExtractionError(f"invalid descriptor base64: {name}") from error
        decoded = decode_descriptor(raw)
        filename = decoded.get("name", "")
        require(bool(re.fullmatch(r"[A-Za-z0-9_/.-]+\.proto", filename)) and ".." not in filename,
                "unsafe or absent descriptor filename")
        stem = filename.replace("/", "_") + ".json"
        require(stem not in descriptors, "duplicate descriptor output name")
        descriptors[stem] = decoded
        inventory.append({"name": filename, "source_method": name, "source_rva": hex(start - pe.base),
                          "source_end_rva": hex(end - pe.base), "fragments": len(fragments),
                          "descriptor_bytes": len(raw), "descriptor_sha256": hashlib.sha256(raw).hexdigest()})
    require(len(descriptors) == EXPECTED_DESCRIPTOR_COUNT, "descriptor recovery incomplete")
    names = {descriptor["name"] for descriptor in descriptors.values()}
    missing = sorted({dependency for descriptor in descriptors.values() for dependency in descriptor.get("dependencies", [])} - names)
    require(not missing, "descriptor dependency closure incomplete: " + ", ".join(missing))
    output.mkdir(parents=True, exist_ok=True)
    unexpected = {p.name for p in output.glob("*.proto.json")} - descriptors.keys()
    require(not unexpected, "output contains descriptors from another build; choose a fresh directory")
    # Validate the entire recovery before writing any output. Existing same-build
    # JSON is deterministically replaced; original input files are never opened for write.
    for name, descriptor in sorted(descriptors.items()):
        (output / name).write_text(json.dumps(descriptor, indent=2), encoding="utf-8")
    provenance = {"recipe": "build-37822-il2cpp-v31-x64-v1", "static_extraction": True,
                  "game_assembly_sha256": GAME_ASSEMBLY_SHA256, "metadata_sha256": METADATA_SHA256,
                  "descriptor_count": len(descriptors), "dependencies_complete": True,
                  "descriptors": inventory,
                  "limits": ["Exact supported original files only; patched or other builds are rejected.",
                             "Build-specific instruction signatures, not a general x64 disassembler.",
                             "JSON projects selected standard descriptor fields; unknown options are omitted."]}
    (output / "extraction-inventory.json").write_text(json.dumps(provenance, indent=2) + "\n", encoding="utf-8")
    return provenance


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--game-assembly", required=True, type=pathlib.Path, help="Original build 37822 GameAssembly.dll")
    parser.add_argument("--metadata", required=True, type=pathlib.Path, help="Same installation's global-metadata.dat")
    parser.add_argument("--output", type=pathlib.Path, default=ROOT / "local/assets/build-37822/descriptors")
    args = parser.parse_args(argv)
    try:
        result = extract(args.game_assembly, args.metadata, args.output)
    except (OSError, ValueError, UnicodeError) as error:
        print(f"Descriptor extraction failed: {error}", file=sys.stderr)
        return 1
    print(json.dumps({"descriptor_count": result["descriptor_count"], "dependencies_complete": True,
                      "output": str(args.output.resolve())}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
