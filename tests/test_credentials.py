"""Auth/persistence logic uses an explicitly mocked OS privacy boundary.

The opt-in Windows DACL test uses the real implementation, reporting sandbox
permission limits separately. No tokens or credential fixtures are committed.
"""
import base64
from concurrent.futures import ThreadPoolExecutor
from contextlib import redirect_stderr, redirect_stdout
import hashlib
import io
import json
import os
from pathlib import Path
import secrets
import shutil
import subprocess
import sys
import unittest
from unittest import mock
import uuid

from server import credentials as c

ROOT = Path(__file__).resolve().parents[1]


def private_test_folder(prefix):
    path = ROOT / "local/test-runs" / (prefix + uuid.uuid4().hex)
    path.mkdir(parents=True)
    return path


def remove_test_folder(path):
    resolved = path.resolve()
    resolved.relative_to((ROOT / "local/test-runs").resolve())
    shutil.rmtree(resolved)


class CredentialsTests(unittest.TestCase):
    def setUp(self):
        self.folder = private_test_folder("credentials-")
        # Windows restricted execution may deny a deliberately owner-only DACL.
        # Mock only that boundary; actual locks, fsync, replace, and parsing run.
        self.patches = [
            mock.patch.object(c, "_ensure_private_directory", side_effect=lambda path: path.mkdir(parents=True, exist_ok=True)),
            mock.patch.object(c, "_assert_private_path"),
            mock.patch.object(c, "_private_create", side_effect=lambda path: path.open("x+b")),
        ]
        for patch in self.patches: patch.start()
        self.store = c.CredentialStore(self.folder / "store")

    def tearDown(self):
        for patch in reversed(self.patches): patch.stop()
        remove_test_folder(self.folder)

    def issue(self, name="player", **kwargs):
        output = self.folder / (name + ".credential.json")
        public = self.store.issue_to_file(output, **kwargs)
        return public, c.read_credential_file(output)

    def test_issue_hash_only_private_handoff_and_persistence(self):
        public, handoff = self.issue(label="Player One")
        self.assertEqual(len(handoff["token"]), 47)
        self.assertEqual(len(base64.urlsafe_b64decode(handoff["token"][4:] + "=")), 32)
        self.assertEqual(self.store.authenticate(handoff["token"]), public["player_id"])
        stored = self.store.path.read_text()
        self.assertNotIn(handoff["token"], stored)
        self.assertIn(hashlib.sha256(handoff["token"].encode()).hexdigest(), stored)
        self.assertNotIn("token_sha256", public)
        self.assertNotIn("token", public)
        reopened = c.CredentialStore(self.store.directory)
        self.assertEqual(reopened.authenticate(handoff["token"]), public["player_id"])
        self.assertEqual(reopened.list_public(), [public])

    def test_bad_revoked_and_profile_mismatch_are_generic_and_revocation_is_live(self):
        public, handoff = self.issue()
        second_store = c.CredentialStore(self.store.directory)
        failures = []
        for token, expected in (("ba1_" + secrets.token_urlsafe(32), None),
                                (handoff["token"], "p_" + secrets.token_hex(16))):
            with self.assertRaises(c.AuthenticationError) as error:
                second_store.authenticate(token, expected_player_id=expected)
            failures.append(str(error.exception))
        self.assertTrue(self.store.revoke(public["invite_id"]))
        self.assertFalse(self.store.revoke(public["invite_id"]))
        with self.assertRaises(c.AuthenticationError) as error:
            second_store.authenticate(handoff["token"])
        failures.append(str(error.exception))
        self.assertEqual(set(failures), {"invalid or revoked credential"})
        self.assertIsNotNone(second_store.list_public()[0]["revoked_at"])

    def test_server_issued_profile_binding_survives_explicit_reissue(self):
        original, first = self.issue("original")
        replacement, second = self.issue("replacement", player_id=original["player_id"])
        self.assertEqual(original["player_id"], replacement["player_id"])
        self.assertNotEqual(original["invite_id"], replacement["invite_id"])
        self.assertNotEqual(first["token"], second["token"])
        self.store.revoke(original["invite_id"])
        self.assertEqual(self.store.authenticate(second["token"], expected_player_id=original["player_id"]), original["player_id"])
        with self.assertRaises(c.CredentialError):
            self.issue("forged", player_id="p_" + secrets.token_hex(16))
        self.assertFalse((self.folder / "forged.credential.json").exists())

    def test_strict_bounded_and_canonical_token_parsing(self):
        _, handoff = self.issue()
        alphabet = "ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789-_"
        token = handoff["token"]
        noncanonical = token[:-1] + alphabet[alphabet.index(token[-1]) | 1]
        for bad in (None, b"", 1, "", " " + token, token + "\n", "z" * 1000000,
                    token.replace("ba1_", "ba2_"), noncanonical, "\ud800" * 47):
            with self.subTest(kind=type(bad).__name__, length=len(bad) if isinstance(bad, (str, bytes)) else None):
                with self.assertRaises(c.AuthenticationError):
                    self.store.authenticate(bad)

    def test_digest_comparison_scans_all_fixed_size_records(self):
        _, first = self.issue("one")
        self.issue("two")
        self.issue("three")
        compare = c.hmac.compare_digest
        with mock.patch.object(c.hmac, "compare_digest", wraps=compare) as comparisons:
            self.store.authenticate(first["token"])
            self.assertEqual(comparisons.call_count, 3)
            self.assertTrue(all(len(call.args[0]) == len(call.args[1]) == 64 for call in comparisons.call_args_list))

    def test_existing_output_is_never_overwritten_or_deleted(self):
        output = self.folder / "existing.credential.json"
        original = b"authored pre-existing file"
        output.write_bytes(original)
        with self.assertRaises(c.CredentialError):
            self.store.issue_to_file(output)
        self.assertEqual(output.read_bytes(), original)
        self.assertEqual(self.store.list_public(), [])

    def test_commit_failure_keeps_old_store_and_removes_unactivated_handoff(self):
        public, handoff = self.issue("existing")
        before = self.store.path.read_bytes()
        with mock.patch.object(c.os, "replace", side_effect=OSError("authored disk failure")):
            with self.assertRaises(c.CredentialError): self.issue("failed")
            with self.assertRaises(c.CredentialError): self.store.revoke(public["invite_id"])
        self.assertEqual(self.store.path.read_bytes(), before)
        self.assertFalse((self.folder / "failed.credential.json").exists())
        self.assertEqual(list(self.store.directory.glob("*.tmp")), [])
        self.assertEqual(self.store.authenticate(handoff["token"]), public["player_id"])

    def test_handoff_flush_failure_does_not_activate_token(self):
        with mock.patch.object(c.os, "fsync", side_effect=OSError("authored flush failure")):
            with self.assertRaises(c.CredentialError): self.issue("failed")
        self.assertFalse((self.folder / "failed.credential.json").exists())
        self.assertEqual(self.store.list_public(), [])

    def test_preexisting_atomic_temporary_collision_is_not_deleted(self):
        public, handoff = self.issue()
        temporary = self.store.directory / (".credentials-" + "ab" * 16 + ".tmp")
        marker = b"authored pre-existing temporary path"
        temporary.write_bytes(marker)
        with mock.patch.object(c.secrets, "token_hex", return_value="ab" * 16):
            with self.assertRaises(c.CredentialError): self.store.revoke(public["invite_id"])
        self.assertEqual(temporary.read_bytes(), marker)
        self.assertEqual(self.store.authenticate(handoff["token"]), public["player_id"])

    def test_malformed_store_never_resets_or_authorizes(self):
        _, handoff = self.issue()
        original = json.loads(self.store.path.read_text())
        cases = [b"{", b'{"schema":1,"schema":1,"invites":[]}', b"[]", b"null",
                 json.dumps(dict(original, schema=True)).encode(), b" " * (c.MAX_STORE_BYTES + 1)]
        for field, value in (("player_id", "client_supplied_name"), ("token_sha256", "bad"),
                             ("created_at", True), ("revoked_at", -1), ("label", "\ud800")):
            changed = json.loads(json.dumps(original))
            changed["invites"][0][field] = value
            cases.append(json.dumps(changed).encode())
        duplicate = json.loads(json.dumps(original))
        duplicate["invites"].append(duplicate["invites"][0])
        cases.append(json.dumps(duplicate).encode())
        for index, bad in enumerate(cases):
            with self.subTest(index=index):
                self.store.path.write_bytes(bad)
                with self.assertRaises(c.CredentialError): self.store.authenticate(handoff["token"])
                with self.assertRaises(c.CredentialError): self.store.list_public()
                self.assertEqual(self.store.path.read_bytes(), bad)

    def test_handoff_reader_rejects_extra_fields_wrong_identity_and_oversize(self):
        _, handoff = self.issue()
        path = self.folder / "malformed.credential.json"
        for value in (dict(handoff, schema=True), dict(handoff, player_id="chosen_name"),
                      dict(handoff, extra=True), {"schema": 1}):
            path.write_text(json.dumps(value))
            with self.assertRaises(c.CredentialError): c.read_credential_file(path)
        path.write_bytes(b" " * (c.MAX_CREDENTIAL_BYTES + 1))
        with self.assertRaises(c.CredentialError): c.read_credential_file(path)

    def test_concurrent_writers_keep_all_records(self):
        def issue(number):
            return self.issue("parallel_" + str(number))[0]
        with ThreadPoolExecutor(max_workers=4) as pool:
            records = list(pool.map(issue, range(12)))
        self.assertEqual(len(self.store.list_public()), 12)
        self.assertEqual(len({record["player_id"] for record in records}), 12)

    def test_separate_process_writer_lock_and_persistence(self):
        # Authored subprocess fixture explicitly mocks only the same OS privacy
        # boundary. The production cross-process lock/atomic storage is retained.
        script = ("from pathlib import Path\nimport sys\nfrom server import credentials as c\n"
                  "c._ensure_private_directory=lambda p:p.mkdir(parents=True,exist_ok=True)\n"
                  "c._assert_private_path=lambda *a,**k:None\n"
                  "c._private_create=lambda p:p.open('x+b')\n"
                  "c.CredentialStore(Path(sys.argv[1])).issue_to_file(Path(sys.argv[2]))\n")
        children = []
        try:
            for number in range(4):
                children.append(subprocess.Popen([sys.executable, "-c", script, str(self.store.directory),
                    str(self.folder / f"process_{number}.credential.json")], cwd=ROOT,
                    stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                    creationflags=subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0))
            for child in children:
                stdout, stderr = child.communicate(timeout=10)
                self.assertEqual(child.returncode, 0, stderr.decode())
                self.assertEqual(stdout, b"")
            self.assertEqual(len(self.store.list_public()), 4)
        finally:
            for child in children:
                if child.poll() is None:
                    child.kill(); child.wait(timeout=5)
                for stream in (child.stdout, child.stderr): stream.close()

    def test_lock_deadline_is_bounded(self):
        short = c.CredentialStore(self.store.directory, lock_timeout=0.03)
        with self.store._locked():
            with self.assertRaisesRegex(c.CredentialError, "busy or unavailable"):
                short.list_public()

    def test_source_tree_destinations_and_unknown_profile_fail_before_handoff(self):
        with self.assertRaises(c.CredentialError):
            self.store.issue_to_file(ROOT / "tests/do-not-create.credential.json")
        self.assertFalse((ROOT / "tests/do-not-create.credential.json").exists())
        for label in ("line\nbreak", "\ud800", "x" * 97):
            with self.assertRaises(c.CredentialError): self.issue("badlabel", label=label)

    def test_cli_prints_only_public_metadata_and_never_echoes_secret_argument(self):
        output = self.folder / "cli.credential.json"
        stdout, stderr = io.StringIO(), io.StringIO()
        with redirect_stdout(stdout), redirect_stderr(stderr):
            self.assertEqual(c.main(["--store", str(self.store.directory), "issue", "--out", str(output)]), 0)
        token = c.read_credential_file(output)["token"]
        public = json.loads(stdout.getvalue())
        self.assertNotIn(token, stdout.getvalue() + stderr.getvalue())
        self.assertNotIn("token_sha256", public)
        with redirect_stdout(io.StringIO()) as listing, redirect_stderr(io.StringIO()):
            self.assertEqual(c.main(["--store", str(self.store.directory), "list"]), 0)
        self.assertNotIn(token, listing.getvalue())
        with redirect_stdout(io.StringIO()), redirect_stderr(io.StringIO()) as invalid:
            with self.assertRaises(SystemExit) as error:
                c.main(["--accidentally-pasted-token", token])
        self.assertEqual(error.exception.code, 2)
        self.assertNotIn(token, invalid.getvalue())
        with redirect_stdout(io.StringIO()), redirect_stderr(io.StringIO()):
            self.assertEqual(c.main(["--store", str(self.store.directory), "revoke", public["invite_id"]]), 0)
        with self.assertRaises(c.AuthenticationError): self.store.authenticate(token)


@unittest.skipUnless(os.name == "nt" and os.environ.get("BA_RUN_PRIVATE_ACL_TESTS") == "1",
                     "real protected-DACL test requires explicit BA_RUN_PRIVATE_ACL_TESTS=1 on Windows")
class WindowsCredentialPrivacyTests(unittest.TestCase):
    def test_real_private_creation_permissions_and_authentication(self):
        folder = private_test_folder("credentials-real-acl-")
        private = folder / "private"
        try:
            try:
                store = c.CredentialStore(private)
                output = private / "player.credential.json"
                public = store.issue_to_file(output)
                handoff = c.read_credential_file(output)
                self.assertEqual(store.authenticate(handoff["token"]), public["player_id"])
                self.assertEqual(c._windows().inspect(private), c._windows().sddl(True))
                for path in (store.path, store.lock_path, output):
                    self.assertEqual(c._windows().inspect(path), c._windows().sddl())
            except c.CredentialError as error:
                if any(fragment in str(error) for fragment in ("inaccessible", "unavailable", "cannot create private")):
                    self.skipTest("observed restricted-token/private-DACL limitation: " + str(error))
                raise
        finally:
            try:
                remove_test_folder(folder)
            except PermissionError:
                # Do not relax a private ACL or alter host policy for test cleanup.
                # An empty inaccessible test directory may remain under local/.
                try: private.rmdir(); folder.rmdir()
                except OSError: pass


if __name__ == "__main__":
    unittest.main()
