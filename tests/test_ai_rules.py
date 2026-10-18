import hashlib
import json
from contextlib import contextmanager
from pathlib import Path
import shutil
import struct
import unittest
import uuid

from server.ai_rules import RuleBook, RuleFormatError, SUPPORTED_AI_SHA256, validate_rules
from server.native_ai import NativeAIError, decode_action_queue
from server.protobuf_wire import WireError, encode_varint, field_bytes, field_uint


@contextmanager
def fixture_directory():
    base = (Path(__file__).resolve().parents[1]/'local/test-ai-rules').resolve()
    path = base/uuid.uuid4().hex
    path.mkdir(parents=True)
    try: yield path
    finally:
        if path.resolve().parent != base or len(path.name) != 32:
            raise RuntimeError('test cleanup outside fixture directory')
        shutil.rmtree(path)


def synthetic_rules():
    """Independent forward builder for tiny authored admission fixtures."""
    data = bytearray(4)
    marks = {}

    def align(multiple):
        data.extend(bytes((-len(data)) % multiple))

    def table(name, values):
        align(2); vt = len(data)
        data.extend(struct.pack('<HH', 4+2*len(values), 4+4*len(values)))
        data.extend(b''.join(struct.pack('<H', 4+4*i) for i in range(len(values))))
        align(4); at = len(data)
        data.extend(struct.pack('<i', at-vt) + bytes(4*len(values)))
        marks[name] = at; marks[name+'_vtable'] = vt
        for index, value in enumerate(values):
            field = at+4+index*4
            marks[name+f'.{index}'] = field
            if callable(value):
                target = value(); struct.pack_into('<I', data, field, target-field)
            else:
                struct.pack_into('<f' if isinstance(value, float) else '<I', data, field, value)
        return at

    def vector(*children):
        align(4); at = len(data)
        data.extend(struct.pack('<I', len(children)) + bytes(4*len(children)))
        for index, child in enumerate(children):
            field = at+4+4*index
            if callable(child):
                target = child(); struct.pack_into('<I', data, field, target-field)
            else: struct.pack_into('<I', data, field, child)
        return at

    root = table('root', [
        lambda: vector(lambda: table('rules', [7,
            lambda: vector(lambda: table('rule', [0, 1, 0.0, 1.0, 2.0, 3.0, 0])),
            lambda: vector(lambda: table('output', [1.0, 0, 0]))])),
        lambda: vector(), lambda: vector(), lambda: vector(),
        lambda: vector(lambda: table('fuzzy', [1, 0.0, 1.0, 2.0, 3.0])),
        lambda: vector(lambda: table('unit', [1, 0, 1.0])),
        lambda: vector(lambda: table('tag', [1, 0])),
        lambda: vector(lambda: table('weight', [0, 1.0])), lambda: vector(1),
    ])
    struct.pack_into('<I', data, 0, root)
    return bytes(data), marks


class RuleValidationTests(unittest.TestCase):
    def test_complete_authored_graph_and_legitimate_empty_vectors(self):
        data, _ = synthetic_rules()
        result = validate_rules(data)
        self.assertEqual(result['root_vector_counts'], [1, 0, 0, 0, 1, 1, 1, 1, 1])
        self.assertEqual(result['entity_ids'], [1])

    def test_negative_vtable_distance_is_legal(self):
        data, marks = synthetic_rules()
        changed = bytearray(data)
        vt = marks['root_vtable']; length = struct.unpack_from('<H', changed, vt)[0]
        relocated = len(changed)
        changed.extend(changed[vt:vt+length]); changed.extend(bytes((-len(changed)) % 4))
        struct.pack_into('<i', changed, marks['root'], marks['root']-relocated)
        validate_rules(bytes(changed))

    def test_truncated_every_boundary_and_fake_wrappers(self):
        data, _ = synthetic_rules()
        for size in range(len(data)):
            with self.subTest(size=size), self.assertRaises(RuleFormatError): validate_rules(data[:size])
        for invalid in (b'\0'*4+data, struct.pack('<I', len(data))+data, b'\0'*len(data)):
            with self.assertRaises(RuleFormatError): validate_rules(invalid)

    def test_bad_offsets_vectors_fields_enums_and_native_float_conversion(self):
        data, m = synthetic_rules()
        root_vector = m['root.0']+struct.unpack_from('<I', data, m['root.0'])[0]
        cases = [
            (0, 'I', 0xffffffff), (m['root'], 'i', 0),
            (m['root_vtable'], 'H', 65534), (m['root_vtable']+2, 'H', 3),
            (m['root_vtable']+4, 'H', 0), (m['root_vtable']+6, 'H', 4),
            (m['root.0'], 'I', 0), (m['root.0'], 'I', 5),
            (root_vector, 'I', 0xffffffff), (root_vector+4, 'I', 4),
            (m['rule.0'], 'I', 33), (m['rule.1'], 'I', 176), (m['rule.1'], 'I', 2), (m['rule.6'], 'I', 5),
            (m['output.1'], 'I', 11), (m['output.2'], 'I', 6),
            (m['fuzzy.0'], 'I', 0xffffffff), (m['unit.1'], 'I', 4),
            (m['tag.1'], 'I', 1), (m['weight.0'], 'I', 45),
        ]
        cases += [(m['unit.2'], 'f', value) for value in (float('nan'), float('inf'), -float('inf'), 2147483648.0, -2147483648.0)]
        for offset, kind, value in cases:
            changed = bytearray(data); struct.pack_into('<'+kind, changed, offset, value)
            with self.subTest(offset=offset, value=value), self.assertRaises(RuleFormatError): validate_rules(bytes(changed))

    def test_manifest_hash_identity_inventory_and_filename_are_enforced(self):
        data, _ = synthetic_rules()
        with fixture_directory() as directory:
            root = Path(directory); (root/'ai-rules-4.fb').write_bytes(data)
            entry = dict(profile=4, mode=1, enabled=True, file='ai-rules-4.fb', bytes=len(data), sha256=hashlib.sha256(data).hexdigest())
            manifest = dict(schema=1, build=37822, format='Uncapped.Flatbuffers.Fuzzy', default_profile=4,
                            ai_dll_sha256=SUPPORTED_AI_SHA256, profiles=[entry])
            def write(): (root/'ai-rules.json').write_text(json.dumps(manifest), encoding='utf-8')
            write(); self.assertEqual(RuleBook(root).rules[4], data)
            for field, bad in (('file', '../ai-rules-4.fb'), ('sha256', '0'*64), ('bytes', len(data)+4), ('profile', True)):
                old = entry[field]; entry[field] = bad; write()
                with self.subTest(field=field), self.assertRaises(ValueError): RuleBook(root)
                entry[field] = old
            manifest['profiles'].append(entry); write()
            with self.assertRaises(ValueError): RuleBook(root)


class AIQueueTests(unittest.TestCase):
    def test_exact_length_preserves_all_actions_and_ignores_unused_capacity(self):
        actions = (field_uint(3, 6), field_bytes(1, b'authored command'))
        body = b''.join(field_bytes(1, action) for action in actions)
        self.assertEqual(decode_action_queue(encode_varint(len(body))+body+b'\xff'*16), actions)
        self.assertEqual(decode_action_queue(b'\0'+b'\xff'*16), ())

    def test_unwritten_oversized_truncated_or_wrong_wire_queues_fail(self):
        for data, capacity in ((b'\xff'*10, 20), (b'\x14'+bytes(20), 19), (b'\x14'+bytes(2), 20),
                               (b'\x02\x08\x01', 20), (b'\x02\x0a\x00', 20)):
            with self.subTest(data=data), self.assertRaises((NativeAIError, WireError)):
                decode_action_queue(data, capacity)


if __name__ == '__main__': unittest.main()
