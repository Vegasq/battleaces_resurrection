"""Exact-build Windows AI decision world beside one authoritative simulation.

AI emits ordinary InputAction messages; it never owns a second combat world.
Use only in an isolated match worker with locally exported, validated rules.
"""
from __future__ import annotations

from collections import deque
import ctypes as C
import hashlib
import os
from pathlib import Path
import threading

from .ai_rules import SUPPORTED_AI_SHA256, validate_rules
from .protobuf_wire import decode_varint, get_repeated_bytes, get_uint, parse_fields

MAX_BUFFER = 16 * 1024 * 1024
COMMAND_CAPACITY = 1024 * 1024
_lock = threading.RLock()
_runtime = None


class NativeAIError(RuntimeError):
    pass


def decode_action_queue(buffer: bytes, capacity=COMMAND_CAPACITY) -> tuple[bytes, ...]:
    """The DLL writes a varint length, not a returned byte count."""
    size, offset = decode_varint(buffer, 0)
    if size > capacity or offset + size > len(buffer):
        raise NativeAIError('AI command queue size outside capacity')
    body = buffer[offset:offset+size]
    fields = parse_fields(body, max_fields=65536)
    if any(field.number != 1 or field.wire_type != 2 or not field.value for field in fields):
        raise NativeAIError('AI command queue has invalid fields')
    return tuple(field.value for field in fields)


class _Runtime:
    def __init__(self, path):
        if os.name != 'nt' or C.sizeof(C.c_void_p) != 8:
            raise NativeAIError('aiprogram.dll requires64-bit Windows Python')
        if hashlib.sha256(path.read_bytes()).hexdigest() != SUPPORTED_AI_SHA256:
            raise NativeAIError('unsupported aiprogram.dll hash')
        self.path, self.worlds = path, 0
        self.logs = deque(maxlen=256)
        self.search = os.add_dll_directory(str(path.parent))
        try:
            self.dll = C.CDLL(str(path))
            signatures = {
                'AIInit': [C.c_uint8], 'AIDestroy': [],
                'AISetLogCallBack': [C.c_void_p], 'AISetLogFlags': [C.c_uint32],
                'AICreateWorld': [C.c_void_p, C.c_uint32, C.POINTER(C.c_uint64), C.c_void_p, C.c_uint32],
                'AIDestroyWorld': [C.c_uint64], 'AIAddAIArmyId': [C.c_uint64, C.c_uint32],
                'AIRemoveAIArmyId': [C.c_uint64, C.c_uint32],
                'AIStep': [C.c_uint64, C.c_int32],
            }
            for name in ('AIUpdateRule', 'AIUpdateLabel', 'AIUpdateSimFrame', 'AISpyOnSimFrame', 'GetAIInputAction'):
                signatures[name] = [C.c_uint64, C.c_uint32, C.c_void_p, C.c_uint32]
            for name, args in signatures.items():
                method = getattr(self.dll, name); method.argtypes = args; method.restype = C.c_int32
            @C.CFUNCTYPE(None, C.c_int32, C.c_char_p)
            def log(kind, message):
                try: self.logs.append({'type': kind, 'message': (message or b'').decode('utf-8', 'replace')[:16384]})
                except Exception: pass
            self.callback = log
            self.call('AISetLogFlags', 0)
            self.call('AIInit', 0)
            try: self.call('AISetLogCallBack', C.cast(log, C.c_void_p))
            except Exception:
                self.call('AIDestroy')
                raise
        except Exception:
            self.search.close()
            raise

    def call(self, name, *args):
        status = getattr(self.dll, name)(*args)
        if status:
            context = self.logs[-1]['message'] if self.logs else ''
            raise NativeAIError(f'{name} failed, code{status}: {context}')

    def close(self):
        try:
            self.call('AISetLogCallBack', C.c_void_p())
            self.call('AIDestroy')
        finally: self.search.close()


class NativeAI:
    def __init__(self, simulation, game_config: bytes, *, dll_path: Path,
                 rules: dict[int, bytes], default_profile: int, bots: dict[int, int]):
        global _runtime
        self._runtime = None
        self.world = C.c_uint64()
        self.registered = []
        self._counted = False
        self.last_frame = 0
        self.steps = 0
        self.max_command_body_bytes = 0
        self.simulation = simulation
        if not isinstance(game_config, bytes) or not 8 <= len(game_config) <= MAX_BUFFER:
            raise ValueError('AI requires raw GameConfig bytes')
        if simulation.frame != -1 or hashlib.sha256(game_config).hexdigest() != simulation.game_config_sha256:
            raise ValueError('AI requires the exact unstarted simulation configuration')
        self.bots = dict(bots)
        armies = get_repeated_bytes(game_config, 2)
        self.alliances = {get_uint(army, 1): get_uint(army, 4) for army in armies}
        if not (1 <= len(armies) <= 4 and len(self.alliances) == len(armies) and
                all(type(army) is int and 0 <= army < 4 and 0 <= alliance < 32 for army, alliance in self.alliances.items()) and
                self.bots and set(self.bots) <= set(self.alliances)):
            raise ValueError('AI requires a valid configured army/bot roster')
        needed = set(self.bots.values()) | {default_profile}
        checked = {}
        for profile in needed:
            if type(profile) is not int or profile <= 0 or profile not in rules:
                raise ValueError('AI profile rules missing')
            data = rules[profile]
            validate_rules(data)
            checked[profile] = data
        # Original policy: first configured army in the first other alliance.
        self.spies = set()
        for bot in self.bots:
            enemies = sorted((alliance, army) for army, alliance in self.alliances.items()
                             if alliance != self.alliances[bot])
            if not enemies: raise ValueError('AI roster has no enemy alliance')
            self.spies.add(enemies[0][1])
        path = Path(dll_path).resolve()
        with _lock:
            if _runtime is not None and _runtime.path != path:
                raise NativeAIError('one AI DLL build per worker process')
            if _runtime is None: _runtime = _Runtime(path)
            self._runtime = _runtime
            try:
                map_frame = simulation.map_bytes()
                config_buffer, map_buffer = C.create_string_buffer(game_config), C.create_string_buffer(map_frame)
                self._runtime.call('AICreateWorld', config_buffer, len(game_config), C.byref(self.world), map_buffer, len(map_frame))
                if not self.world.value: raise NativeAIError('empty AI world handle')
                self._runtime.worlds += 1
                self._counted = True
                for army in self.alliances:
                    self._bytes('AIUpdateRule', army, checked[default_profile])
                for army, profile in self.bots.items():
                    self._runtime.call('AIAddAIArmyId', self.world, army)
                    self.registered.append(army)
                    self._bytes('AIUpdateRule', army, checked[profile])
            except Exception:
                self.close()
                raise

    def _bytes(self, method, selector, data):
        if not isinstance(data, bytes) or not 8 <= len(data) <= MAX_BUFFER:
            raise NativeAIError('native AI input outside bounds')
        buffer = C.create_string_buffer(data)
        self._runtime.call(method, self.world, selector, buffer, len(data))

    @property
    def native_logs(self):
        return list(self._runtime.logs) if self._runtime else []

    def commands(self) -> dict[int, tuple[bytes, ...]]:
        """Read decisions for the next canonical frame, every five sim frames."""
        with _lock:
            if self._runtime is None: raise NativeAIError('AI world is closed')
            frame = self.simulation.frame
            if frame < self.last_frame:
                if frame == -1 and self.last_frame == 0: return {}
                raise NativeAIError('simulation frame moved backwards')
            if frame - self.last_frame < 5: return {}
            if frame - self.last_frame != 5:
                raise NativeAIError('AI decision cadence skipped simulation frames')
            for registry in (3, 1):
                data = self.simulation.label_bytes(registry)
                if data: self._bytes('AIUpdateLabel', registry, data)
            views = {alliance: self.simulation.snapshot_bytes(alliance) for alliance in set(self.alliances.values())}
            for army in sorted(self.spies - self.bots.keys()):
                self._bytes('AISpyOnSimFrame', army, views[self.alliances[army]])
            for army in sorted(self.bots):
                self._bytes('AIUpdateSimFrame', army, views[self.alliances[army]])
                if army in self.spies: self._bytes('AISpyOnSimFrame', army, views[self.alliances[army]])
            self._runtime.call('AIStep', self.world, 50)
            self.last_frame = frame; self.steps += 1
            result = {}
            for army in sorted(self.bots):
                # Original capacity check excludes the varint prefix. Keep ten
                # extra bytes and a canary, and detect an unwritten/oversize queue.
                output = C.create_string_buffer(COMMAND_CAPACITY + 26)
                C.memset(output, 0xff, COMMAND_CAPACITY + 10)
                C.memset(C.addressof(output) + COMMAND_CAPACITY + 10, 0xa5, 16)
                self._runtime.call('GetAIInputAction', self.world, army, output, COMMAND_CAPACITY)
                if output.raw[-16:] != b'\xa5' * 16:
                    raise NativeAIError('AI command buffer canary changed')
                raw = output.raw[:COMMAND_CAPACITY + 10]
                result[army] = decode_action_queue(raw)
                self.max_command_body_bytes = max(self.max_command_body_bytes, decode_varint(raw)[0])
            return result

    def close(self):
        global _runtime
        with _lock:
            runtime = self._runtime
            if runtime is None: return
            self._runtime = None
            try:
                if self.world.value:
                    try:
                        for army in reversed(self.registered): runtime.call('AIRemoveAIArmyId', self.world, army)
                    finally:
                        runtime.call('AIDestroyWorld', self.world)
                        if self._counted: runtime.worlds -= 1
            finally:
                self.world.value = 0; self.registered.clear()
                if not runtime.worlds:
                    try: runtime.close()
                    finally: _runtime = None

    def __enter__(self): return self
    def __exit__(self, *_): self.close()
