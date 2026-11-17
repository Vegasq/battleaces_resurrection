"""Exercise the actual Rust library ABI using only authored public fixtures."""
import argparse
import hashlib
import json
from pathlib import Path

from server.rust_snapshot_decoder import RustSnapshotDecoder
from tools import verify_rust_snapshot_decoder as v


def sources():
    return {**v.source_hashes(), **{name:hashlib.sha256((v.ROOT/name).read_bytes()).hexdigest()
            for name in ('server/rust_snapshot_decoder.py', 'tools/verify_rust_ffi.py')}}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--library', required=True, type=Path)
    args = parser.parse_args()
    path = args.library.resolve()
    before = sources()
    library_sha = hashlib.sha256(path.read_bytes()).hexdigest()
    decoder = RustSnapshotDecoder(path, library_sha)
    valid, refused = 0, 0
    for case in v.fixtures.valid_cases():
        v.assert_equivalent(decoder.decode(case['raw'], case['viewer'], include_entities=case['include_entities']),
                            v.decode_snapshot(case['raw'], case['viewer'], include_entities=case['include_entities']))
        valid += 1
    for case in v.fixtures.invalid_cases()+v.fixtures.json_refusal_cases():
        try:
            decoder.decode(case['raw'], case['viewer'], include_entities=case['include_entities'])
        except (ValueError, RuntimeError):
            refused += 1
        else:
            raise ValueError('FFI refusal missing: '+case['name'])
    # Exercise repeated allocation/free and successful recovery after all refusals.
    raw = v.fixtures.make_snapshot(8)
    expected = v.decode_snapshot(raw, 31, include_entities=True)
    for _ in range(1000):
        v.assert_equivalent(decoder.decode(raw, 31, include_entities=True), expected)
    v.require(before == sources() and library_sha == hashlib.sha256(path.read_bytes()).hexdigest(),
              'source/library changed')
    print(json.dumps(dict(passed=True, valid=valid, refused=refused, ownership_cycles=1000,
                          library_sha256=library_sha, authored_inputs_only=True)))


if __name__ == '__main__':
    main()
