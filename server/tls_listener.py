"""Accept/cap raw sockets before handing them to asyncio's maintained TLS stack."""
from __future__ import annotations

import asyncio
import inspect
import ipaddress
import math
import socket
import time


class HandshakeBudget:
    """Event-loop-owned, bounded global/source token buckets and reservations."""
    def __init__(self, *, maximum=32, per_address=4, burst=16, rate=2.0,
                 global_burst=64, global_rate=16.0, max_addresses=4096, clock=time.monotonic):
        from .tls_transport import TLSConfigurationError
        for value, upper in ((maximum, 256), (per_address, 64), (burst, 256),
                             (global_burst, 1024), (max_addresses, 65536)):
            if type(value) is not int or not 1 <= value <= upper:
                raise TLSConfigurationError("invalid TLS handshake capacity")
        for value in (rate, global_rate):
            if type(value) not in (int, float) or not math.isfinite(value) or not 0 < value <= 256:
                raise TLSConfigurationError("invalid TLS handshake rate")
        if per_address > maximum:
            raise TLSConfigurationError("per-address handshake capacity exceeds total")
        self.maximum, self.per_address = maximum, per_address
        self.burst, self.rate = burst, rate
        self.global_burst, self.global_rate = global_burst, global_rate
        self.max_addresses, self.clock = max_addresses, clock
        self.pending, self.active, self.addresses = 0, {}, {}
        self.global_tokens, self.previous = float(global_burst), clock()
        self.next_cleanup = self.previous

    def acquire(self, source):
        # Collapse IPv4-mapped IPv6 so one source cannot obtain two budgets.
        address = ipaddress.ip_address(source)
        key = str(getattr(address, "ipv4_mapped", None) or address)
        now = self.clock()
        if now >= self.next_cleanup:
            expiry = max(60.0, self.burst / self.rate)
            self.addresses = {key: row for key, row in self.addresses.items()
                              if now - row[1] < expiry or key in self.active}
            self.next_cleanup = now + 5.0
        self.global_tokens = min(float(self.global_burst), self.global_tokens +
                                 max(0.0, now - self.previous) * self.global_rate)
        self.previous = now
        if self.pending >= self.maximum or self.active.get(key, 0) >= self.per_address:
            return None, "capacity"
        if key not in self.addresses and len(self.addresses) >= self.max_addresses:
            return None, "address_limit"
        if self.global_tokens < 1.0:
            return None, "global_rate"
        tokens, previous = self.addresses.get(key, (float(self.burst), now))
        tokens = min(float(self.burst), tokens + max(0.0, now - previous) * self.rate)
        if tokens < 1.0:
            self.addresses[key] = tokens, now
            return None, "source_rate"
        self.addresses[key] = tokens - 1.0, now
        self.global_tokens -= 1.0
        self.pending += 1
        self.active[key] = self.active.get(key, 0) + 1
        return key, None

    def release(self, key):
        remaining = self.active[key] - 1
        self.pending -= 1
        if remaining:
            self.active[key] = remaining
        else:
            del self.active[key]


class BoundedTLSServer:
    """Small Server-compatible listener; established streams belong to callback.

    close()/wait_closed() stop accepts and reap pending handshakes. Like an
    asyncio.Server, they do not terminate already established application streams.
    """
    def __init__(self, listener, callback, context, *, budget, handshake_timeout,
                 shutdown_timeout, stream_limit):
        self._socket, self._callback, self._context = listener, callback, context
        self.budget = budget
        self._handshake_timeout, self._shutdown_timeout = handshake_timeout, shutdown_timeout
        self._stream_limit = stream_limit
        self._closed, self._pending, self._clients = False, {}, set()
        self.stats = {key: 0 for key in ("accepted", "established", "handshake_failed", "handler_failed",
                                        "capacity", "address_limit", "global_rate", "source_rate")}
        self._accept_task = asyncio.create_task(self._accept(), name="bounded-tls-accept")

    @property
    def sockets(self):
        return () if self._closed else (self._socket,)

    def is_serving(self):
        return not self._closed and not self._accept_task.done()

    async def _accept(self):
        loop = asyncio.get_running_loop()
        turns = 0
        try:
            while not self._closed:
                connection, peer = await loop.sock_accept(self._socket)
                connection.setblocking(False)
                key, reason = self.budget.acquire(peer[0])
                if key is None:
                    self.stats[reason] += 1
                    connection.close()
                else:
                    self.stats["accepted"] += 1
                    task = asyncio.create_task(self._negotiate(connection), name="bounded-tls-handshake")
                    self._pending[task] = connection, key
                    task.add_done_callback(self._finished)
                # A full kernel queue must not starve application/cleanup tasks.
                turns += 1
                if turns % 64 == 0:
                    await asyncio.sleep(0)
        except asyncio.CancelledError:
            raise
        except Exception:
            self.close()
            raise

    def _finished(self, task):
        connection, key = self._pending.pop(task)
        self.budget.release(key)
        if task.cancelled():
            connection.close()
        elif task.exception() is not None:
            connection.close()
            self.stats["handshake_failed"] += 1

    def _client_finished(self, task, writer):
        self._clients.discard(task)
        if task.cancelled():
            writer.transport.abort()
        elif task.exception() is not None:
            self.stats["handler_failed"] += 1
            writer.transport.abort()

    async def _negotiate(self, connection):
        loop = asyncio.get_running_loop()
        reader = asyncio.StreamReader(limit=self._stream_limit)
        protocol = asyncio.StreamReaderProtocol(reader)
        transport = None
        try:
            transport, _ = await loop.connect_accepted_socket(lambda: protocol, connection,
                ssl=self._context, ssl_handshake_timeout=self._handshake_timeout,
                ssl_shutdown_timeout=self._shutdown_timeout)
            if self._closed:
                transport.abort()
                return
            writer = asyncio.StreamWriter(transport, protocol, reader, loop)
            result = self._callback(reader, writer)
            self.stats["established"] += 1
            if inspect.isawaitable(result):
                # Schedule the application coroutine itself: a wrapper cancelled
                # before its first instruction could leave result unawaited.
                task = asyncio.ensure_future(result)
                self._clients.add(task)
                task.add_done_callback(lambda task: self._client_finished(task, writer))
        except BaseException:
            if transport is not None:
                transport.abort()
            raise

    def close(self):
        if self._closed:
            return
        self._closed = True
        # Windows Proactor must cancel its outstanding AcceptEx while the
        # listener handle is still valid, before closing that handle.
        if self._accept_task is not asyncio.current_task():
            self._accept_task.cancel()
        self._socket.close()
        for task in tuple(self._pending):
            task.cancel()

    async def wait_closed(self):
        await asyncio.gather(self._accept_task, return_exceptions=True)
        await asyncio.gather(*tuple(self._pending), return_exceptions=True)
        # Completion callbacks release all reservations, including cancellation
        # before a newly accepted handshake coroutine ever starts.
        await asyncio.sleep(0)

    async def serve_forever(self):
        try:
            await asyncio.shield(self._accept_task)
        finally:
            self.close()
            await self.wait_closed()


def create_listener(callback, host, port, context, *, backlog, budget,
                    handshake_timeout, shutdown_timeout, stream_limit):
    from .tls_transport import TLSConfigurationError
    try:
        address = ipaddress.ip_address(host)
    except (ValueError, TypeError):
        raise TLSConfigurationError("TLS bind host must be a numeric IPv4 or IPv6 address") from None
    family = socket.AF_INET if address.version == 4 else socket.AF_INET6
    listener = socket.socket(family, socket.SOCK_STREAM)
    try:
        if hasattr(socket, "SO_EXCLUSIVEADDRUSE"):
            listener.setsockopt(socket.SOL_SOCKET, socket.SO_EXCLUSIVEADDRUSE, 1)
        else:
            listener.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        if family == socket.AF_INET6:
            listener.setsockopt(socket.IPPROTO_IPV6, socket.IPV6_V6ONLY, 1)
        listener.bind((str(address), port))
        listener.listen(backlog)
        listener.setblocking(False)
        return BoundedTLSServer(listener, callback, context, budget=budget,
            handshake_timeout=handshake_timeout, shutdown_timeout=shutdown_timeout, stream_limit=stream_limit)
    except BaseException:
        listener.close()
        raise
