import hashlib
from pathlib import Path
import unittest

from tools.telemetry_cache_live_root_evidence import validate


class LiveRootEvidenceTests(unittest.TestCase):
    def test_exact_return_and_original_quit_boundary(self):
        settings = Path.home() / 'AppData/LocalLow/Uncapped Games/Battle Aces/gameconfig-localuser.toml'
        application = str(settings.parent)
        digest = lambda value: hashlib.sha256(value.encode('utf-16le')).hexdigest()
        line = (f'[100] TELEMETRY CACHELIVEROOT probe passed: version=1 thread=17 originalGetters=3 '
                f'rootSha256={digest(application + "/Bugsnag")} applicationSha256={digest(application)} '
                f'rootChars={len(application) + len("/Bugsnag")} applicationChars={len(application)} '
                'rootMatchesApplication=1 icallOverride=0 cacheInstanceConstructed=0 '
                'reportPayloadRead=0 queueEnumeration=0')
        rows = [dict(event='OnConfirm.dispatch', tick=110, thread=17)]
        result = validate(line, rows, settings)
        self.assertFalse(result['startup_queue_isolation_qualified'])
        self.assertFalse(result['analytics_removal_qualified'])
        failures = (line.replace('rootSha256=', 'rootSha256=' + '0' * 64 + ' '),
                    line.replace('icallOverride=0', 'icallOverride=1'),
                    line.replace('queueEnumeration=0', 'queueEnumeration=1'),
                    line + '\n' + line,
                    line + '\nTELEMETRY CACHELIVEROOT probe failed: injected')
        for text in failures:
            with self.subTest(text=text[:100]), self.assertRaises(AssertionError):
                validate(text, rows, settings)
        with self.assertRaises(AssertionError):
            validate(line, rows, settings.parent / 'other.toml')
        with self.assertRaises(AssertionError):
            validate(line, [dict(event='OnConfirm.dispatch', tick=99, thread=17)], settings)
