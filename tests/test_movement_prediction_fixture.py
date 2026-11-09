"""Authored move-wire and observable-state fixtures; no native process launches."""
import copy
import math
import struct
import unittest

from server.protobuf_wire import get_bytes,get_repeated_bytes,get_repeated_uint,get_uint,signed64
from tools.verify_movement_prediction import (decode_cooldowns,equal_observations,move_action,position_message)


class MovementFixtureTests(unittest.TestCase):
    def test_move_uses_owned_entity_and_original_ground_target_q32_coordinates(self):
        action = move_action(dict(id=101,type=75,army=0),[1.25,-2.5,0])
        execute = get_bytes(action,1,required=True)
        group, = get_repeated_bytes(execute,1)
        self.assertEqual((get_uint(group,1),get_uint(group,2),get_repeated_uint(group,3)),(75,12,(101,)))
        position = get_bytes(get_bytes(get_bytes(execute,3,required=True),3,required=True),1,required=True)
        self.assertEqual([signed64(get_uint(position,index)) for index in (1,2,3)],
                         [5*2**30,-5*2**31,0])

    def test_target_rejects_nonfinite_and_signed_overflow_before_native_entry(self):
        for point in ([math.nan,0,0],[0,math.inf,0],[2**31,0,0],[-2**31,0,0],[0,0]):
            with self.subTest(point=point),self.assertRaises(ValueError):
                position_message(point)

    @staticmethod
    def charge_buffer():
        data = bytearray(124)
        struct.pack_into('<I',data,0,44)
        struct.pack_into('<HH',data,4,38,8)
        struct.pack_into('<H',data,40,4)  # root field16
        struct.pack_into('<iI',data,44,40,24)  # component table72
        struct.pack_into('<HH',data,56,8,8)
        struct.pack_into('<H',data,62,4)  # component field1
        struct.pack_into('<iII',data,72,16,4,2)  # vector80, two inline structs
        struct.pack_into('<IfIIf',data,84,34,1.,2,1,.5)
        struct.pack_into('<IfIIf',data,104,12,0.,0,0,0.)
        return data

    def test_cooldown_parser_uses_proven_field_stride_and_checks_bounds(self):
        data = self.charge_buffer()
        rows = decode_cooldowns(bytes(data))
        self.assertEqual(rows[0],dict(index=0,ability=34,current_charges=1.,max_charges=2,
                                     available_recharges=1,cooldown=.5))
        self.assertEqual(rows[1]['ability'],12)
        struct.pack_into('<I',data,80,999)
        with self.assertRaises(ValueError):
            decode_cooldowns(bytes(data))

    def test_equivalence_requires_resources_health_and_cooldowns(self):
        original = dict(state=dict(resources={0:dict(primary=100)},entities=[dict(id=5,current_damage=0)]),
                        cooldowns=[dict(ability=34,cooldown=.5)])
        equal_observations(original,copy.deepcopy(original))
        for key in ('resources','entities','cooldowns'):
            changed = copy.deepcopy(original)
            if key == 'cooldowns': changed[key][0]['cooldown'] = .25
            else: changed['state'][key] = {}
            with self.subTest(key=key),self.assertRaises(AssertionError):
                equal_observations(changed,original)


if __name__ == '__main__':
    unittest.main()
