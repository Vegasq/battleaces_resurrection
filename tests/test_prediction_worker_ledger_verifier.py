"""File-only fixture/coordinator controls; never load Simulation.dll."""
import contextlib
import importlib
import io
import struct
import unittest
from pathlib import Path
from unittest.mock import patch

from server.game_data import encode_frame, encode_identity, encode_player_input
from server.protobuf_wire import field_bytes, field_uint, get_repeated_bytes


class LedgerVerifierTests(unittest.TestCase):
    def setUp(self):
        self.tool=importlib.import_module('tools.verify_prediction_worker_ledger')

    def test_entity_packet_exact_frame_sorted_unique_and_bounds(self):
        raw=struct.pack('<iI',4,2)+struct.pack('<III',0,0,3)+struct.pack('<III',74,0,75)
        self.assertEqual(self.tool.entity_packet(raw),(4,{0:(0,3),74:(0,75)}))
        for bad in (raw[:-1],raw+b'x',struct.pack('<iI',-2,0),struct.pack('<iI',0,262145),
                    struct.pack('<iI',4,2)+struct.pack('<III',74,0,75)*2):
            with self.subTest(length=len(bad)),self.assertRaises(AssertionError):self.tool.entity_packet(bad)

    def test_append_actions_preserves_remote_and_existing_own_fifo(self):
        identities={slot:encode_identity(slot+1,str(slot)) for slot in (0,1)}
        old=field_bytes(5,field_bytes(1,b''));new=field_bytes(5,field_bytes(2,b''))
        players={slot:encode_player_input(identities[slot],[old]) for slot in (0,1)}
        raw=encode_frame(3,players)
        calls=[]
        def validate(slot,body):calls.append((slot,body));return body
        changed=self.tool.append_own_actions(raw,identities[0],[new,new],validate)
        parts=get_repeated_bytes(changed,6)
        self.assertEqual(get_repeated_bytes(parts[0],2),(old,new,new))
        self.assertEqual(parts[1],players[1])
        self.assertEqual(calls,[(0,parts[0])])
        self.assertEqual(raw,encode_frame(3,players))

    def test_local_registration_must_succeed_before_authority_or_network_disposition(self):
        action=field_bytes(5,field_bytes(1,b''))
        raw=encode_player_input(encode_identity(1,'x'),[action])
        calls=[]
        def dispatch(op,body):
            calls.append((op,body))
            return 0,struct.pack('<Qi',7,500)
        self.assertEqual(self.tool.register_batch(dispatch,9,7,raw,expected_frame=500),7)
        self.assertEqual(calls,[(67,struct.pack('<QQ',9,7)+raw)])
        for response in ((1,b''),(0,struct.pack('<Qi',8,500)),(0,struct.pack('<Qi',7,501)),(0,b'')):
            with self.subTest(response=response),self.assertRaises(AssertionError):
                self.tool.register_batch(lambda *_:response,9,7,raw,expected_frame=500)

    def test_static_plan_keeps_window_and_terminal_drain_bounded(self):
        plan=self.tool.CASE_PLAN
        self.assertEqual((plan['first_local'],plan['second_local'],plan['server_commit'],plan['authority_frontier'],plan['head']),
                         (500,506,502,503,507))
        self.assertEqual(plan['head']-(plan['first_local']-1),8)
        self.assertLessEqual(plan['last_frame']-plan['terminal_frame'],12)
        self.assertLess(plan['last_frame']+1,1200)

    def test_prepare_only_cli_never_reaches_native_runner(self):
        with patch.object(self.tool,'prepare',return_value=dict(output='authored')) as prepare, \
             patch.object(self.tool,'run_prepared',side_effect=AssertionError('native launched')), \
             patch('subprocess.Popen',side_effect=AssertionError('process started')), \
             patch('sys.argv',['verifier','--prepare-only','--output','authored','--original-dll','a',
                               '--heap-helper','b','--cooperative','c','--baseline','d']), \
             contextlib.redirect_stdout(io.StringIO()) as output:
            self.assertEqual(self.tool.main(),0)
        self.assertEqual(prepare.call_count,1)
        self.assertIn('"native_executed": false',output.getvalue())


if __name__=='__main__':unittest.main()
