"""Bounded credential exchange, permitted only inside an established TLS stream.

This prelude precedes the existing game HELLO. No credential payload is logged or
included in public errors. Game/profile identity comes from the credential store.
"""
from __future__ import annotations

import asyncio
from concurrent.futures import ThreadPoolExecutor
import ipaddress
import ssl
import struct
import time

from . import protocol as p
from .credentials import AuthenticationError, CredentialError, PLAYER_ID, TOKEN

AUTH, AUTH_OK, AUTH_VERSION = 20, 30, 1
MAX_AUTH_BODY = 128


class AdmissionError(ValueError):
    def __init__(self, category="invalid"):
        super().__init__("authentication failed")
        self.category = category


async def _receive(reader):
    size, = struct.unpack("<I", await reader.readexactly(4))
    if not 1 <= size <= MAX_AUTH_BODY:
        raise AdmissionError("protocol")
    body = await reader.readexactly(size)
    return body[0], body[1:]


def _require_tls(writer, *, client=False):
    tls = writer.get_extra_info("ssl_object")
    if tls is None or tls.version() not in ("TLSv1.2", "TLSv1.3"):
        raise AdmissionError("tls_required")
    if tls.context.keylog_filename:
        raise AdmissionError("keylogging_forbidden")
    if client and (tls.context.verify_mode != ssl.CERT_REQUIRED or not tls.context.check_hostname
                   or tls.context.hostname_checks_common_name):
        raise AdmissionError("verified_tls_required")


class AdmissionController:
    def __init__(self, store, *, timeout=5.0, max_pending=16, burst=8,
                 attempts_per_second=1.0, max_addresses=4096, clock=time.monotonic):
        if not 0 < timeout <= 30 or type(max_pending) is not int or not 1 <= max_pending <= 256:
            raise ValueError("invalid admission deadline or capacity")
        if (type(burst) is not int or not 1 <= burst <= 64 or not 0 < attempts_per_second <= 10
                or type(max_addresses) is not int or not 1 <= max_addresses <= 65536):
            raise ValueError("invalid admission rate limits")
        self.store, self.timeout, self.max_pending = store, timeout, max_pending
        self.burst, self.rate, self.max_addresses = burst, attempts_per_second, max_addresses
        self.clock, self.addresses = clock, {}
        self.pending, self.verifications = 0, set()
        self.closing = False
        # Credential filesystem delays must not consume the event loop's shared
        # executor, which is also used for worker/process shutdown.
        self._executor = ThreadPoolExecutor(max_workers=max_pending, thread_name_prefix="credential-check")

    def _admit(self, writer):
        if self.closing:
            raise AdmissionError("closed")
        _require_tls(writer)
        peer = writer.get_extra_info("peername")
        try:
            address = str(ipaddress.ip_address(peer[0]))
        except (ValueError, TypeError, IndexError):
            raise AdmissionError("address") from None
        now = self.clock()
        # Expired buckets can be discarded without giving active sources extra
        # attempts. Keep this table bounded even with many different source IPs.
        expiry = max(60.0, self.burst / self.rate)
        self.addresses = {key: row for key, row in self.addresses.items() if now - row[1] < expiry}
        if address not in self.addresses and len(self.addresses) >= self.max_addresses:
            raise AdmissionError("rate_limit")
        tokens, previous = self.addresses.get(address, (float(self.burst), now))
        tokens = min(float(self.burst), tokens + max(0.0, now - previous) * self.rate)
        if tokens < 1.0:
            self.addresses[address] = (tokens, now)
            raise AdmissionError("rate_limit")
        self.addresses[address] = (tokens - 1.0, now)
        if self.pending >= self.max_pending:
            raise AdmissionError("capacity")
        self.pending += 1

    async def authenticate(self, reader, writer):
        """Return a server-issued player ID; caller sends only a generic error."""
        self._admit(writer)
        verification = None
        release_here = True
        deadline = asyncio.get_running_loop().time() + self.timeout
        try:
            kind, payload = await asyncio.wait_for(_receive(reader), self.timeout)
            if kind != AUTH or len(payload) != 49 or payload[:2] != struct.pack("<H", AUTH_VERSION):
                raise AdmissionError("protocol")
            try:
                token = payload[2:].decode("ascii")
            except UnicodeError:
                raise AdmissionError("invalid") from None
            if not TOKEN.fullmatch(token):
                raise AdmissionError("invalid")
            if self.closing:
                raise AdmissionError("closed")
            verification = asyncio.get_running_loop().run_in_executor(self._executor, self.store.authenticate, token)
            self.verifications.add(verification)
            verification.add_done_callback(self.verifications.discard)
            remaining = max(0.0, deadline - asyncio.get_running_loop().time())
            try:
                player_id = await asyncio.wait_for(asyncio.shield(verification), remaining)
            except BaseException:
                if not verification.done():
                    # Cancellation cannot stop filesystem work in a thread.
                    # Retain its capacity reservation until that work finishes.
                    release_here = False
                    def finished(task):
                        self.pending -= 1
                        if not task.cancelled():
                            task.exception()  # Retrieve errors; never log the input.
                    verification.add_done_callback(finished)
                raise
            if self.closing:
                raise AdmissionError("closed")
            if not isinstance(player_id, str) or not PLAYER_ID.fullmatch(player_id):
                raise AdmissionError("storage")
            writer.write(p.encode(AUTH_OK, struct.pack("<H", AUTH_VERSION) + p.encode_string(player_id)))
            await asyncio.wait_for(writer.drain(), max(0.0, deadline - asyncio.get_running_loop().time()))
            return player_id
        except AdmissionError:
            raise
        except AuthenticationError:
            raise AdmissionError("invalid") from None
        except CredentialError:
            raise AdmissionError("storage") from None
        except asyncio.TimeoutError:
            raise AdmissionError("timeout") from None
        except (OSError, asyncio.IncompleteReadError):
            raise AdmissionError("connection") from None
        except Exception:
            # A custom store failure must not reach the coordinator's generic
            # exception logger with arbitrary exception text or credential data.
            raise AdmissionError("internal") from None
        finally:
            if release_here:
                self.pending -= 1

    def stop_accepting(self):
        self.closing = True

    async def close(self, *, timeout=3.0):
        """Stop new admissions and drain bounded verification work if possible.

        Returning False reports pending native filesystem work; it cannot be
        safely interrupted by cancelling its Python awaiter.
        """
        if not 0 < timeout <= 30:
            raise ValueError("invalid admission shutdown timeout")
        self.stop_accepting()
        # Do not cancel queued/running filesystem calls or release reservations
        # early. Python may still wait for these threads at interpreter exit.
        self._executor.shutdown(wait=False, cancel_futures=False)
        pending = list(self.verifications)
        if not pending:
            return True
        finished, _ = await asyncio.wait(pending, timeout=timeout)
        for task in finished:
            if not task.cancelled():
                task.exception()
        return len(finished) == len(pending)


async def authenticate_client(reader, writer, token, *, timeout=5.0):
    """Exchange an in-memory credential only after verified TLS; never use CLI tokens."""
    _require_tls(writer, client=True)
    if not isinstance(token, str) or not TOKEN.fullmatch(token) or not 0 < timeout <= 30:
        raise AdmissionError("invalid")
    async def exchange():
        writer.write(p.encode(AUTH, struct.pack("<H", AUTH_VERSION) + token.encode("ascii")))
        await writer.drain()
        kind, payload = await _receive(reader)
        if (kind != AUTH_OK or len(payload) != 38 or payload[:4] != struct.pack("<HH", AUTH_VERSION, 34)):
            raise AdmissionError("protocol")
        try:
            player = payload[4:].decode("ascii")
        except UnicodeError:
            raise AdmissionError("protocol") from None
        if not PLAYER_ID.fullmatch(player):
            raise AdmissionError("protocol")
        return player
    try:
        return await asyncio.wait_for(exchange(), timeout)
    except (OSError, asyncio.TimeoutError, asyncio.IncompleteReadError):
        raise AdmissionError("connection") from None
