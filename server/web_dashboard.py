"""Read-only host dashboard; bounded summaries, no raw logs or credentials."""
from __future__ import annotations

import asyncio
from collections import OrderedDict
from datetime import datetime, timezone
import ipaddress
import json
import os
from pathlib import Path
import re
import stat
import time
from urllib.parse import parse_qs, urlsplit

from .web_dashboard_page import PAGE, STYLE, SCRIPT

HISTORY_LIMIT = 1000
PAGE_SIZE = 50
MAX_BYTES = 4 * 1024 * 1024
TERMINAL = frozenset(('completed', 'aborted', 'interrupted'))
EVENTS = {'match_preparing': 'preparing', 'match_created': 'loading',
          'match_started': 'running', 'match_completed': 'completed', 'match_aborted': 'aborted'}
MODES = {1: '1v1', 2: '2v2', 5: '2vAI'}


def utc():
    return datetime.now(timezone.utc).isoformat()


def ordinary(path):
    try: info = path.lstat()
    except FileNotFoundError: return
    if not stat.S_ISREG(info.st_mode) or getattr(info, 'st_file_attributes', 0) & 0x400:
        raise ValueError('Dashboard history must be an ordinary file')
    if info.st_size > MAX_BYTES: raise ValueError('Dashboard history exceeds its limit')


def valid_record(row):
    fields = {'id', 'mode', 'kind', 'state', 'created_at', 'started_at', 'ended_at',
              'seconds', 'players', 'winning_alliance'}
    if not isinstance(row, dict) or set(row) != fields: return False
    if not isinstance(row['id'], str) or not re.fullmatch(r'[A-Za-z0-9_-]{1,64}', row['id']): return False
    if type(row['mode']) is not int or row['mode'] not in MODES: return False
    if row['kind'] not in ('Custom', 'Public', 'Direct'): return False
    if row['state'] not in ('preparing', 'loading', 'running', *TERMINAL): return False
    for key in ('created_at', 'started_at', 'ended_at'):
        if row[key] is None and key != 'created_at': continue
        if not isinstance(row[key], str) or len(row[key]) > 40: return False
        try:
            if datetime.fromisoformat(row[key]).tzinfo is None: return False
        except ValueError: return False
    if type(row['seconds']) not in (int, float) or not 0 <= row['seconds'] <= 107374183: return False
    if row['winning_alliance'] is not None and (type(row['winning_alliance']) is not int
                                               or not 0 <= row['winning_alliance'] <= 31): return False
    if not isinstance(row['players'], list) or not 1 <= len(row['players']) <= 4: return False
    for player in row['players']:
        if not isinstance(player, dict) or set(player) != {'id', 'name', 'slot', 'alliance', 'bot'}: return False
        if player['id'] is not None and (not isinstance(player['id'], str)
                                         or not re.fullmatch(r'[A-Za-z0-9_-]{1,48}', player['id'])): return False
        if not isinstance(player['name'], str) or len(player['name']) > 64: return False
        if type(player['bot']) is not bool: return False
        if type(player['slot']) is not int or not 0 <= player['slot'] <= 3: return False
        if type(player['alliance']) is not int or not 0 <= player['alliance'] <= 31: return False
    return True


def read_history(path):
    ordinary(path)
    if not path.exists(): return []
    with path.open('rb') as stream: raw = stream.read(MAX_BYTES + 1)
    try:
        value = json.loads(raw)
    except (ValueError, RecursionError):
        raise ValueError('Invalid dashboard history; existing file preserved') from None
    if (len(raw) > MAX_BYTES or not isinstance(value, dict) or set(value) != {'schema', 'matches'}
            or type(value['schema']) is not int or value['schema'] != 1
            or not isinstance(value['matches'], list) or len(value['matches']) > HISTORY_LIMIT
            or not all(valid_record(row) for row in value['matches'])
            or len({row['id'] for row in value['matches']}) != len(value['matches'])):
        raise ValueError('Invalid dashboard history; existing file preserved')
    return value['matches']


def write_history(path, rows):
    ordinary(path)
    encoded = (json.dumps({'schema': 1, 'matches': rows}, ensure_ascii=True) + '\n').encode('ascii')
    if len(encoded) > MAX_BYTES: raise ValueError('Dashboard history exceeds its limit')
    temporary = path.with_name('.web-matches-' + os.urandom(12).hex() + '.tmp')
    try:
        with temporary.open('xb') as stream:
            stream.write(encoded); stream.flush(); os.fsync(stream.fileno())
        os.replace(temporary, path)
    finally:
        temporary.unlink(missing_ok=True)


class Dashboard:
    def __init__(self, server, path):
        self.server, self.path = server, Path(path)
        self.records = OrderedDict()
        self.listener = self.worker = None
        self.handlers = set()
        self.changed = asyncio.Event()
        self.stopping = False
        self.persistence_ok = True
        self.started = time.monotonic()

    async def start(self, host='127.0.0.1', port=47624):
        ipaddress.IPv4Address(host)
        rows = await asyncio.to_thread(read_history, self.path)
        for row in rows:
            if row['state'] not in TERMINAL:
                row = dict(row, state='interrupted', ended_at=utc(), winning_alliance=None)
                self.changed.set()
            self.records[row['id']] = row
        self.listener = await asyncio.start_server(self.handle, host, port, limit=8192, backlog=32)
        self.server.match_observer = self.record
        self.worker = asyncio.create_task(self.persist())
        return self.listener.sockets[0].getsockname()

    def record(self, room, event, fields):
        if event not in EVENTS or not room.match_id: return
        old = self.records.get(room.match_id)
        if old and old['state'] in TERMINAL: return  # Result cleanup cannot rewrite a finished match.
        now = utc()
        if old is None:
            players = []
            for slot in sorted(room.peers.keys() | room.bots.keys()):
                bot = room.bots.get(slot)
                peer = room.peers.get(slot)
                players.append(dict(id=None if bot else peer.profile_id,
                                    name=(bot.name if bot else peer.name)[:64], slot=slot,
                                    alliance=room.template.alliances[slot], bot=bot is not None))
            old = dict(id=room.match_id, mode=room.mode,
                       kind='Public' if room.public_match else 'Custom' if room.community_lobby else 'Direct',
                       created_at=now, started_at=None, ended_at=None, players=players,
                       seconds=0, winning_alliance=None)
        state = EVENTS[event]
        result = fields.get('result')
        winner = result.get('winning_alliance') if state == 'completed' and isinstance(result, dict) and result.get('complete') else None
        if type(winner) is not int or winner not in {p['alliance'] for p in old['players']}: winner = None
        row = dict(old, state=state, seconds=round(room.frame * .05, 2), winning_alliance=winner,
                   started_at=now if event == 'match_started' else old['started_at'],
                   ended_at=now if state in TERMINAL else None)
        if not valid_record(row):
            self.persistence_ok = False
            return
        self.records[row['id']] = row
        self.records.move_to_end(row['id'])
        while len(self.records) > HISTORY_LIMIT:
            expired = next((key for key, item in self.records.items() if item['state'] in TERMINAL), None)
            if expired is None: break
            del self.records[expired]
        self.changed.set()

    async def persist(self):
        while True:
            await self.changed.wait()
            self.changed.clear()
            try:
                await asyncio.to_thread(write_history, self.path, list(self.records.values()))
                self.persistence_ok = True
            except (OSError, ValueError):
                self.persistence_ok = False
            if self.stopping and not self.changed.is_set(): return
            # Coalesce bursts without putting file I/O or JSON encoding on the match loop.
            await asyncio.sleep(.25)

    def snapshot(self, page=0):
        players = []
        statuses = {0: 'Available', 1: 'In lobby', 2: 'In match', 3: 'Unavailable', 4: 'Searching'}
        for profile, name, status, _ in self.server.community.directory_rows:
            players.append(dict(id=profile, name=name, status=statuses.get(status, 'Connected')))
        active = []
        for room in self.server.rooms.values():
            row = self.records.get(room.match_id)
            if row and row['state'] not in TERMINAL:
                active.append(dict(row, seconds=round(room.frame * .05, 2)))
        history = [row for row in reversed(self.records.values()) if row['state'] in TERMINAL]
        pages = max(1, (len(history) + PAGE_SIZE - 1) // PAGE_SIZE)
        page = min(page, pages - 1)
        return dict(utc=utc(), uptime_seconds=int(time.monotonic()-self.started),
                    online=players, active=active, history=history[page*PAGE_SIZE:(page+1)*PAGE_SIZE],
                    history_total=len(history), history_limit=HISTORY_LIMIT, page=page, pages=pages,
                    completed=sum(row['state']=='completed' for row in history),
                    persistence_ok=self.persistence_ok, closing=self.server.closing)

    async def handle(self, reader, writer):
        task = asyncio.current_task()
        if self.stopping or len(self.handlers) >= 24:
            writer.close()
            return
        self.handlers.add(task)
        try:
            async with asyncio.timeout(5):
                raw = await reader.readuntil(b'\r\n\r\n')
                if len(raw) > 8192: return
                lines = raw.decode('ascii').split('\r\n')
                method, target, version = lines[0].split(' ')
                if version not in ('HTTP/1.0', 'HTTP/1.1'): return
                headers = {}
                for line in lines[1:-2]:
                    name, value = line.split(':', 1)
                    if name.lower() in headers: return
                    headers[name.lower()] = value.strip()
                # Local dashboard cannot be read through an unrelated DNS-rebinding host.
                authority = headers.get('host', '')
                hostname = authority.split(':')[0].lower()
                try: host_ok = bool(ipaddress.IPv4Address(hostname))
                except ValueError: host_ok = hostname == 'localhost'
                if not host_ok:
                    await self.reply(writer, 403, b'Use the server IP address.', 'text/plain'); return
                if method not in ('GET', 'HEAD'):
                    await self.reply(writer, 405, b'Read-only dashboard.', 'text/plain'); return
                if 'transfer-encoding' in headers or headers.get('content-length', '0') != '0': return
                if not target.startswith('/') or target.startswith('//'): return
                route = urlsplit(target)
                if route.path == '/api/status':
                    query = parse_qs(route.query, strict_parsing=True, max_num_fields=1)
                    if set(query) - {'page'}: raise ValueError()
                    page = int(query.get('page', ['0'])[0])
                    if not 0 <= page < HISTORY_LIMIT: raise ValueError()
                    body = json.dumps(self.snapshot(page), ensure_ascii=True).encode('ascii')
                    mime = 'application/json'
                elif route.path in ('/', '/dashboard.css', '/dashboard.js') and not route.query:
                    body, mime = {'/': (PAGE, 'text/html'), '/dashboard.css': (STYLE, 'text/css'),
                                  '/dashboard.js': (SCRIPT, 'text/javascript')}[route.path]
                    body = body.encode('utf-8')
                else:
                    await self.reply(writer, 404, b'Not found.', 'text/plain'); return
                await self.reply(writer, 200, body, mime, head=method == 'HEAD')
        except (ValueError, UnicodeError, asyncio.IncompleteReadError, asyncio.LimitOverrunError):
            pass
        except (OSError, TimeoutError):
            pass
        finally:
            writer.close()
            try: await asyncio.wait_for(writer.wait_closed(), 1)
            except (OSError, TimeoutError): pass
            self.handlers.discard(task)

    @staticmethod
    async def reply(writer, code, body, mime, *, head=False):
        reason = {200:'OK', 403:'Forbidden', 404:'Not Found', 405:'Method Not Allowed'}[code]
        header = (f'HTTP/1.1 {code} {reason}\r\nContent-Type: {mime}; charset=utf-8\r\n'
                  f'Content-Length: {len(body)}\r\nConnection: close\r\nCache-Control: no-store\r\n'
                  "X-Content-Type-Options: nosniff\r\nReferrer-Policy: no-referrer\r\n"
                  "Content-Security-Policy: default-src 'none'; script-src 'self'; style-src 'self'; "
                  "connect-src 'self'; frame-ancestors 'none'; base-uri 'none'\r\n\r\n")
        writer.write(header.encode('ascii') + (b'' if head else body))
        await writer.drain()

    async def close(self):
        self.stopping = True
        if self.server.match_observer == self.record: self.server.match_observer = None
        if self.listener:
            self.listener.close()
        for task in list(self.handlers): task.cancel()
        if self.handlers: await asyncio.gather(*list(self.handlers), return_exceptions=True)
        if self.listener: await self.listener.wait_closed()
        if self.worker:
            self.changed.set()
            await self.worker
            self.worker = None
