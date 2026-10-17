"""Headless bridge to the exact shipped Battle Aces x64 Simulation.dll.

Only stdlib is required. Native creation takes a full GamePb.GameData protobuf,
NOT a GameConfig or gzip stream. process_frame takes GamePb.InputActions bytes.
The server must validate client identity/commands before constructing those bytes.
This module owns an independent native world; it does not launch Unity or Steam.

ABI/static evidence and runtime limitations: investigation/dedicated/native-server.txt.
"""
from __future__ import annotations
import ctypes as C
import hashlib
import os
import pathlib
import struct
import threading
from collections import deque

SUPPORTED_DLL_SHA256 = "107bb83dc416a16492277392c50104660e34c48911345ae2e0d5afe3929a07fb"
from .paths import SIMULATION_DLL
DEFAULT_DLL = SIMULATION_DLL
MAX_MESSAGE_BYTES = 32 * 1024 * 1024
MAX_SNAPSHOT_BYTES = 16 * 1024 * 1024
RESOURCE_NAMES = ("primary", "secondary", "current_supply", "max_supply", "primary_gathered",
                  "secondary_gathered", "primary_lost", "secondary_lost")


class NativeSimulationError(RuntimeError):
    """A native call failed; callers should stop the affected match."""


class SnapshotFormatError(ValueError):
    pass


def _protobuf_header(data: bytes) -> tuple[int, int]:
    """Read InputActions frame and step without a protobuf runtime; validate bounds."""
    p = 0
    frame, step = 0, 0
    def varint():
        nonlocal p
        value = 0
        for shift in range(0, 70, 7):
            if p >= len(data):
                raise ValueError("truncated InputActions varint")
            b = data[p]; p += 1
            if shift == 63 and b > 1:
                raise ValueError("InputActions varint exceeds uint64")
            value |= (b & 127) << shift
            if not b & 128:
                return value
        raise ValueError("overlong InputActions varint")
    while p < len(data):
        tag = varint(); number, wire = tag >> 3, tag & 7
        if not number:
            raise ValueError("zero InputActions field number")
        if wire == 0:
            value = varint()
            if number == 1: frame = value
            elif number == 3: step = value
        elif wire == 2:
            size = varint(); p += size
        elif wire in (1, 5):
            p += 8 if wire == 1 else 4
        else:
            raise ValueError("unsupported InputActions wire type")
        if p > len(data):
            raise ValueError("truncated InputActions field")
    if not 0 <= frame <= 0x7fffffff:
        raise ValueError("InputActions frame outside nonnegative int32")
    if not 1 <= step <= 1000:
        raise ValueError("InputActions time step outside1..1000ms")
    return frame, step


class _Buffer:
    def __init__(self, data: bytes):
        self.data = data

    def bounds(self, offset: int, size: int):
        if offset < 0 or size < 0 or offset > len(self.data) or size > len(self.data) - offset:
            raise SnapshotFormatError("snapshot bounds")

    def read(self, fmt: str, offset: int):
        self.bounds(offset, struct.calcsize("<" + fmt))
        return struct.unpack_from("<" + fmt, self.data, offset)[0]

    def field(self, table: int, index: int) -> int:
        if not table:
            return 0
        vtable = table - self.read("i", table)
        slot = 4 + 2 * index
        if slot + 2 > self.read("H", vtable):
            return 0
        relative = self.read("H", vtable + slot)
        if not relative:
            return 0
        self.bounds(table + relative, 1)
        return table + relative

    def indirect(self, offset: int) -> int:
        if not offset:
            return 0
        target = offset + self.read("I", offset)
        self.bounds(target, 4)
        return target

    def table(self, table: int, index: int) -> int:
        return self.indirect(self.field(table, index))

    def vector(self, table: int, index: int, stride: int) -> tuple[int, int]:
        offset = self.indirect(self.field(table, index))
        if not offset:
            return 0, 0
        count = self.read("I", offset)
        if count > 1_000_000:
            raise SnapshotFormatError("snapshot vector count exceeds bound")
        self.bounds(offset + 4, count * stride)
        return offset + 4, count

    def scalar(self, table: int, field: int, fmt: str, default=0):
        p = self.field(table, field)
        return self.read(fmt, p) if p else default


def decode_snapshot(data: bytes, viewer: int = 31, *, include_entities: bool = False) -> dict:
    """Decode selected canonical state and GameState from the shipped FlatBuffer.

    The canonical hash matches lan_audit.cpp for the same native frame/view. It is
    an observable-state comparison, not a complete hidden-world checksum.
    """
    b = _Buffer(data)
    root = b.read("I", 0); b.bounds(root, 4)
    frame = b.scalar(root, 0, "I")
    canonical = bytearray(struct.pack("<III", 1, viewer, frame))
    components = {}
    for field, words, name, health in ((2, 1, "army", False), (3, 1, "type", False),
                                      (5, 1, "health", True), (7, 3, "position", False),
                                      (21, 8, "resources", False)):
        table = b.table(root, field)
        ids, count = b.vector(table, 0, 4)
        values, value_count = b.vector(table, 1, 4 * words)
        damage, damage_count = b.vector(table, 2, 4) if health else (0, 0)
        if value_count != count or health and damage_count != count:
            raise SnapshotFormatError("component vector lengths disagree")
        rows = []
        for i in range(count):
            row = [b.read("I", ids + i * 4)]
            row.extend(b.read("I", values + (i * words + j) * 4) for j in range(words))
            if health: row.append(b.read("I", damage + i * 4))
            rows.append(row)
        rows.sort(key=lambda row: row[0])
        if any(rows[i][0] == rows[i-1][0] for i in range(1, len(rows))):
            raise SnapshotFormatError("duplicate component ID")
        canonical.extend(struct.pack("<II", field, count))
        for row in rows:
            canonical.extend(struct.pack("<" + "I" * len(row), *row))
        components[name] = rows
    fnv = 14695981039346656037
    for value in canonical:
        fnv = ((fnv ^ value) * 1099511628211) & 0xffffffffffffffff
    state = b.table(root, 23)
    game_state = {
        "complete": bool(b.scalar(state, 0, "B")),
        "game_over_frame": b.scalar(state, 1, "i"),
        "winning_alliance": b.scalar(state, 2, "I"),
        "army_conceded_flag": b.scalar(state, 3, "I"),
        "game_over_checksum": b.scalar(state, 4, "Q"),
    }
    resources = {}
    for row in components["resources"]:
        resources[row[0]] = {name: value if value < 1 << 31 else value - (1 << 32)
                             for name, value in zip(RESOURCE_NAMES, row[1:])}
    result = {
        "frame": frame, "viewer": viewer, "local_alliance": b.scalar(root, 1, "I"),
        "canonical_fnv1a64": f"{fnv:016x}", "raw_sha256": hashlib.sha256(data).hexdigest(),
        "byte_count": len(data), "counts": {name: len(rows) for name, rows in components.items()},
        "resources": resources, "game_state": game_state,
    }
    if include_entities:
        entities = {}
        for name in ("army", "type", "health", "position"):
            for entity, *values in components[name]:
                item = entities.setdefault(entity, {"id": entity})
                if name in ("army", "type"): item[name] = values[0]
                elif name == "health": item.update(max_health=values[0], current_damage=values[1])
                else: item["position"] = list(struct.unpack("<fff", struct.pack("<III", *values)))
        result["entities"] = [entities[k] for k in sorted(entities)]
    return result


canonical_snapshot = decode_snapshot


_runtime_lock = threading.RLock()
_runtime = None


class _Runtime:
    """Process-global DLL lifetime; all exports are serialized by _runtime_lock."""
    def __init__(self, path: pathlib.Path):
        if os.name != "nt" or C.sizeof(C.c_void_p) != 8:
            raise NativeSimulationError("Simulation.dll requires64-bit Windows Python")
        actual = hashlib.sha256(path.read_bytes()).hexdigest()
        if actual != SUPPORTED_DLL_SHA256:
            raise NativeSimulationError(f"unsupported Simulation.dll SHA256: {actual}")
        self.path, self.sha256 = path, actual
        self.world_count = 0
        self.logs = deque(maxlen=256)
        self.search = os.add_dll_directory(str(path.parent))
        self.dll = C.CDLL(str(path))
        signatures = {
            "SimInit": [C.c_bool], "SimDestroy": [],
            "SimSetLogCallBack": [C.c_void_p], "SimSetLogFlags": [C.c_uint32],
            "SimCreateWorld": [C.c_void_p, C.c_uint32, C.POINTER(C.c_uint64)],
            "SimDestroyWorld": [C.c_uint64],
            "SimProcessMsg": [C.c_uint64, C.c_void_p, C.c_uint32],
            "SimStep": [C.c_uint64, C.c_uint32, C.POINTER(C.c_int32)],
            "SimMakeSimFrame": [C.c_uint64, C.c_uint32, C.POINTER(C.c_uint32)],
            "SimGetSimFrameBuffer": [C.c_uint64, C.c_void_p],
        }
        for name, arguments in signatures.items():
            f = getattr(self.dll, name); f.argtypes = arguments; f.restype = C.c_int
        @C.CFUNCTYPE(None, C.c_int, C.c_char_p)
        def callback(kind, text):
            # Never raise through a native callback and never acquire a second lock.
            try: self.logs.append({"type": kind, "message": (text or b"").decode("utf-8", "replace")[:16384]})
            except Exception: pass
        self.callback = callback  # Keep the unmanaged callback alive for the entire DLL lifetime.
        self.call("SimInit", False)
        try:
            self.call("SimSetLogCallBack", C.cast(self.callback, C.c_void_p))
        except Exception:
            self.call("SimDestroy")
            raise

    def call(self, name: str, *arguments):
        result = getattr(self.dll, name)(*arguments)
        if result:
            context = self.logs[-1]["message"] if self.logs else ""
            raise NativeSimulationError(f"{name} failed, code{result}: {context}")
        return result

    def close(self):
        # SimInit may log before the next callback is installed. Never leave a
        # pointer to a Python callback behind after this runtime is released.
        self.call("SimSetLogCallBack", C.c_void_p())
        self.call("SimDestroy")
        self.search.close()


class NativeSimulation:
    """One authoritative world, independent of any connected player's process.

    process_frame advances exactly one frame from the coordinator's ordered log.
    Native acceptance alone does not imply a command was legal or executed: inspect
    authoritative state changes and enforce the server's client-action allowlist.
    """
    def __init__(self, game_data: bytes, dll_path: str | pathlib.Path | None = None):
        global _runtime
        if not isinstance(game_data, bytes) or not 1 <= len(game_data) <= MAX_MESSAGE_BYTES:
            raise ValueError("full GameData bytes are required (1..32MiB)")
        if game_data.startswith(b"\x1f\x8b"):
            raise ValueError("decompress GameData gzip before native creation")
        self._runtime = None
        self._world = C.c_uint64()
        self.frame = -1
        self.game_time_seconds = 0
        self.game_data_sha256 = hashlib.sha256(game_data).hexdigest()
        path = pathlib.Path(dll_path or DEFAULT_DLL).resolve()
        with _runtime_lock:
            if _runtime and _runtime.path != path:
                raise NativeSimulationError("one simulation DLL build per process is supported")
            if _runtime is None:
                _runtime = _Runtime(path)
            runtime = _runtime
            data_buffer = C.create_string_buffer(game_data)
            try:
                runtime.call("SimCreateWorld", data_buffer, len(game_data), C.byref(self._world))
                if not self._world.value:
                    raise NativeSimulationError("SimCreateWorld returned an empty world handle")
            except Exception:
                if not runtime.world_count:
                    try: runtime.close()
                    finally: _runtime = None
                raise
            runtime.world_count += 1
            self._runtime = runtime

    @property
    def dll_sha256(self) -> str:
        return SUPPORTED_DLL_SHA256

    @property
    def closed(self) -> bool:
        return self._runtime is None

    @property
    def native_logs(self) -> list[dict]:
        return list(self._require().logs)

    def _require(self) -> _Runtime:
        if self._runtime is None:
            raise NativeSimulationError("simulation world is closed")
        return self._runtime

    def process_frame(self, input_actions: bytes, dt_ms: int | None = None) -> int:
        """Apply InputActions then step; return native whole game-time seconds.

        First frame must be0 and subsequent frames consecutive. The caller must
        deliver the identical bytes to clients. An explicit dt must match the wire.
        """
        if not isinstance(input_actions, bytes) or not 1 <= len(input_actions) <= MAX_MESSAGE_BYTES:
            raise ValueError("serialized InputActions bytes required (1..32MiB)")
        frame, wire_dt = _protobuf_header(input_actions)
        if dt_ms is not None and dt_ms != wire_dt:
            raise ValueError("native step must match InputActions.debug_game_time_step_ms")
        with _runtime_lock:
            runtime = self._require()
            if frame != self.frame + 1:
                raise ValueError(f"expected frame{self.frame+1}, received{frame}")
            message = C.create_string_buffer(input_actions)
            current = C.c_int32()
            runtime.call("SimProcessMsg", self._world, message, len(input_actions))
            runtime.call("SimStep", self._world, wire_dt, C.byref(current))
            self.frame, self.game_time_seconds = frame, current.value
            return self.game_time_seconds

    def snapshot_bytes(self, viewer: int = 31) -> bytes:
        if not isinstance(viewer, int) or not 0 <= viewer <= 31:
            raise ValueError("viewer must be in0..31")
        with _runtime_lock:
            runtime = self._require()
            size = C.c_uint32()
            runtime.call("SimMakeSimFrame", self._world, viewer, C.byref(size))
            if not 8 <= size.value <= MAX_SNAPSHOT_BYTES:
                raise NativeSimulationError(f"snapshot size outside bounds: {size.value}")
            output = C.create_string_buffer(size.value)
            runtime.call("SimGetSimFrameBuffer", self._world, output)
            return output.raw

    def snapshot(self, viewer: int = 31) -> bytes:
        """Return the raw native FlatBuffer; use canonical_snapshot to decode it."""
        return self.snapshot_bytes(viewer)

    def state(self, viewer: int = 31, *, include_entities: bool = False) -> dict:
        return decode_snapshot(self.snapshot_bytes(viewer), viewer, include_entities=include_entities)

    def close(self):
        global _runtime
        with _runtime_lock:
            runtime = self._runtime
            if runtime is None:
                return
            self._runtime = None
            try:
                runtime.call("SimDestroyWorld", self._world)
            finally:
                self._world.value = 0
                runtime.world_count -= 1
                if runtime.world_count == 0:
                    try: runtime.close()
                    finally: _runtime = None

    def __enter__(self):
        return self

    def __exit__(self, *_):
        self.close()
