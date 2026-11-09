"""Pure private-worker CRT thread-attach deferral for one exact native image.

No DLL is loaded or written. Only the two eager PTD-initialization CALLs are
replaced; lazy CRT getters, process attach, thread detach and TLS callbacks
retain their original bytes. Runtime parity/lifecycle qualification is separate.
"""
from __future__ import annotations

import copy
import hashlib
import struct

from client_patch.patcher.pe_imports import _require, pe_checksum
from tools.prepare_prediction_native import (
    SUPPORTED_ORIGINAL_SHA256, _Image, _byte_patches, derive_native,
)

ATTACH_RVA = 0x3403AC
ATTACH_BODY = bytes.fromhex(
    '4883ec28e8d733000084c0750432c0eb12e89626020084c07507e8d5330000ebecb0014883c428c3'
)
# Relative to ATTACH_RVA; both original functions return bool tested via AL.
CALLS = ((4, bytes.fromhex('e8d7330000')), (17, bytes.fromhex('e896260200')))
RETURN_TRUE = bytes.fromhex('b801000000')
MAX_IMAGE = 16 * 1024 * 1024


def _sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _original_from_manifest(derived: bytes, manifest: dict) -> bytes:
    """Undo only a bounded, verified byte-patch journal; never trust its hash."""
    _require(isinstance(derived, bytes) and 0 < len(derived) <= MAX_IMAGE,
             'Bounded derived bytes required')
    _require(type(manifest) is dict, 'Derivation manifest must be an object')
    _require(manifest.get('original_sha256') == SUPPORTED_ORIGINAL_SHA256,
             'Unsupported original Simulation.dll SHA256')
    _require(manifest.get('derived_sha256') == _sha(derived),
             'Current derived SHA256 differs from manifest')
    original_size = manifest.get('original_size')
    _require(type(original_size) is int and 0 < original_size <= len(derived) and
             manifest.get('derived_size') == len(derived), 'Invalid derivation sizes')
    patches = manifest.get('byte_patches')
    _require(type(patches) is list and 0 < len(patches) <= 4096,
             'Invalid derivation byte-patch journal')
    original = bytearray(derived[:original_size])
    previous_end = 0
    appended = False
    for patch in patches:
        _require(type(patch) is dict and type(patch.get('offset')) is int,
                 'Invalid derivation patch record')
        offset = patch['offset']
        values = [patch.get(name) for name in ('before_hex', 'after_hex')]
        _require(all(isinstance(value, str) and len(value) <= MAX_IMAGE * 2 for value in values),
                 'Invalid derivation patch hex')
        try:
            before, after = (bytes.fromhex(value) for value in values)
        except ValueError as error:
            raise ValueError('Invalid derivation patch hex') from error
        _require(offset >= previous_end and offset + len(after) <= len(derived) and
                 derived[offset:offset + len(after)] == after,
                 'Derivation patch does not match current image')
        if offset == original_size and not before:
            _require(not appended and offset + len(after) == len(derived),
                     'Invalid appended derivation bytes')
            appended = True
        else:
            _require(len(before) == len(after) > 0 and offset + len(before) <= original_size,
                     'Derivation patches must preserve original offsets')
            original[offset:offset + len(before)] = before
        previous_end = offset + len(after)
    _require(_sha(original) == SUPPORTED_ORIGINAL_SHA256,
             'Reconstructed original SHA256 is unsupported')
    return bytes(original)


def defer_crt_thread_attach(derived: bytes, manifest: dict) -> tuple[bytes, dict]:
    """Return fresh bytes/manifest, or fail without changing either argument.

    Reconstruct the original from the import derivation journal, independently
    require its exact SHA, and reproduce the complete import derivation. This
    rejects unrelated edits even if a caller rewrites the current-image hash.
    The former manifest is retained under ``import_derivation``; its original
    section-preservation claims apply only to that earlier image.
    """
    original = _original_from_manifest(derived, manifest)
    canonical, canonical_manifest = derive_native(original)
    _require(canonical == derived, 'Image differs from exact private import derivation')
    _require(all(manifest.get(key) == value for key, value in canonical_manifest.items()),
             'Import derivation metadata differs from canonical derivation')
    image = _Image(derived)
    checksum_offset = image.opt + 64
    _require(image.u32(checksum_offset) == pe_checksum(derived, checksum_offset),
             'Derived PE checksum is invalid')
    body_offset = image.mapped(ATTACH_RVA, len(ATTACH_BODY))
    _require(derived[body_offset:body_offset + len(ATTACH_BODY)] == ATTACH_BODY,
             'Complete CRT thread-attach body guard differs')
    patches = []
    for relative, expected in CALLS:
        offset = image.mapped(ATTACH_RVA + relative, len(expected))
        _require(derived[offset:offset + len(expected)] == expected,
                 'CRT thread-attach CALL guard differs')
        patches.append(dict(rva=ATTACH_RVA + relative, offset=offset,
                            before_hex=expected.hex(), after_hex=RETURN_TRUE.hex()))
    # All scope, hash and byte guards finish before constructing an output.
    output = bytearray(derived)
    for patch in patches:
        output[patch['offset']:patch['offset'] + len(RETURN_TRUE)] = RETURN_TRUE
    struct.pack_into('<I', output, checksum_offset, pe_checksum(output, checksum_offset))
    result = bytes(output)
    updated = copy.deepcopy(manifest)
    updated['import_derivation'] = copy.deepcopy(manifest)
    updated.update(status='DERIVED_CRT_ATTACH_DEFERRED_NOT_LOADED',
                   derived_sha256=_sha(result), derived_size=len(result),
                   original_sections_preserved=False,
                   crt_thread_attach_deferral=dict(
                       version=1, scope='private experimental worker only',
                       input_sha256=_sha(derived), output_sha256=_sha(result),
                       body_rva=ATTACH_RVA, body_before_hex=ATTACH_BODY.hex(),
                       patches=patches, checksum_offset=checksum_offset,
                       checksum_before=image.u32(checksum_offset),
                       checksum_after=struct.unpack_from('<I', result, checksum_offset)[0],
                       process_attach_unchanged=True, lazy_getters_unchanged=True,
                       runtime_qualified=False),
                   byte_patches=_byte_patches(original, result),
                   loader_qualified=False)
    preserved, modified = [], []
    for section in canonical_manifest['preserved_original_sections']:
        entry = copy.deepcopy(section)
        offset, size = entry['raw_offset'], entry['raw_size']
        final_sha = _sha(result[offset:offset + size])
        if final_sha == entry['sha256']:
            preserved.append(entry)
        else:
            entry['original_sha256'] = entry.pop('sha256')
            entry['derived_sha256'] = final_sha
            modified.append(entry)
    _require(len(modified) == 1, 'Expected exactly one changed original section')
    updated['preserved_original_sections'] = preserved
    updated['modified_original_sections'] = modified
    return result, updated
