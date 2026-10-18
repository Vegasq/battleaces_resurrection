"""Private, server-assigned AI inputs; never accepts a network client's bot roster."""
from __future__ import annotations

from dataclasses import dataclass
import hashlib
from pathlib import Path
import struct
from types import MappingProxyType

from .game_data import decode_identity, encode_player_input
from .protobuf_wire import field_bytes, field_uint, get_bytes, get_repeated_bytes, get_uint, parse_fields

MAX_INPUT = 65536


def require(condition, message):
    if not condition:
        raise ValueError(message)


@dataclass(frozen=True)
class AISetup:
    directory: Path
    bots: object

    def __post_init__(self):
        bots = dict(self.bots)
        require(1 <= len(bots) <= 4 and all(type(a) is int and 0 <= a < 4 and
                type(p) is int and 0 < p <= 0xffffffff for a, p in bots.items()), 'invalid worker AI assignments')
        object.__setattr__(self, 'directory', Path(self.directory).resolve())
        object.__setattr__(self, 'bots', MappingProxyType(bots))

    def wire(self):
        return {'directory': str(self.directory), 'bots': {str(a): p for a, p in sorted(self.bots.items())}}

    @classmethod
    def from_wire(cls, value):
        require(isinstance(value, dict) and set(value) == {'directory', 'bots'} and
                isinstance(value['directory'], str) and Path(value['directory']).is_absolute() and
                isinstance(value['bots'], dict) and all(a in ('0', '1', '2', '3') for a in value['bots']),
                'invalid worker AI configuration')
        return cls(Path(value['directory']), {int(a): p for a, p in value['bots'].items()})


def pack_inputs(inputs):
    require(1 <= len(inputs) <= 4, 'invalid bot input count')
    output = bytes([len(inputs)])
    for army, data in sorted(inputs.items()):
        require(type(army) is int and 0 <= army < 4 and isinstance(data, bytes) and
                1 <= len(data) <= MAX_INPUT, 'invalid bot input size/army')
        output += struct.pack('<BI', army, len(data)) + data
    return output


def unpack_inputs(payload):
    require(isinstance(payload, bytes) and 1 <= len(payload) <= 1 + 4*(5 + MAX_INPUT), 'invalid bot packet size')
    count, position, result = payload[0], 1, {}
    require(1 <= count <= 4, 'invalid bot input count')
    for _ in range(count):
        require(position + 5 <= len(payload), 'truncated bot input header')
        army, length = struct.unpack_from('<BI', payload, position); position += 5
        require(army < 4 and army not in result and 1 <= length <= MAX_INPUT and
                position + length <= len(payload), 'invalid/truncated bot input')
        result[army] = payload[position:position+length]; position += length
    require(position == len(payload), 'trailing bot input bytes')
    return result


class BotRoster:
    """Frozen GameData identity/deck ownership and exact prepared-frame checking."""
    def __init__(self, game_data, bots):
        self.bots = dict(bots)
        self.game_config = get_bytes(game_data, 1, required=True)
        armies = get_repeated_bytes(self.game_config, 2)
        self.armies = {get_uint(army, 1): army for army in armies}
        require(1 <= len(armies) <= 4 and len(self.armies) == len(armies) and
                set(self.armies) <= {0, 1, 2, 3}, 'invalid AI world armies')
        self.identities = {a: get_bytes(data, 2, required=True) for a, data in self.armies.items()}
        assigned = {a: decode_identity(identity)['ai_profile_id'] for a, identity in self.identities.items()}
        require(self.bots and self.bots == {a: p for a, p in assigned.items() if p},
                'worker bot assignments differ from frozen GameData')
        require(len(set(self.identities.values())) == len(self.identities), 'duplicate AI world identities')

    def make_inputs(self, frame, decisions):
        require(set(decisions) <= set(self.bots), 'AI produced input for an unassigned army')
        result = {}
        for army in sorted(self.bots):
            actions = list(decisions.get(army, ()))
            require(len(actions) <= 128, 'AI action count limit')
            for action in actions:
                fields = parse_fields(action, max_bytes=MAX_INPUT)
                require(len(fields) == 1 and fields[0].wire_type == 2 and fields[0].number in (1, 5),
                        'AI may only emit Execute/UI commands')
            if frame == 0:
                data = self.armies[army]
                join = field_uint(1, army) + field_bytes(2, get_bytes(data, 3, required=True))
                for target, source in ((3, 5), (4, 6)):
                    value = get_uint(data, source)
                    if value: join += field_uint(target, value)
                actions.insert(0, field_bytes(3, join))
            body = encode_player_input(self.identities[army], actions)
            require(len(body) <= MAX_INPUT, 'AI player input exceeds frame limit')
            result[army] = body
        return result

    def check_inputs(self, inputs):
        require(set(inputs) == set(self.bots), 'bot input roster differs')
        for army, body in inputs.items():
            require(get_bytes(body, 1, required=True) == self.identities[army], 'bot input identity differs')

    def check_frame(self, actions, prepared):
        """Require every generated bot action exactly once in the accepted frame."""
        seen = {}
        identity_armies = {identity: army for army, identity in self.identities.items()}
        for body in get_repeated_bytes(actions, 6):
            army = identity_armies.get(get_bytes(body, 1, required=True))
            require(army is not None and army not in seen, 'frame has unknown/duplicate army identity')
            seen[army] = body
        expected = {a: body for a, body in prepared.items() if get_repeated_bytes(body, 2)}
        require({a: body for a, body in seen.items() if a in self.bots} == expected,
                'frame changed or omitted prepared bot inputs')


class WorkerAI(BotRoster):
    def __init__(self, simulation, game_data, setup):
        super().__init__(game_data, setup.bots)
        from .ai_rules import RuleBook, SUPPORTED_AI_SHA256
        from .native_ai import NativeAI
        book = RuleBook(setup.directory)
        require(all(p in book.entries and book.entries[p]['enabled'] for p in self.bots.values()),
                'worker AI profile is missing/disabled')
        self.info = {'bots': {str(a): p for a, p in sorted(self.bots.items())},
                     'dll_sha256': SUPPORTED_AI_SHA256,
                     'manifest_sha256': hashlib.sha256(book.files['ai-rules.json']).hexdigest()}
        self.simulation, self.prepared, self.prepared_frame = simulation, None, None
        self.native = NativeAI(simulation, self.game_config, dll_path=setup.directory/'aiprogram.dll',
                               rules=book.rules, default_profile=book.default_profile, bots=self.bots)

    def prepare(self, frame):
        require(frame == self.simulation.frame + 1 and self.prepared is None, 'bot inputs already prepared or wrong frame')
        self.prepared = self.make_inputs(frame, self.native.commands())
        self.prepared_frame = frame
        return self.prepared

    def before_step(self, frame, payload):
        require(self.prepared is not None and self.prepared_frame == frame, 'bot inputs must be prepared before STEP')
        self.check_frame(payload, self.prepared)

    def after_step(self):
        self.prepared = self.prepared_frame = None

    def close(self):
        self.native.close()
