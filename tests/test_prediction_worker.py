"""File-only worker protocol and injected raw ABI; never load a game DLL."""
import ctypes as C
import hashlib
import io
import json
from pathlib import Path
import struct
import tempfile
import threading
import unittest

from client_patch.prediction_worker import wire as w
from client_patch.prediction_worker.__main__ import run_streams
from client_patch.prediction_worker.native import (
    HostError, NativeSession, SIGNATURES, helper_receipt, validate_debug_stubs,
    DEBUG_STUB_RVA, DEBUG_STUB_BYTES, DEBUG_STUB_NAMES,
)


def command(op, payload=b''):
    return w.decode_request(w.Packet(op, 1, payload))


def responses(raw):
    result = []
    while raw:
        magic, version, op, flags, request_id, size = w.HEADER.unpack_from(raw)
        assert magic == w.MAGIC and version == w.VERSION and size <= w.MAX_PAYLOAD
        body, raw = raw[w.HEADER.size:w.HEADER.size + size], raw[w.HEADER.size + size:]
        code, count = struct.unpack_from('<iI', body)
        offset, logs = 8, []
        for _ in range(count):
            kind, length = struct.unpack_from('<iI', body, offset)
            offset += 8
            logs.append((kind, body[offset:offset + length]))
            offset += length
        result.append((op, flags, request_id, code, logs, body[offset:]))
    return result


class Raw:
    def __init__(self):
        self.calls, self.codes = [], {}
        self.frame, self.labels, self.players, self.map = b'FRAME123', b'LABEL123', b'PLAYER12', b'MAPBYTES'
        self.raw_world, self.version, self.step = 0x123456780000, 9, 17
        self.make_size = None

    @staticmethod
    def out(pointer, value, kind=C.c_uint32):
        C.cast(pointer, C.POINTER(kind))[0] = value

    def call(self, name, *args):
        self.calls.append((name, args))
        code = self.codes.get(name, 8 if name in DEBUG_STUB_NAMES else 0)
        if code:
            return code  # Real nonzero codes may leave out seeds untouched.
        if name == 'SimCreateWorld':
            self.out(args[2], self.raw_world, C.c_uint64)
        elif name == 'SimStep':
            self.out(args[2], self.step, C.c_int32)
        elif name == 'SimMakeSimFrame':
            self.out(args[2], len(self.frame) if self.make_size is None else self.make_size)
        elif name == 'SimGetSimFrameBuffer':
            C.memmove(args[1], self.frame, len(self.frame))
        elif name == 'SimGetLabelsFrameBufferSize':
            self.out(args[2], len(self.labels))
        elif name == 'SimGetLabelsFrameBuffer':
            C.memmove(args[2], self.labels, len(self.labels))
        elif name == 'SimGetConnectedPlayersSizeAndVersion':
            self.out(args[1], len(self.players), C.c_int32)
            self.out(args[2], self.version, C.c_int32)
        elif name == 'SimGetConnectedPlayers':
            C.memmove(args[1], self.players, len(self.players))
        elif name == 'SimGetMapFrameSize':
            self.out(args[1], len(self.map), C.c_int32)
        elif name == 'SimGetMapFrame':
            C.memmove(args[1], self.map, len(self.map))
        elif name == 'SimGetSystemCount':
            self.out(args[1], 2)
        elif name == 'SimGetSystemIDAttributes':
            for index in range(min(args[2], 2)):
                C.memmove(C.addressof(args[1]) + 128 * index, bytes([65 + index]) * 128, 128)
        # Exact debug aliases leave caller-provided output bytes unchanged.
        return 0


class Cooperative:
    def __init__(self):
        self.closed = False
    def healthy(self):
        return not self.closed
    def close(self):
        self.closed = True


def world_session(**kwargs):
    raw = Raw()
    session = NativeSession(raw, **kwargs)
    session.dispatch(command(w.Op.INIT, b'\0'))
    code, data = session.dispatch(command(w.Op.CREATE_WORLD, b'authored-GameData'))
    assert code == 0
    return raw, session, struct.unpack('<Q', data)[0]


class CodecTests(unittest.TestCase):
    def test_all_wire_shapes_and_local_get_refusal(self):
        bodies = {1:b'\0', 2:b'', 3:b'\1', 4:struct.pack('<I', 1), 5:b'g',
                  6:struct.pack('<Q', 1), 7:struct.pack('<Q', 1)+b'a',
                  8:struct.pack('<QIi', 1, 50, -1), 9:struct.pack('<QII', 1, 31, 0),
                  11:struct.pack('<QII', 1, 1, 0), 13:struct.pack('<Qii', 1, 0, -1),
                  15:struct.pack('<Qi', 1, 0), 17:b'', 18:struct.pack('<QI', 1, 0),
                  19:struct.pack('<QII', 1, 0, 2), 21:struct.pack('<Q', 1),
                  22:struct.pack('<QIii', 1, 2, -1, 3), 23:struct.pack('<QI', 1, 0),
                  24:struct.pack('<QI', 1, 2)+b'X'*256,
                  64:struct.pack('<QII', 1, 12, 16*1024*1024),
                  65:struct.pack('<Q', 1)+b'frame',66:struct.pack('<Q',1),
                  67:struct.pack('<QQ',1,1)+b'player',68:struct.pack('<Q',1),
                  69:struct.pack('<Qi',1,0),70:struct.pack('<Q',1),71:struct.pack('<Q',1),
                  76:struct.pack('<QI',1,0),127:b''}
        self.assertEqual(set(bodies), {int(op) for op in w.WIRE_OPS})
        for op, body in bodies.items():
            encoded = w.encode_request(op, 1, body)
            packet, parsed = w.read_request(io.BytesIO(encoded), 1)
            self.assertEqual((packet.payload, parsed.opcode), (body, op))
        for op in w.LOCAL_GETS:
            with self.assertRaises(w.ProtocolError):
                command(op, struct.pack('<Q', 1))

    def test_count_length_bool_and_reserved_refusals(self):
        for op, body in ((1,b'\2'), (3,b'\xff'), (8,b'\0'*15), (7,b'\0'*8), (5,b''),
                         (22,struct.pack('<QI',1,2)+b'\0'*4),
                         (24,struct.pack('<QI',1,2049)+b'\0'*128),
                         (24,struct.pack('<QI',1,1)+b'\0'*127),
                         (67,struct.pack('<QQ',1,0)+b'x'), (67,struct.pack('<QQ',1,1)),
                         (67,struct.pack('<QQ',1,1)+b'x'*65537),
                         (68,struct.pack('<Q',1)+b'x'), (69,struct.pack('<Qi',1,-1)),
                         (70,struct.pack('<Q',1)+b'x'), (70,struct.pack('<Q',0))):
            with self.subTest(op=op), self.assertRaises(w.ProtocolError):
                command(op, body)
        for op in (0, 25, 71, 126, 128, 255):
            with self.assertRaises(w.ProtocolError):
                command(op)

    def test_header_cap_rejects_without_reading_payload(self):
        class Source:
            def __init__(self, header):self.header,self.reads=header,0
            def read(self, size):
                self.reads += 1
                if self.reads != 1:raise AssertionError('unbounded payload read attempted')
                return self.header
        source = Source(w.HEADER.pack(w.MAGIC,1,1,0,1,w.MAX_PAYLOAD+1))
        with self.assertRaisesRegex(w.ProtocolError, 'limit'):
            w.read_request(source, 1)
        self.assertEqual(source.reads, 1)

    def test_truncated_header_and_body(self):
        for value in (b'BAP', w.HEADER.pack(w.MAGIC,1,1,0,1,1)):
            with self.assertRaises(w.ProtocolError):w.read_request(io.BytesIO(value),1)
        self.assertIsNone(w.read_request(io.BytesIO(),1))

    def test_response_log_bounds_and_wire_layout(self):
        packet=w.Packet(9,8,b'')
        encoded=w.encode_response(packet,7,b'data',[(2,b'owned log')])
        self.assertEqual(responses(encoded),[(137,0,8,7,[(2,b'owned log')],b'data')])
        with self.assertRaises(w.ProtocolError):w.encode_response(packet,0,logs=[(1,b'')]*257)
        with self.assertRaises(w.ProtocolError):w.encode_response(packet,0,logs=[(1,b'X'*(w.MAX_LOG_BYTES+1))])


class DispatcherTests(unittest.TestCase):
    def test_atomic_outputs_and_distinct_native_codes(self):
        raw,s,key=world_session();body=struct.pack('<QII',key,31,0)
        code,data=s.dispatch(command(w.Op.MAKE_FRAME,body))
        self.assertEqual((code,struct.unpack('<IiI',data[:12]),data[12:]),(0,(8,0,8),raw.frame))
        self.assertEqual([x[0] for x in raw.calls[-2:]],['SimMakeSimFrame','SimGetSimFrameBuffer'])
        raw.codes['SimGetSimFrameBuffer']=7
        self.assertEqual(s.dispatch(command(w.Op.MAKE_FRAME,body)),(0,struct.pack('<IiI',8,7,0)))
        raw.codes['SimMakeSimFrame']=6;before=len(raw.calls)
        self.assertEqual(s.dispatch(command(w.Op.MAKE_FRAME,struct.pack('<QII',key,31,999))),
                         (6,struct.pack('<IiI',999,-1,0)))
        self.assertEqual(len(raw.calls),before+1)
        s.close()

    def test_successful_oversize_refuses_before_get(self):
        raw,s,key=world_session();raw.make_size=w.MAX_BUFFER+1
        with self.assertRaises(HostError):s.dispatch(command(9,struct.pack('<QII',key,31,0)))
        self.assertNotIn('SimGetSimFrameBuffer',[x[0] for x in raw.calls]);s.close()

    def test_failed_step_preserves_seed_and_owner_refuses_foreign_thread(self):
        raw,s,key=world_session();raw.codes['SimStep']=14
        self.assertEqual(s.dispatch(command(8,struct.pack('<QIi',key,50,-3))),
                         (14,struct.pack('<i',-3)))
        failures=[];before=len(raw.calls)
        def foreign():
            try:s.dispatch(command(8,struct.pack('<QIi',key,50,0)))
            except HostError as error:failures.append(str(error))
        thread=threading.Thread(target=foreign);thread.start();thread.join(5)
        self.assertFalse(thread.is_alive());self.assertEqual(len(failures),1)
        self.assertEqual(len(raw.calls),before);s.close()

    def test_init_postcheck_failure_still_destroys_initialized_runtime(self):
        raw=Raw()
        class Fault:
            fired=False
            def healthy(self):
                if not self.fired and raw.calls and raw.calls[-1][0]=='SimInit':
                    self.fired=True;raise HostError('authored post-init failure')
        s=NativeSession(raw,arena=Fault())
        with self.assertRaises(HostError):s.dispatch(command(1,b'\0'))
        s.close();self.assertEqual([x[0] for x in raw.calls].count('SimDestroy'),1)

    def test_players_size_is_bytes_and_version_signed(self):
        raw,s,key=world_session();code,data=s.dispatch(command(13,struct.pack('<Qii',key,0,-1)))
        self.assertEqual((code,struct.unpack('<iiiI',data[:16]),data[16:]),(0,(8,9,0,8),raw.players));s.close()

    def test_inline_names_preserve_unwritten_seed_records(self):
        raw,s,key=world_session();code,data=s.dispatch(command(24,struct.pack('<QI',key,3)+b'Z'*384))
        self.assertEqual((code,len(data),data),(0,384,b'A'*128+b'B'*128+b'Z'*128));s.close()

    def test_zero_labels_get_and_noop_debug_seeds(self):
        raw,s,key=world_session();raw.labels=b''
        self.assertEqual(s.dispatch(command(11,struct.pack('<QII',key,3,0))),
                         (0,struct.pack('<IiI',0,0,0)))
        self.assertEqual(raw.calls[-1][0],'SimGetLabelsFrameBuffer')
        self.assertEqual(s.dispatch(command(18,struct.pack('<QI',key,123))),(8,struct.pack('<I',123)))
        self.assertEqual(s.dispatch(command(19,struct.pack('<QII',key,0,2))),
                         (8,struct.pack('<IiI',0,8,0)))
        self.assertEqual(s.dispatch(command(19,struct.pack('<QII',key,0xffffffff,2))),
                         (8,struct.pack('<IiI',0xffffffff,8,0)))
        self.assertNotIn('SimGetDebugDrawCommandBuffer',[name for name,_ in raw.calls]);s.close()

    def test_opaque_world_rematch_and_cooperative_lifetime(self):
        created=[]
        def make():
            value=Cooperative();created.append(value);return value
        first=make();raw,s,key=world_session(cooperative=first,cooperative_factory=make)
        self.assertNotEqual(key,raw.raw_world)
        with self.assertRaises(HostError):s.dispatch(command(5,b'second'))
        s.dispatch(command(6,struct.pack('<Q',key)));self.assertTrue(first.closed)
        code,data=s.dispatch(command(5,b'rematch'));new=struct.unpack('<Q',data)[0]
        self.assertEqual(code,0);self.assertGreater(new,key);self.assertFalse(created[-1].closed)
        with self.assertRaises(HostError):s.dispatch(command(8,struct.pack('<QIi',key,50,0)))
        s.close();self.assertTrue(created[-1].closed)

    def test_all_exports_are_dispatched_except_guarded_client_local_debug_get(self):
        raw,s,key=world_session()
        for op,body in ((3,b'\1'),(4,struct.pack('<I',0)),(7,struct.pack('<Q',key)+b'i'),
                        (8,struct.pack('<QIi',key,50,-1)),(9,struct.pack('<QII',key,0,0)),
                        (11,struct.pack('<QII',key,1,0)),(13,struct.pack('<Qii',key,0,-1)),
                        (15,struct.pack('<Qi',key,0)),(17,b''),(18,struct.pack('<QI',key,0)),
                        (19,struct.pack('<QII',key,0,0)),(21,struct.pack('<Q',key)),
                        (22,struct.pack('<QI',key,0)),(23,struct.pack('<QI',key,0)),
                        (24,struct.pack('<QI',key,1)+b'\0'*128)):
            s.dispatch(command(op,body))
        s.close();self.assertEqual({x[0] for x in raw.calls},set(SIGNATURES)-{'SimGetDebugDrawCommandBuffer'})

    def test_debug_stub_guard_rejects_wrong_return_bytes_or_alias_address(self):
        base=0x180000000;pointers={name:base+DEBUG_STUB_RVA for name in DEBUG_STUB_NAMES}
        reads=[]
        def reader(address,size):reads.append((address,size));return DEBUG_STUB_BYTES
        validate_debug_stubs(base,pointers,reader)
        self.assertEqual(reads,[(base+DEBUG_STUB_RVA,6)])
        with self.assertRaises(HostError):validate_debug_stubs(base,pointers,lambda *_:b'\x33\xc0\xc3')
        pointers['SimGetDebugDrawCommandBuffer']+=1
        with self.assertRaises(HostError):validate_debug_stubs(base,pointers,reader)

    def test_creation_postcheck_failure_still_cleans_owned_world(self):
        raw=Raw()
        class Fault:
            fired=False
            def healthy(self):
                if not self.fired and raw.calls and raw.calls[-1][0]=='SimCreateWorld':
                    self.fired=True;raise HostError('authored post-create failure')
        s=NativeSession(raw,arena=Fault());s.dispatch(command(1,b'\0'))
        with self.assertRaises(HostError):s.dispatch(command(5,b'g'))
        s.close();self.assertEqual([x[0] for x in raw.calls].count('SimDestroyWorld'),1)

    def test_destroy_postcheck_failure_does_not_double_destroy(self):
        raw,s,key=world_session()
        class Fault:
            fired=False
            def healthy(self):
                if not self.fired and raw.calls[-1][0]=='SimDestroyWorld':
                    self.fired=True;raise HostError('authored post-destroy failure')
        s.arena=Fault()
        with self.assertRaises(HostError):s.dispatch(command(6,struct.pack('<Q',key)))
        s.close();self.assertEqual([x[0] for x in raw.calls].count('SimDestroyWorld'),1)


class StreamTests(unittest.TestCase):
    def test_sequence_error_has_no_second_native_mutation_and_cleans(self):
        raw=Raw();s=NativeSession(raw)
        source=io.BytesIO(w.encode_request(1,1,b'\0')+w.encode_request(4,3,struct.pack('<I',1)))
        sink=io.BytesIO();self.assertEqual(run_streams(source,sink,s),1)
        got=responses(sink.getvalue());self.assertEqual([x[1] for x in got],[0,1])
        self.assertNotIn('SimSetLogFlags',[x[0] for x in raw.calls]);self.assertTrue(s.closed)

    def test_shutdown_closes_world_before_ack_and_eof_cleanup_once(self):
        raw=Raw();s=NativeSession(raw);sink=io.BytesIO()
        request=w.encode_request(1,1,b'\0')+w.encode_request(5,2,b'g')+w.encode_request(127,3)
        self.assertEqual(run_streams(io.BytesIO(request),sink,s),0)
        self.assertEqual(responses(sink.getvalue())[-1][:4],(255,0,3,0))
        names=[x[0] for x in raw.calls];self.assertEqual(names.count('SimDestroyWorld'),1)
        self.assertEqual(names.count('SimDestroy'),1);self.assertTrue(s.closed)
        raw=Raw();s=NativeSession(raw)
        self.assertEqual(run_streams(io.BytesIO(w.encode_request(1,1,b'\0')),io.BytesIO(),s),0)
        self.assertEqual([x[0] for x in raw.calls].count('SimDestroy'),1)

    def test_native_nonzero_is_not_transport_error(self):
        raw=Raw();raw.codes['SimInit']=12;s=NativeSession(raw);sink=io.BytesIO()
        self.assertEqual(run_streams(io.BytesIO(w.encode_request(1,1,b'\0')+w.encode_request(127,2)),sink,s),0)
        self.assertEqual(responses(sink.getvalue())[0][1:4],(0,1,12))

    def test_cleanup_failure_returns_terminal_shutdown(self):
        raw=Raw();s=NativeSession(raw);raw.codes['SimSetLogCallBack']=7;sink=io.BytesIO()
        self.assertEqual(run_streams(io.BytesIO(w.encode_request(127,1)),sink,s),1)
        self.assertEqual(responses(sink.getvalue())[0][1:4],(1,1,-1))

    def test_callback_bounds_fail_closed_and_utf8_is_bounded(self):
        raw=Raw();s=NativeSession(raw);s._log(1,b'\xff')
        self.assertEqual(s.drain_logs(),[(1,'\ufffd'.encode())])
        for _ in range(w.MAX_LOGS+1):s._log(2,b'log')
        sink=io.BytesIO();self.assertEqual(run_streams(io.BytesIO(w.encode_request(4,1,struct.pack('<I',0))),sink,s),1)
        self.assertEqual(responses(sink.getvalue())[0][1],1)

    def test_receipts_validate_installed_hash_without_cpp_sources(self):
        with tempfile.TemporaryDirectory() as folder:
            p=Path(folder)/'BAHeap.dll';p.write_bytes(b'authored helper fixture')
            receipt={'experimental':True,'dll_sha256':hashlib.sha256(p.read_bytes()).hexdigest(),
                     'source_sha256':'a'*64,'page_source_sha256':'b'*64}
            (p.parent/'build.json').write_text(json.dumps(receipt))
            self.assertEqual(helper_receipt(p,arena=True)[0],p)
            p.write_bytes(b'changed')
            with self.assertRaises(HostError):helper_receipt(p,arena=True)


if __name__=='__main__':unittest.main()
