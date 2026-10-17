"""Actual loopback TLS with ephemeral OpenSSL-generated, locally ignored PKI.

generate_test_pki(folder) is reusable by authenticated-admission integration tests.
No private keys, certificates or bearer credentials are embedded in source.
"""
import asyncio
from pathlib import Path
import os
import secrets
import shutil
import ssl
import subprocess
import time
import unittest
from unittest import mock
import uuid

from server import tls_transport as tls

ROOT = Path(__file__).resolve().parents[1]


def find_openssl():
    candidates = [shutil.which("openssl"),
        r"C:\Program Files\Git\mingw64\bin\openssl.exe",
        r"C:\Program Files\Git\usr\bin\openssl.exe"]
    for candidate in candidates:
        if candidate and Path(candidate).is_file():
            return Path(candidate)
    raise unittest.SkipTest("installed OpenSSL executable unavailable; real-certificate cases not verified")


def generate_test_pki(folder):
    """Create fresh authored PKI under local/; caller owns cleanup of folder.

    Returns ca, cert, key, expired_cert, unrelated_ca, unrelated_key, cn_only_cert,
    encrypted_key and password_file Paths. No host trust store is accessed/changed.
    """
    openssl = find_openssl()
    folder = Path(folder).resolve()
    folder.relative_to((ROOT / "local").resolve())
    folder.mkdir(parents=True, exist_ok=False)

    def run(*arguments):
        result = subprocess.run([str(openssl), *arguments], cwd=folder, stdin=subprocess.DEVNULL,
            stdout=subprocess.PIPE, stderr=subprocess.PIPE, timeout=15,
            creationflags=subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0)
        if result.returncode:
            # Do not echo argv, PEM files, password files or openssl output.
            raise AssertionError("ephemeral OpenSSL fixture generation failed")

    for prefix in ("ca", "unrelated"):
        run("req", "-x509", "-newkey", "rsa:2048", "-nodes", "-days", "2",
            "-keyout", prefix + ".key", "-out", prefix + ".pem", "-subj", "/CN=Authored TLS Test " + prefix,
            "-addext", "basicConstraints=critical,CA:TRUE", "-addext", "keyUsage=critical,keyCertSign,cRLSign",
            "-addext", "subjectKeyIdentifier=hash")
    run("req", "-new", "-newkey", "rsa:2048", "-nodes", "-keyout", "server.key",
        "-out", "server.csr", "-subj", "/CN=localhost")
    common = ("basicConstraints=critical,CA:FALSE\nkeyUsage=critical,digitalSignature,keyEncipherment\n"
              "extendedKeyUsage=serverAuth\nsubjectKeyIdentifier=hash\nauthorityKeyIdentifier=keyid,issuer\n")
    server_ext = common + "subjectAltName=DNS:localhost,DNS:game.test,IP:127.0.0.1\n"
    (folder / "server.ext").write_text(server_ext)
    (folder / "cn-only.ext").write_text(common)
    for name, extensions in (("server", "server.ext"), ("cn-only", "cn-only.ext")):
        run("x509", "-req", "-in", "server.csr", "-CA", "ca.pem", "-CAkey", "ca.key",
            "-CAcreateserial", "-days", "2", "-out", name + ".pem", "-extfile", extensions)
    (folder / "issued").mkdir()
    (folder / "index.txt").write_text("")
    (folder / "serial.txt").write_text("1000\n")
    config = ("[ca]\ndefault_ca=test_ca\n[test_ca]\nnew_certs_dir=issued\n"
              "database=index.txt\nserial=serial.txt\ncertificate=ca.pem\nprivate_key=ca.key\n"
              "default_md=sha256\npolicy=test_policy\nunique_subject=no\n[test_policy]\ncommonName=supplied\n"
              "[server_ext]\n" + server_ext)
    (folder / "ca.cnf").write_text(config)
    run("ca", "-batch", "-config", "ca.cnf", "-in", "server.csr", "-out", "expired.pem", "-notext",
        "-startdate", "20000101000000Z", "-enddate", "20010101000000Z", "-extensions", "server_ext")
    (folder / "password.txt").write_text(secrets.token_urlsafe(32))
    run("pkey", "-in", "server.key", "-aes-256-cbc", "-passout", "file:password.txt", "-out", "encrypted.key")
    return {name: folder / filename for name, filename in dict(ca="ca.pem", cert="server.pem", key="server.key",
        expired_cert="expired.pem", unrelated_ca="unrelated.pem", unrelated_key="unrelated.key",
        cn_only_cert="cn-only.pem", encrypted_key="encrypted.key", password_file="password.txt").items()}


def remove_test_pki(folder):
    folder = Path(folder).resolve()
    folder.relative_to((ROOT / "local").resolve())
    shutil.rmtree(folder)


class TLSParsingTests(unittest.IsolatedAsyncioTestCase):
    def test_expected_dns_ip_normalization_and_bad_names(self):
        for source, expected in (("Game.Example.", "game.example"), ("127.0.0.1", "127.0.0.1"),
                                 ("2001:0db8::1", "2001:db8::1"), ("localhost", "localhost"),
                                 ("münich.example", "xn--mnich-kva.example")):
            self.assertEqual(tls.normalize_server_name(source), expected)
        for value in (None, "", "host:123", "https://host", "127.000.0.1", "*.example", "x..y", "[::1]",
                      "fe80::1%adapter", "a_b", "-host", "host-", "x" * 254, "host\n", "\ud800"):
            with self.subTest(value_type=type(value).__name__):
                with self.assertRaises(tls.TLSConfigurationError): tls.normalize_server_name(value)

    def test_missing_invalid_files_fail_closed(self):
        missing = ROOT / "local/does-not-exist-tls-test.pem"
        with self.assertRaises(tls.TLSConfigurationError): tls.load_server_context(missing, missing)
        with self.assertRaises(tls.TLSConfigurationError): tls.load_client_context(missing, "localhost")

    async def test_close_deadline_aborts_unresponsive_transport(self):
        writer = mock.Mock()
        async def blocked(): await asyncio.Event().wait()
        writer.wait_closed = blocked
        start = time.monotonic()
        self.assertFalse(await tls.close_tls_stream(writer, timeout=0.03))
        self.assertLess(time.monotonic() - start, 1)
        writer.close.assert_called_once()
        writer.transport.abort.assert_called_once()

    async def test_cancelled_close_aborts_and_propagates(self):
        writer = mock.Mock()
        entered = asyncio.Event()
        async def blocked():
            entered.set()
            await asyncio.Event().wait()
        writer.wait_closed = blocked
        pending = asyncio.create_task(tls.close_tls_stream(writer))
        await entered.wait()
        pending.cancel()
        with self.assertRaises(asyncio.CancelledError): await pending
        writer.transport.abort.assert_called_once()


class TLSLoopbackTests(unittest.IsolatedAsyncioTestCase):
    @classmethod
    def setUpClass(cls):
        cls.folder = ROOT / "local/test-runs" / ("tls-" + uuid.uuid4().hex)
        try: cls.pki = generate_test_pki(cls.folder)
        except BaseException:
            if cls.folder.exists(): remove_test_pki(cls.folder)
            raise

    @classmethod
    def tearDownClass(cls):
        remove_test_pki(cls.folder)

    async def asyncSetUp(self):
        self.servers, self.writers, self.handlers, self.received, self.loop_errors = [], [], set(), [], []
        self.loop = asyncio.get_running_loop()
        self.previous_error_handler = self.loop.get_exception_handler()
        self.loop.set_exception_handler(lambda loop, context: self.loop_errors.append(context))

    async def asyncTearDown(self):
        for server in self.servers: server.close()
        await asyncio.gather(*(tls.close_tls_stream(writer, timeout=0.2) for writer in self.writers), return_exceptions=True)
        await asyncio.gather(*(server.wait_closed() for server in self.servers))
        for handler in self.handlers: handler.cancel()
        await asyncio.gather(*self.handlers, return_exceptions=True)
        self.loop.set_exception_handler(self.previous_error_handler)
        for context in self.loop_errors:
            self.assertIsInstance(context.get("exception"), (ssl.SSLError, OSError, TimeoutError), str(context))

    async def echo(self, reader, writer):
        self.handlers.add(asyncio.current_task())
        self.writers.append(writer)
        try:
            message = await reader.readexactly(4)
            self.received.append(message)
            writer.write(message)
            await writer.drain()
        except (OSError, asyncio.IncompleteReadError):
            pass
        finally:
            await tls.close_tls_stream(writer, timeout=0.2)

    async def listener(self, cert="cert", context=None, **kwargs):
        context = context or tls.load_server_context(self.pki[cert], self.pki["key"])
        server = await tls.start_tls_server(self.echo, "127.0.0.1", 0, context, **kwargs)
        self.servers.append(server)
        return server.sockets[0].getsockname()[1]

    async def exchange(self, port, expected="localhost", ca="ca"):
        client = tls.load_client_context(self.pki[ca], expected)
        reader, writer = await tls.open_verified_connection("127.0.0.1", port, client)
        self.writers.append(writer)
        writer.write(b"test")
        await writer.drain()
        self.assertEqual(await asyncio.wait_for(reader.readexactly(4), 2), b"test")
        return writer.get_extra_info("ssl_object").version()

    async def test_verified_dns_and_ip_connections(self):
        port = await self.listener()
        for expected in ("localhost", "game.test", "127.0.0.1"):
            with self.subTest(expected=expected):
                self.assertIn(await self.exchange(port, expected), ("TLSv1.2", "TLSv1.3"))
        self.assertEqual(self.received, [b"test"] * 3)

    async def test_tls12_remains_supported_with_verified_identity(self):
        context = tls.load_server_context(self.pki["cert"], self.pki["key"])
        context.maximum_version = ssl.TLSVersion.TLSv1_2
        self.assertEqual(await self.exchange(await self.listener(context=context)), "TLSv1.2")

    async def test_wrong_host_is_rejected_before_application_data(self):
        port = await self.listener()
        with self.assertRaises(ssl.SSLCertVerificationError) as error:
            await self.exchange(port, "wrong.invalid")
        self.assertEqual(error.exception.verify_code, 62)
        self.assertEqual(self.received, [])

    async def test_untrusted_ca_is_rejected_before_application_data(self):
        port = await self.listener()
        with self.assertRaises(ssl.SSLCertVerificationError):
            await self.exchange(port, ca="unrelated_ca")
        self.assertEqual(self.received, [])

    async def test_expired_certificate_is_rejected(self):
        with self.assertRaises(ssl.SSLCertVerificationError) as error:
            await self.exchange(await self.listener(cert="expired_cert"))
        self.assertEqual(error.exception.verify_code, 10)
        self.assertEqual(self.received, [])

    async def test_common_name_without_subject_alt_name_is_rejected(self):
        with self.assertRaises(ssl.SSLCertVerificationError):
            await self.exchange(await self.listener(cert="cn_only_cert"))
        self.assertEqual(self.received, [])

    def test_contexts_require_minimum_and_explicit_ca(self):
        server = tls.load_server_context(self.pki["cert"], self.pki["key"])
        client = tls.load_client_context(self.pki["ca"], "localhost")
        self.assertEqual(server.minimum_version, ssl.TLSVersion.TLSv1_2)
        self.assertEqual(client.context.minimum_version, ssl.TLSVersion.TLSv1_2)
        self.assertTrue(client.context.check_hostname)
        self.assertEqual(client.context.verify_mode, ssl.CERT_REQUIRED)
        self.assertFalse(client.context.hostname_checks_common_name)
        self.assertEqual(client.context.cert_store_stats()["x509_ca"], 1)

    def test_malformed_ca_cert_key_and_mismatched_key_fail(self):
        invalid = self.folder / "invalid.pem"
        invalid.write_bytes(b"authored invalid PEM test input")
        for cert, key in ((invalid, self.pki["key"]), (self.pki["cert"], invalid),
                          (self.pki["cert"], self.pki["unrelated_key"])):
            with self.assertRaises(tls.TLSConfigurationError): tls.load_server_context(cert, key)
        with self.assertRaises(tls.TLSConfigurationError): tls.load_client_context(invalid, "localhost")

    def test_encrypted_key_never_prompts_and_explicit_provider_works(self):
        with self.assertRaises(tls.TLSConfigurationError):
            tls.load_server_context(self.pki["cert"], self.pki["encrypted_key"])
        context = tls.load_server_context(self.pki["cert"], self.pki["encrypted_key"],
            password_provider=lambda: self.pki["password_file"].read_bytes())
        self.assertEqual(context.protocol, ssl.PROTOCOL_TLS_SERVER)

    async def test_environment_cannot_enable_session_key_logging(self):
        keylog = self.folder / "must-not-create-keylog.log"
        with mock.patch.dict(os.environ, {"SSLKEYLOGFILE": str(keylog)}):
            port = await self.listener()
            await self.exchange(port)
        self.assertFalse(keylog.exists())

    async def test_wrong_role_and_unbounded_timeouts_fail_before_network(self):
        server = tls.load_server_context(self.pki["cert"], self.pki["key"])
        client = tls.load_client_context(self.pki["ca"], "localhost")
        with self.assertRaises(tls.TLSConfigurationError):
            await tls.open_verified_connection("127.0.0.1", 1, tls.ClientTLS(server, "localhost"))
        for value in (None, True, 0, -1, float("nan"), float("inf"), 31):
            with self.subTest(value=value):
                with self.assertRaises(tls.TLSConfigurationError):
                    await tls.open_verified_connection("127.0.0.1", 1, client, handshake_timeout=value)

    async def test_stalled_client_handshake_is_bounded_without_application_callback(self):
        port = await self.listener(handshake_timeout=0.08)
        reader, writer = await asyncio.open_connection("127.0.0.1", port)
        self.writers.append(writer)
        started = time.monotonic()
        try:
            self.assertEqual(await asyncio.wait_for(reader.read(1), 2), b"")
        except ConnectionResetError:
            pass
        self.assertLess(time.monotonic() - started, 1.5)
        self.assertEqual(self.received, [])

    async def test_stalled_server_handshake_has_total_connect_deadline(self):
        disconnected = asyncio.Event()
        async def silent(reader, writer):
            self.handlers.add(asyncio.current_task())
            self.writers.append(writer)
            try:
                while await reader.read(65536): pass
            finally:
                disconnected.set()
                writer.close()
        server = await asyncio.start_server(silent, "127.0.0.1", 0)
        self.servers.append(server)
        port = server.sockets[0].getsockname()[1]
        client = tls.load_client_context(self.pki["ca"], "localhost")
        started = time.monotonic()
        with self.assertRaises(TimeoutError):
            await tls.open_verified_connection("127.0.0.1", port, client,
                connect_timeout=0.08, handshake_timeout=1)
        await asyncio.wait_for(disconnected.wait(), 2)
        self.assertLess(time.monotonic() - started, 1.5)


if __name__ == "__main__":
    unittest.main()
