"""Explicit verified or RC-unverified TLS streams; admission is separate.

Owner-supplied PEM files are read only. No OS trust-store edits, certificate
generation, plaintext fallback, credential logging or TLS key logging occurs.
"""
from __future__ import annotations

import asyncio
from dataclasses import dataclass
import ipaddress
import math
from pathlib import Path
import re
import ssl
import stat
from typing import Callable

MINIMUM_TLS = ssl.TLSVersion.TLSv1_2
DEFAULT_HANDSHAKE_TIMEOUT = 5.0
DEFAULT_SHUTDOWN_TIMEOUT = 2.0
DEFAULT_CONNECT_TIMEOUT = 10.0
DEFAULT_STREAM_LIMIT = 65536


class TLSConfigurationError(ValueError):
    """Safe configuration error with no private-key/password/payload contents."""


@dataclass(frozen=True)
class ClientTLS:
    context: ssl.SSLContext
    server_hostname: str
    verify_certificate: bool = True


def normalize_server_name(value):
    """Return the expected DNS/IP certificate identity, independently of routing."""
    if not isinstance(value, str) or not 1 <= len(value) <= 253 or any(
            character.isspace() or ord(character) < 32 for character in value):
        raise TLSConfigurationError("expected server name must be a DNS name or unbracketed IP address")
    if any(character in value for character in ("/", "\\", "%", "@", "[", "]", "*", "\0")):
        raise TLSConfigurationError("expected server name must not contain URL, wildcard or zone syntax")
    try:
        return ipaddress.ip_address(value).compressed
    except ValueError:
        if ":" in value or all(character in "0123456789." for character in value):
            raise TLSConfigurationError("invalid expected server IP address") from None
    try:
        name = value.removesuffix(".").encode("idna").decode("ascii").lower()
    except UnicodeError:
        raise TLSConfigurationError("invalid expected server DNS name") from None
    labels = name.split(".")
    if len(name) > 253 or any(not re.fullmatch(r"[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?", label) for label in labels):
        raise TLSConfigurationError("invalid expected server DNS name")
    return name


def _pem_file(value, *, maximum):
    try:
        path = Path(value)
        information = path.stat()
        if not stat.S_ISREG(information.st_mode) or not 0 < information.st_size <= maximum:
            raise TLSConfigurationError("TLS input must be a bounded nonempty regular PEM file")
        return path
    except (OSError, TypeError, ValueError):
        raise TLSConfigurationError("TLS PEM file is missing, inaccessible or outside size limits") from None


def _password_required():
    # Passing a callable also prevents OpenSSL from falling back to a console
    # password prompt during server startup.
    raise TLSConfigurationError("encrypted private key requires an explicit password provider")


def load_server_context(cert_file, key_file, *, password_provider: Callable[[], str | bytes] | None = None):
    cert = _pem_file(cert_file, maximum=1024 * 1024)
    key = _pem_file(key_file, maximum=65536)
    if password_provider is not None and not callable(password_provider):
        raise TLSConfigurationError("private-key password provider must be callable")
    context = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
    context.minimum_version = MINIMUM_TLS
    try:
        context.load_cert_chain(cert, key, password=password_provider or _password_required)
    except TLSConfigurationError:
        raise
    except (OSError, ValueError, TypeError):
        raise TLSConfigurationError("cannot load a matching server certificate/private key") from None
    return context


def load_client_context(ca_bundle, server_name):
    expected = normalize_server_name(server_name)
    ca = _pem_file(ca_bundle, maximum=4 * 1024 * 1024)
    # Unlike create_default_context(), the constructor does not honor the ambient
    # SSLKEYLOGFILE variable. PROTOCOL_TLS_CLIENT enables required peer validation
    # and hostname checking; only this explicitly enrolled CA bundle is loaded.
    context = ssl.SSLContext(ssl.PROTOCOL_TLS_CLIENT)
    context.minimum_version = MINIMUM_TLS
    context.hostname_checks_common_name = False  # Require DNS/IP subjectAltName.
    try:
        context.load_verify_locations(cafile=str(ca))
    except (OSError, ValueError):
        raise TLSConfigurationError("cannot load the explicit CA trust bundle") from None
    result = ClientTLS(context, expected)
    _validate_client(result)
    return result


def rc_client_context(server_host):
    """Explicit RC transport: encryption without certificate/hostname validation."""
    context = ssl.SSLContext(ssl.PROTOCOL_TLS_CLIENT)
    context.minimum_version = MINIMUM_TLS
    context.check_hostname = False
    context.verify_mode = ssl.CERT_NONE
    return ClientTLS(context, normalize_server_name(server_host), False)


def _validate_common(context, protocol):
    if (not isinstance(context, ssl.SSLContext) or context.protocol != protocol
            or context.minimum_version < MINIMUM_TLS or context.keylog_filename is not None):
        raise TLSConfigurationError("TLS context must preserve its role, minimum version and disabled key logging")


def _validate_client(tls):
    if not isinstance(tls, ClientTLS):
        raise TLSConfigurationError("a ClientTLS configuration is required")
    _validate_common(tls.context, ssl.PROTOCOL_TLS_CLIENT)
    if tls.verify_certificate is False:
        if (tls.context.verify_mode != ssl.CERT_NONE or tls.context.check_hostname
                or normalize_server_name(tls.server_hostname) != tls.server_hostname):
            raise TLSConfigurationError('Invalid RC TLS configuration')
        return
    if tls.verify_certificate is not True:
        raise TLSConfigurationError('Invalid certificate verification setting')
    if (tls.context.verify_mode != ssl.CERT_REQUIRED or not tls.context.check_hostname
            or tls.context.hostname_checks_common_name
            or normalize_server_name(tls.server_hostname) != tls.server_hostname):
        raise TLSConfigurationError("client TLS requires certificate and subjectAltName verification")


def _timeout(value, maximum, name):
    if type(value) not in (int, float) or not math.isfinite(value) or not 0 < value <= maximum:
        raise TLSConfigurationError(name + " must be finite, positive and within its bound")
    return float(value)


def _stream_limit(value):
    if type(value) is not int or not 1024 <= value <= 2 * 1024 * 1024:
        raise TLSConfigurationError("stream limit must be in1024..2097152 bytes")
    return value


async def open_verified_connection(host, port, tls: ClientTLS, *, connect_timeout=DEFAULT_CONNECT_TIMEOUT,
        handshake_timeout=DEFAULT_HANDSHAKE_TIMEOUT, shutdown_timeout=DEFAULT_SHUTDOWN_TIMEOUT,
        stream_limit=DEFAULT_STREAM_LIMIT):
    """Return TLS streams using the explicit ClientTLS policy; no plaintext retry.

    host routes the TCP connection; tls.server_hostname is the enrolled identity
    checked against the certificate in verified mode. RC mode explicitly skips
    that validation. No verification failure automatically switches modes.
    """
    _validate_client(tls)
    total = _timeout(connect_timeout, 60, "connect timeout")
    handshake = _timeout(handshake_timeout, 30, "handshake timeout")
    shutdown = _timeout(shutdown_timeout, 10, "shutdown timeout")
    limit = _stream_limit(stream_limit)
    if type(port) is not int or not 1 <= port <= 65535:
        raise TLSConfigurationError("connection port must be in1..65535")
    async with asyncio.timeout(total):
        reader, writer = await asyncio.open_connection(host, port, ssl=tls.context,
            server_hostname=tls.server_hostname, ssl_handshake_timeout=handshake,
            ssl_shutdown_timeout=shutdown, limit=limit)
    if writer.get_extra_info("ssl_object") is None:
        writer.transport.abort()
        raise TLSConfigurationError("verified TLS transport was not established")
    return reader, writer


async def start_tls_server(client_connected, host, port, context, *, handshake_timeout=DEFAULT_HANDSHAKE_TIMEOUT,
        shutdown_timeout=DEFAULT_SHUTDOWN_TIMEOUT, stream_limit=DEFAULT_STREAM_LIMIT, backlog=128,
        max_handshakes=32, max_handshakes_per_address=4, handshake_burst=16,
        handshakes_per_second=2.0, global_handshake_burst=64, global_handshakes_per_second=16.0,
        max_addresses=4096):
    """Start TLS-only listener; callback runs after the TLS handshake.

    Raw accepts are bounded before TLS allocation by global/source capacity and
    token buckets. The application callback owns established streams and AUTH.
    """
    _validate_common(context, ssl.PROTOCOL_TLS_SERVER)
    handshake = _timeout(handshake_timeout, 30, "handshake timeout")
    shutdown = _timeout(shutdown_timeout, 10, "shutdown timeout")
    limit = _stream_limit(stream_limit)
    if type(port) is not int or not 0 <= port <= 65535:
        raise TLSConfigurationError("listener port must be in0..65535")
    if type(backlog) is not int or not 1 <= backlog <= 1024:
        raise TLSConfigurationError("listener backlog must be in1..1024")
    from .tls_listener import HandshakeBudget, create_listener
    budget = HandshakeBudget(maximum=max_handshakes, per_address=max_handshakes_per_address,
        burst=handshake_burst, rate=handshakes_per_second, global_burst=global_handshake_burst,
        global_rate=global_handshakes_per_second, max_addresses=max_addresses)
    return create_listener(client_connected, host, port, context, backlog=backlog, budget=budget,
        handshake_timeout=handshake, shutdown_timeout=shutdown, stream_limit=limit)


async def close_tls_stream(writer, *, timeout=DEFAULT_SHUTDOWN_TIMEOUT):
    """Return True on graceful close, False on bounded abort; propagate cancellation."""
    timeout = _timeout(timeout, 10, "close timeout")
    writer.close()
    try:
        async with asyncio.timeout(timeout):
            await writer.wait_closed()
        return True
    except asyncio.CancelledError:
        writer.transport.abort()
        raise
    except (OSError, TimeoutError):
        writer.transport.abort()
        return False
