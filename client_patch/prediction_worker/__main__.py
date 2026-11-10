"""Ordered stdio entry point; no additional threads or implicit game launch."""
from __future__ import annotations

import argparse
from pathlib import Path
import sys

from . import wire as w
from .native import NativeSession


def _position_trace_spec(value):
    """Validate diagnostic input before stdout isolation or a native DLL load."""
    from .observation import parse_position_trace_spec
    try:
        return parse_position_trace_spec(value)
    except ValueError as error:
        raise argparse.ArgumentTypeError(str(error)) from error


def run_streams(source, sink, backend):
    """Synthetic tests inject streams/backend; product supplies original DLLs."""
    expected, closed = 1, False
    packet = None

    def close():
        nonlocal closed
        if not closed:
            closed = True
            backend.close()

    try:
        while True:
            packet = None
            item = w.read_request(source, expected)
            if item is None:
                close()
                return 0
            packet, command = item
            result, data = backend.dispatch(command)
            if command.opcode == w.Op.SHUTDOWN:
                close()
            logs = backend.drain_logs()
            w.write_packet(sink, w.encode_response(packet, result, data, logs))
            if command.opcode == w.Op.SHUTDOWN:
                return 0
            expected += 1
    except Exception as error:
        if packet is None and isinstance(error, w.ProtocolError) and error.opcode is not None:
            packet = w.Packet(error.opcode, error.request_id, b'')
        try:
            close()
        except Exception as cleanup:
            error = RuntimeError(str(error) + '; cleanup: ' + str(cleanup))
        if packet is not None:
            try:
                w.write_packet(sink, w.encode_response(packet, -1, w.error_data(error), backend.drain_logs(), error=True))
            except Exception:
                pass  # Broken pipe: native cleanup still ran, no retry/mutation.
        return 1
    finally:
        if not closed:
            close()


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--original-dll', required=True)
    parser.add_argument('--heap-helper', required=True)
    parser.add_argument('--cooperative', required=True)
    parser.add_argument('--data-dir', required=True)
    parser.add_argument('--movement-observe', action='store_true',
                        help='explicit diagnostic-only confirmed Spectator31 state journal')
    parser.add_argument('--movement-observe-position', type=_position_trace_spec,
                        metavar='ID:TYPE:ARMY:FIRST:LAST',
                        help='diagnostic-only native position copies from the existing state query; requires --movement-observe')
    args = parser.parse_args(argv)
    if args.movement_observe_position is not None and not args.movement_observe:
        parser.error('--movement-observe-position requires --movement-observe')
    # Preserve the private protocol pipe before any DLL initializer/CRT output.
    from server.simulation_worker import isolate_protocol_stdout
    sink = isolate_protocol_stdout()
    session = None
    try:
        observation_path = Path(args.data_dir).resolve() / 'canonical-state.jsonl' if args.movement_observe else None
        session = NativeSession.open(original_dll=args.original_dll, heap_helper=args.heap_helper,
                                     cooperative=args.cooperative, data_dir=args.data_dir)
        if observation_path is not None:
            if args.movement_observe_position is None:
                session.enable_movement_observation(observation_path)
            else:
                session.enable_movement_observation(observation_path, position_trace=args.movement_observe_position)
    except Exception as error:
        if session is not None:
            try:session.close()
            except Exception as cleanup:error = RuntimeError(str(error) + '; cleanup: ' + str(cleanup))
        print('Prediction worker startup failed: ' + str(error), file=sys.stderr)
        return 1
    return run_streams(sys.stdin.buffer, sink, session)


if __name__ == '__main__':
    raise SystemExit(main())
