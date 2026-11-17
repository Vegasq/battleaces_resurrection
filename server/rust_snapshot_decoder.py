"""Explicit, hash-bound ctypes adapter for the experimental Rust decoder.

There is no library discovery or fallback. The caller owns the decoder's life;
each returned Rust allocation is released before decode returns or raises.
"""
from __future__ import annotations

import ctypes as C
import hashlib
import json
import math
from pathlib import Path
import re

from .native_simulation import RESOURCE_NAMES
from .state_projection import _UNSET, resolve_mode, PROJECTION_VERSION, STATE_MODES

ABI_VERSION = 1
MAX_INPUT = 16 * 1024 * 1024
MAX_OUTPUT = 64 * 1024 * 1024
_HEX64 = re.compile(r"[0-9a-f]{64}\Z")
_HEX16 = re.compile(r"[0-9a-f]{16}\Z")


class RustDecoderError(ValueError):
    """Invalid configuration, ABI output or snapshot; never silently retried."""


class _Buffer(C.Structure):
    _fields_ = [("data", C.POINTER(C.c_uint8)), ("len", C.c_size_t)]


def verified_library_path(library_path, expected_sha256):
    """Validate an explicit local file without loading any executable code."""
    if not isinstance(expected_sha256, str) or not _HEX64.fullmatch(expected_sha256):
        raise RustDecoderError("snapshot decoder requires an expected lowercase SHA256")
    if library_path is None:
        raise RustDecoderError("snapshot decoder requires an explicit absolute library path")
    path = Path(library_path)
    if not path.is_absolute():
        raise RustDecoderError("snapshot decoder library path must be absolute")
    path = path.resolve(strict=True)
    if not path.is_file():
        raise RustDecoderError("snapshot decoder library must be a regular file")
    actual = hashlib.sha256(path.read_bytes()).hexdigest()
    if actual != expected_sha256:
        raise RustDecoderError("snapshot decoder library SHA256 mismatch")
    return path


def _require(condition, message):
    if not condition:
        raise RustDecoderError("invalid Rust decoder output: " + message)


def _integer(value, minimum=0, maximum=0xffffffff):
    return type(value) is int and minimum <= value <= maximum


def _unique_object(pairs):
    result = {}
    for key, value in pairs:
        _require(key not in result, "duplicate JSON key")
        result[key] = value
    return result


def _refuse_constant(value):
    raise RustDecoderError("invalid Rust decoder output: nonfinite JSON")


def _validate_state(state, raw, viewer, include_entities=_UNSET, *, mode=None):
    selected = resolve_mode(include_entities, mode)
    keys = {"frame", "viewer", "local_alliance", "canonical_fnv1a64", "raw_sha256",
            "byte_count", "counts", "resources", "game_state"}
    if selected != "summary":
        keys.add("entities" if selected == "full" else "ownership")
    _require(type(state) is dict and state.keys() == keys, "state keys")
    _require(all(_integer(state[k]) for k in ("frame", "viewer", "local_alliance")), "state integers")
    _require(state["viewer"] == viewer, "viewer differs")
    _require(_integer(state["byte_count"], 0, MAX_INPUT), "byte count")
    _require(type(state["raw_sha256"]) is str and _HEX64.fullmatch(state["raw_sha256"]), "snapshot digest")
    if raw is not None:
        _require(state["byte_count"] == len(raw), "byte count differs")
        _require(state["raw_sha256"] == hashlib.sha256(raw).hexdigest(), "snapshot digest differs")
    _require(type(state["canonical_fnv1a64"]) is str and
             _HEX16.fullmatch(state["canonical_fnv1a64"]), "canonical digest")
    counts = state["counts"]
    _require(type(counts) is dict and counts.keys() == {"army", "type", "health", "position", "resources"}
             and all(_integer(v, 0, 1_000_000) for v in counts.values()), "component counts")
    game = state["game_state"]
    _require(type(game) is dict and game.keys() == {"complete", "game_over_frame", "winning_alliance",
             "army_conceded_flag", "game_over_checksum"}, "game state keys")
    _require(type(game["complete"]) is bool and _integer(game["game_over_frame"], -(1 << 31), (1 << 31)-1)
             and _integer(game["winning_alliance"]) and _integer(game["army_conceded_flag"])
             and _integer(game["game_over_checksum"], 0, (1 << 64)-1), "game state values")
    resources = state["resources"]
    _require(type(resources) is dict and len(resources) == counts["resources"], "resources count")
    normalized = {}
    for key, values in resources.items():
        _require(type(key) is str and key.isascii() and key.isdecimal() and len(key) <= 10,
                 "resource ID")
        entity = int(key)
        _require(_integer(entity) and str(entity) == key, "resource ID")
        _require(type(values) is dict and values.keys() == set(RESOURCE_NAMES) and
                 all(_integer(v, -(1 << 31), (1 << 31)-1) for v in values.values()), "resource values")
        normalized[entity] = values
    state["resources"] = normalized
    if selected == "full":
        entities = state["entities"]
        _require(type(entities) is list and len(entities) <= sum(counts[k] for k in ("army", "type", "health", "position")),
                 "entity list")
        observed = dict.fromkeys(("army", "type", "health", "position"), 0)
        previous = -1
        for item in entities:
            _require(type(item) is dict and "id" in item and item.keys() <= {
                "id", "army", "type", "max_health", "current_damage", "position"}, "entity keys")
            _require(_integer(item["id"]) and item["id"] > previous, "entity order/ID")
            previous = item["id"]
            _require(("max_health" in item) == ("current_damage" in item), "health pair")
            for key in ("army", "type", "max_health", "current_damage"):
                _require(key not in item or _integer(item[key]), "entity integer")
            if "position" in item:
                position = item["position"]
                _require(type(position) is list and len(position) == 3 and
                         all(type(v) is float and math.isfinite(v) for v in position), "entity position")
            present = ("army" in item, "type" in item, "max_health" in item, "position" in item)
            _require(any(present), "empty entity")
            for key, exists in zip(observed, present):
                observed[key] += exists
        _require(all(counts[k] == v for k, v in observed.items()), "entity component counts")
    elif selected == "ownership":
        records = state["ownership"]
        _require(type(records) is list and len(records) <= min(counts["army"], counts["type"]),
                 "ownership count")
        previous = -1
        for item in records:
            _require(type(item) is dict and item.keys() == {"id", "army", "type"}
                     and all(_integer(v) for v in item.values()), "ownership record")
            _require(item["id"] > previous, "ownership order/ID")
            previous = item["id"]
    return state


# The worker checks the same schema at a separate boundary. Keep this stable
# alias distinct from the Rust adapter's instrumented validation call site.
validate_state_shape = _validate_state


class RustSnapshotDecoder:
    def __init__(self, library_path, expected_sha256):
        path = verified_library_path(library_path, expected_sha256)
        try:
            self._library = C.CDLL(str(path))
            version = self._library.ba_snapshot_decoder_abi_version
            version.argtypes, version.restype = [], C.c_uint32
            self._decode = self._library.ba_decode_snapshot
            self._decode.argtypes = [C.POINTER(C.c_uint8), C.c_size_t, C.c_uint32, C.c_uint8, C.POINTER(_Buffer)]
            self._decode.restype = C.c_int32
            self._free = self._library.ba_free_buffer
            self._free.argtypes = [C.POINTER(C.c_uint8), C.c_size_t]
            self._free.restype = C.c_int32
            if version() != ABI_VERSION:
                raise RustDecoderError("snapshot decoder ABI version mismatch")
        except (OSError, AttributeError) as error:
            raise RustDecoderError("cannot load snapshot decoder library/exports") from error
        # Optional exports are additive; a present unsupported version is never ignored.
        self._decode_v2 = getattr(self._library, "ba_decode_snapshot_v2", None)
        projection = getattr(self._library, "ba_snapshot_decoder_projection_version", None)
        self.projection_version = None
        if projection is not None:
            projection.argtypes, projection.restype = [], C.c_uint32
            if projection() != PROJECTION_VERSION:
                raise RustDecoderError("snapshot decoder projection version mismatch")
        if self._decode_v2 is not None and projection is not None:
            self._decode_v2.argtypes = [C.POINTER(C.c_uint8), C.c_size_t, C.c_uint32,
                                       C.c_uint32, C.POINTER(_Buffer)]
            self._decode_v2.restype = C.c_int32
            self.projection_version = PROJECTION_VERSION
        self.info = {"implementation": "rust", "abi_version": ABI_VERSION,
                     "library_sha256": expected_sha256, "library_path": str(path)}

    def decode(self, raw, viewer=31, *, include_entities=_UNSET, mode=None):
        try:
            selected = resolve_mode(include_entities, mode)
        except ValueError as error:
            raise RustDecoderError(str(error)) from error
        if mode is not None and self.projection_version != PROJECTION_VERSION:
            raise RustDecoderError("snapshot decoder lacks requested projection capability")
        if type(raw) is not bytes or len(raw) > MAX_INPUT:
            raise RustDecoderError("snapshot must be bytes of at most16MiB")
        if type(viewer) is not int or not 0 <= viewer <= 0xffffffff:
            raise RustDecoderError("invalid snapshot viewer/include_entities")
        # The bytes object is immutable and remains alive until the FFI call ends.
        source = C.cast(C.c_char_p(raw), C.POINTER(C.c_uint8))
        output = _Buffer()
        try:
            if mode is None:
                status = self._decode(source, len(raw), viewer, int(selected == "full"), C.byref(output))
            else:
                status = self._decode_v2(source, len(raw), viewer, STATE_MODES.index(mode), C.byref(output))
            if status != 0:
                raise RustDecoderError(f"Rust snapshot decoder failed, status{status}")
            _require(bool(output.data) and 0 < output.len <= MAX_OUTPUT, "buffer pointer/length")
            encoded = C.string_at(output.data, output.len)
            try:
                state = json.loads(encoded.decode("utf-8"), parse_constant=_refuse_constant,
                                   object_pairs_hook=_unique_object)
            except (ValueError, UnicodeError, RecursionError) as error:
                raise RustDecoderError("invalid Rust decoder JSON") from error
            if mode is None:
                return _validate_state(state, raw, viewer, selected == "full")
            return _validate_state(state, raw, viewer, mode=mode)
        finally:
            if output.data:
                status = self._free(output.data, output.len)
                if status != 0:
                    raise RustDecoderError(f"Rust snapshot decoder free failed, status{status}")
