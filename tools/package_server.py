"""Portable host entry points, always resolving defaults from the package."""
import argparse
import json
from pathlib import Path
import sys

from .package_integrity import verify, PackageError, SafeParser

PACKAGE = Path(__file__).resolve().parents[3]


def main(argv=None):
    parser = SafeParser(description=__doc__)
    commands = parser.add_subparsers(dest='command', required=True)
    commands.add_parser('verify', help='verify immutable bundled files, not imported game assets')
    sub = commands.add_parser('service-command', help='print registration settings; does not install or start a service')
    sub.add_argument('--config', type=Path, default=PACKAGE / 'config/host.json')
    sub.add_argument('--name', default='BattleAcesResurrection')
    for action in ('start', 'check'):
        sub = commands.add_parser(action)
        sub.add_argument('--config', type=Path, default=PACKAGE / 'config/host.json')
    for action in ('backup', 'verify-backup', 'restore'):
        sub = commands.add_parser(action)
        sub.add_argument('--config', type=Path, default=PACKAGE / 'config/host.json')
        if action == 'backup': sub.add_argument('--out', type=Path, required=True)
        else: sub.add_argument('--input', type=Path, required=True)
        if action == 'restore': sub.add_argument('--destination', type=Path, required=True)
    sub = commands.add_parser('import-assets')
    sub.add_argument('--game-dir', type=Path, required=True)
    sub.add_argument('--export-dir', type=Path, required=True)
    sub.add_argument('--original', type=Path)
    sub.add_argument('--destination', type=Path, default=PACKAGE / 'assets/build-37822')
    sub = commands.add_parser('credentials')
    sub.add_argument('--store', type=Path, default=PACKAGE / 'data/private/credentials')
    sub.add_argument('arguments', nargs=argparse.REMAINDER)
    args = parser.parse_args(argv)
    try:
        verify(PACKAGE, 'server')
        if args.command == 'verify':
            print('Server package files verified. Imported assets are checked by the check/start commands.')
            return 0
        if args.command == 'service-command':
            from server.windows_service import registration
            print(json.dumps(registration(PACKAGE, args.config, args.name), indent=2))
            return 0
        if args.command in ('start', 'check'):
            if args.command == 'start' and not args.config.exists():
                from server.rc_host import initialize
                initialize(args.config, PACKAGE / 'assets/build-37822')
            from server.host import main as host
            return host(['--config', str(args.config.resolve())] + (['--check'] if args.command == 'check' else []))
        if args.command == 'credentials':
            from server.credentials import main as credentials
            return credentials(['--store', str(args.store.resolve()), *args.arguments])
        if args.command in ('backup', 'verify-backup', 'restore'):
            from server.state_backup import main as maintenance
            arguments = [args.command, '--config', str(args.config.resolve())]
            if args.command == 'backup': arguments.extend(['--out', str(args.out.resolve())])
            else: arguments.extend(['--input', str(args.input.resolve())])
            if args.command == 'restore': arguments.extend(['--destination', str(args.destination.resolve())])
            return maintenance(arguments)
        from tools.import_assets import import_assets
        result = import_assets(args.game_dir, args.export_dir, args.destination, args.original)
        print(f"Imported build{result['game_build']}: {result['playable_units']} playable units; local files only.")
        return 0
    except (OSError, ValueError, PackageError):
        print('Server command failed: verify package files and local source assets. See QUICKSTART.txt.', file=sys.stderr)
        return 1


if __name__ == '__main__': raise SystemExit(main())
