"""Actual socket failure paths must not persist arbitrary exception content."""
import asyncio
import errno
import json
import struct
from unittest import mock
from server import community_protocol as c,protocol as p,public_protocol as q
from server.host_audit import HostAudit
from tests.test_dedicated_server import DedicatedFixture,wait_until
from tests import test_community as community_cases,test_public_matchmaking as public_cases,test_profile_save_races as race_cases
from server.diagnostics import failure_fields,validation_reason
from server.worker_client import WorkerError,WorkerTimeout
import unittest

PRIVATE='never-persist-this-error-content'


class HostFailureDiagnosticsTests(DedicatedFixture):
    online,command,invite_pair=community_cases.CommunityTests.online,community_cases.CommunityTests.command,community_cases.CommunityTests.invite_pair
    public_command=public_cases.PublicQueueTests.public_command
    start_public=race_cases.ProfileSaveRaceTests.start_public

    def assert_safe_event(self,event,kind,*,code=None):
        records=[row for row in self.events if row['event']==event]
        self.assertEqual(len(records),1)
        audit=HostAudit(self.folder/'diagnostics',max_bytes=65536,backups=1)
        try:
            for row in self.events:audit(row['event'],**{k:v for k,v in row.items() if k!='event'})
        finally:audit.close()
        data=(self.folder/'diagnostics/events.jsonl').read_text()
        self.assertNotIn(PRIVATE,data)
        self.assertEqual(records[0]['error_kind'],kind)
        if code is not None:self.assertEqual(records[0]['errno'],code)
        return records[0]

    async def test_community_load_fallback_keeps_default_deck_without_exception_content(self):
        await self.start()
        with mock.patch.object(self.server.profiles,'load_state',side_effect=PermissionError(errno.EACCES,PRIVATE,PRIVATE)):
            peer=await self.online()
        self.assertEqual(peer.deck,list(self.template.default_decks[0]))
        await self.command(peer,c.REFRESH)
        self.assert_safe_event('profile_load_fallback','permission',code=errno.EACCES)

    async def test_legacy_load_fallback_keeps_default_deck_without_exception_content(self):
        await self.start()
        with mock.patch.object(self.server.profiles,'load_state',side_effect=PermissionError(errno.EACCES,PRIVATE,PRIVATE)):
            peer=await self.connect('diagnostic_load')
        self.assertEqual(peer.deck,list(self.template.default_decks[0]))
        self.assert_safe_event('profile_load_fallback','permission',code=errno.EACCES)

    async def test_custom_save_failure_keeps_data_and_session_reusable_without_exception_content(self):
        await self.start();peer=await self.online()
        await self.server.profile_io.save(peer.profile,peer.deck)
        path=self.server.profiles._path(peer.profile);before=path.read_bytes()
        with mock.patch.object(self.server.profiles,'save',side_effect=PermissionError(errno.EACCES,PRIVATE,PRIVATE)):
            reason=await self.command(peer,c.SET_DECK,p.deck_bytes(peer.deck),ok=False)
        self.assertEqual(reason,'profile save unavailable');self.assertEqual(path.read_bytes(),before)
        await self.command(peer,c.SET_DECK,p.deck_bytes(peer.deck))
        self.assert_safe_event('profile_save_failed','permission',code=errno.EACCES)

    async def test_public_save_failure_has_no_ticket_and_same_session_can_retry_without_exception_content(self):
        await self.start_public();peer=await self.online();peer.ticket=1
        await self.server.profile_io.save(peer.profile,peer.deck)
        path=self.server.profiles._path(peer.profile);before=path.read_bytes()
        with mock.patch.object(self.server.profiles,'save',side_effect=PermissionError(errno.EACCES,PRIVATE,PRIVATE)):
            reason=await self.public_command(peer,q.ENTER,mode=1,deck=peer.deck,ok=False)
        self.assertEqual(reason,'profile save unavailable');self.assertEqual(path.read_bytes(),before)
        self.assertNotIn(peer.profile,self.server.community.public.entries)
        await self.public_command(peer,q.ENTER,mode=1,deck=peer.deck)
        self.assertEqual(self.server.community.public.entries[peer.profile].ticket,1)
        self.assert_safe_event('profile_save_failed','permission',code=errno.EACCES)

    async def test_simulation_failure_aborts_unknown_result_without_exception_content(self):
        await self.start();peers=await self.pair('diagnostic_worker');room=self.server.rooms['diagnostic_worker']
        with mock.patch.object(room.sim,'process_frame',mock.AsyncMock(side_effect=RuntimeError(PRIVATE))):
            await asyncio.gather(*(peer.send(p.INPUT,struct.pack('<I',0)) for peer in peers))
            reasons=await asyncio.gather(*(peer.receive(p.ERROR) for peer in peers))
        self.assertTrue(all(b'server simulation error' in reason for reason in reasons))
        self.assertIsNone(room.result)
        self.assertFalse(any(kind==p.FRAME for peer in peers for kind,payload in peer.observed))
        await wait_until(lambda:room.sim is None or room.sim.process.poll() is not None)
        self.assert_safe_event('simulation_error','internal')

    async def test_unexpected_connection_failure_closes_peer_without_exception_content(self):
        await self.start();peer=await self.online()
        with mock.patch.object(self.server.community,'handle',mock.AsyncMock(side_effect=RuntimeError(PRIVATE))):
            await peer.send(c.REFRESH,struct.pack('<I',1))
            reason=await peer.receive(p.ERROR)
        self.assertNotIn(PRIVATE.encode(),reason)
        await wait_until(lambda:not self.server.peers)
        self.assert_safe_event('connection_error','internal')

    async def test_unexpected_value_error_is_not_an_authored_protocol_message(self):
        await self.start();peer=await self.online()
        with mock.patch.object(self.server.community,'handle',mock.AsyncMock(side_effect=ValueError(PRIVATE))):
            await peer.send(c.REFRESH,struct.pack('<I',1))
            reason=await peer.receive(p.ERROR)
        self.assertEqual(reason,b'invalid client request')
        await wait_until(lambda:not self.server.peers)
        self.assert_safe_event('protocol_error','invalid_data')

    async def test_unknown_custom_storage_value_error_is_not_sent_in_rejection(self):
        await self.start();peer=await self.online()
        with mock.patch.object(self.server.profiles,'save',side_effect=ValueError(PRIVATE)):
            reason=await self.command(peer,c.SET_DECK,p.deck_bytes(peer.deck),ok=False)
        self.assertEqual(reason,'invalid selection or saved profile')
        await self.command(peer,c.SET_DECK,p.deck_bytes(peer.deck))

    async def test_unknown_public_storage_value_error_is_not_sent_in_rejection(self):
        await self.start_public();peer=await self.online();peer.ticket=1
        with mock.patch.object(self.server.profiles,'save',side_effect=ValueError(PRIVATE)):
            reason=await self.public_command(peer,q.ENTER,mode=1,deck=peer.deck,ok=False)
        self.assertEqual(reason,'invalid selection or saved profile')
        self.assertNotIn(peer.profile,self.server.community.public.entries)
        await self.public_command(peer,q.ENTER,mode=1,deck=peer.deck)


class FailureCategoryTests(unittest.TestCase):
    def test_authored_validation_stays_useful_while_unknown_text_hooks_are_not_called(self):
        self.assertEqual(validation_reason(p.ProtocolError('invalid ready flag'),'fallback'),'invalid ready flag')
        def forbidden(*args):raise AssertionError('unknown exception text was evaluated')
        cls=type(PRIVATE,(ValueError,),dict(__str__=forbidden,__repr__=forbidden))
        self.assertEqual(validation_reason(cls(PRIVATE),'fallback'),'fallback')

    def test_categories_are_fixed_and_keep_worker_consumer_compatibility(self):
        for cls,kind in ((WorkerTimeout,'worker_timeout'),(WorkerError,'worker_error'),(TimeoutError,'timeout'),
                         (PermissionError,'permission'),(FileNotFoundError,'missing_file'),(OSError,'os_error'),
                         (ValueError,'invalid_data'),(KeyError,'missing_field'),(RuntimeError,'internal')):
            with self.subTest(cls=cls):
                value=failure_fields(cls(PRIVATE));self.assertEqual(value['error_kind'],kind)
                self.assertNotIn(PRIVATE,json.dumps(value))
        self.assertEqual(failure_fields(WorkerTimeout(PRIVATE))['error'],'WorkerTimeout()')
        self.assertEqual(failure_fields(WorkerError(PRIVATE))['error'],'WorkerError()')

    def test_exception_string_hooks_and_dynamic_class_names_are_never_read(self):
        def forbidden(*args):raise AssertionError('exception text was evaluated')
        cls=type(PRIVATE,(RuntimeError,),dict(__str__=forbidden,__repr__=forbidden))
        self.assertEqual(failure_fields(cls(PRIVATE)),dict(error_kind='internal',error='Exception()'))

    def test_only_bounded_integer_os_codes_survive(self):
        error=OSError(errno.ENOSPC,PRIVATE,PRIVATE);error.winerror=5
        self.assertEqual(failure_fields(error),dict(error_kind='os_error',error='OSError()',errno=errno.ENOSPC,winerror=5))
        for value in (PRIVATE,True,2**64):
            error.errno=error.winerror=value
            self.assertEqual(failure_fields(error),dict(error_kind='os_error',error='OSError()'))
