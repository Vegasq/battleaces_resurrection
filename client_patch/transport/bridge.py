"""Explicit verified/invite or RC-open TLS behind a private inherited stream.

There is no local listener, credential CLI argument or plaintext remote fallback.
One inherited connection can carry successive game sessions with monotonic IDs.
"""
from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
import ssl
import struct

from server.admission import authenticate_client, AdmissionError
from server.credentials import PLAYER_ID, TOKEN
from server import tls_transport as tls

VERSION = 1
DYNAMIC_VERSION = 2
OPEN, DATA, CLOSE, FAILURE = 1, 2, 3, 4
READY = 5
TLS_FAILURE, CONNECT_FAILURE, AUTH_FAILURE, IDENTITY_FAILURE = 1, 2, 3, 4
QUEUE_FAILURE, INTERNAL_FAILURE, TIMEOUT_FAILURE = 5, 6, 7
UNCONFIGURED_FAILURE, CONFIG_FAILURE = 8, 9
CHUNK = 65536
MAX_BODY = CHUNK + 6
QUEUE_BYTES, QUEUE_MESSAGES = 2 * 1024 * 1024, 64


class BridgeProtocolError(ValueError):
    def __init__(self):
        super().__init__('invalid private transport protocol')


class IdentityError(ValueError):
    pass


class RemoteUnavailable(ValueError):
    """Local availability only; never includes paths, invites or config contents."""
    def __init__(self, reason=UNCONFIGURED_FAILURE):
        if reason not in (UNCONFIGURED_FAILURE, CONFIG_FAILURE):
            raise ValueError('invalid local availability reason')
        self.reason = reason
        super().__init__('online connection is not configured or locally available')


def valid_ready(payload):
    if len(payload) != 34:
        return False
    try:
        return bool(PLAYER_ID.fullmatch(payload.decode('ascii')))
    except UnicodeError:
        return False


def encode(kind, session, payload=b'', *, version=VERSION):
    if (type(version) is not int or version not in (VERSION, DYNAMIC_VERSION)
            or type(session) is not int or not 1 <= session <= 0xffffffff
            or kind not in ((OPEN, DATA, CLOSE, FAILURE, READY) if version == DYNAMIC_VERSION else (OPEN, DATA, CLOSE, FAILURE))
            or not isinstance(payload, bytes)
            or len(payload) > CHUNK or (kind in (OPEN, CLOSE) and payload)
            or (kind == DATA and not payload)
            or (kind == READY and not valid_ready(payload))
            or (kind == FAILURE and (len(payload) != 1 or not TLS_FAILURE <= payload[0] <=
                                    (CONFIG_FAILURE if version == DYNAMIC_VERSION else TIMEOUT_FAILURE)))):
        raise BridgeProtocolError()
    return struct.pack('<IBBI', len(payload) + 6, version, kind, session) + payload


async def receive(reader, *, version=VERSION):
    length, = struct.unpack('<I', await reader.readexactly(4))
    if not 6 <= length <= MAX_BODY:
        raise BridgeProtocolError()
    body = await reader.readexactly(length)
    received_version, kind, session = struct.unpack_from('<BBI', body)
    if received_version != version:
        raise BridgeProtocolError()
    payload = body[6:]
    encode(kind, session, payload, version=version)  # Same bounds in both directions.
    return kind, session, payload


@dataclass(frozen=True)
class Remote:
    host: str
    port: int
    tls: tls.ClientTLS
    player_id: str
    token: str = field(repr=False)

    def __post_init__(self):
        tls.normalize_server_name(self.host)
        if (type(self.port) is not int or not 1 <= self.port <= 65535
                or not isinstance(self.player_id, str) or not PLAYER_ID.fullmatch(self.player_id)
                or not isinstance(self.token, str) or not TOKEN.fullmatch(self.token)):
            raise ValueError('invalid secure transport settings')


class Session:
    def __init__(self, owner, identity):
        self.owner, self.identity = owner, identity
        self.queue, self.queued_bytes = asyncio.Queue(maxsize=QUEUE_MESSAGES), 0
        self.remote_writer = None
        self.authenticated = False
        self.ready_sent = False
        self.task = asyncio.create_task(self.run(), name='authenticated-game-session')
        self.task.add_done_callback(self.finished)

    def finished(self, task):
        if not task.cancelled() and task.exception() is not None:
            # A failed local write cannot be reported over that same stream.
            # Abort it so the game observes EOF instead of waiting indefinitely.
            self.owner.writer.transport.abort()

    def enqueue(self, data):
        if self.task.done():
            return
        if self.queued_bytes + len(data) > QUEUE_BYTES or self.queue.full():
            raise asyncio.QueueFull()
        self.queue.put_nowait(data)
        self.queued_bytes += len(data)

    async def upload(self, writer):
        while True:
            data = await self.queue.get()
            self.queued_bytes -= len(data)
            writer.write(data)
            await asyncio.wait_for(writer.drain(), 5)

    async def download(self, reader):
        while data := await reader.read(CHUNK):
            await self.owner.send(DATA, self.identity, data)

    async def run(self):
        children = []
        failure = None
        try:
            remote = await self.owner.resolve_remote()
            reader, self.remote_writer = await tls.open_verified_connection(remote.host, remote.port, remote.tls)
            identity = await authenticate_client(reader, self.remote_writer, remote.token,
                                                 rc_open=not remote.tls.verify_certificate)
            if identity != remote.player_id:
                raise IdentityError()
            self.authenticated = True
            if self.owner.version == DYNAMIC_VERSION:
                # Only authenticated public identity crosses this boundary.
                # The game builds its HELLO after receiving this session's READY.
                await self.owner.send(READY, self.identity, identity.encode('ascii'))
            children = [asyncio.create_task(self.upload(self.remote_writer)),
                        asyncio.create_task(self.download(reader))]
            finished, _ = await asyncio.wait(children, return_when=asyncio.FIRST_COMPLETED)
            for task in finished:
                task.result()
        except asyncio.CancelledError:
            raise
        except ssl.SSLCertVerificationError:
            failure = TLS_FAILURE
        except (ssl.SSLError, tls.TLSConfigurationError):
            failure = TLS_FAILURE
        except AdmissionError:
            failure = AUTH_FAILURE
        except IdentityError:
            failure = IDENTITY_FAILURE
        except RemoteUnavailable as error:
            failure = error.reason if self.owner.version == DYNAMIC_VERSION else INTERNAL_FAILURE
        except TimeoutError:
            failure = TIMEOUT_FAILURE
        except (OSError, asyncio.IncompleteReadError):
            failure = CONNECT_FAILURE
        except Exception:
            failure = INTERNAL_FAILURE
        finally:
            for task in children: task.cancel()
            await asyncio.gather(*children, return_exceptions=True)
            if self.remote_writer is not None:
                await tls.close_tls_stream(self.remote_writer)
            # Do not retain stale session input while waiting for a new OPEN.
            while not self.queue.empty(): self.queue.get_nowait()
            self.queued_bytes = 0
        if failure is not None:
            await self.owner.send(FAILURE, self.identity, bytes([failure]))
        else:
            await self.owner.send(CLOSE, self.identity)

    async def close(self):
        self.task.cancel()
        await asyncio.gather(self.task, return_exceptions=True)


class Bridge:
    """Own one inherited socket stream, one remote session and bounded queues."""
    def __init__(self, reader, writer, remote, *, version=VERSION):
        if (version not in (VERSION, DYNAMIC_VERSION) or type(version) is not int
                or (version == VERSION and not isinstance(remote, Remote))
                or (remote is not None and not isinstance(remote, Remote) and not callable(remote))):
            raise ValueError('invalid private bridge configuration')
        self.reader, self.writer, self.remote = reader, writer, remote
        self.version = version
        self.session, self.last_session = None, 0
        self.send_lock = asyncio.Lock()

    async def resolve_remote(self):
        if self.remote is None:
            raise RemoteUnavailable()
        if isinstance(self.remote, Remote):
            return self.remote
        # The parent may reload local settings/invite on every OPEN. Cancellation
        # must stop before TLS/AUTH if that request has already been retired.
        async with asyncio.timeout(5):
            remote = await self.remote()
        if not isinstance(remote, Remote):
            raise RemoteUnavailable(CONFIG_FAILURE)
        return remote

    async def send(self, kind, identity, data=b''):
        async with asyncio.timeout(5):
            async with self.send_lock:
                self.writer.write(encode(kind, identity, data, version=self.version))
                if kind == READY and self.session is not None and self.session.identity == identity:
                    # READY is now in the ordered private stream. Mark before
                    # drain can yield to a client replying to those bytes.
                    self.session.ready_sent = True
                await self.writer.drain()

    async def close_session(self):
        session, self.session = self.session, None
        if session is not None:
            await session.close()

    async def run(self):
        turns = 0
        try:
            while True:
                kind, identity, data = await receive(self.reader, version=self.version)
                turns += 1
                if turns % 64 == 0:
                    await asyncio.sleep(0)
                if kind == OPEN:
                    if identity != self.last_session + 1:
                        raise BridgeProtocolError()
                    await self.close_session()
                    self.last_session = identity
                    self.session = Session(self, identity)
                elif identity > self.last_session or kind in (FAILURE, READY):
                    raise BridgeProtocolError()
                elif identity < self.last_session or self.session is None:
                    continue  # Discard bounded late data from a retired session.
                elif kind == CLOSE:
                    await self.close_session()
                    await self.send(CLOSE, identity)
                elif kind == DATA:
                    if self.version == DYNAMIC_VERSION and not self.session.ready_sent:
                        raise BridgeProtocolError()
                    try:
                        self.session.enqueue(data)
                    except asyncio.QueueFull:
                        await self.close_session()
                        await self.send(FAILURE, identity, bytes([QUEUE_FAILURE]))
        except (BridgeProtocolError, OSError, asyncio.IncompleteReadError, TimeoutError):
            pass  # Fixed protocol errors, never arbitrary contents or tokens.
        finally:
            await self.close_session()
            self.writer.close()
            try:
                await asyncio.wait_for(self.writer.wait_closed(), 2)
            except (OSError, TimeoutError):
                self.writer.transport.abort()
