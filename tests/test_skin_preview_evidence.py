import copy
import unittest

from tools.verify_skin_previews import validate_cases, failed_return_can_quit, validate_pool_cases


class SkinPreviewEvidenceTests(unittest.TestCase):
    def setUp(self):
        self.expected = {1000+i: 2000+i for i in range(13)}
        rows = [dict(index=i, item=item, expected_event=event, unit_type=99,
                     preview_events=[event], unit_base_events=[9], loaded_event_count=2, registered_event_count=2,
                     prior_unit_active=False, pooled_unit_reused=False)
                for i, (item, event) in enumerate(self.expected.items())]
        rows.append(dict(rows[0], index=13))
        self.proof = dict(runtime_observations_complete=True, visual_review_complete=False,
                          loadout_unchanged=True, cases=rows)
        self.returned = dict(original_back=True, loadout_unchanged=True,
                             scene_active_after_back=False, unit_active_after_back=False)

    def test_complete_contract_and_pool_reuse(self):
        validate_cases(self.proof, self.returned, self.expected)
        self.proof['cases'][1].update(prior_unit_active=True, pooled_unit_reused=True)
        validate_cases(self.proof, self.returned, self.expected)

    def test_missing_or_duplicate_skin_rejected(self):
        for change in ('missing', 'duplicate', 'wrong_return'):
            with self.subTest(change=change):
                proof = copy.deepcopy(self.proof)
                if change == 'missing': proof['cases'].pop(3)
                elif change == 'duplicate': proof['cases'][3]['item'] = proof['cases'][2]['item']
                else: proof['cases'][-1]['item'] = proof['cases'][1]['item']
                with self.assertRaises(AssertionError): validate_cases(proof, self.returned, self.expected)

    def test_unapplied_stale_event_or_unreleased_unit_rejected(self):
        for changes in ({'registered_event_count': 1}, {'loaded_event_count': 0}, {'preview_events': [9]},
                        {'expected_event': 9}, {'prior_unit_active': True}):
            with self.subTest(changes=changes):
                proof = copy.deepcopy(self.proof)
                proof['cases'][2].update(changes)
                with self.assertRaises(AssertionError): validate_cases(proof, self.returned, self.expected)

    def test_back_must_release_and_preserve_loadout(self):
        for field in self.returned:
            with self.subTest(field=field):
                returned = dict(self.returned)
                returned[field] = not returned[field]
                with self.assertRaises(AssertionError): validate_cases(self.proof, returned, self.expected)

    def test_native_evidence_cannot_assert_visual_review(self):
        self.proof['visual_review_complete'] = True
        with self.assertRaises(AssertionError): validate_cases(self.proof, self.returned, self.expected)

    def test_failed_back_cleanup_does_not_accept_active_unit(self):
        returned = dict(self.returned, unit_active_after_back=True)
        self.assertTrue(failed_return_can_quit('SKIN PREVIEW failed: cleanup', returned))
        with self.assertRaises(AssertionError): validate_cases(self.proof, returned, self.expected)
        self.assertFalse(failed_return_can_quit('SKIN PREVIEW failed:', dict(returned, scene_active_after_back=True)))
        self.assertFalse(failed_return_can_quit('SKIN PREVIEW failed:', dict(returned, original_back=False)))
        self.assertFalse(failed_return_can_quit('', returned))

    def pool_fixture(self):
        proof = copy.deepcopy(self.proof)
        proof['cases'] = proof['cases'][:3]+[dict(proof['cases'][0], index=3)]
        for i, row in enumerate(proof['cases']):
            unit = 10+(i if i < 3 else 0)
            row.update(current_pool=dict(unit_instance=unit, count_all=1, count_available=0,
                available_contains_unit=False, created_tracker_present=True, created_tracker_contains_unit=True,
                active_in_hierarchy=True), previous_pool=None if i == 0 else dict(available_contains_unit=True),
                first_unit_reused=i == 3)
        returned = dict(self.returned, unit_active_after_back=True, renderer_unit_cleared=True,
                        returned_to_available_pool=True, pool=dict(available_contains_unit=True))
        families = {1000: 'core', 1001: 'expansion', 1002: 'worker'}
        return proof, returned, families

    def test_available_active_pool_object_is_not_a_leak(self):
        proof, returned, families = self.pool_fixture()
        validate_pool_cases(proof, returned, self.expected, families)

    def test_pool_check_rejects_missing_return_or_fake_reuse(self):
        for failure in ['previous', 'renderer', 'returned', 'reuse', 'current']:
            proof, returned, families = self.pool_fixture()
            if failure == 'previous': proof['cases'][1]['previous_pool']['available_contains_unit'] = False
            elif failure == 'renderer': returned['renderer_unit_cleared'] = False
            elif failure == 'returned': returned['returned_to_available_pool'] = False
            elif failure == 'reuse': proof['cases'][-1]['current_pool']['unit_instance'] = 999
            else: proof['cases'][0]['current_pool']['available_contains_unit'] = True
            with self.subTest(failure=failure), self.assertRaises(AssertionError):
                validate_pool_cases(proof, returned, self.expected, families)


if __name__ == '__main__':
    unittest.main()
