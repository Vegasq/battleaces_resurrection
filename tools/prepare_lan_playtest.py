"""Owner-run LAN playtest provisioning, using verified packaged production code.

Creates a fresh private CA/server key and two persistent player invitations.
No game or listening server starts; no existing config, ACL, firewall, system
trust, service, or router setting is changed. This is local qualification tooling,
not a portable host certificate installer or a clean-PC release claim.
"""
from __future__ import annotations
import argparse
import ctypes as c
import hashlib
import io
import ipaddress
import json
import os
from pathlib import Path
import ssl
import subprocess
import sys
import zipfile


ROOT = Path(__file__).resolve().parents[1]


def require(value, message):
    if not value:
        raise ValueError(message)


def digest(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def lan_address(value):
    address = ipaddress.IPv4Address(value)
    networks = ('10.0.0.0/8', '172.16.0.0/12', '192.168.0.0/16')
    require(any(address in ipaddress.IPv4Network(n) for n in networks),
            'Select the host Ethernet/Wi-Fi RFC1918 IPv4 address')
    return str(address)


def restricted_token():
    """Read-only token preflight. Never attempt private writes after a restriction."""
    from ctypes import wintypes as w
    kernel = c.WinDLL('kernel32', use_last_error=True)
    advapi = c.WinDLL('advapi32', use_last_error=True)
    kernel.GetCurrentProcess.restype = w.HANDLE
    kernel.CloseHandle.argtypes = [w.HANDLE]
    advapi.OpenProcessToken.argtypes = [w.HANDLE, w.DWORD, c.POINTER(w.HANDLE)]
    advapi.OpenProcessToken.restype = w.BOOL
    advapi.IsTokenRestricted.argtypes = [w.HANDLE]; advapi.IsTokenRestricted.restype = w.BOOL
    token = w.HANDLE()
    require(advapi.OpenProcessToken(kernel.GetCurrentProcess(), 8, c.byref(token)), 'Cannot inspect process token')
    try:
        c.set_last_error(0)
        restricted = bool(advapi.IsTokenRestricted(token)); error = c.get_last_error()
        require(restricted or error == 0, 'Cannot inspect token restrictions')
        return restricted
    finally:
        kernel.CloseHandle(token)


def handshake(cert, key, ca, identity):
    """Exercise real certificate/identity verification without opening a socket."""
    from server.tls_transport import load_client_context, load_server_context
    sin, sout, cin, cout = (ssl.MemoryBIO() for _ in range(4))
    server = load_server_context(cert, key).wrap_bio(sin, sout, server_side=True)
    client = load_client_context(ca, identity).context.wrap_bio(cin, cout, server_hostname=identity)
    done = [False, False]
    for _ in range(32):
        for i, connection in enumerate((client, server)):
            if not done[i]:
                try:
                    connection.do_handshake(); done[i] = True
                except ssl.SSLWantReadError:
                    pass
        if cout.pending: sin.write(cout.read())
        if sout.pending: cin.write(sout.read())
        if all(done):
            require(client.version() == server.version(), 'TLS versions differ')
            return client.version()
    raise ValueError('TLS memory handshake did not complete')


def make_pki(folder, openssl, address):
    from server import credentials as private
    private._ensure_private_directory(folder)
    # OpenSSL writes existing files in place. Create both key destinations with
    # the production protected DACL first and recheck it after every operation.
    for name in ('ca.key', 'server.key'):
        private._write_file(folder/name, b'')
    def run(*arguments):
        result = subprocess.run([str(openssl), *arguments], cwd=folder, stdin=subprocess.DEVNULL,
            stdout=subprocess.PIPE, stderr=subprocess.PIPE, timeout=30,
            creationflags=subprocess.CREATE_NO_WINDOW if os.name == 'nt' else 0)
        require(result.returncode == 0, 'Certificate provisioning command failed')
        for name in ('ca.key', 'server.key'): private._assert_private_path(folder/name)
    run('req', '-x509', '-newkey', 'rsa:3072', '-nodes', '-days', '30', '-sha256',
        '-keyout', 'ca.key', '-out', 'ca.pem', '-subj', '/CN=Battle Aces LAN Playtest CA',
        '-addext', 'basicConstraints=critical,CA:TRUE,pathlen:0',
        '-addext', 'keyUsage=critical,keyCertSign,cRLSign', '-addext', 'subjectKeyIdentifier=hash')
    run('req', '-new', '-newkey', 'rsa:3072', '-nodes', '-sha256', '-keyout', 'server.key',
        '-out', 'server.csr', '-subj', '/CN=Battle Aces LAN Playtest')
    (folder/'server.ext').write_text('basicConstraints=critical,CA:FALSE\n'
        'keyUsage=critical,digitalSignature,keyEncipherment\nextendedKeyUsage=serverAuth\n'
        'subjectKeyIdentifier=hash\nauthorityKeyIdentifier=keyid,issuer\n'
        'subjectAltName=IP:'+address+'\n', encoding='ascii')
    run('x509', '-req', '-in', 'server.csr', '-CA', 'ca.pem', '-CAkey', 'ca.key',
        '-CAcreateserial', '-days', '30', '-sha256', '-out', 'server.pem', '-extfile', 'server.ext')
    version = handshake(folder/'server.pem', folder/'server.key', folder/'ca.pem', address)
    try:
        handshake(folder/'server.pem', folder/'server.key', folder/'ca.pem', 'wrong.invalid')
    except ssl.SSLCertVerificationError:
        pass
    else:
        raise ValueError('Wrong certificate identity was accepted')
    return version


def write_new(path, value):
    with path.open('x', encoding='utf-8', newline='\n') as target:
        target.write(json.dumps(value, indent=2)+'\n')


def read_client_archive(player, manifest, expected_sha256):
    """Return only the exact verified client archive, never host/private data."""
    archive = player.parent/'battleaces-client-win64.zip'
    require(0 < archive.stat().st_size <= 64*1024*1024, 'Client archive exceeds bound')
    raw = archive.read_bytes()
    require(hashlib.sha256(raw).hexdigest() == expected_sha256, 'Client archive hash differs from the reviewed handoff')
    names = set(manifest['files']) | {'package-manifest.json'}
    prefix = 'battleaces-client-win64/'
    with zipfile.ZipFile(io.BytesIO(raw)) as bundle:
        info = bundle.infolist()
        require(len(info) == len(names) and {i.filename for i in info} == {prefix+n for n in names} and
                sum(i.file_size for i in info) <= 256*1024*1024, 'Unexpected client archive contents')
        require(all(bundle.read(prefix+name) == (player/name).read_bytes() for name in names),
                'Client archive differs from the selected verified package')
    return raw


def prepare(args):
    from tools.package_integrity import verify
    from client_patch.transport import client, launcher
    from server import credentials as private
    server, player, game, openssl, report_path = (p.resolve() for p in
        (args.server_package, args.client_package, args.game, args.openssl, args.report))
    address = lan_address(args.host_ip)
    require(os.name == 'nt' and 1 <= args.port <= 65535, 'Windows and a valid TCP port required')
    require(all(p.is_relative_to(ROOT/'local') for p in (server, player, game, report_path)),
            'Owned ignored local packages/game/report required')
    require(report_path.parent.is_dir(), 'Report directory must already exist')
    require(not report_path.exists() and openssl.is_file(), 'Fresh report and installed OpenSSL required')
    require(digest(__file__) == args.expected_source_sha256, 'Setup source changed; regenerate the reviewed command')
    before = dict(server=verify(server, 'server'), client=verify(player, 'client'))
    client_zip = read_client_archive(player, before['client'], args.expected_client_archive_sha256)
    require(sys.executable == str(player/'program/runtime/python.exe'), 'Run using the selected bundled client runtime')
    require(Path(private.__file__).resolve() == player/'program/app/server/credentials.py' and
            Path(client.__file__).resolve() == player/'program/app/client_patch/transport/client.py' and
            Path(launcher.__file__).resolve() == player/'program/app/client_patch/transport/launcher.py',
            'Production imports must come from the selected verified client package')
    require(digest(server/'program/app/server/credentials.py') == digest(player/'program/app/server/credentials.py'),
            'Packaged credential implementations differ')
    launcher.verify_game(game, community=True, bridge_version=2, unified=True, player_features=True)
    require(digest(game/'BattleAcesOffline.dll') == digest(player/'program/client-helper/BattleAcesOffline.dll'),
            'Working game helper differs from the selected package')
    host_config = server/'config/host.json'; client_config = player/'config/client.json'
    require(not host_config.exists() and not client_config.exists(), 'Existing player/host settings are never overwritten')
    require((server/'assets/build-37822/asset-manifest.json').is_file(), 'Import the local host assets first')
    report = dict(passed=False, stage='owner_preflight', host_ip=address, port=args.port,
                  protected_operations_attempted=False, server_or_game_started=False,
                  source_sha256=digest(__file__), invites_persist=False)
    store = None
    try:
        if restricted_token():
            report['stage'] = 'normal_desktop_account_required'
            return 2
        if args.preflight_only:
            report.update(stage='preflight_complete', passed=True)
            return 0
        report.update(stage='private_pki', protected_operations_attempted=True)
        private_root = server/'data/private'
        require(not private_root.exists(), 'Use fresh packages without existing private host data')
        private._ensure_private_directory(private_root)
        pki = private_root/'lan-playtest-tls'
        require(not pki.exists(), 'Choose fresh playtest packages')
        report['verified_tls_memory_handshake'] = make_pki(pki, openssl, address)
        report['stage'] = 'player_invites'
        store = private.CredentialStore(private_root/'credentials')
        handoff = private_root/'friend-handoff'
        private._ensure_private_directory(handoff)
        host_invite = private_root/'host-player.json'
        store.issue_to_file(host_invite, label='LAN playtest host')
        store.issue_to_file(handoff/'player-invite.json', label='LAN playtest friend')
        # The host invite, private keys and host credential database stay outside
        # this handoff folder. Only this friend's invite is transferable.
        (handoff/'public-ca.pem').write_bytes((pki/'ca.pem').read_bytes())
        with (handoff/'battleaces-client-win64.zip').open('xb') as target: target.write(client_zip)
        details = ('LAN PLAYTEST CONNECTION\n\nServer address and certificate name: '+address+
            '\nTCP port: '+str(args.port)+'\nPublic CA file SHA256: '+digest(handoff/'public-ca.pem')+
            '\nClient ZIP SHA256: '+args.expected_client_archive_sha256+'\n\n'
            'Extract the client ZIP. Open BattleAces-Client.cmd for Connection Setup.\n'
            'Select your own working game copy and Install patch. Enter your player\n'
            'name, the address/port/name above, public-ca.pem and player-invite.json.\n'
            'Confirm the CA hash with your host through a trusted channel, then\n'
            'Save connection and Test connection.\n'
            'The host must start the server before Test connection. After successful\n'
            'setup use Start Client.cmd for normal play. Keep this invite private.\n'
            'This certificate expires after 30 days; this is a LAN test candidate.\n')
        with (handoff/'CONNECTION.txt').open('x', encoding='utf-8', newline='\n') as target: target.write(details)
        host = json.loads((server/'config/host.example.json').read_bytes())
        host.update(listen_host=address, listen_port=args.port, certificate_file=str(pki/'server.pem'),
                    private_key_file=str(pki/'server.key'), credential_directory=str(private_root/'credentials'))
        write_new(host_config, host)
        report['stage'] = 'host_client_enrollment'
        settings = client.defaults(game)
        settings.update(display_name='LAN Host', local_profile='lan_playtest_host')
        write_new(client_config, settings)
        request = dict(schema=1, game_directory=str(game), server_host=address, server_port=args.port,
            server_name=address, display_name='LAN Host', room='community', ca_source=str(handoff/'public-ca.pem'),
            invite_source=str(host_invite), expected_ca_sha256=digest(handoff/'public-ca.pem'),
            expected_config_sha256=digest(client_config))
        request_path = report_path.parent/'host-client-enrollment-request.json'
        write_new(request_path, request)
        try:
            enrolled = subprocess.run([sys.executable, '-I', '-B', '-m', 'tools.package_client', 'enroll',
                '--request', str(request_path), '--config', str(client_config)], stdin=subprocess.DEVNULL,
                stdout=subprocess.PIPE, stderr=subprocess.PIPE, timeout=60, creationflags=subprocess.CREATE_NO_WINDOW)
            require(enrolled.returncode == 0 and not enrolled.stderr and json.loads(enrolled.stdout).get('ok') is True,
                    'Packaged host-player enrollment failed')
        finally:
            request_path.unlink(missing_ok=True)
        report['stage'] = 'native_host_check'
        checked = subprocess.run([str(server/'program/runtime/python.exe'), '-I', '-B', '-m', 'tools.package_server', 'check'],
            cwd=server, stdin=subprocess.DEVNULL, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
            timeout=60, creationflags=subprocess.CREATE_NO_WINDOW)
        require(checked.returncode == 0 and not checked.stderr, 'Packaged protected host check failed')
        health = json.loads(checked.stdout)
        require(health.get('passed') is True and health.get('tls') is True and health.get('credential_store_checked') is True and
                health.get('native', {}).get('exit_code') == 0 and health['native'].get('reaped') is True,
                'Protected TLS/credential/native readiness incomplete')
        require(verify(server, 'server') == before['server'] and verify(player, 'client') == before['client'],
                'Immutable package changed during setup')
        require(digest(__file__) == args.expected_source_sha256, 'Setup source changed during provisioning')
        report.update(passed=True, stage='ready', invites_persist=True, health=health,
            ca_sha256=digest(handoff/'public-ca.pem'), friend_invite=str(handoff/'player-invite.json'),
            friend_handoff=str(handoff), client_archive_sha256=args.expected_client_archive_sha256,
            public_ca=str(handoff/'public-ca.pem'), server_entry=str(server/'Start Server.exe'),
            host_client_entry=str(player/'Start Client.cmd'),
            qualification='Local provisioning/readiness only; no LAN reachability or graphical match proof')
        return 0
    except (Exception, KeyboardInterrupt) as error:
        report['error_type'] = type(error).__name__
        report['error'] = 'LAN setup failed at '+report['stage']+'; partial new files are retained for inspection.'
        if store is not None:
            revoked = True
            try:
                # This store belongs exclusively to this fresh setup, including
                # a possible commit preceding an issuance readback failure.
                for item in store.list_public(): store.revoke(item['invite_id'])
            except Exception:
                revoked = False
            report['failed_setup_invites_revoked'] = revoked
            report['invites_persist'] = False if revoked else None
            report['invites_may_persist'] = not revoked
        return 1
    finally:
        write_new(report_path, report)
        print(json.dumps({k: report[k] for k in ('passed', 'stage', 'protected_operations_attempted',
                                                'server_or_game_started', 'invites_persist')}))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ('server-package', 'client-package', 'game', 'openssl', 'report'):
        parser.add_argument('--'+name, type=Path, required=True)
    parser.add_argument('--host-ip', required=True)
    parser.add_argument('--port', type=int, default=47623)
    parser.add_argument('--expected-source-sha256', required=True)
    parser.add_argument('--expected-client-archive-sha256', required=True)
    parser.add_argument('--preflight-only', action='store_true')
    return prepare(parser.parse_args())


if __name__ == '__main__':
    raise SystemExit(main())
