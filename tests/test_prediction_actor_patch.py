"""Authored PE controls for the optional actor-repair admission guard."""
from contextlib import ExitStack
import hashlib
from pathlib import Path
import re
import struct
import unittest
from unittest.mock import patch

from client_patch.patcher import patch_client
from client_patch.patcher import prediction_actor_repair as actor


def fixture():
    data = bytearray(0x700)
    data[:2] = b'MZ'
    struct.pack_into('<I', data, 0x3c, 0x80)
    data[0x80:0x84] = b'PE\0\0'
    struct.pack_into('<HH', data, 0x84, 0x8664, 2)
    struct.pack_into('<H', data, 0x94, 0xf0)
    struct.pack_into('<H', data, 0x98, 0x20b)
    struct.pack_into('<I', data, 0x98 + 60, 0x200)
    # Deliberately different RVA-to-raw deltas and a virtual zero-fill tail.
    for at, name, virtual_size, rva, size, raw in (
            (0x188, b'.first', 0x180, 0x1000, 0x100, 0x200),
            (0x1b0, b'.second', 0x200, 0x4000, 0x180, 0x500)):
        struct.pack_into('<8sIIII', data, at, name, virtual_size, rva, size, raw)
    data[0x203:0x207] = b'ABCD'
    data[0x510:0x513] = b'XYZ'
    data[0x518:0x51d] = bytes.fromhex('e801020304')
    return bytes(data)


class PredictionActorGuardTests(unittest.TestCase):
    def test_runtime_begin_requires_every_installed_actor_selection_hook(self):
        # Cross-module recipe/runtime contract: adding a patch descriptor must
        # also make an old or partially installed image fail before BEGIN.
        source = (Path(__file__).resolve().parents[1] /
                  'client_patch/src/prediction_worker.cpp').read_text(encoding='utf-8-sig')
        body = source.split('static void requireActorHook() {', 1)[1].split('\n}', 1)[0]
        required = [(int(site, 16), name) for site, name in re.findall(
            r'requireMovementHook\((0x[0-9a-fA-F]+),\s*"([^"]+)"\);', body)]
        self.assertEqual(len(required), len(set(required)))
        self.assertEqual(set(required), {(hook['rva'], hook['name']) for hook in actor.CALL_HOOKS})
        tails = [(int(site, 16), name) for site, name in re.findall(
            r'requireMovementTailHook\((0x[0-9a-fA-F]+),\s*"([^"]+)"\);', body)]
        self.assertEqual(len(tails), len(set(tails)))
        self.assertEqual(set(tails), {(hook['rva'], hook['name']) for hook in actor.TAIL_HOOKS})
        pointers = [(int(site, 16), name) for site, name in re.findall(
            r'requireMovementPointerHook\((0x[0-9a-fA-F]+),\s*"([^"]+)"\);', body)]
        self.assertEqual(len(pointers), len(set(pointers)))
        self.assertEqual(set(pointers), {(hook['rva'], hook['name']) for hook in actor.POINTER_HOOKS})
        byte_patches = [(int(site, 16), bytes(int(x, 16) for x in re.findall(r'\\x([0-9a-fA-F]{2})', before)).hex(), int(count))
                        for site, before, count in re.findall(
            r'requireMovementBytes\((0x[0-9a-fA-F]+),\s*"([^"]+)",\s*(\d+)\);', body)]
        self.assertEqual(set(byte_patches), {(row['rva'], row['after'], len(bytes.fromhex(row['after']))) for row in actor.PATCHES})

    def setUp(self):
        self.original = fixture()
        self.sha = hashlib.sha256(self.original).hexdigest()
        self.guards = [dict(rva=0x1003, before=b'ABCD'.hex()),
                       dict(rva=0x4010, before=b'XYZ'.hex())]
        self.hooks = [dict(name='OwnedActorFixture', rva=0x4018, offset=0x518,
                           before='e801020304')]

    def admitted_fixture(self):
        stack = ExitStack()
        stack.enter_context(patch.object(actor, 'SUPPORTED_ORIGINAL_SHA256', self.sha))
        stack.enter_context(patch.object(actor, 'BODY_GUARDS', self.guards))
        stack.enter_context(patch.object(actor, 'CALL_HOOKS', self.hooks))
        stack.enter_context(patch.object(actor, 'TAIL_HOOKS', []))
        stack.enter_context(patch.object(actor, 'POINTER_HOOKS', []))
        stack.enter_context(patch.object(actor, 'PATCHES', []))
        # The independent selection guard has its own authored controls in
        # test_prediction_selection_patch; isolate these actor PE controls.
        stack.enter_context(patch.object(actor.prediction_selection, 'validate_original',
                                         return_value={'fixture': 'actor-only'}))
        return stack

    def test_each_section_maps_its_own_delta_and_metadata(self):
        with self.admitted_fixture():
            result = actor.validate_original(self.original, expected_sha256=self.sha)
        self.assertEqual(result['original_sha256'], self.sha)
        self.assertEqual(result['supported_original_sha256'], self.sha)
        self.assertEqual([row['offset'] for row in result['body_guards']], [0x203, 0x510])
        self.assertEqual(result['call_hooks'], self.hooks)
        self.assertEqual(actor.rva_to_offset(self.original, 0, 2), 0)
        self.assertEqual(self.original, fixture())

    def test_unbacked_zero_fill_and_cross_boundary_rejected(self):
        for rva, size in ((0x1100, 1), (0x10ff, 2), (0x3000, 1),
                          (0x4180, 1), (0x417f, 2), (0x1ff, 2)):
            with self.subTest(rva=rva, size=size), self.assertRaisesRegex(ValueError, 'not file-backed'):
                actor.rva_to_offset(self.original, rva, size)

    def test_invalid_rva_ranges_rejected(self):
        for rva, size in ((-1, 1), (0, 0), (True, 1), (0, True),
                          (0xffffffff, 2), (0x1000, -1)):
            with self.subTest(rva=rva, size=size), self.assertRaisesRegex(ValueError, 'invalid RVA'):
                actor.rva_to_offset(self.original, rva, size)

    def test_independent_build_pin_and_actual_digest_both_required(self):
        with self.admitted_fixture():
            with self.assertRaisesRegex(ValueError, 'differs from patch recipe'):
                actor.validate_original(self.original, expected_sha256='0' * 64)
            with self.assertRaisesRegex(ValueError, 'original SHA256 does not match'):
                actor.validate_original(self.original[:-1], expected_sha256=self.sha)

    def test_body_guard_mismatch_is_not_admitted_by_valid_file_hash(self):
        with self.admitted_fixture(), patch.object(actor, 'BODY_GUARDS',
                                                   [dict(rva=0x1003, before='00000000')]):
            with self.assertRaisesRegex(ValueError, 'body guard mismatch'):
                actor.validate_original(self.original, expected_sha256=self.sha)
        self.assertEqual(self.original, fixture())

    def test_call_offset_and_call_bytes_are_independently_guarded(self):
        for change in (dict(offset=0x517), dict(before='e800000000')):
            with self.subTest(change=change), self.admitted_fixture(), patch.object(
                    actor, 'CALL_HOOKS', [dict(self.hooks[0], **change)]):
                with self.assertRaisesRegex(ValueError, 'call guard/mapping mismatch'):
                    actor.validate_original(self.original, expected_sha256=self.sha)

    def test_truncated_headers_are_value_errors(self):
        for length in (0, 0x3f, 0x83, 0x97, 0x187, 0x1d7):
            with self.subTest(length=length), self.assertRaises(ValueError):
                actor.rva_to_offset(self.original[:length], 0x1003, 4)

    def test_malformed_headers_sections_and_overflow_are_rejected(self):
        mutations = (
            (0, '<H', 0), (0x3c, '<I', 0xfffffff0),
            (0x84, '<H', 0x14c), (0x86, '<H', 0), (0x86, '<H', 97),
            (0x94, '<H', 111), (0x98, '<H', 0x10b),
            (0x98 + 60, '<I', 0x1d7), (0x98 + 60, '<I', 0x701),
            (0x188 + 12, '<I', 0x100),   # Virtual section overlaps headers.
            (0x188 + 20, '<I', 0x100),   # Raw section overlaps headers.
            (0x188 + 20, '<I', 0x680),   # Raw section goes beyond EOF.
            (0x1b0 + 20, '<I', 0x280),   # Raw sections overlap.
            (0x1b0 + 12, '<I', 0x1080),  # Virtual sections overlap.
            (0x1b0 + 12, '<I', 0xfffffff0),
        )
        for offset, fmt, value in mutations:
            data = bytearray(self.original)
            struct.pack_into(fmt, data, offset, value)
            with self.subTest(offset=offset, value=value), self.assertRaises(ValueError):
                actor.rva_to_offset(bytes(data), 0x1003, 4)

    def test_movement_requires_worker_and_community_before_pe_processing(self):
        for worker, community in ((False, False), (False, True), (True, False)):
            with self.subTest(worker=worker, community=community):
                with self.assertRaisesRegex(ValueError, 'requires prediction_worker=True and community=True'):
                    patch_client.build_patch(b'', prediction_worker=worker,
                                             community=community, prediction_movement=True)

    def test_optional_guard_is_run_before_any_patch_transformation(self):
        with patch.object(patch_client, 'digest', return_value=patch_client.ORIGINAL_SHA256), \
                patch.object(actor, 'validate_original', side_effect=ValueError('owned guard failure')) as guard, \
                patch.object(patch_client.telemetry, 'patch_component') as transform:
            with self.assertRaisesRegex(ValueError, 'owned guard failure'):
                patch_client.build_patch(self.original, prediction_worker=True,
                                         community=True, prediction_movement=True)
            guard.assert_called_once_with(self.original, expected_sha256=patch_client.ORIGINAL_SHA256)
            transform.assert_not_called()

    def test_default_does_not_enter_optional_guard(self):
        with patch.object(actor, 'validate_original') as guard:
            with self.assertRaisesRegex(ValueError, 'Original build SHA256'):
                patch_client.build_patch(b'')
            guard.assert_not_called()

    def test_group_release_declines_only_the_original_complete_typed_remove_call(self):
        hooks = [row for row in actor.CALL_HOOKS
                 if row['name'] == 'OfflinePredictionGroupReleaseRemove']
        self.assertEqual(len(hooks), 1)
        hook = hooks[0]
        self.assertEqual(hook, dict(name='OfflinePredictionGroupReleaseRemove',
                                   rva=0x3ea625a, offset=0x3ea485a,
                                   before='e8b103dcff'))
        call = bytes.fromhex(hook['before'])
        self.assertEqual(hook['rva'] + 5 + struct.unpack_from('<i', call, 1)[0],
                         0x3c66610)
        guards = {row['rva']: row['before'] for row in actor.BODY_GUARDS}
        # The first original operation removes the tracking marker. The shim
        # replaces only the subsequent complete UnitSelectionSet.Remove.
        self.assertEqual(guards[0x3ea6236],
                         '8b974c0100004533c0e82cc38dff498b4d20'
                         '4885c90f84f40000008b974c0100004533c0')
        self.assertEqual(guards[0x3ea625f], 'eb660fb7c84803c9')
        self.assertIn(0x3c66610, guards)
        self.assertEqual(guards[0x3b02170],
                         '807910007511488b01488b909001000048ffa088010000c6411201c3')
        self.assertNotIn(0x3ea5c56, {row['rva'] for row in actor.CALL_HOOKS})

    def test_group_release_descriptor_rejects_mutated_call_before_publication(self):
        original_hook = next(row for row in actor.CALL_HOOKS
                             if row['name'] == 'OfflinePredictionGroupReleaseRemove')
        hook = dict(original_hook, rva=0x4018, offset=0x518)
        data = bytearray(self.original)
        data[0x518:0x51d] = bytes.fromhex(hook['before'])
        data = bytes(data)
        sha = hashlib.sha256(data).hexdigest()
        with self.admitted_fixture(), patch.object(actor, 'SUPPORTED_ORIGINAL_SHA256', sha), \
                patch.object(actor, 'CALL_HOOKS', [hook]):
            self.assertEqual(actor.validate_original(data, expected_sha256=sha)['call_hooks'], [hook])
            for mismatch in (dict(offset=0x519), dict(before='e8b003dcff')):
                with self.subTest(mismatch=mismatch), patch.object(actor, 'CALL_HOOKS',
                                                                  [dict(hook, **mismatch)]):
                    with self.assertRaisesRegex(ValueError, 'call guard/mapping mismatch'):
                        actor.validate_original(data, expected_sha256=sha)

    def test_visual_join_is_only_the_original_final_step_call(self):
        hooks = [h for h in actor.CALL_HOOKS if h['name'] == 'OfflinePredictionVisualJoin']
        self.assertEqual(hooks, [dict(name='OfflinePredictionVisualJoin', rva=0x3c563cf,
                                      offset=0x3c549cf, before='e86cfcffff')])
        call = bytes.fromhex(hooks[0]['before'])
        self.assertEqual(hooks[0]['rva'] + 5 + struct.unpack_from('<i', call, 1)[0], 0x3c56040)
        guards = {g['rva']: g['before'] for g in actor.BODY_GUARDS}
        self.assertEqual(guards[0x3c563be], '85db74303bde0f851808000033d2488bcf')
        self.assertEqual(guards[0x3c563d4], '488b4f104885c90f842c080000')
        self.assertEqual(guards[0x3c56040], '48895c2408574883ec204883b9a800000000488bd97431')
        for ordinary in (patch_client.CALL_HOOKS, patch_client.COMMUNITY_CALL_HOOKS,
                         patch_client.COSMETIC_CALL_HOOKS, patch_client.QUIT_CALL_HOOKS):
            self.assertNotIn('OfflinePredictionVisualJoin', [h['name'] for h in ordinary])

    def test_visual_join_wrong_call_mapping_or_body_refuses_admission(self):
        selected = next(h for h in actor.CALL_HOOKS if h['name'] == 'OfflinePredictionVisualJoin')
        hook = dict(selected, rva=0x4018, offset=0x518)
        guards = {g['rva']: g['before'] for g in actor.BODY_GUARDS}
        body = [dict(rva=target, before=guards[source]) for source, target in
                ((0x3c563be, 0x1003), (0x3c563d4, 0x1030), (0x3c56040, 0x4100))]
        data = bytearray(self.original)
        data[0x518:0x51d] = bytes.fromhex(hook['before'])
        for guard in body:
            raw = bytes.fromhex(guard['before']); at = actor.rva_to_offset(data, guard['rva'], len(raw))
            data[at:at+len(raw)] = raw
        original = bytes(data); sha = hashlib.sha256(original).hexdigest()
        with self.admitted_fixture(), patch.object(actor, 'SUPPORTED_ORIGINAL_SHA256', sha), \
                patch.object(actor, 'CALL_HOOKS', [hook]), patch.object(actor, 'BODY_GUARDS', body):
            self.assertEqual(actor.validate_original(original, expected_sha256=sha)['call_hooks'], [hook])
            for change in (dict(offset=0x519), dict(before='e86dfcffff')):
                with self.subTest(change=change), patch.object(actor, 'CALL_HOOKS', [dict(hook, **change)]):
                    with self.assertRaisesRegex(ValueError, 'call guard/mapping mismatch'):
                        actor.validate_original(original, expected_sha256=sha)
            for guard in body:
                changed = bytearray(original); at = actor.rva_to_offset(changed, guard['rva'], 1)
                changed[at] ^= 1; changed = bytes(changed); changed_sha = hashlib.sha256(changed).hexdigest()
                with self.subTest(body=guard['rva']), patch.object(actor, 'SUPPORTED_ORIGINAL_SHA256', changed_sha):
                    with self.assertRaisesRegex(ValueError, 'body guard mismatch'):
                        actor.validate_original(changed, expected_sha256=changed_sha)

    def test_visual_join_patch_requires_movement_and_leaves_other_paths_untouched(self):
        selected = next(h for h in actor.CALL_HOOKS if h['name'] == 'OfflinePredictionVisualJoin')
        hook = dict(selected, rva=0x4018, offset=0x518)
        original = bytearray(self.original); original[0x518:0x51d] = bytes.fromhex(hook['before'])
        original = bytes(original); sha = hashlib.sha256(original).hexdigest()

        def imports(data, dll, exports, *, thunk_exports):
            self.assertEqual(dll, 'BattleAcesOffline.dll'); self.assertEqual(exports, thunk_exports)
            return data, {}, {name: 0x8000 for name in exports}

        with self.admitted_fixture() as stack:
            for module, name, value in ((actor, 'SUPPORTED_ORIGINAL_SHA256', sha),
                                        (actor, 'CALL_HOOKS', [hook]),
                                        (patch_client, 'ORIGINAL_SHA256', sha)):
                stack.enter_context(patch.object(module, name, value))
            for name in ('PATCHES', 'HOOKS', 'TAIL_HOOKS', 'CALL_HOOKS', 'COMMUNITY_CALL_HOOKS',
                         'COMMUNITY_TAIL_HOOKS', 'COSMETIC_PATCHES', 'COSMETIC_CALL_HOOKS',
                         'COSMETIC_TAIL_HOOKS', 'QUIT_CALL_HOOKS', 'QUIT_POINTER_HOOKS', 'DLSS_PRIVACY_PATCHES'):
                stack.enter_context(patch.object(patch_client, name, []))
            stack.enter_context(patch.object(patch_client.prediction_worker_patch, 'CALL_HOOKS', []))
            imported = stack.enter_context(patch.object(patch_client, 'extend_imports_with_thunks', side_effect=imports))
            guarded = stack.enter_context(patch.object(actor, 'validate_original', wraps=actor.validate_original))
            ordinary = patch_client.build_patch(original, include_telemetry=False)
            worker = patch_client.build_patch(original, include_telemetry=False, community=True, prediction_worker=True)
            guarded.assert_not_called()
            self.assertEqual(imported.call_args_list[0].args[2], [])
            self.assertEqual(imported.call_args_list[1].args[2], [])
            for data in (ordinary, worker):
                self.assertEqual(data[0x518:0x51d], original[0x518:0x51d])
            movement = patch_client.build_patch(original, include_telemetry=False, community=True,
                                                prediction_worker=True, prediction_movement=True)
            guarded.assert_called_once_with(original, expected_sha256=sha)
            self.assertEqual(imported.call_args.args[2], ['OfflinePredictionVisualJoin'])
            self.assertEqual(movement[0x518], 0xe8)
            self.assertEqual(0x4018 + 5 + struct.unpack_from('<i', movement, 0x519)[0], 0x8000)
        self.assertEqual(original[0x518:0x51d], bytes.fromhex(selected['before']))

    def test_visual_join_pinned_original_admission_when_available(self):
        path = Path(__file__).resolve().parents[2] / 'investigation/original/GameAssembly.dll'
        if not path.is_file():
            self.skipTest('private pinned original DLL is not available')
        original = path.read_bytes(); before = hashlib.sha256(original).hexdigest()
        admitted = actor.validate_original(original, expected_sha256=patch_client.ORIGINAL_SHA256)
        self.assertEqual(before, actor.SUPPORTED_ORIGINAL_SHA256)
        self.assertIn(dict(name='OfflinePredictionVisualJoin', rva=0x3c563cf,
                           offset=0x3c549cf, before='e86cfcffff'), admitted['call_hooks'])
        self.assertEqual(hashlib.sha256(original).hexdigest(), before)


if __name__ == '__main__':
    unittest.main()
