"""Validate only an original SDK cache-root return in an owned menu run."""
import hashlib
from pathlib import Path
import re


LINE = re.compile(
    r'^\[(\d+)\] TELEMETRY CACHELIVEROOT probe passed: version=1 thread=(\d+) '
    r'originalGetters=3 rootSha256=([0-9a-f]{64}) applicationSha256=([0-9a-f]{64}) '
    r'rootChars=(\d+) applicationChars=(\d+) rootMatchesApplication=1 icallOverride=0 '
    r'cacheInstanceConstructed=0 reportPayloadRead=0 queueEnumeration=0$', re.M)


def _sha(value):
    return hashlib.sha256(value.encode('utf-16le')).hexdigest()


def validate(log, quit_rows, shared_settings):
    path = Path(shared_settings).resolve()
    expected = Path.home() / 'AppData/LocalLow/Uncapped Games/Battle Aces/gameconfig-localuser.toml'
    if path != expected.resolve():
        raise AssertionError('live root requires the real read-only Windows game settings path')
    matches = list(LINE.finditer(log))
    confirms = [row for row in quit_rows if row.get('event') == 'OnConfirm.dispatch']
    if (len(matches) != 1 or log.count('TELEMETRY CACHELIVEROOT probe passed:') != 1 or
            'TELEMETRY CACHELIVEROOT probe failed:' in log or len(confirms) != 1 or
            int(matches[0][1]) > confirms[0]['tick'] or int(matches[0][2]) != confirms[0]['thread'] or
            'TELEMETRY CACHEPATH' in log or 'TELEMETRY CACHESTARTUP' in log):
        raise AssertionError('one original unmodified root return before same-thread Quit required')
    item = matches[0]
    application = str(path.parent)
    candidates = (application, application.replace('\\', '/'))
    if not any(item[4] == _sha(candidate) and item[3] == _sha(candidate + '/Bugsnag') and
               int(item[6]) == len(candidate) and int(item[5]) == len(candidate) + len('/Bugsnag')
               for candidate in candidates):
        raise AssertionError('original getter return differs from canonical Windows game root')
    return dict(passed=True, version=1, thread=int(item[2]), tick=int(item[1]),
                root_sha256=item[3], application_sha256=item[4],
                expected_root=str(path.parent) + '/Bugsnag',
                original_getters=3, root_override=False, queue_enumerated=False,
                payload_read=False, startup_queue_isolation_qualified=False,
                analytics_removal_qualified=False)
