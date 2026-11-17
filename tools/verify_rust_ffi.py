"""Exercise the actual Rust library ABI using only authored public fixtures."""
import argparse
import hashlib
import json
import math
from pathlib import Path

from server.rust_snapshot_decoder import RustSnapshotDecoder, RustDecoderError
from tools import verify_rust_snapshot_decoder as v


def sources():
    return {**v.source_hashes(), **{name:hashlib.sha256((v.ROOT/name).read_bytes()).hexdigest()
            for name in ('server/rust_snapshot_decoder.py', 'server/state_projection.py',
                         'tools/verify_rust_ffi.py', 'tests/test_rust_projection_ffi_verifier.py')}}


COMMON = frozenset(('frame', 'viewer', 'local_alliance', 'canonical_fnv1a64',
                    'raw_sha256', 'byte_count', 'counts', 'resources', 'game_state'))


def verify_projection(decoder):
    """Require ABI-v2 parity on authored bytes with an independent full reference.

    This helper is usable with an actual hash-bound native ELF/PE decoder.
    Legacy summary's deliberately accepted nonfinite fixture remains a legacy
    control; explicit nonfinite statuses are separately checked in every mode.
    """
    v.require(type(decoder.projection_version) is int and decoder.projection_version == 1,
              'projection version1 required; no legacy fallback')
    cases, comparisons, refused, legacy_only = 0, 0, 0, []
    for case in v.fixtures.valid_cases():
        raw, viewer = case['raw'], case['viewer']
        # The original full decoder is the reference; ownership is an independent
        # intersection, never supplied by the implementation under test.
        full = v.decode_snapshot(raw, viewer, include_entities=True)
        if any(not math.isfinite(value) for entity in full['entities'] for value in entity.get('position', ())):
            legacy_only.append(case['name'])
            continue
        v.require(full.keys() == COMMON | {'entities'}, 'reference full schema differs')
        v.require(full['raw_sha256'] == hashlib.sha256(raw).hexdigest() and full['byte_count'] == len(raw),
                  'independent raw SHA256/byte count differs')
        summary = {key: full[key] for key in COMMON}
        ownership = {**summary, 'ownership': [
            {key: entity[key] for key in ('id', 'army', 'type')} for entity in full['entities']
            if 'army' in entity and 'type' in entity]}
        for mode, expected in (('summary', summary), ('full', full), ('ownership', ownership)):
            v.assert_equivalent(decoder.decode(raw, viewer, mode=mode), expected)
            comparisons += 1
        cases += 1
    for case in v.fixtures.json_refusal_cases():
        for mode in ('summary', 'full', 'ownership'):
            try:
                decoder.decode(case['raw'], case['viewer'], mode=mode)
            except RustDecoderError as error:
                # Explicit mode must fail during the native scan (SNAPSHOT=2),
                # rather than merely failing Python/JSON output validation.
                v.require(str(error) == 'Rust snapshot decoder failed, status2',
                          'explicit nonfinite input did not return native SNAPSHOT status2: '+case['name']+'/'+mode)
                refused += 1
            else:
                raise ValueError('projection nonfinite refusal missing: '+case['name']+'/'+mode)
    v.require(cases > 0 and comparisons == cases * 3 and refused == len(v.fixtures.json_refusal_cases()) * 3
              and refused > 0, 'explicit projection controls incomplete')
    return dict(version=1, valid_cases=cases, mode_comparisons=comparisons, nonfinite_refused=refused,
                legacy_only_nonfinite_cases=legacy_only, same_raw_all_nine_common_fields=True)


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--library', required=True, type=Path)
    parser.add_argument('--require-projection', action='store_true',
                        help='also require actual v2 exports/parity and native nonfinite scan refusals')
    args = parser.parse_args(argv)
    path = args.library.resolve()
    before = sources()
    library_sha = hashlib.sha256(path.read_bytes()).hexdigest()
    decoder = RustSnapshotDecoder(path, library_sha)
    projection = verify_projection(decoder) if args.require_projection else None
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
    report = dict(passed=True, valid=valid, refused=refused, ownership_cycles=1000,
                  library_sha256=library_sha, authored_inputs_only=True)
    if args.require_projection:
        report['projection'] = projection
        report.update(source_unchanged=True, library_unchanged=True, source_sha256=before)
    print(json.dumps(report))


if __name__ == '__main__':
    main()
