"""Execute guarded patch snippets in authored x64 harnesses, never game APIs."""
import ctypes
import os
import platform
import struct
import unittest
from client_patch.patcher.legacy_compliance import PATCHES, descriptor


class PolicyTests(unittest.TestCase):
    def test_original_branch_destination_is_retained(self):
        site = PATCHES[3]
        before, after = bytes.fromhex(site['before']), bytes.fromhex(site['after'])
        original_target = site['rva'] + 6 + struct.unpack_from('<i', before, 2)[0]
        patched_target = site['rva'] + 5 + struct.unpack_from('<i', after, 1)[0]
        self.assertEqual(original_target, 0x3e3f298)
        self.assertEqual(patched_target, original_target)

    def test_restore_descriptor_does_not_claim_disabled_policy(self):
        current, restored = descriptor(), descriptor(restored=True)
        self.assertEqual(current['korean_login_compliance'], 'disabled')
        self.assertEqual(restored['korean_login_compliance'], 'original-restored')
        for key in ('dialog_creation_blocked', 'validation_request_blocked', 'original_pending_gate_skipped'):
            self.assertTrue(current[key]); self.assertFalse(restored[key])
        self.assertFalse(current['community_transport_changed'])


@unittest.skipUnless(os.name == 'nt' and platform.machine().lower() in ('amd64', 'x86_64'),
                     'Authored Windows x64 machine-code harness')
class NativeBoundaryTests(unittest.TestCase):
    def invoke(self, code, result, arguments, *values):
        kernel = ctypes.WinDLL('kernel32', use_last_error=True)
        kernel.VirtualAlloc.argtypes = [ctypes.c_void_p, ctypes.c_size_t, ctypes.c_uint32, ctypes.c_uint32]
        kernel.VirtualAlloc.restype = ctypes.c_void_p
        kernel.VirtualProtect.argtypes = [ctypes.c_void_p, ctypes.c_size_t, ctypes.c_uint32, ctypes.POINTER(ctypes.c_uint32)]
        kernel.VirtualProtect.restype = ctypes.c_int
        kernel.VirtualFree.argtypes = [ctypes.c_void_p, ctypes.c_size_t, ctypes.c_uint32]
        kernel.VirtualFree.restype = ctypes.c_int
        kernel.GetCurrentProcess.restype = ctypes.c_void_p
        kernel.FlushInstructionCache.argtypes = [ctypes.c_void_p, ctypes.c_void_p, ctypes.c_size_t]
        kernel.FlushInstructionCache.restype = ctypes.c_int
        address = kernel.VirtualAlloc(None, len(code), 0x3000, 0x04)
        self.assertTrue(address)
        try:
            ctypes.memmove(address, code, len(code))
            old = ctypes.c_uint32()
            self.assertTrue(kernel.VirtualProtect(address, len(code), 0x20, ctypes.byref(old)))
            self.assertTrue(kernel.FlushInstructionCache(kernel.GetCurrentProcess(), address, len(code)))
            return ctypes.WINFUNCTYPE(result, *arguments)(address)(*values)
        finally:
            self.assertTrue(kernel.VirtualFree(address, 0, 0x8000))

    def test_dialog_and_request_guards_return_without_dereferencing_inputs(self):
        for site in PATCHES[:2]:
            with self.subTest(site=site['name']):
                self.invoke(bytes.fromhex(site['after']), None,
                            [ctypes.c_void_p, ctypes.c_void_p, ctypes.c_void_p], 1, 1, 1)

    def test_pending_clear_preserves_adjacent_owner_state(self):
        for value in (0, 1, 255):
            owner = ctypes.create_string_buffer(b'\xa5' * 0x120)
            owner[0x108] = bytes([value])
            before = owner.raw
            # Save nonvolatile RDI, bind RCX owner, execute exact installed
            # snippet, read the flag and restore RDI. No original native call.
            code = bytes.fromhex('574889cf') + bytes.fromhex(PATCHES[2]['after']) + bytes.fromhex('0fb687080100005fc3')
            self.assertEqual(self.invoke(code, ctypes.c_uint32, [ctypes.c_void_p], ctypes.addressof(owner)), 0)
            expected = before[:0x108] + b'\0' + before[0x109:]
            self.assertEqual(owner.raw, expected)

    def test_gate_always_skips_obsolete_prompt_block(self):
        branch = bytes.fromhex(PATCHES[3]['after'])
        destination = 5 + struct.unpack_from('<i', branch, 1)[0]
        code = branch + bytes.fromhex('b801000000c3')
        code += b'\xcc' * (destination - len(code))
        code += bytes.fromhex('b802000000c3')
        self.assertEqual(self.invoke(code, ctypes.c_uint32, []), 2)


if __name__ == '__main__':
    unittest.main()
