"""Portable player commands; private invite values never enter command arguments."""
import json
import os
from pathlib import Path
import subprocess
import sys

from .package_integrity import verify, PackageError, SafeParser

PACKAGE = Path(__file__).resolve().parents[3]


def main(argv=None):
    parser = SafeParser(description=__doc__)
    commands = parser.add_subparsers(dest='command', required=True)
    commands.add_parser('verify', help='verify bundled files')
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
        if args.command in ('install', 'restore'):
            from client_patch.patcher.patch_client import install
            result = install(args.game, helper=PACKAGE / 'program/client-helper/BattleAcesOffline.dll',
                original_path=args.original, restore=args.command == 'restore', dry_run=args.dry_run, community=True)
            print(json.dumps(result, indent=2))
            return 0
        if args.command == 'launch':
            from client_patch.transport.launcher import main as launch
            return launch(['--config', str(args.config.resolve()), '--community-experimental'])
        # Windows PowerShell is part of the OS. Use its known system path rather
        # than a PATH executable; no profile, policy change or global Python.
        shell = Path(os.environ.get('SystemRoot', r'C:\Windows')) / 'System32/WindowsPowerShell/v1.0/powershell.exe'
        script = PACKAGE / 'program/app/client_patch/launcher/Launch-Client.ps1'
        return subprocess.run([str(shell), '-NoProfile', '-File', str(script),
            '-OfflinePractice', '-Config', str(args.config.resolve())], check=False).returncode
    except (OSError, ValueError, PackageError):
        print('Client command failed: verify package files, config and supported game installation. See QUICKSTART.txt.', file=sys.stderr)
        return 1


if __name__ == '__main__': raise SystemExit(main())
