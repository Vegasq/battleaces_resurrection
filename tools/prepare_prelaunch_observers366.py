"""Prepare passive native observers for an owned suspended packaged run."""
from __future__ import annotations

import argparse
import hashlib
import json
import secrets
from pathlib import Path

from tools.frida_attribution_source import build_source
from tools.frida_prelaunch_exit367 import build_source as build_exit_source
from tools.frida_prelaunch_socket_exit370 import build_source as build_socket_exit_source
from tools.frida_resolved_file_source371 import build_source as build_resolved_source
from tools.frida_preexisting_file_source372 import build_source as build_existing_file_source
from tools.frida_unresolved_file_status373 import build_source as build_unresolved_status_source
from tools.frida_sdk_send408 import build_source as build_sdk_send_source
from tools.frida_sdk_queue440 import build_source as build_sdk_queue_source
from tools.frida_device_io410 import build_source as build_device_io_source
from tools.frida_state3_entry427 import build_source as build_state3_source

ROOT = Path(__file__).resolve().parents[1]


def sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--game', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--exit-boundary', action='store_true')
    parser.add_argument('--socket-handles', action='store_true')
    parser.add_argument('--resolve-roots', action='store_true')
    parser.add_argument('--resolve-existing-files', action='store_true')
    parser.add_argument('--unresolved-file-status', action='store_true')
    parser.add_argument('--sdk-send', action='store_true')
    parser.add_argument('--sdk-queue', action='store_true')
    parser.add_argument('--device-io', action='store_true')
    parser.add_argument('--state3-entry', action='store_true')
    parser.add_argument('--clients', type=int, choices=(1, 2, 4), default=2)
    args = parser.parse_args()
    game, output = args.game.resolve(), args.output.resolve()
    assert game.is_relative_to(ROOT/'local') and output.is_relative_to(ROOT/'local')
    assert game.name == 'Battle Aces.exe' and game.is_file()
    assert output.is_dir() and not any(output.iterdir())
    assert not args.socket_handles or args.exit_boundary
    assert not args.resolve_roots or (args.socket_handles and args.exit_boundary)
    assert not args.resolve_existing_files or args.resolve_roots
    assert not args.unresolved_file_status or args.resolve_existing_files
    assert not args.sdk_send or args.unresolved_file_status
    assert not args.sdk_queue or args.unresolved_file_status
    assert not args.device_io or args.unresolved_file_status
    assert not (args.sdk_send and args.device_io)
    assert not args.state3_entry or args.unresolved_file_status
    assert sum((args.sdk_send, args.sdk_queue, args.device_io, args.state3_entry)) <= 1
    sdk = Path.home()/'AppData/LocalLow/Uncapped Games/Battle Aces/Bugsnag'
    for index in range(args.clients):
        config = dict(image=str(game), runId=secrets.token_hex(16),
                      fileRoots=[str(sdk)], eventLimit=4096)
        source = (build_state3_source(config) if args.state3_entry else
                  build_device_io_source(config) if args.device_io else
                  build_sdk_send_source(config) if args.sdk_send else
                  build_sdk_queue_source(config) if args.sdk_queue else
                  build_unresolved_status_source(config) if args.unresolved_file_status else
                  build_existing_file_source(config) if args.resolve_existing_files else
                  build_resolved_source(config) if args.resolve_roots else
                  build_socket_exit_source(config) if args.socket_handles else
                  build_exit_source(config) if args.exit_boundary else build_source(config))
        source_path = output/f'observer-{index}.js'
        source_path.write_text(source, encoding='utf-8')
        (output/f'config-{index}.json').write_text(json.dumps(dict(config=config,
            source_sha256=sha(source_path), game_sha256=sha(game),
            exit_boundary=args.exit_boundary, socket_handles=args.socket_handles,
            resolve_roots=args.resolve_roots,
            resolve_existing_files=args.resolve_existing_files,
            unresolved_file_status=args.unresolved_file_status,
            sdk_send=args.sdk_send, sdk_queue=args.sdk_queue, device_io=args.device_io,
            state3_entry=args.state3_entry), indent=2)+'\n',
            encoding='utf-8')
    print(json.dumps({'prepared': True, 'output': str(output)}))


if __name__ == '__main__':
    main()
