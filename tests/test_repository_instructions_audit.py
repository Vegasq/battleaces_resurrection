import unittest

from tools.audit_repository import inspect_content


class RepositoryInstructionsAuditTests(unittest.TestCase):
    def test_project_instructions_are_an_allowed_root_document(self):
        self.assertEqual(inspect_content('AGENTS.md', b'# Project instructions\nRead DEV.txt.\n'), [])

    def test_instruction_allowlist_keeps_binary_checks(self):
        self.assertIn('binary or archive content', inspect_content('AGENTS.md', b'MZpayload'))

    def test_instruction_allowlist_keeps_absolute_path_checks(self):
        self.assertIn('developer-specific absolute path',
                      inspect_content('AGENTS.md', b'E:' + bytes([92]) + b'games' + bytes([92]) + b'local'))

    def test_personal_worksheet_and_other_root_files_remain_outside_allowlist(self):
        for path in ('DEV.txt', 'NICK.txt', 'OTHER.md'):
            with self.subTest(path=path):
                self.assertIn('not an allowed source/documentation path', inspect_content(path, b'local worksheet'))


if __name__ == '__main__':
    unittest.main()
