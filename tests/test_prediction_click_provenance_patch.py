"""File-only controls for exact original selection call/tail observation."""
from contextlib import ExitStack
import hashlib
from pathlib import Path
import struct
import unittest
from unittest.mock import patch

from client_patch.patcher import patch_client
from client_patch.patcher import prediction_actor_repair as actor
from client_patch.patcher import prediction_click_provenance as provenance
from tests.test_prediction_actor_patch import fixture


class ClickProvenancePatchTests(unittest.TestCase):
    def setUp(self):
        original = bytearray(fixture())
        original[0x518:0x51d] = bytes.fromhex('e900000000')
        self.original = bytes(original)
        self.sha = hashlib.sha256(self.original).hexdigest()
        self.tail = dict(name='AuthoredNaturalRemoval', rva=0x4018, offset=0x518,
                         before='e900000000')

    def recipe(self):
        context = ExitStack()
        context.enter_context(patch.object(actor, 'SUPPORTED_ORIGINAL_SHA256', self.sha))
        context.enter_context(patch.object(actor.prediction_selection, 'validate_original',
                                          return_value={'scope': 'separately tested selection admission'}))
        for name, value in (('BODY_GUARDS', []), ('CALL_HOOKS', []), ('TAIL_HOOKS', [self.tail]),
                            ('POINTER_HOOKS', []), ('PATCHES', [])):
            context.enter_context(patch.object(actor, name, value))
        context.enter_context(patch.object(patch_client, 'ORIGINAL_SHA256', self.sha))
        for name in ('PATCHES', 'HOOKS', 'TAIL_HOOKS', 'CALL_HOOKS', 'COMMUNITY_CALL_HOOKS',
                     'COMMUNITY_TAIL_HOOKS', 'COSMETIC_PATCHES', 'COSMETIC_CALL_HOOKS',
                     'COSMETIC_TAIL_HOOKS', 'QUIT_CALL_HOOKS', 'QUIT_POINTER_HOOKS',
                     'DLSS_PRIVACY_PATCHES'):
            context.enter_context(patch.object(patch_client, name, []))
        context.enter_context(patch.object(patch_client.prediction_worker_patch, 'CALL_HOOKS', []))
        return context

    def test_tail_is_movement_only_and_emits_jump_preserving_fallthrough(self):
        def imports(data, dll, exports, *, thunk_exports):
            self.assertEqual(dll, 'BattleAcesOffline.dll')
            self.assertEqual(exports, thunk_exports)
            return data, {}, {name: 0x8000 for name in exports}

        with self.recipe(), patch.object(patch_client.telemetry, 'patch_component',
                                         side_effect=lambda _, data: data), \
                patch.object(patch_client, 'extend_imports_with_thunks', side_effect=imports) as published:
            ordinary = patch_client.build_patch(self.original)
            worker = patch_client.build_patch(self.original, community=True, prediction_worker=True)
            for invocation in published.call_args_list:
                self.assertNotIn(self.tail['name'], invocation.args[2])
            movement = patch_client.build_patch(self.original, community=True,
                                                prediction_worker=True, prediction_movement=True)
            self.assertEqual(published.call_args.args[2], [self.tail['name']])
        offset = self.tail['offset']
        self.assertEqual(ordinary[offset:offset+5], self.original[offset:offset+5])
        self.assertEqual(worker[offset:offset+5], self.original[offset:offset+5])
        self.assertEqual(movement[offset], 0xe9)
        self.assertEqual(self.tail['rva']+5+struct.unpack_from('<i', movement, offset+1)[0], 0x8000)
        self.assertEqual(movement[offset+5:offset+16], self.original[offset+5:offset+16])

    def test_bad_tail_bytes_mapping_or_opcode_refuse_before_publication(self):
        for change in (dict(offset=0x519), dict(before='e900000001'),
                       dict(before='e9000000'), dict(before='e800000000')):
            with self.subTest(change=change), self.recipe(), \
                    patch.object(actor, 'TAIL_HOOKS', [dict(self.tail, **change)]), \
                    patch.object(patch_client.telemetry, 'patch_component') as transform, \
                    patch.object(patch_client, 'extend_imports_with_thunks') as imports:
                with self.assertRaisesRegex(ValueError, 'tail guard/mapping'):
                    patch_client.build_patch(self.original, community=True,
                                             prediction_worker=True, prediction_movement=True)
                transform.assert_not_called()
                imports.assert_not_called()

    def test_admitted_call_opcode_cannot_be_reclassified_as_an_original_tail(self):
        changed = bytearray(self.original)
        changed[0x518] = 0xe8
        changed = bytes(changed)
        sha = hashlib.sha256(changed).hexdigest()
        with self.recipe(), patch.object(actor, 'SUPPORTED_ORIGINAL_SHA256', sha), \
                patch.object(actor, 'TAIL_HOOKS', [dict(self.tail, before='e800000000')]):
            with self.assertRaisesRegex(ValueError, 'tail guard/mapping'):
                actor.validate_original(changed, expected_sha256=sha)

    def test_shipped_edges_target_exact_original_collection_methods(self):
        targets = {
            'OfflinePredictionNaturalSelectionRemove': 0x3bf0cf0,
            'OfflinePredictionPreviewAdd': 0x3c661b0,
            'OfflinePredictionSelectionAdd': 0x3c661b0,
            'OfflinePredictionPreviewClear': 0x3c66c50,
            'OfflinePredictionSelectionClear': 0x3c66c50,
            'OfflinePredictionSelectionRemovePreview': 0x3c66610,
            'OfflinePredictionSelectionRemoveCurrent': 0x3c66610,
        }
        self.assertEqual(len(provenance.CALL_HOOKS), 5)
        self.assertEqual(len(provenance.TAIL_HOOKS), 5)
        for kind, hooks, opcode in (('call', provenance.CALL_HOOKS, 0xe8),
                                    ('tail', provenance.TAIL_HOOKS, 0xe9)):
            for hook in hooks:
                with self.subTest(kind=kind, site=hook['rva']):
                    before = bytes.fromhex(hook['before'])
                    self.assertEqual(len(before), 5)
                    self.assertEqual(before[0], opcode)
                    self.assertEqual(hook['rva']+5+struct.unpack_from('<i', before, 1)[0], targets[hook['name']])
        self.assertEqual(provenance.BODY_GUARDS[0], dict(rva=0x3bf3310, before='498b104533c0'))

    def test_pinned_original_accepts_all_new_edges_without_loading_it(self):
        path = Path(__file__).resolve().parents[2]/'investigation/original/GameAssembly.dll'
        if not path.is_file():
            self.skipTest('private pinned original DLL unavailable')
        original = path.read_bytes()
        result = actor.validate_original(original, expected_sha256=patch_client.ORIGINAL_SHA256)
        self.assertEqual(result['tail_hooks'], actor.TAIL_HOOKS)
        self.assertTrue(all(row in result['call_hooks'] for row in provenance.CALL_HOOKS))
        self.assertEqual(hashlib.sha256(original).hexdigest(), actor.SUPPORTED_ORIGINAL_SHA256)


if __name__ == '__main__':
    unittest.main()
