"""Owner-managed invite credentials. Transport/TLS integration is separate.

The database stores SHA256 token digests, never bearer tokens. The sole secret
handoff is an exclusively created private local credential file.
"""
from __future__ import annotations

import argparse
import base64
from contextlib import contextmanager
import hashlib
import hmac
import json
import os
from pathlib import Path
import re
import secrets
import stat
import sys
import time

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_DIRECTORY = ROOT / "local/data/credentials"
MAX_STORE_BYTES = 1024 * 1024
MAX_INVITES = 4096
MAX_CREDENTIAL_BYTES = 4096
TOKEN = re.compile(r"ba1_[A-Za-z0-9_-]{43}\Z")
PLAYER_ID = re.compile(r"p_[0-9a-f]{32}\Z")
INVITE_ID = re.compile(r"i_[0-9a-f]{32}\Z")
HASH = re.compile(r"[0-9a-f]{64}\Z")


class CredentialError(ValueError):
    """Safe owner-facing error; contains no credential payloads."""


class AuthenticationError(CredentialError):
    def __init__(self):
        super().__init__("invalid or revoked credential")


class _WindowsPrivacy:
    """Protected DACLs at creation; never change an existing object's ACL."""
    def __init__(self):
        import ctypes as c
        from ctypes import wintypes as w
        self.c, self.w = c, w
        self.kernel = k = c.WinDLL("kernel32", use_last_error=True)
        self.advapi = a = c.WinDLL("advapi32", use_last_error=True)
        k.GetCurrentProcess.restype = w.HANDLE
        k.CloseHandle.argtypes = [w.HANDLE]; k.CloseHandle.restype = w.BOOL
        k.LocalFree.argtypes = [c.c_void_p]; k.LocalFree.restype = c.c_void_p
        a.OpenProcessToken.argtypes = [w.HANDLE, w.DWORD, c.POINTER(w.HANDLE)]; a.OpenProcessToken.restype = w.BOOL
        a.GetTokenInformation.argtypes = [w.HANDLE, c.c_int, c.c_void_p, w.DWORD, c.POINTER(w.DWORD)]
        a.GetTokenInformation.restype = w.BOOL
        a.ConvertSidToStringSidW.argtypes = [c.c_void_p, c.POINTER(w.LPWSTR)]
        a.ConvertSidToStringSidW.restype = w.BOOL
        a.ConvertStringSecurityDescriptorToSecurityDescriptorW.argtypes = [w.LPCWSTR, w.DWORD, c.POINTER(c.c_void_p), c.c_void_p]
        a.ConvertStringSecurityDescriptorToSecurityDescriptorW.restype = w.BOOL
        a.GetNamedSecurityInfoW.argtypes = [w.LPCWSTR, c.c_int, w.DWORD, c.c_void_p, c.c_void_p,
                                           c.c_void_p, c.c_void_p, c.POINTER(c.c_void_p)]
        a.GetNamedSecurityInfoW.restype = w.DWORD
        a.ConvertSecurityDescriptorToStringSecurityDescriptorW.argtypes = [c.c_void_p, w.DWORD, w.DWORD,
                                                                           c.POINTER(w.LPWSTR), c.c_void_p]
        a.ConvertSecurityDescriptorToStringSecurityDescriptorW.restype = w.BOOL
        class Attributes(c.Structure):
            _fields_ = [("length", w.DWORD), ("descriptor", c.c_void_p), ("inherit", w.BOOL)]
        self.Attributes = Attributes
        k.CreateDirectoryW.argtypes = [w.LPCWSTR, c.POINTER(Attributes)]; k.CreateDirectoryW.restype = w.BOOL
        k.CreateFileW.argtypes = [w.LPCWSTR, w.DWORD, w.DWORD, c.POINTER(Attributes), w.DWORD, w.DWORD, w.HANDLE]
        k.CreateFileW.restype = w.HANDLE
        token, size, sid_text = w.HANDLE(), w.DWORD(), w.LPWSTR()
        try:
            if not a.OpenProcessToken(k.GetCurrentProcess(), 0x0008, c.byref(token)):
                raise CredentialError("cannot inspect current Windows identity")
            a.GetTokenInformation(token, 1, None, 0, c.byref(size))  # TokenUser.
            buffer = c.create_string_buffer(size.value)
            if not a.GetTokenInformation(token, 1, buffer, size.value, c.byref(size)):
                raise CredentialError("cannot inspect current Windows identity")
            sid = c.cast(buffer, c.POINTER(c.c_void_p))[0]
            if not a.ConvertSidToStringSidW(sid, c.byref(sid_text)):
                raise CredentialError("cannot inspect current Windows identity")
            self.sid = sid_text.value
        finally:
            if sid_text: k.LocalFree(c.cast(sid_text, c.c_void_p))
            if token: k.CloseHandle(token)

    def sddl(self, directory=False):
        flags = "OICI" if directory else ""
        return f"D:P(A;{flags};FA;;;SY)(A;{flags};FA;;;{self.sid})"

    @contextmanager
    def attributes(self, directory=False):
        descriptor = self.c.c_void_p()
        if not self.advapi.ConvertStringSecurityDescriptorToSecurityDescriptorW(
                self.sddl(directory), 1, self.c.byref(descriptor), None):
            raise CredentialError("cannot create private Windows security descriptor")
        try:
            yield self.Attributes(self.c.sizeof(self.Attributes), descriptor, False)
        finally:
            self.kernel.LocalFree(descriptor)

    def create_directory(self, path):
        with self.attributes(True) as attributes:
            if not self.kernel.CreateDirectoryW(str(path), self.c.byref(attributes)):
                if self.c.get_last_error() != 183:
                    raise CredentialError("cannot create private credential directory")

    def create_file(self, path):
        import msvcrt
        with self.attributes() as attributes:
            handle = self.kernel.CreateFileW(str(path), 0xC0000000, 0, self.c.byref(attributes), 1, 0x80, None)
        if handle == self.c.c_void_p(-1).value:
            error = self.c.get_last_error()
            if error in (80, 183):
                raise FileExistsError("credential output already exists")
            raise CredentialError(f"cannot create private credential file (Windows error {error})")
        try:
            descriptor = msvcrt.open_osfhandle(handle, os.O_RDWR | os.O_BINARY | os.O_NOINHERIT)
        except BaseException:
            self.kernel.CloseHandle(handle)
            raise
        return os.fdopen(descriptor, "w+b")

    def inspect(self, path):
        descriptor, text = self.c.c_void_p(), self.w.LPWSTR()
        if self.advapi.GetNamedSecurityInfoW(str(path), 1, 4, None, None, None, None, self.c.byref(descriptor)):
            raise CredentialError("private credential path is inaccessible to this process")
        try:
            if not self.advapi.ConvertSecurityDescriptorToStringSecurityDescriptorW(
                    descriptor, 1, 4, self.c.byref(text), None):
                raise CredentialError("cannot verify credential permissions")
            return text.value
        finally:
            if text: self.kernel.LocalFree(self.c.cast(text, self.c.c_void_p))
            self.kernel.LocalFree(descriptor)


_windows_privacy = None


def _windows():
    global _windows_privacy
    if _windows_privacy is None:
        _windows_privacy = _WindowsPrivacy()
    return _windows_privacy


def _local_path(value):
    path = Path(value).absolute()
    if str(path).startswith("\\\\"):
        raise CredentialError("credentials require a local filesystem path")
    try:
        information = path.lstat()
    except FileNotFoundError:
        pass
    else:
        if stat.S_ISLNK(information.st_mode) or getattr(information, "st_file_attributes", 0) & 0x400:
            raise CredentialError("credential destinations may not be links or reparse points")
    path = path.resolve()
    # Prevent accidental source-tree secrets without changing repository ignore
    # policy. These roots are already ignored; external deployment paths work.
    if path.is_relative_to(ROOT) and not any(path.is_relative_to(ROOT / root)
            for root in ("local", "server/data", "server/test-data")):
        raise CredentialError("credential paths inside the repository must use an ignored runtime directory")
    return path


def _assert_private_path(path, *, directory=False):
    information = path.lstat()
    if stat.S_ISLNK(information.st_mode) or getattr(information, "st_file_attributes", 0) & 0x400:
        raise CredentialError("credential paths may not be links or reparse points")
    if not (stat.S_ISDIR(information.st_mode) if directory else stat.S_ISREG(information.st_mode)):
        raise CredentialError("unexpected credential path type")
    if os.name == "nt":
        if _windows().inspect(path) != _windows().sddl(directory):
            raise CredentialError("credential path lacks the required private protected DACL")
    elif information.st_uid != os.getuid() or stat.S_IMODE(information.st_mode) != (0o700 if directory else 0o600):
        raise CredentialError("credential path lacks owner-only permissions")


def _ensure_private_directory(path):
    path.parent.mkdir(parents=True, exist_ok=True)
    if not path.exists():
        if os.name == "nt":
            _windows().create_directory(path)
        else:
            try: path.mkdir(mode=0o700)
            except FileExistsError: pass
    _assert_private_path(path, directory=True)


def _private_create(path):
    if os.name == "nt":
        return _windows().create_file(path)
    descriptor = os.open(path, os.O_RDWR | os.O_CREAT | os.O_EXCL, 0o600)
    return os.fdopen(descriptor, "w+b")


def _write_file(path, data):
    with _private_create(path) as stream:
        stream.write(data)
        stream.flush()
        os.fsync(stream.fileno())
    _assert_private_path(path)


def _read_file(path, maximum):
    _assert_private_path(path)
    with path.open("rb") as stream:
        if os.fstat(stream.fileno()).st_size > maximum:
            raise CredentialError("credential file exceeds size limit")
        data = stream.read(maximum + 1)
    if len(data) > maximum:
        raise CredentialError("credential file exceeds size limit")
    return data


def _json(data):
    def unique(pairs):
        result = {}
        for key, value in pairs:
            if key in result:
                raise CredentialError("duplicate credential JSON key")
            result[key] = value
        return result
    try:
        return json.loads(data.decode("utf-8"), object_pairs_hook=unique)
    except (UnicodeError, ValueError, RecursionError):
        raise CredentialError("malformed credential JSON") from None


def _token_hash(token):
    if not isinstance(token, str) or len(token) != 47 or not TOKEN.fullmatch(token):
        raise AuthenticationError()
    decoded = base64.urlsafe_b64decode(token[4:] + "=")
    if len(decoded) != 32 or base64.urlsafe_b64encode(decoded).rstrip(b"=").decode("ascii") != token[4:]:
        raise AuthenticationError()
    return hashlib.sha256(token.encode("ascii")).hexdigest()


def _public(record):
    return {key: value for key, value in record.items() if key != "token_sha256"}


def parse_credential_handoff(raw):
    """Validate transfer bytes without authorizing them or relaxing runtime ACLs."""
    if not isinstance(raw, bytes) or not 1 <= len(raw) <= MAX_CREDENTIAL_BYTES:
        raise CredentialError("invalid credential handoff size")
    value = _json(raw)
    if (not isinstance(value, dict) or set(value) != {"schema", "player_id", "invite_id", "token"}
            or type(value["schema"]) is not int or value["schema"] != 1
            or not isinstance(value["player_id"], str) or not PLAYER_ID.fullmatch(value["player_id"])
            or not isinstance(value["invite_id"], str) or not INVITE_ID.fullmatch(value["invite_id"])):
        raise CredentialError("invalid credential handoff")
    _token_hash(value["token"])
    return value


def read_credential_file(path):
    """Read a bounded private handoff; callers must never log the returned token."""
    try:
        return parse_credential_handoff(_read_file(_local_path(path), MAX_CREDENTIAL_BYTES))
    except OSError:
        raise CredentialError("cannot read private credential handoff") from None


def import_credential_file(source_path, output_path, *, expected_sha256=None):
    """Enroll a user-selected transferred invite into a new protected local file.

    Transfer files are untrusted input and may have download-folder permissions.
    Only this explicit import reads them without the runtime reader's DACL check.
    The original is never changed/deleted, existing output is never overwritten,
    and the copy must pass the ordinary strict reader before it is usable.
    """
    source, output = _local_path(source_path), _local_path(output_path)
    if source == output: raise CredentialError('Choose a new private invite destination')
    created = False
    try:
        information = source.lstat()
        if not stat.S_ISREG(information.st_mode) or not 0 < information.st_size <= MAX_CREDENTIAL_BYTES:
            raise CredentialError('Transferred invite must be a bounded regular local file')
        with source.open('rb') as stream: raw = stream.read(MAX_CREDENTIAL_BYTES+1)
        if expected_sha256 is not None and hashlib.sha256(raw).hexdigest() != expected_sha256:
            raise CredentialError('Transferred invite changed during setup')
        value = parse_credential_handoff(raw)
        _ensure_private_directory(output.parent)
        with _private_create(output) as stream:
            created = True
            stream.write((json.dumps(value, separators=(',', ':'))+'\n').encode('utf-8'))
            stream.flush(); os.fsync(stream.fileno())
        copied = read_credential_file(output)
        if copied != value: raise CredentialError('Private invite readback did not match')
        return dict(player_id=value['player_id'], invite_id=value['invite_id'])
    except (OSError, CredentialError):
        if created:
            try: output.unlink()
            except OSError: raise CredentialError('Invite import failed; a protected partial copy remains') from None
        raise CredentialError('Invite import failed; check the transfer format and private destination permissions') from None


class CredentialStore:
    def __init__(self, directory=DEFAULT_DIRECTORY, *, lock_timeout=2.0):
        if not isinstance(lock_timeout, (int, float)) or not 0 < lock_timeout <= 30:
            raise CredentialError("lock timeout must be in (0,30] seconds")
        self.directory, self.lock_timeout = _local_path(directory), lock_timeout
        self.path, self.lock_path = self.directory / "credentials.json", self.directory / "credentials.lock"
        try:
            _ensure_private_directory(self.directory)
            try: _write_file(self.lock_path, b"\0")
            except FileExistsError: _assert_private_path(self.lock_path)
        except OSError:
            raise CredentialError("private credential storage is unavailable; existing permissions were not changed") from None

    @contextmanager
    def _locked(self):
        try:
            stream = self.lock_path.open("r+b")
        except OSError:
            raise CredentialError("cannot open private credential lock") from None
        acquired = False
        deadline = time.monotonic() + self.lock_timeout
        try:
            while not acquired:
                try:
                    if os.name == "nt":
                        import msvcrt
                        stream.seek(0)
                        msvcrt.locking(stream.fileno(), msvcrt.LK_NBLCK, 1)
                    else:
                        import fcntl
                        fcntl.flock(stream.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
                    acquired = True
                except OSError:
                    if time.monotonic() >= deadline:
                        raise CredentialError("credential store busy or unavailable") from None
                    time.sleep(0.01)
            yield
        finally:
            if acquired:
                if os.name == "nt":
                    stream.seek(0)
                    msvcrt.locking(stream.fileno(), msvcrt.LK_UNLCK, 1)
                else:
                    fcntl.flock(stream.fileno(), fcntl.LOCK_UN)
            stream.close()

    def _load(self):
        try:
            raw = _read_file(self.path, MAX_STORE_BYTES)
        except FileNotFoundError:
            return []
        except OSError:
            raise CredentialError("cannot read private credential store") from None
        value = _json(raw)
        if (not isinstance(value, dict) or set(value) != {"schema", "invites"}
                or type(value["schema"]) is not int or value["schema"] != 1
                or not isinstance(value["invites"], list) or len(value["invites"]) > MAX_INVITES):
            raise CredentialError("invalid credential store schema")
        ids, hashes = set(), set()
        for row in value["invites"]:
            if (not isinstance(row, dict) or set(row) != {"invite_id", "player_id", "label", "token_sha256", "created_at", "revoked_at"}
                    or not isinstance(row["invite_id"], str) or not INVITE_ID.fullmatch(row["invite_id"])
                    or not isinstance(row["player_id"], str) or not PLAYER_ID.fullmatch(row["player_id"])
                    or not isinstance(row["token_sha256"], str) or not HASH.fullmatch(row["token_sha256"])
                    or not self._label_valid(row["label"])
                    or type(row["created_at"]) is not int or not 0 <= row["created_at"] < 1 << 63
                    or (row["revoked_at"] is not None and (type(row["revoked_at"]) is not int
                        or not 0 <= row["revoked_at"] < 1 << 63))
                    or row["invite_id"] in ids or row["token_sha256"] in hashes):
                raise CredentialError("invalid credential store record")
            ids.add(row["invite_id"]); hashes.add(row["token_sha256"])
        return value["invites"]

    @staticmethod
    def _label_valid(label):
        try:
            return (isinstance(label, str) and len(label) <= 96 and len(label.encode("utf-8")) <= 96
                    and all(ord(character) >= 32 and ord(character) != 127 for character in label))
        except UnicodeError:
            return False

    def _save(self, records):
        data = (json.dumps({"schema": 1, "invites": records}, separators=(",", ":")) + "\n").encode()
        if len(data) > MAX_STORE_BYTES:
            raise CredentialError("credential store size limit")
        temporary = self.directory / (".credentials-" + secrets.token_hex(16) + ".tmp")
        created = False
        try:
            with _private_create(temporary) as stream:
                created = True
                stream.write(data); stream.flush(); os.fsync(stream.fileno())
            _assert_private_path(temporary)
            os.replace(temporary, self.path)
        except OSError:
            raise CredentialError("credential store commit failed") from None
        finally:
            if created:
                try: temporary.unlink(missing_ok=True)
                except OSError: pass  # Contains hashes only; never relax ACLs to remove it.

    def issue_to_file(self, output_path, *, label="", player_id=None):
        """Create one secret handoff; return public metadata only.

        Supplying a player_id reissues for an already server-created identity.
        It does not revoke earlier invites; owners can revoke those explicitly.
        """
        output = _local_path(output_path)
        if not self._label_valid(label):
            raise CredentialError("invalid public credential label")
        if output in (self.path, self.lock_path) or not output.parent.is_dir():
            raise CredentialError("credential output requires an existing local parent directory")
        with self._locked():
            records = self._load()
            if len(records) >= MAX_INVITES:
                raise CredentialError("credential invite limit")
            if player_id is not None and (not isinstance(player_id, str) or not PLAYER_ID.fullmatch(player_id)
                    or not any(row["player_id"] == player_id for row in records)):
                raise CredentialError("reissue requires an existing server-issued player identity")
            for _ in range(8):
                token = "ba1_" + secrets.token_urlsafe(32)
                token_hash = _token_hash(token)
                invite = "i_" + secrets.token_hex(16)
                player = player_id or "p_" + secrets.token_hex(16)
                if (all(row["invite_id"] != invite and row["token_sha256"] != token_hash for row in records)
                        and (player_id is not None or all(row["player_id"] != player for row in records))):
                    break
            else:
                raise CredentialError("credential entropy collision; nothing issued")
            row = dict(invite_id=invite, player_id=player, label=label, token_sha256=token_hash,
                       created_at=int(time.time()), revoked_at=None)
            handoff = (json.dumps(dict(schema=1, player_id=player, invite_id=invite, token=token)) + "\n").encode()
            created = False
            try:
                # Keep ownership explicit: never remove a pre-existing file on
                # failure. Both files are flushed; only database replace commits.
                with _private_create(output) as stream:
                    created = True
                    stream.write(handoff); stream.flush(); os.fsync(stream.fileno())
                _assert_private_path(output)
                if read_credential_file(output)["token"] != token:
                    raise CredentialError("private credential handoff verification failed")
                self._save(records + [row])
            except (OSError, CredentialError):
                if created:
                    try: output.unlink()
                    except OSError:
                        raise CredentialError("issuance failed; unactivated private handoff could not be removed") from None
                raise CredentialError("credential issuance failed; no token activated and existing output was not overwritten") from None
            return _public(row)

    def authenticate(self, token, *, expected_player_id=None):
        """Return the bound identity; malformed/bad/revoked/mismatched are generic."""
        submitted = _token_hash(token)
        if expected_player_id is not None and (not isinstance(expected_player_id, str)
                or not PLAYER_ID.fullmatch(expected_player_id)):
            raise AuthenticationError()
        with self._locked():
            found = None
            for row in self._load():
                # Scan every fixed-size digest, including revoked entries. Parsing
                # and I/O are bounded but are not claimed to be constant-time.
                if hmac.compare_digest(submitted, row["token_sha256"]):
                    found = row
            if found is None or found["revoked_at"] is not None:
                raise AuthenticationError()
            if expected_player_id is not None and not hmac.compare_digest(expected_player_id, found["player_id"]):
                raise AuthenticationError()
            return found["player_id"]

    def revoke(self, invite_id):
        if not isinstance(invite_id, str) or not INVITE_ID.fullmatch(invite_id):
            raise CredentialError("invalid public invite ID")
        with self._locked():
            records = self._load()
            found = next((row for row in records if row["invite_id"] == invite_id), None)
            if found is None:
                raise CredentialError("unknown invite ID")
            if found["revoked_at"] is not None:
                return False
            found["revoked_at"] = int(time.time())
            self._save(records)
            return True

    def list_public(self):
        with self._locked():
            return [_public(row) for row in self._load()]


class _Parser(argparse.ArgumentParser):
    def error(self, message):
        # argparse normally repeats invalid argument values, which could include
        # an accidentally pasted token. Never echo command-line data on errors.
        self.print_usage(sys.stderr)
        self.exit(2, "invalid command or arguments; use --help\n")


def main(argv=None):
    parser = _Parser(description="Manage private owner-issued invite files; never accepts a token argument.")
    parser.add_argument("--store", type=Path, default=DEFAULT_DIRECTORY)
    commands = parser.add_subparsers(dest="command", required=True, parser_class=_Parser)
    issue = commands.add_parser("issue")
    issue.add_argument("--out", type=Path, required=True)
    issue.add_argument("--label", default="")
    issue.add_argument("--player-id", help="reissue for an already server-created identity")
    revoke = commands.add_parser("revoke")
    revoke.add_argument("invite_id")
    commands.add_parser("list")
    args = parser.parse_args(argv)
    try:
        store = CredentialStore(args.store)
        if args.command == "issue":
            result = store.issue_to_file(args.out, label=args.label, player_id=args.player_id)
        elif args.command == "revoke":
            result = {"revoked": store.revoke(args.invite_id)}
        else:
            result = store.list_public()
        print(json.dumps(result, separators=(",", ":")))
        return 0
    except CredentialError as error:
        print("credential operation failed: " + str(error), file=sys.stderr)
        return 1
    except OSError:
        print("credential operation failed: private filesystem operation unavailable", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
