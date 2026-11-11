"""Authored file-only controls for optional movement selection admission."""
from contextlib import ExitStack
import hashlib
from pathlib import Path
import struct
import unittest
from unittest.mock import patch

from client_patch.patcher import patch_client
from client_patch.patcher import prediction_actor_repair as actor
from client_patch.patcher import prediction_selection as selection
from tests.test_prediction_actor_patch import fixture


class PredictionSelectionPatchTests(unittest.TestCase):
    INPUT_CALLBACKS = (
        ('OfflinePredictionInputFocusCancel0', 0x3bf7760, 0x6d4db50),
        ('OfflinePredictionInputFocusCancel1', 0x3bf77d0, 0x6d4db58),
        ('OfflinePredictionInputFocusCancel2', 0x3bf7840, 0x6d4db60),
        ('OfflinePredictionInputFocusCancel3', 0x3bf78b0, 0x6d4db68),
        ('OfflinePredictionInputFocusCancel4', 0x3bf7920, 0x6d4db70),
        ('OfflinePredictionInputCancelAbility', 0x3bf7990, 0x6d4db78),
        ('OfflinePredictionInputQueueModifier', 0x3bf79a0, 0x6d4db80),
        ('OfflinePredictionInputForceModifier', 0x3bf7a70, 0x6d4db88),
        ('OfflinePredictionInputPosition', 0x3bf7ad0, 0x6d4db90),
        ('OfflinePredictionInputDown', 0x3bf7d20, 0x6d4db98),
        ('OfflinePredictionInputUp', 0x3bf7f60, 0x6d4dba0),
        ('OfflinePredictionInputContextDown', 0x3bf80f0, 0x6d4dba8),
        ('OfflinePredictionInputContextUp', 0x3bf8290, 0x6d4dbb0),
    )

    def setUp(self):
        data = bytearray(fixture())
        descriptors = (
            ('OfflinePredictionSelectionCommit', 0x4030, '488b9290010000ffd0'),
            ('OfflinePredictionSelectionConfirmer', 0x4040, 'e801000000'),
            ('OfflinePredictionCastingSet', 0x4050, 'e802000000'),
            ('OfflinePredictionCastingSet', 0x4060, 'e803000000'),
            ('OfflinePredictionControlGroupFocus', 0x4070, 'e804000000'),
            ('OfflinePredictionClickDownAccepted', 0x4078, 'e805000000'),
        )
        self.hooks = []
        for name, rva, before in descriptors:
            offset = 0x500 + rva - 0x4000
            data[offset:offset + len(bytes.fromhex(before))] = bytes.fromhex(before)
            self.hooks.append(dict(name=name, rva=rva, offset=offset, before=before))
        # All callback slots share a real authored relocation block. Distinct
        # RVA/raw deltas ensure validation cannot assume the game's usual delta.
        self.image_base = 0x180000000
        struct.pack_into('<Q', data, 0x98 + 24, self.image_base)
        struct.pack_into('<I', data, 0x98 + 108, 16)
        names = ['OfflinePredictionRepeatFocusNext'] + [row[0] for row in self.INPUT_CALLBACKS]
        block_size = 8 + 2 * len(names)
        struct.pack_into('<II', data, 0x98 + 112 + 5 * 8, 0x4120, block_size)
        block = struct.pack('<II', 0x4000, block_size)
        data[0x620:0x628] = block
        self.pointers = []
        for index, name in enumerate(names):
            rva, offset, target = 0x4080 + index * 8, 0x580 + index * 8, 0x1000 + index * 8
            entry_offset = 0x628 + index * 2
            before = struct.pack('<Q', self.image_base + target)
            relocation = struct.pack('<H', 0xa000 | (rva & 0xfff))
            data[offset:offset + 8] = before
            data[entry_offset:entry_offset + 2] = relocation
            self.pointers.append(dict(
                name=name, rva=rva, offset=offset, before=before.hex(), target_rva=target,
                relocation_block_offset=0x620, relocation_block_before=block.hex(),
                relocation_entry_offset=entry_offset, relocation_entry_before=relocation.hex()))
        self.original = bytes(data)
        self.sha = hashlib.sha256(self.original).hexdigest()
        self.guards = [dict(rva=0x1003, before=b'ABCD'.hex()),
                       dict(rva=0x4010, before=b'XYZ'.hex())]

    def admitted_fixture(self):
        stack = ExitStack()
        stack.enter_context(patch.object(selection, 'SUPPORTED_ORIGINAL_SHA256', self.sha))
        stack.enter_context(patch.object(selection, 'BODY_GUARDS', self.guards))
        stack.enter_context(patch.object(selection, 'CALL_HOOKS', self.hooks))
        stack.enter_context(patch.object(selection, 'POINTER_HOOKS', self.pointers))
        stack.enter_context(patch.object(selection, 'PATCHES', []))
        return stack

    def patch_recipe_fixture(self):
        stack = self.admitted_fixture()
        stack.enter_context(patch.object(patch_client, 'ORIGINAL_SHA256', self.sha))
        stack.enter_context(patch.object(actor, 'SUPPORTED_ORIGINAL_SHA256', self.sha))
        stack.enter_context(patch.object(actor, 'BODY_GUARDS', []))
        stack.enter_context(patch.object(actor, 'CALL_HOOKS', self.hooks))
        stack.enter_context(patch.object(actor, 'TAIL_HOOKS', []))
        stack.enter_context(patch.object(actor, 'POINTER_HOOKS', self.pointers))
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
        self.assertEqual(result['pointer_hooks'], self.pointers)
        self.assertEqual(len(result['pointer_guards']), 14)
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

    def test_every_callback_pointer_rejects_changed_mapping_target_and_relocation(self):
        saved = self.original
        for index, pointer in enumerate(self.pointers):
            changes = (
                dict(before='00' * 8), dict(offset=pointer['offset'] + 1),
                dict(target_rva=pointer['target_rva'] + 1),
                dict(relocation_block_offset=pointer['relocation_block_offset'] + 8),
                dict(relocation_block_before='00' * 8),
                dict(relocation_entry_offset=pointer['relocation_entry_offset'] + 2),
                dict(relocation_entry_before='0000'),
            )
            for change in changes:
                pointers = [dict(row) for row in self.pointers]
                pointers[index].update(change)
                with self.subTest(name=pointer['name'], change=change), self.admitted_fixture(), \
                        patch.object(selection, 'POINTER_HOOKS', pointers):
                    with self.assertRaisesRegex(ValueError, 'Prediction actor pointer:'):
                        selection.validate_original(self.original, expected_sha256=self.sha)
        self.assertEqual(self.original, saved)

    def test_callback_dir64_corruption_refuses_before_transform_or_imports(self):
        # The file hash alone cannot waive the independently pinned relocation.
        changed = bytearray(self.original)
        pointer = self.pointers[-1]
        changed[pointer['relocation_entry_offset'] + 1] ^= 0x10
        changed = bytes(changed)
        sha = hashlib.sha256(changed).hexdigest()
        with self.patch_recipe_fixture(), \
                patch.object(selection, 'SUPPORTED_ORIGINAL_SHA256', sha), \
                patch.object(actor, 'SUPPORTED_ORIGINAL_SHA256', sha), \
                patch.object(patch_client, 'ORIGINAL_SHA256', sha), \
                patch.object(patch_client.telemetry, 'patch_component') as transform, \
                patch.object(patch_client, 'extend_imports_with_thunks') as imports:
            with self.assertRaisesRegex(ValueError, 'relocation bytes/entry mismatch'):
                patch_client.build_patch(changed, community=True,
                                         prediction_worker=True, prediction_movement=True)
            transform.assert_not_called()
            imports.assert_not_called()

    def test_input_descriptors_cover_exact_callback_slots_and_original_down_call(self):
        callbacks = [row for row in selection.POINTER_HOOKS
                     if row['name'].startswith('OfflinePredictionInput')]
        self.assertEqual([(row['name'], row['target_rva'], row['rva']) for row in callbacks],
                         list(self.INPUT_CALLBACKS))
        for row in callbacks:
            self.assertEqual(int.from_bytes(bytes.fromhex(row['before']), 'little'),
                             0x180000000 + row['target_rva'])
            relocation = int.from_bytes(bytes.fromhex(row['relocation_entry_before']), 'little')
            self.assertEqual(relocation >> 12, 10)
            self.assertEqual(relocation & 0xfff, row['rva'] & 0xfff)
        marker = [row for row in selection.CALL_HOOKS
                  if row['name'] == 'OfflinePredictionClickDownAccepted']
        self.assertEqual(marker, [dict(name='OfflinePredictionClickDownAccepted',
                                      rva=0x3bf7e64, offset=0x3bf6464,
                                      before='e8f7cbffff')])
        call = bytes.fromhex(marker[0]['before'])
        self.assertEqual(marker[0]['rva'] + 5 + struct.unpack_from('<i', call, 1)[0],
                         0x3bf4a60)
        guards = {row['rva']: row['before'] for row in selection.BODY_GUARDS}
        self.assertTrue(all(target in guards for _, target, _ in self.INPUT_CALLBACKS))
        # Original Down supplies RCX=selector and RDX=null MethodInfo. Its
        # original return/epilogue remains outside the complete five-byte CALL.
        self.assertEqual(guards[0x3bf7e5f], '33d2488bcb')
        self.assertEqual(guards[0x3bf7e69], '488b5c2448488b7424504883c4305fc3')
        self.assertEqual(guards[0x18d00],
                         '40534883ec20833d3bd7e20600488bda498b40084c8bc948894110'
                         '4c89412848895120')

    def test_subscribe_and_unsubscribe_keep_the_same_callback_methodinfo_cells(self):
        guards = {row['rva']: bytes.fromhex(row['before']) for row in selection.BODY_GUARDS}
        # The original special constructor consumes RCX=new delegate,
        # RDX=actual selector, R8=callback MethodInfo. No delegate layout edit.
        subscribe = (0x3bee820, 0x3bee991, 0x3beeb02, 0x3beec73, 0x3beede4,
                     0x3beee5f, 0x3beeeda, 0x3beef55, 0x3beefd0, 0x3bef04b,
                     0x3bef0c6, 0x3bef141, 0x3bef1bc, 0x3bef237, 0x3bef2ae)
        unsubscribe = (0x3befb80, 0x3befcf1, 0x3befe62, 0x3beffd3, 0x3bf0144,
                       0x3bf01bf, 0x3bf023a, 0x3bf02b5, 0x3bf0330, 0x3bf03ab,
                       0x3bf0426, 0x3bf04a1, 0x3bf051c, 0x3bf0597, 0x3bf060e)
        cells = []
        for sites in (subscribe, unsubscribe):
            route = []
            for rva in sites:
                code = guards[rva]
                self.assertEqual(len(code), 21)
                self.assertEqual(code[:3], bytes.fromhex('4c8b05'))
                self.assertEqual(code[7:13], bytes.fromhex('488bd7488bc8'))
                # The original retains the delegate in RBP or RSI; both leave
                # RCX/RDX/R8 unchanged for the special constructor.
                self.assertIn(code[13:16], (bytes.fromhex('488be8'), bytes.fromhex('488bf0')))
                self.assertEqual(code[16], 0xe8)
                self.assertEqual(rva + 21 + struct.unpack_from('<i', code, 17)[0], 0x18d00)
                route.append(rva + 7 + struct.unpack_from('<i', code, 3)[0])
            cells.append(route)
        self.assertEqual(cells[0], cells[1])
        self.assertEqual(len(set(cells[0])), 13)

    def test_pinned_original_validation_when_private_original_is_available(self):
        # Optional local file-only admission, never a fixture binary in Git.
        original_path = (Path(__file__).resolve().parents[2] /
                         'investigation/original/GameAssembly.dll')
        if not original_path.is_file():
            self.skipTest('private pinned original DLL is not available')
        original = original_path.read_bytes()
        saved_hash = hashlib.sha256(original).hexdigest()
        result = selection.validate_original(original, expected_sha256=patch_client.ORIGINAL_SHA256)
        self.assertEqual(saved_hash, selection.SUPPORTED_ORIGINAL_SHA256)
        self.assertEqual(result['call_hooks'], selection.CALL_HOOKS)
        self.assertEqual(result['pointer_hooks'], selection.POINTER_HOOKS)
        self.assertEqual(len(result['pointer_guards']), len(selection.POINTER_HOOKS))
        self.assertEqual(hashlib.sha256(original).hexdigest(), saved_hash)

    def test_movement_only_patch_emits_calls_and_callback_slots_preserving_dir64(self):
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
            for hook in self.pointers:
                o = hook['offset']
                self.assertEqual(ordinary[o:o + 8], self.original[o:o + 8])
                self.assertEqual(worker[o:o + 8], self.original[o:o + 8])
            movement = patch_client.build_patch(self.original, community=True,
                                                prediction_worker=True, prediction_movement=True)
            guard.assert_called_once_with(self.original, expected_sha256=self.sha)
        exported = imports.call_args.args[2]
        for invocation in imports.call_args_list[:2]:
            self.assertFalse(any(name.startswith('OfflinePredictionInput') or
                                 name == 'OfflinePredictionClickDownAccepted'
                                 for name in invocation.args[2]))
        self.assertEqual(exported, ['OfflinePredictionSelectionCommit',
                                    'OfflinePredictionSelectionConfirmer',
                                    'OfflinePredictionCastingSet',
                                    'OfflinePredictionControlGroupFocus',
                                    'OfflinePredictionClickDownAccepted'] +
                                   [row['name'] for row in self.pointers])
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
        for hook in self.pointers:
            target = 0x8000 + exported.index(hook['name']) * 16
            self.assertEqual(struct.unpack_from('<Q', movement, hook['offset'])[0],
                             self.image_base + target)
            entry = hook['relocation_entry_offset']
            self.assertEqual(movement[entry:entry + 2], self.original[entry:entry + 2])
        self.assertEqual(movement[0x620:0x644], self.original[0x620:0x644])


if __name__ == '__main__':
    unittest.main()
