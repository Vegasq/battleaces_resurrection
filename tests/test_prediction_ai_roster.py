"""Frozen original bootstrap roster; authored data/ABI only, no game DLL."""
import ctypes as C
import struct
import unittest

from client_patch.prediction_worker import commands, wire as w
from client_patch.prediction_worker.native import NativeSession, HostError
from server.game_data import encode_frame, encode_identity
from server.protobuf_wire import field_bytes as b, field_uint as u, get_bytes, get_uint, get_repeated_bytes
from tests.test_prediction_command_ledger import body, join, MOVE
from tests.test_prediction_worker import Raw, command
from tests.test_native_prediction_adapter import Heap
from tests.test_prediction_worker_ledger_integration import NativeFixture, SnapshotHeap


def roster_data(*, mode=1, ai=7, human_ai=0, armies=(0, 1), alliances=(0, 1)):
    identities=(encode_identity(1,'Human',ai_profile_id=human_ai), encode_identity(2,'Bot',ai_profile_id=ai))
    config=u(36,mode)+b''.join(b(2,u(1,army)+u(4,alliance)+b(2,identity))
        for army,alliance,identity in zip(armies,alliances,identities))
    return b(1,config),identities


def player(identity, actions=()):
    return b(1,identity)+b''.join(b(2,action) for action in actions)


class FrozenRosterTests(unittest.TestCase):
    def test_canonical_bot_bytes_are_validated_without_becoming_local_human_input(self):
        raw,identities=roster_data();roster=commands.CanonicalRoster.from_game_data(raw)
        own,bot=player(identities[0],[join()]),player(identities[1],[join(1),MOVE])
        frame=encode_frame(0,{0:own,1:bot})
        self.assertEqual(commands.own_player_body(frame,0,roster=roster),own)
        self.assertEqual(commands.own_player_body(encode_frame(1,{0:b'',1:bot}),0,roster=roster),b'')
        with self.assertRaises(ValueError):commands.own_player_body(frame,0)
        with self.assertRaises(ValueError):commands.player_slot(bot)
        with self.assertRaises(ValueError):commands.CommandLedger(0).register(1,bot,0)
        with self.assertRaises(ValueError):commands.own_player_body(frame,1,roster=roster)

    def test_frozen_ai_profile_name_ownership_and_duplicates_are_not_inferred(self):
        raw,ids=roster_data();roster=commands.CanonicalRoster.from_game_data(raw)
        for identity in (encode_identity(2,'Bot',ai_profile_id=8),encode_identity(2,'Other',ai_profile_id=7),
                         encode_identity(2,'Bot'),encode_identity(1,'Human',ai_profile_id=7)):
            with self.subTest(identity=identity),self.assertRaises(ValueError):
                commands.own_player_body(encode_frame(1,{0:b'',1:player(identity,[MOVE])}),0,roster=roster)
        duplicate=encode_frame(1,{0:player(ids[1],[MOVE]),1:player(ids[1],[MOVE])})
        with self.assertRaises(ValueError):commands.own_player_body(duplicate,0,roster=roster)
        malformed=player(ids[1],[MOVE])+u(3,1)
        with self.assertRaises(ValueError):commands.own_player_body(encode_frame(1,{0:b'',1:malformed}),0,roster=roster)

    def test_bootstrap_requires_exact_solo_mode_one_armies_alliances_and_roles(self):
        for kwargs in ({'mode':2},{'mode':5},{'ai':0},{'human_ai':3},{'armies':(0,0)},{'alliances':(0,0)}):
            with self.subTest(kwargs=kwargs),self.assertRaises(ValueError):commands.CanonicalRoster.from_game_data(roster_data(**kwargs)[0])
        raw,ids=roster_data()
        for bad in (b'',b'not protobuf',raw+raw,b(1,b(2,u(1,0)+b(2,ids[0])))):
            with self.subTest(bad=bad),self.assertRaises(ValueError):commands.CanonicalRoster.from_game_data(bad)


class NativeRosterTests(unittest.TestCase):
    def make(self):
        raw=Raw();session=NativeSession(raw,arena=Heap());self.addCleanup(session.close)
        session.dispatch(command(1,b'\0'))
        bootstrap,identities=roster_data()
        _,encoded=session.dispatch(command(5,bootstrap));key,=struct.unpack('<Q',encoded)
        return raw,session,key,identities

    def test_explicit_roster_binds_actual_create_bytes_before_begin_without_native_call(self):
        raw,session,key,ids=self.make();before=len(raw.calls)
        self.assertEqual(session.dispatch(command(76,struct.pack('<QI',key,0))),(0,b''))
        self.assertEqual(len(raw.calls),before)
        with self.assertRaises(HostError):session.dispatch(command(76,struct.pack('<QI',key,0)))
        session.dispatch(command(64,struct.pack('<QII',key,12,1024*1024)))
        session.dispatch(command(67,struct.pack('<QQ',key,1)+body([join()])))
        frame=encode_frame(0,{0:player(ids[0],[join()]),1:player(ids[1],[join(1)])})
        self.assertEqual(session.dispatch(command(65,struct.pack('<Q',key)+frame)),(0,b''))
        self.assertEqual(session.predictions[key].received_frame,0)
        self.assertEqual(session.command_ledgers[key].received_frame,0)
        before=session.command_ledgers[key].metrics
        bad=encode_frame(1,{0:b'',1:player(encode_identity(2,'Wrong',ai_profile_id=7),[MOVE])})
        with self.assertRaises(ValueError):session.dispatch(command(65,struct.pack('<Q',key)+bad))
        self.assertEqual(session.command_ledgers[key].metrics,before)
        self.assertEqual(session.predictions[key].received_frame,0)
        session.dispatch(command(6,struct.pack('<Q',key)))
        self.assertFalse(session.canonical_rosters);self.assertFalse(session.world_bootstraps)

    def test_retroactive_roster_enable_or_wrong_human_slot_is_refused(self):
        raw,session,key,ids=self.make()
        for payload in (struct.pack('<QI',key,1),struct.pack('<Q',key),struct.pack('<QI',0,0)):
            with self.subTest(payload=payload),self.assertRaises(ValueError):session.dispatch(command(76,payload))
        self.assertFalse(session.canonical_rosters)
        session.dispatch(command(64,struct.pack('<QII',key,12,1024*1024)))
        with self.assertRaises(HostError):session.dispatch(command(76,struct.pack('<QI',key,0)))


class AiFixture(NativeFixture):
    def call(self, name, *args):
        if name == 'SimProcessMsg':
            raw = C.string_at(args[1], args[2])
            self.inputs.append(raw);self.next_frame=get_uint(raw,1)
            for participant in get_repeated_bytes(raw,6):
                if get_uint(get_bytes(participant,1),2):
                    self.remote |= any(get_bytes(action,1) for action in get_repeated_bytes(participant,2))
            return Raw.call(self,name,*args)
        return super().call(name,*args)


class AiReplayTests(unittest.TestCase):
    def test_delayed_canonical_bot_action_restores_and_replays_exact_ai_bytes(self):
        raw=AiFixture();heap=SnapshotHeap(raw);session=NativeSession(raw,arena=heap)
        self.addCleanup(session.close)
        def send(op,body=b''):return session.dispatch(command(op,body))
        send(1,b'\0');bootstrap,ids=roster_data()
        _,data=send(5,bootstrap);key,=struct.unpack('<Q',data)
        world=struct.pack('<Q',key)
        send(76,world+struct.pack('<I',0));send(64,world+struct.pack('<II',12,1024*1024))
        send(67,struct.pack('<QQ',key,1)+body([join()]))
        startup=encode_frame(0,{0:player(ids[0],[join()]),1:player(ids[1],[join(1)])})
        send(65,world+startup)
        def advance(frame):
            send(7,world+encode_frame(frame,{0:b'',1:b''}))
            send(8,struct.pack('<QIi',key,50,-1));send(9,struct.pack('<QII',key,0,0))
        for frame in range(4):advance(frame)
        self.assertFalse(raw.remote)
        self.assertEqual(raw.inputs[0],startup)
        before=len(raw.calls),tuple(heap.events)
        delayed=encode_frame(1,{0:b'',1:player(ids[1],[MOVE])})
        send(65,world+delayed)
        self.assertEqual((len(raw.calls),tuple(heap.events)),before)
        count=len(raw.inputs);advance(4)
        replay=raw.inputs[count:]
        self.assertEqual([get_uint(value,1) for value in replay],[1,2,3,4])
        self.assertEqual(replay[0],delayed)
        self.assertTrue(raw.remote)
        self.assertEqual(session.predictions[key].metrics['corrections'],1)
        self.assertEqual(session.identity_histories[key].lookup(79),(1,75))
        self.assertFalse(session.command_ledgers[key].pending)
        send(6,world)
        self.assertFalse(session.canonical_rosters);self.assertFalse(session.world_bootstraps)


if __name__=='__main__':unittest.main()
