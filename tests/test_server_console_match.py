"""Authored evidence rejection controls; no simulation/deployment pass is mocked."""
import copy
import struct
from unittest import TestCase

from server import protocol as p
from tools import server_console_match as probe


class Stream:
    def __init__(self,data):self.data=bytearray(data)
    def recv(self,size):
        result=bytes(self.data[:min(1,size)]);del self.data[:len(result)];return result
    def settimeout(self,value):pass


class PacketTests(TestCase):
    def test_fragmented_header_and_body(self):
        self.assertEqual(probe.packet(Stream(p.encode(p.FRAME,b'authored'))),(p.FRAME,b'authored'))

    def test_clean_eof_is_distinct_from_partial_packet(self):
        with self.assertRaises(EOFError):probe.packet(Stream(b''))
        for data in (b'\x05',struct.pack('<I',3)+b'\x0e'):
            with self.subTest(data=data),self.assertRaises(AssertionError):probe.packet(Stream(data))

    def test_unbounded_and_empty_packets_are_rejected(self):
        for size in (0,p.MAX_BODY+1):
            with self.subTest(size=size),self.assertRaises(AssertionError):probe.packet(Stream(struct.pack('<I',size)))

    def test_unexpected_error_packet_is_never_skipped_as_background_lobby(self):
        with self.assertRaises(AssertionError):probe.receive(Stream(p.encode(p.ERROR,b'authored refusal')),p.FRAME)


class AuditRejectionTests(TestCase):
    def setUp(self):
        self.hashes=[f'{frame:064x}' for frame in range(40)]
        self.records=[]
        def add(event,**fields):
            self.records.append(dict(event=event,match='authored',perf_counter_ns=len(self.records),**fields))
        add('worker_started',worker_pid=17);add('match_created');add('match_started')
        for frame,digest in enumerate(self.hashes):add('frame_queued',frame=frame,frame_payload_sha256=digest)
        for frame in (0,20):
            for viewer in (0,1):add('native_snapshot',frame=frame,viewer=viewer,game_state=dict(complete=False),counts=dict(type=10))
        add('match_aborted',reason='server stopped',next_frame=40)
        add('worker_released',worker_pid=17);add('server_stopped')

    def verify(self,records=None):
        return probe.validate_audit(records or self.records,'authored',stopped=True,stop_ns=46,received_hashes=self.hashes)

    def test_ordered_stop_requires_matching_received_frames_and_worker(self):
        self.assertEqual(self.verify(),17)

    def test_socket_disconnect_from_listener_cancel_must_follow_ctrl_c(self):
        abort=next(row for row in self.records if row['event']=='match_aborted')
        abort['reason']='player disconnected'
        self.assertEqual(self.verify(),17)
        abort['perf_counter_ns']=45
        with self.assertRaises(AssertionError):self.verify()

    def test_missing_or_wrong_worker_release_cannot_pass(self):
        release=next(row for row in self.records if row['event']=='worker_released')
        release['worker_pid']=18
        with self.assertRaises(AssertionError):self.verify()
        self.records.remove(release)
        with self.assertRaises(AssertionError):self.verify()

    def test_host_shutdown_before_worker_release_cannot_pass(self):
        self.records[-1]['perf_counter_ns']=0
        with self.assertRaises(AssertionError):self.verify()

    def test_gap_duplicate_or_changed_frame_cannot_pass(self):
        for mutate in (lambda row:row.update(frame=19),lambda row:row.update(frame_payload_sha256='0'*64)):
            records=copy.deepcopy(self.records);mutate(records[23])
            with self.assertRaises(AssertionError):self.verify(records)

    def test_complete_or_empty_native_world_cannot_pass(self):
        snapshot=next(row for row in self.records if row['event']=='native_snapshot')
        snapshot['game_state']['complete']=True
        with self.assertRaises(AssertionError):self.verify()
        snapshot['game_state']['complete']=False;snapshot['counts']['type']=0
        with self.assertRaises(AssertionError):self.verify()

    def test_failed_authentication_is_not_hidden_by_successful_cleanup(self):
        self.records.append(dict(event='authentication_failed'))
        with self.assertRaises(AssertionError):self.verify()
