import unittest

from tools.verify_postcheck_content import refusal_lines, last_event_state


class ReadFailureEvidenceTests(unittest.TestCase):
    def setUp(self):
        self.target = r'C:\owned\game\StreamingAssets\selected.bundle'

    def test_original_open_failure_binds_the_complete_target(self):
        line = 'Unable to open archive file: '+self.target
        self.assertEqual(refusal_lines(line, self.target), [line])

    def test_windows_case_and_separator_variants(self):
        line = 'Failed to open C:/OWNED/GAME/StreamingAssets/selected.bundle'
        self.assertEqual(refusal_lines(line, self.target), [line])

    def test_unrelated_file_failure_does_not_release_control(self):
        text = 'Unable to open archive file: C:/elsewhere/selected.bundle'
        self.assertEqual(refusal_lines(text, self.target), [])

    def test_successful_load_is_not_a_failure(self):
        self.assertEqual(refusal_lines('Loaded '+self.target, self.target), [])

    def test_failure_and_target_on_different_lines_are_insufficient(self):
        text = 'Failed to open some other file\nLoaded '+self.target
        self.assertEqual(refusal_lines(text, self.target), [])

    def test_partial_append_retains_previous_complete_state(self):
        raw = b'{"state":{"lock_released":false}}\n{"state":{"lock_released":'
        self.assertEqual(last_event_state(raw), {'lock_released': False})
        self.assertEqual(last_event_state(b'{"state":'), {})
        self.assertEqual(last_event_state(raw+b'true}}\n'), {'lock_released': True})


if __name__ == '__main__':
    unittest.main()
