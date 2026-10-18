"""Bounded admission for locally exported build37822 AI rule FlatBuffers.

The original native importer ignores its byte-count argument. Validate every
reachable object and the enums used as native array indices before entering it.
No original rule content is distributed here. See docs/server-ai-runtime.txt.
"""
from __future__ import annotations

import hashlib
import json
import math
from pathlib import Path
import struct
from types import MappingProxyType

SUPPORTED_AI_SHA256 = '14b504d4946fe60d0d62e1e8b8a641b4c1bbd07277d1bbca09e0151512ff19ca'
MAX_RULE_BYTES = 8 * 1024 * 1024
# Authored schema: all fields occupy four bytes; ':' indicates a table vector.
_TABLES = {
    'Fuzzy': (':FuzzyRules', ':FuzzyRules', ':FuzzyRules', ':FuzzyRules', ':FuzzySet',
              ':AIUnitDataFloat', ':AIUnitDataTag', ':CrispWeightValue', ':uint'),
    'FuzzyRules': ('uint', ':FuzzyRule', ':CrispOutput'),
    'FuzzyRule': ('input', 175, 'float', 'float', 'float', 'float', 4),
    'CrispOutput': ('float', 'output', 5),
    'FuzzySet': (175, 'float', 'float', 'float', 'float'),
    'CrispWeightValue': (44, 'float'),
    'AIUnitDataFloat': ('uint', 3, 'float'),
    'AIUnitDataTag': ('uint', 0),
}
_DOMAINS = ((32, 10), (75, 62), (32, 4), (43, 13))


class RuleFormatError(ValueError):
    pass


def _require(value, message):
    if not value: raise RuleFormatError(message)


class _Validator:
    def __init__(self, data):
        _require(isinstance(data, bytes) and 8 <= len(data) <= MAX_RULE_BYTES and len(data) % 4 == 0,
                 'invalid AI rule blob size')
        self.data = data
        self.spans = {}
        self.tables = self.items = 0
        self.root_counts = []
        self.entity_ids = set()
        self.fuzzy_defined, self.fuzzy_references, self.crisp_weights = set(), set(), set()

    def bounds(self, position, size):
        _require(0 <= position <= len(self.data) and 0 <= size <= len(self.data)-position, 'AI rule bounds')

    def number(self, position, fmt):
        self.bounds(position, struct.calcsize('<'+fmt))
        return struct.unpack_from('<'+fmt, self.data, position)[0]

    def span(self, position, size, kind):
        self.bounds(position, size)
        _require(position >= 4 or position == 0 and kind == 'header', 'AI object overlaps header')
        key = (position, position+size)
        _require(key not in self.spans or self.spans[key] == kind, 'AI bytes have incompatible types')
        self.spans[key] = kind

    def offset(self, position, minimum):
        _require(position % 4 == 0, 'unaligned AI offset')
        relative = self.number(position, 'I')
        target = position+relative
        _require(relative >= 4 and target >= minimum and target % 4 == 0, 'invalid AI forward offset')
        self.bounds(target, 4)
        return target

    def table(self, position, name, context=None, depth=1):
        self.tables += 1
        _require(depth <= 5 and self.tables <= 16384 and position % 4 == 0, 'AI table graph limit/alignment')
        distance = self.number(position, 'i')
        vtable = position-distance
        _require(distance != 0 and vtable >= 4 and vtable % 2 == 0, 'invalid AI vtable position')
        length, size = self.number(vtable, 'H'), self.number(vtable+2, 'H')
        fields = _TABLES[name]
        _require(4 <= length <= 4+2*len(fields) and length % 2 == 0 and size >= 4, 'invalid AI table layout')
        self.span(vtable, length, 'vtable'); self.span(position, size, name)
        occupied = set()
        for index, kind in enumerate(fields):
            slot = 4+2*index
            relative = self.number(vtable+slot, 'H') if slot < length else 0
            pointer = position+relative if relative else None
            if relative:
                _require(relative >= 4 and relative+4 <= size and pointer % 4 == 0 and relative not in occupied,
                         'invalid or aliased AI field')
                occupied.add(relative)
            if isinstance(kind, str) and kind.startswith(':'):
                _require(pointer is not None, 'missing native-required AI vector')
                vector = self.offset(pointer, position+size)
                count = self.number(vector, 'I'); self.items += count
                _require(count <= 16384 and self.items <= 65536, 'AI vector count limit')
                end = vector+4+4*count
                self.span(vector, 4+4*count, kind)
                if name == 'Fuzzy': self.root_counts.append(count)
                child_context = index if name == 'Fuzzy' and index < 4 else context
                for item in range(count):
                    entry = vector+4+4*item
                    if kind == ':uint': self.entity_ids.add(self.number(entry, 'I'))
                    else: self.table(self.offset(entry, end), kind[1:], child_context, depth+2)
                continue
            fmt = 'f' if kind == 'float' else 'i' if isinstance(kind, int) else 'I'
            value = self.number(pointer, fmt) if pointer is not None else 0
            if kind == 'float':
                _require(math.isfinite(value) and -2147483648 < value < 2147483648, 'AI float outside native fixed-point range')
            elif isinstance(kind, int):
                _require(0 <= value <= kind, 'AI enum outside exact-build domain')
            elif kind in ('input', 'output'):
                _require(context in range(4) and 0 <= value <= _DOMAINS[context][kind == 'output'],
                         'AI category input/output outside domain')
            elif name in ('AIUnitDataFloat', 'AIUnitDataTag') and index == 0:
                self.entity_ids.add(value)
            if name == 'FuzzyRule' and index == 1: self.fuzzy_references.add(value)
            if name == 'FuzzySet' and index == 0:
                _require(value not in self.fuzzy_defined, 'duplicate AI fuzzy-set ID')
                self.fuzzy_defined.add(value)
            if name == 'CrispWeightValue' and index == 0:
                _require(value not in self.crisp_weights, 'duplicate AI crisp-weight ID')
                self.crisp_weights.add(value)

    def validate(self):
        self.span(0, 4, 'header')
        self.table(self.offset(0, 4), 'Fuzzy')
        _require(self.fuzzy_references <= self.fuzzy_defined | {0}, 'AI fuzzy-set reference is missing')
        previous_end = 0
        for start, end in sorted(self.spans):
            _require(start >= previous_end, 'overlapping AI objects')
            previous_end = end
        return {'bytes': len(self.data), 'table_visits': self.tables, 'vector_elements': self.items,
                'root_vector_counts': self.root_counts, 'entity_ids': sorted(self.entity_ids)}


def validate_rules(data: bytes) -> dict:
    return _Validator(data).validate()


def _unique_object(pairs):
    result = {}
    for key, value in pairs:
        _require(key not in result, 'duplicate AI manifest field')
        result[key] = value
    return result


class RuleBook:
    """Immutable validated rules with exact profile/filename/build identity."""
    def __init__(self, directory: Path):
        directory = Path(directory)
        manifest_path = directory/'ai-rules.json'
        _require(manifest_path.stat().st_size <= 1024*1024, 'AI manifest size limit')
        manifest_bytes = manifest_path.read_bytes()
        manifest = json.loads(manifest_bytes, object_pairs_hook=_unique_object)
        _require(isinstance(manifest, dict) and (manifest.get('schema'), manifest.get('build'), manifest.get('format')) ==
                 (1, 37822, 'Uncapped.Flatbuffers.Fuzzy') and manifest.get('ai_dll_sha256') == SUPPORTED_AI_SHA256,
                 'unsupported AI rule manifest')
        profiles = manifest.get('profiles')
        _require(isinstance(profiles, list) and 0 < len(profiles) <= 256, 'AI profile inventory limit')
        rules, entries, files, summaries = {}, {}, {'ai-rules.json': manifest_bytes}, {}
        total = 0
        for entry in profiles:
            _require(isinstance(entry, dict), 'invalid AI profile entry')
            profile = entry.get('profile')
            _require(type(profile) is int and 0 < profile <= 0xffffffff and profile not in rules, 'invalid AI profile ID')
            name = f'ai-rules-{profile}.fb'
            _require(entry.get('file') == name and type(entry.get('bytes')) is int and 8 <= entry['bytes'] <= MAX_RULE_BYTES
                     and type(entry.get('enabled')) is bool and type(entry.get('mode')) is int and 0 <= entry['mode'] <= 5,
                     'invalid AI profile file/metadata')
            path = directory/name
            _require(path.stat().st_size == entry['bytes'], 'AI rule size mismatch')
            total += entry['bytes']; _require(total <= 32*1024*1024, 'AI aggregate size limit')
            data = path.read_bytes()
            _require(hashlib.sha256(data).hexdigest() == entry.get('sha256'), 'AI rule hash mismatch')
            summaries[profile] = validate_rules(data)
            rules[profile], entries[profile], files[name] = data, MappingProxyType(dict(entry)), data
        self.default_profile = manifest.get('default_profile')
        _require(type(self.default_profile) is int and self.default_profile in rules, 'AI default profile missing')
        self.rules, self.entries, self.files = MappingProxyType(rules), MappingProxyType(entries), MappingProxyType(files)
        self.summaries = MappingProxyType(summaries)
