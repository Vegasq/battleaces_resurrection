"""Verified remote TLS/authentication behind a private inherited client stream.

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
OPEN, DATA, CLOSE, FAILURE = 1, 2, 3, 4
TLS_FAILURE, CONNECT_FAILURE, AUTH_FAILURE, IDENTITY_FAILURE = 1, 2, 3, 4
QUEUE_FAILURE, INTERNAL_FAILURE, TIMEOUT_FAILURE = 5, 6, 7
CHUNK = 65536
MAX_BODY = CHUNK + 6
QUEUE_BYTES, QUEUE_MESSAGES = 2 * 1024 * 1024, 64


class BridgeProtocolError(ValueError):
    def __init__(self):
        super().__init__('invalid private transport protocol')


class IdentityError(ValueError):
    pass


def encode(kind, session, payload=b''):
    if (type(session) is not int or not 1 <= session <= 0xffffffff
            or kind not in (OPEN, DATA, CLOSE, FAILURE) or not isinstance(payload, bytes)
            or len(payload) > CHUNK or (kind in (OPEN, CLOSE) and payload)
            or (kind == DATA and not payload)
            or (kind == FAILURE and (len(payload) != 1 or not TLS_FAILURE <= payload[0] <= TIMEOUT_FAILURE))):
        raise BridgeProtocolError()
    return struct.pack('<IBBI', len(payload) + 6, VERSION, kind, session) + payload


async def receive(reader):
    length, = struct.unpack('<I', await reader.readexactly(4))
    if not 6 <= length <= MAX_BODY:
        raise BridgeProtocolError()
    body = await reader.readexactly(length)
    version, kind, session = struct.unpack_from('<BBI', body)
    if version != VERSION:
        raise BridgeProtocolError()
    payload = body[6:]
    encode(kind, session, payload)  # Same bounds in both directions.
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
            remote = self.owner.remote
            reader, self.remote_writer = await tls.open_verified_connection(remote.host, remote.port, remote.tls)
            identity = await authenticate_client(reader, self.remote_writer, remote.token)
            if identity != remote.player_id:
                raise IdentityError()
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
    def __init__(self, reader, writer, remote):
        self.reader, self.writer, self.remote = reader, writer, remote
        self.session, self.last_session = None, 0
        self.send_lock = asyncio.Lock()

    async def send(self, kind, identity, data=b''):
        async with asyncio.timeout(5):
            async with self.send_lock:
                self.writer.write(encode(kind, identity, data))
                await self.writer.drain()

    async def close_session(self):
        session, self.session = self.session, None
        if session is not None:
            await session.close()

    async def run(self):
        turns = 0
        try:
            while True:
                kind, identity, data = await receive(self.reader)
                turns += 1
                if turns % 64 == 0:
                    await asyncio.sleep(0)
                if kind == OPEN:
                    if identity != self.last_session + 1:
                        raise BridgeProtocolError()
                    await self.close_session()
                    self.last_session = identity
                    self.session = Session(self, identity)
                elif identity > self.last_session or kind == FAILURE:
                    raise BridgeProtocolError()
                elif identity < self.last_session or self.session is None:
                    continue  # Discard bounded late data from a retired session.
                elif kind == CLOSE:
                    await self.close_session()
                    await self.send(CLOSE, identity)
                elif kind == DATA:
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
