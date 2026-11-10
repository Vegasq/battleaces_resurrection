"""Authored file-only controls for optional movement selection admission."""
from contextlib import ExitStack
import hashlib
import struct
import unittest
from unittest.mock import patch

from client_patch.patcher import patch_client
from client_patch.patcher import prediction_actor_repair as actor
from client_patch.patcher import prediction_selection as selection
from tests.test_prediction_actor_patch import fixture


class PredictionSelectionPatchTests(unittest.TestCase):
    def setUp(self):
        data = bytearray(fixture())
        descriptors = (
            ('OfflinePredictionSelectionCommit', 0x4030, '488b9290010000ffd0'),
            ('OfflinePredictionSelectionConfirmer', 0x4040, 'e801000000'),
            ('OfflinePredictionCastingSet', 0x4050, 'e802000000'),
            ('OfflinePredictionCastingSet', 0x4060, 'e803000000'),
            ('OfflinePredictionControlGroupFocus', 0x4070, 'e804000000'),
        )
        self.hooks = []
        for name, rva, before in descriptors:
            offset = 0x500 + rva - 0x4000
            data[offset:offset + len(bytes.fromhex(before))] = bytes.fromhex(before)
            self.hooks.append(dict(name=name, rva=rva, offset=offset, before=before))
        self.original = bytes(data)
        self.sha = hashlib.sha256(self.original).hexdigest()
        self.guards = [dict(rva=0x1003, before=b'ABCD'.hex()),
                       dict(rva=0x4010, before=b'XYZ'.hex())]

    def admitted_fixture(self):
        stack = ExitStack()
        stack.enter_context(patch.object(selection, 'SUPPORTED_ORIGINAL_SHA256', self.sha))
        stack.enter_context(patch.object(selection, 'BODY_GUARDS', self.guards))
        stack.enter_context(patch.object(selection, 'CALL_HOOKS', self.hooks))
        stack.enter_context(patch.object(selection, 'POINTER_HOOKS', []))
        stack.enter_context(patch.object(selection, 'PATCHES', []))
        return stack

    def patch_recipe_fixture(self):
        stack = self.admitted_fixture()
        stack.enter_context(patch.object(patch_client, 'ORIGINAL_SHA256', self.sha))
        stack.enter_context(patch.object(actor, 'SUPPORTED_ORIGINAL_SHA256', self.sha))
        stack.enter_context(patch.object(actor, 'BODY_GUARDS', []))
        stack.enter_context(patch.object(actor, 'CALL_HOOKS', self.hooks))
        stack.enter_context(patch.object(actor, 'POINTER_HOOKS', []))
        stack.enter_context(patch.object(actor, 'PATCHES', []))
        for name in ('PATCHES', 'HOOKS', 'TAIL_HOOKS', 'CALL_HOOKS',
                     'COMMUNITY_CALL_HOOKS', 'COMMUNITY_TAIL_HOOKS',
                     'COSMETIC_PATCHES', 'COSMETIC_CALL_HOOKS', 'COSMETIC_TAIL_HOOKS',
                     'QUIT_CALL_HOOKS', 'QUIT_POINTER_HOOKS', 'DLSS_PRIVACY_PATCHES'):
            stack.enter_context(patch.object(patch_client, name, []))
        stack.enter_context(patch.object(patch_client.prediction_worker_patch, 'CALL_HOOKS', []))
        return stack

    def test_every_guard_uses_complete_file_backed_range_and_has_provenance(self):
        with self.admitted_fixture():
            result = selection.validate_original(self.original, expected_sha256=self.sha)
        self.assertEqual(result['original_sha256'], self.sha)
        self.assertEqual(result['supported_original_sha256'], self.sha)
        self.assertEqual([g['offset'] for g in result['body_guards']], [0x203, 0x510])
        self.assertEqual(result['call_hooks'], self.hooks)
        self.assertEqual(self.original[0x530:0x539], bytes.fromhex('488b9290010000ffd0'))

    def test_independent_build_pin_and_actual_hash_are_both_required(self):
        with self.admitted_fixture():
            with self.assertRaisesRegex(ValueError, 'differs from patch recipe'):
                selection.validate_original(self.original, expected_sha256='0' * 64)
            with self.assertRaisesRegex(ValueError, 'original SHA256 does not match'):
                selection.validate_original(self.original[:-1], expected_sha256=self.sha)

    def test_each_body_guard_fails_even_with_admitted_file_digest(self):
        for index in range(len(self.guards)):
            guards = [dict(g) for g in self.guards]
            guards[index]['before'] = '00' * len(bytes.fromhex(guards[index]['before']))
            with self.subTest(index=index), self.admitted_fixture(), patch.object(
                    selection, 'BODY_GUARDS', guards):
                with self.assertRaisesRegex(ValueError, 'body guard mismatch'):
                    selection.validate_original(self.original, expected_sha256=self.sha)

    def test_each_hook_rejects_wrong_bytes_or_offset_without_mutation(self):
        saved = self.original
        for index in range(len(self.hooks)):
            for field, value in (('before', '00' * len(bytes.fromhex(self.hooks[index]['before']))),
                                 ('offset', self.hooks[index]['offset'] + 1)):
                hooks = [dict(h) for h in self.hooks]
                hooks[index][field] = value
                with self.subTest(index=index, field=field), self.admitted_fixture(), patch.object(
                        selection, 'CALL_HOOKS', hooks):
                    with self.assertRaisesRegex(ValueError, 'call guard/mapping mismatch'):
                        selection.validate_original(self.original, expected_sha256=self.sha)
        self.assertEqual(self.original, saved)

    def test_ninth_dispatch_byte_is_guarded(self):
        changed = bytearray(self.original)
        changed[0x538] ^= 1
        sha = hashlib.sha256(changed).hexdigest()
        with self.admitted_fixture(), patch.object(selection, 'SUPPORTED_ORIGINAL_SHA256', sha):
            with self.assertRaisesRegex(ValueError, 'call guard/mapping mismatch'):
                selection.validate_original(bytes(changed), expected_sha256=sha)

    def test_zero_fill_or_cross_boundary_guard_is_rejected(self):
        for guard in (dict(rva=0x1100, before='00'), dict(rva=0x10ff, before='0000')):
            with self.subTest(guard=guard), self.admitted_fixture(), patch.object(
                    selection, 'BODY_GUARDS', [guard]):
                with self.assertRaisesRegex(ValueError, 'not file-backed'):
                    selection.validate_original(self.original, expected_sha256=self.sha)

    def test_actor_descriptor_requires_independent_selection_validation(self):
        with self.patch_recipe_fixture(), patch.object(
                selection, 'SUPPORTED_ORIGINAL_SHA256', '0' * 64):
            with self.assertRaisesRegex(ValueError, 'Prediction selection supported original'):
                actor.validate_original(self.original, expected_sha256=self.sha)

    def test_guard_failure_precedes_transform_and_import_publication(self):
        with self.patch_recipe_fixture(), patch.object(selection, 'BODY_GUARDS',
                                                       [dict(rva=0x1003, before='00000000')]), \
                patch.object(patch_client.telemetry, 'patch_component') as transform, \
                patch.object(patch_client, 'extend_imports_with_thunks') as imports:
            with self.assertRaisesRegex(ValueError, 'Prediction selection body guard mismatch'):
                patch_client.build_patch(self.original, community=True,
                                         prediction_worker=True, prediction_movement=True)
            transform.assert_not_called()
            imports.assert_not_called()

    def test_movement_only_patch_emits_five_calls_and_four_unique_thunks(self):
        def import_fixture(data, dll, exports, *, thunk_exports):
            self.assertEqual(dll, 'BattleAcesOffline.dll')
            self.assertEqual(exports, thunk_exports)
            return data, {}, {name: 0x8000 + index * 16 for index, name in enumerate(exports)}

        with self.patch_recipe_fixture(), patch.object(patch_client.telemetry, 'patch_component',
                                                       side_effect=lambda _, data: data), \
                patch.object(patch_client, 'extend_imports_with_thunks',
                             side_effect=import_fixture) as imports, \
                patch.object(selection, 'validate_original',
                             wraps=selection.validate_original) as guard:
            ordinary = patch_client.build_patch(self.original)
            worker = patch_client.build_patch(self.original, community=True, prediction_worker=True)
            guard.assert_not_called()
            for hook in self.hooks:
                o = hook['offset']; n = len(bytes.fromhex(hook['before']))
                self.assertEqual(ordinary[o:o + n], self.original[o:o + n])
                self.assertEqual(worker[o:o + n], self.original[o:o + n])
            movement = patch_client.build_patch(self.original, community=True,
                                                prediction_worker=True, prediction_movement=True)
            guard.assert_called_once_with(self.original, expected_sha256=self.sha)
        exported = imports.call_args.args[2]
        self.assertEqual(exported, ['OfflinePredictionSelectionCommit',
                                    'OfflinePredictionSelectionConfirmer',
                                    'OfflinePredictionCastingSet',
                                    'OfflinePredictionControlGroupFocus'])
        targets = {}
        for hook in self.hooks:
            o = hook['offset']; n = len(bytes.fromhex(hook['before']))
            self.assertEqual(movement[o], 0xe8)
            target = hook['rva'] + 5 + struct.unpack_from('<i', movement, o + 1)[0]
            self.assertEqual(target, 0x8000 + exported.index(hook['name']) * 16)
            self.assertEqual(movement[o + 5:o + n], b'\x90' * (n - 5))
            if hook['name'] in targets:
                self.assertEqual(target, targets[hook['name']])
            targets[hook['name']] = target


if __name__ == '__main__':
    unittest.main()
