"""Real HTTP, persistence and synthetic coordinator lifecycle; no original assets."""
import asyncio
import json
from pathlib import Path
import tempfile
from types import SimpleNamespace as NS
import unittest
from unittest import mock

from server.web_dashboard import Dashboard, read_history, HISTORY_LIMIT
from server.web_dashboard_page import SCRIPT
from tests.test_dedicated_server import DedicatedFixture, wait_until


class DashboardTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.path = Path(self.temporary.name)/'web-matches.json'
        self.server = NS(rooms={}, closing=False, match_observer=None,
                         community=NS(directory_rows=(('p_alice', '<img src=x onerror=alert(1)>', 0, True),)))
        self.web = Dashboard(self.server, self.path)
        self.address = await self.web.start('127.0.0.1', 0)

    async def asyncTearDown(self):
        await self.web.close()
        self.temporary.cleanup()

    async def request(self, route='/', method='GET', host='127.0.0.1'):
        reader, writer = await asyncio.open_connection(*self.address[:2])
        writer.write(f'{method} {route} HTTP/1.1\r\nHost: {host}\r\n\r\n'.encode('ascii'))
        await writer.drain()
        result = await asyncio.wait_for(reader.read(), 2)
        writer.close(); await writer.wait_closed()
        return result

    def room(self, id='match_one'):
        return NS(match_id=id, mode=1, public_match=None, community_lobby='custom', frame=0,
                  template=NS(alliances={0: 0, 1: 1}),
                  peers={0:NS(profile_id='p_alice', name='Alice')},
                  bots={1:NS(name='Computer', profile_id=9)})

    async def test_actual_http_routes_readonly_and_no_files_or_secrets(self):
        for route, mime in (('/',b'text/html'),('/dashboard.js',b'text/javascript'),('/dashboard.css',b'text/css')):
            response=await self.request(route)
            self.assertIn(b'200 OK', response)
            self.assertIn(mime, response)
            self.assertIn(b"frame-ancestors 'none'",response)
        response=await self.request('/api/status')
        data=json.loads(response.split(b'\r\n\r\n')[1])
        self.assertEqual(data['online'][0]['name'],'<img src=x onerror=alert(1)>')
        self.assertEqual(set(data['online'][0]),{'id','name','status'})
        self.assertNotIn('innerHTML',SCRIPT)
        self.assertIn('textContent',SCRIPT)
        for path in ('/../config/host.json','/web-matches.json','/api/stop','/favicon.ico'):
            self.assertIn(b'404 Not Found',await self.request(path))
        self.assertIn(b'405 Method Not Allowed',await self.request('/api/status','POST'))
        self.assertIn(b'403 Forbidden',await self.request('/api/status',host='unrelated.example'))
        self.assertEqual(await self.request('/api/status?page=-1'),b'')
        self.assertEqual(await self.request('/api/status?page=1&page=2'),b'')
        head=await self.request('/',method='HEAD')
        self.assertEqual(head.split(b'\r\n\r\n')[1],b'')

    async def test_durable_results_roster_and_restart_interruption(self):
        room=self.room()
        self.web.record(room,'match_preparing',{})
        self.web.record(room,'match_started',{})
        room.frame=200
        self.web.record(room,'match_completed',{'result':{'complete':True,'winning_alliance':1,'secret':'not public'}})
        self.web.record(room,'match_aborted',{})
        unfinished=self.room('unfinished')
        self.web.record(unfinished,'match_preparing',{})
        await self.web.close()
        rows=read_history(self.path)
        self.assertEqual(len(rows),2)
        result=rows[0]
        self.assertEqual(result['state'],'completed')
        self.assertEqual(result['winning_alliance'],1)
        self.assertEqual(result['seconds'],10)
        self.assertTrue(result['players'][1]['bot'])
        self.assertIsNone(result['players'][1]['id'])
        self.assertNotIn('secret',json.dumps(rows))
        self.web=Dashboard(self.server,self.path)
        self.address=await self.web.start('127.0.0.1',0)
        history=self.web.snapshot()['history']
        self.assertEqual([r['state'] for r in history],['interrupted','completed'])
        self.assertIsNone(history[0]['winning_alliance'])

    async def test_atomic_failure_preserves_prior_history_and_live_view(self):
        self.web.record(self.room(),'match_preparing',{})
        await wait_until(lambda:self.path.exists())
        before=self.path.read_bytes()
        with mock.patch('server.web_dashboard.os.replace',side_effect=OSError('test disk full')):
            self.web.record(self.room(),'match_aborted',{})
            await wait_until(lambda:not self.web.persistence_ok)
            self.assertEqual(self.path.read_bytes(),before)
            self.assertIn(b'200 OK',await self.request('/api/status'))
        self.web.changed.set()
        await wait_until(lambda:self.web.persistence_ok)
        self.assertEqual(read_history(self.path)[0]['state'],'aborted')

    async def test_retention_and_pagination_preserve_active_matches(self):
        for index in range(HISTORY_LIMIT+3):
            room=self.room('match_'+str(index))
            self.web.record(room,'match_preparing',{})
            self.web.record(room,'match_aborted',{})
        self.assertEqual(len(self.web.records),HISTORY_LIMIT)
        snapshot=self.web.snapshot(1)
        self.assertEqual(snapshot['history_total'],HISTORY_LIMIT)
        self.assertEqual(len(snapshot['history']),50)
        self.assertEqual(snapshot['history'][0]['id'],'match_952')
        room=self.room('active');self.server.rooms['room']=room
        self.web.record(room,'match_preparing',{})
        room.frame=80
        self.assertEqual(self.web.snapshot()['active'][0]['seconds'],4)

    async def test_corrupt_history_refused_without_overwriting(self):
        await self.web.close()
        for data in (b'{broken',b'{"schema":1,"matches":[{"id":"bad"}]}',b'['*2000+b']'*2000):
            self.path.write_bytes(data)
            self.web=Dashboard(self.server,self.path)
            with self.assertRaises(ValueError): await self.web.start('127.0.0.1',0)
            await self.web.close()
            self.assertEqual(self.path.read_bytes(),data)

    async def test_slow_http_clients_are_closed_on_shutdown(self):
        reader,writer=await asyncio.open_connection(*self.address[:2])
        writer.write(b'GET / HTTP/1.1\r\n');await writer.drain()
        await wait_until(lambda:bool(self.web.handlers))
        await asyncio.wait_for(self.web.close(),2)
        self.assertEqual(await reader.read(),b'')
        writer.close();await writer.wait_closed()
        self.assertFalse(self.web.handlers)


class DashboardLifecycleTests(DedicatedFixture):
    async def test_real_coordinator_records_complete_and_abort_and_disconnect(self):
        await self.start()
        web=Dashboard(self.server,self.folder/'web-matches.json')
        await web.start('127.0.0.1',0)
        try:
            peers=await self.pair('dashboard')
            self.assertEqual(len(web.snapshot()['online']),2)
            self.assertEqual(web.snapshot()['active'][0]['state'],'running')
            room,_=await self.complete('dashboard',peers)
            self.assertEqual(web.snapshot()['history'][0]['id'],room.match_id)
            self.assertEqual(web.snapshot()['history'][0]['state'],'completed')
            await asyncio.gather(*(peer.close() for peer in peers))
            await wait_until(lambda:not web.snapshot()['online'])
            second=await self.pair('abort')
            room=self.server.rooms['abort']
            await second[0].close()
            await wait_until(lambda:room.state=='closed')
            self.assertEqual(web.snapshot()['history'][0]['state'],'aborted')
            self.assertIsNone(web.snapshot()['history'][0]['winning_alliance'])
        finally:
            await self.server.close()
            await web.close()
        self.assertEqual(len(read_history(self.folder/'web-matches.json')),2)


class HostDashboardTests(unittest.IsolatedAsyncioTestCase):
    async def test_host_lifetime_disabled_check_and_web_failure(self):
        from server import host
        config = NS(data_directory=Path('unused-data'), assets_directory=Path('unused-assets'),
                    log_max_bytes=65536, log_backups=2, diagnostic_audit=False,
                    max_rooms=4, input_window=64, access_mode='rc-open',
                    listen_host='127.0.0.1', listen_port=47623,
                    dashboard_host='127.0.0.1', dashboard_port=47624)
        manifest = dict(game_build=37822, asset_format=1, files={})
        for label in ('normal', 'port_conflict', 'corrupt_history', 'disabled', 'check_only'):
            with self.subTest(label=label):
                server = mock.Mock()
                server.start = mock.AsyncMock(return_value=('127.0.0.1', 47623))
                server.close = mock.AsyncMock()
                server.listener.serve_forever = mock.AsyncMock()
                web = mock.Mock()
                web.start = mock.AsyncMock(return_value=('127.0.0.1', 47624))
                web.close = mock.AsyncMock()
                if label == 'port_conflict': web.start.side_effect = OSError('occupied')
                if label == 'corrupt_history': web.start.side_effect = ValueError('invalid')
                config.dashboard_port = 0 if label == 'disabled' else 47624
                with mock.patch.object(host, 'prepare', return_value=(mock.Mock(), None, None, manifest)), \
                     mock.patch.object(host, 'check_native', mock.AsyncMock(return_value={})), \
                     mock.patch.object(host, 'HostAudit'), mock.patch.object(host, 'ProfileStore'), \
                     mock.patch.object(host, 'DedicatedServer', return_value=server), \
                     mock.patch.object(host, 'Dashboard', return_value=web) as factory, \
                     mock.patch('builtins.print'):
                    await host._run_owned(config, check_only=label == 'check_only')
                if label == 'check_only':
                    server.start.assert_not_awaited()
                else:
                    server.start.assert_awaited_once()
                    server.close.assert_awaited_once()
                if label in ('disabled', 'check_only'):
                    factory.assert_not_called()
                else:
                    web.start.assert_awaited_once_with('127.0.0.1', 47624)
                    web.close.assert_awaited_once()


if __name__=='__main__':unittest.main()
