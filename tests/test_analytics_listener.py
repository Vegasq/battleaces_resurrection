"""Read-only controls for the183 static evidence gate; no target execution."""
import os
from pathlib import Path
import unittest
from unittest.mock import patch

from tools import review_analytics_listener as listener


class AssemblyExtentTests(unittest.TestCase):
    class PE:
        base = 0x1000
        def offset(self, address, length=1): return address-self.base

    def test_complete_authored_extent(self):
        rows = listener.parse_assembly(b'1000: 90  nop\n1001: c3  ret\n', self.PE(), b'\x90\xc3', 0, 2)
        self.assertEqual(list(rows), [0, 1])

    def test_missing_overlapping_crossing_and_changed_bytes_rejected(self):
        for raw in (b'1000: 90  nop\n', b'1001: c3  ret\n',
                    b'1000: 90  nop\n1000: c3  ret\n', b'1000: 90 c3 90  invalid\n',
                    b'1000: 91  xchg\n1001: c3  ret\n'):
            with self.subTest(raw=raw), self.assertRaises(ValueError):
                listener.parse_assembly(raw, self.PE(), b'\x90\xc3', 0, 2)


@unittest.skipUnless(os.environ.get('BA_ANALYTICS_LISTENER_EVIDENCE'), 'Set retained183 evidence directory')
class RetainedListenerTests(unittest.TestCase):
    def setUp(self):
        self.root = Path(__file__).resolve().parents[1]
        self.evidence = Path(os.environ['BA_ANALYTICS_LISTENER_EVIDENCE']).resolve()
        self.original = self.root.parent.parent/'BattleAcesBeta_untouched/UnityPlayer.dll'
        self.installed = self.root/'local/r171g/UnityPlayer.dll'

    def review(self): return listener.review(self.original, self.installed, self.evidence)

    def test_real_static_binding_and_existing_guard(self):
        result = self.review()
        self.assertTrue(result['passed'])
        self.assertTrue(result['existing_start_guard_prevents_named_registration'])
        self.assertEqual(len(result['files']), 8)
        self.assertFalse(result['advertising_producer_resolved'])
        self.assertFalse(result['runtime_observed'])

    def test_changed_dispatch_assembly_and_missing_tail_rejected(self):
        path = self.evidence/'unity-c42790.asm'; original_read = Path.read_bytes
        raw = path.read_bytes()
        variants = [raw.replace(b'call\tr10', b'call\tr11'),
                    raw.replace(b'41 ff d2', b'41 ff d3'),
                    b'\n'.join(raw.splitlines()[:-1])]
        for changed in variants:
            self.assertNotEqual(changed, raw)
            def read(p): return changed if p == path else original_read(p)
            with self.subTest(changed_length=len(changed)), patch.object(Path, 'read_bytes', read), self.assertRaises(ValueError):
                self.review()

    def test_original_start_restored_in_installed_image_rejected(self):
        original_read = Path.read_bytes; raw = bytearray(original_read(self.installed))
        pe = listener.PE(raw); raw[pe.offset(pe.base+0xc66c20)] = 0x40
        def read(p): return bytes(raw) if p == self.installed else original_read(p)
        with patch.object(Path, 'read_bytes', read), self.assertRaises(ValueError): self.review()


if __name__ == '__main__': unittest.main()
