"""Portable player commands; private invite values never enter command arguments."""
import asyncio
import json
import os
from pathlib import Path
import subprocess
import sys
import ssl

from .package_integrity import verify, PackageError, SafeParser

PACKAGE = Path(__file__).resolve().parents[3]


def main(argv=None):
    parser = SafeParser(description=__doc__)
    commands = parser.add_subparsers(dest='command', required=True)
    commands.add_parser('verify', help='verify bundled files')
    for action in ('configure', 'setup-data', 'check'):
        sub = commands.add_parser(action)
        sub.add_argument('--config', type=Path, default=PACKAGE / 'config/client.json')
    sub = commands.add_parser('enroll')
    sub.add_argument('--config', type=Path, default=PACKAGE / 'config/client.json')
    sub.add_argument('--request', type=Path, required=True, help='JSON with public settings and local input paths; never token contents')
    sub = commands.add_parser('ca-fingerprint')
    sub.add_argument('--file', type=Path, required=True)
    sub = commands.add_parser('start', help='start local play with optional server connectivity')
    sub.add_argument('--config', type=Path, default=PACKAGE / 'config/client.json')
    sub.add_argument('--game', type=Path, help='working game folder for first launch')
    for action in ('install', 'restore'):
        sub = commands.add_parser(action)
        sub.add_argument('--game', type=Path, required=True)
        sub.add_argument('--original', type=Path)
        sub.add_argument('--dry-run', action='store_true')
    for action in ('launch', 'practice'):
        sub = commands.add_parser(action)
        sub.add_argument('--config', type=Path, default=PACKAGE / 'config' / ('client.json' if action == 'launch' else 'practice.json'))
    args = parser.parse_args(argv)
    try:
        verify(PACKAGE, 'client')
        if args.command == 'verify':
            print('Client package files verified. This does not verify the game or network.')
            return 0
        if args.command in ('start', 'launch'):
            from client_patch.transport.client import main as start
            arguments = ['--config', str(args.config.resolve())]
            if getattr(args, 'game', None) is not None: arguments.extend(['--game', str(args.game.resolve())])
            return start(arguments, default_game=PACKAGE.parent)
        if args.command in ('setup-data', 'enroll', 'check', 'ca-fingerprint'):
            from client_patch.transport import enrollment
            from client_patch.transport.launcher import read_json, LaunchError
            from server.credentials import CredentialError
            from server.tls_transport import TLSConfigurationError
            from server.admission import AdmissionError
            try:
                if args.command == 'setup-data': result = enrollment.setup_data(args.config)
                elif args.command == 'ca-fingerprint': result = dict(sha256=enrollment.ca_fingerprint(args.file)[1])
                elif args.command == 'enroll': result = enrollment.enroll(read_json(args.request, enrollment.MAX_REQUEST), args.config)
                else: result = asyncio.run(enrollment.check_connection(args.config))
                print(json.dumps(dict(ok=True, result=result)))
                return 0
            except ssl.SSLCertVerificationError:
                message = 'The server certificate did not match the configured trust or server name.'
            except AdmissionError:
                message = 'The server rejected this invite or could not authenticate it. Ask the host to check it.'
            except (enrollment.EnrollmentError, LaunchError, CredentialError, TLSConfigurationError) as error:
                message = str(error)  # These exception types contain authored safe text only.
            except (OSError, ValueError, TimeoutError):
                message = 'The connection or local file operation failed. Check the server address and local files.'
            print(json.dumps(dict(ok=False, error=message)))
            return 1
        if args.command in ('install', 'restore'):
            from client_patch.patcher.patch_client import install
            result = install(args.game, helper=PACKAGE / 'program/client-helper/BattleAcesOffline.dll',
                original_path=args.original, restore=args.command == 'restore', dry_run=args.dry_run, community=True, cosmetics=True)
            print(json.dumps(result, indent=2))
            return 0
        # Windows PowerShell is part of the OS. Use its known system path rather
        # than a PATH executable; no profile, policy change or global Python.
        shell = Path(os.environ.get('SystemRoot', r'C:\Windows')) / 'System32/WindowsPowerShell/v1.0/powershell.exe'
        if args.command == 'configure':
            script = PACKAGE / 'program/app/client_patch/launcher/Configure-Client.ps1'
            return subprocess.run([str(shell), '-NoProfile', '-STA', '-File', str(script),
                '-PythonExecutable', sys.executable, '-ConfigPath', str(args.config.resolve())], check=False).returncode
        script = PACKAGE / 'program/app/client_patch/launcher/Launch-Client.ps1'
        return subprocess.run([str(shell), '-NoProfile', '-File', str(script),
            '-OfflinePractice', '-Config', str(args.config.resolve())], check=False).returncode
    except (OSError, ValueError, PackageError):
        print('Client command failed: verify package files, config and supported game installation. See QUICKSTART.txt.', file=sys.stderr)
        return 1


if __name__ == '__main__': raise SystemExit(main())
