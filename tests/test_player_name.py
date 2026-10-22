import unittest
from unittest import mock
from client_patch.transport import client, player_name


CASES = [
    ('DOMAIN\\nick.smith@example.com', 'nick.smith'),
    ('  __Night-Rider__  ', 'Night-Rider'),
    ('Jane\t  Doe\n', 'Jane Doe'),
    ('Bad"Name/Here\x00', 'Bad Name Here'),
    ('Zo\u0065\u0308 東京 ١٢', 'Zoë 東京 ١٢'),
    ('Alpha\u200bBeta', 'Alpha Beta'),
    ('A'*40, 'A'*32),
    ('\U00010400'*40, '\U00010400'*32),
    ('😀', 'Player'),
    ('---___...  ', 'Player'),
    (None, 'Player'),
]


class PlayerNameTests(unittest.TestCase):
    def test_account_cleanup_and_limits(self):
        for raw, expected in CASES:
            with self.subTest(raw=raw): self.assertEqual(player_name.clean_account_name(raw), expected)

    def test_default_is_computed_on_the_running_player_pc(self):
        with mock.patch.object(player_name.getpass,'getuser',return_value='OFFICE\\Local Pilot'):
            self.assertEqual(client.defaults('.')['display_name'],'Local Pilot')
        with mock.patch.object(player_name.getpass,'getuser',return_value='Other Pilot'):
            self.assertEqual(client.defaults('.')['display_name'],'Other Pilot')
        with mock.patch.object(player_name.getpass,'getuser',side_effect=OSError):
            self.assertEqual(player_name.default_name(),'Player')

    def test_player_choice_is_validated_without_account_name_cleanup(self):
        self.assertEqual(player_name.chosen_name('My @ Handle 🚀'),'My @ Handle 🚀')
        for name in ('',' '*3,'x'*33,'bad"name','bad\\name','bad\nname','\ud800'):
            with self.subTest(name=name), self.assertRaises(ValueError): player_name.chosen_name(name)
