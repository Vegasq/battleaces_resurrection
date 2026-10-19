"""External, disposable localhost host for the normal-owner enrollment diagnostic.

Loaded by the actual SERVER bundled runtime, never installed into either package.
The production coordinator/admission/store are unchanged. No game HELLO or worker
is requested. Stdio carries only bounded public commands/results, never invites.
"""
from __future__ import annotations
import argparse
import asyncio
import hashlib
import json
from pathlib import Path
import socket
import sys


def require(value,message):
    if not value:raise AssertionError(message)


class Host:
    def __init__(self,folder,pki,template):
        self.folder=Path(folder).resolve();self.pki=pki;self.template=template
        self.store=self.server=None;self.port=None;self.closed=None

    async def start(self):
        from server import credentials as private,tls_transport as tls,admission
        from server.dedicated_server import DedicatedServer
        from server.profiles import ProfileStore
        self.folder.mkdir()
        self.store=private.CredentialStore(self.folder/'host-private')
        self.store.issue_to_file(self.folder/'host-private/issued.json',label='Disposable packaged enrollment check')
        self.server=DedicatedServer(self.template,ProfileStore(self.folder/'profiles',self.template),
            tls_context=tls.load_server_context(self.pki['cert'],self.pki['key']),
            admission=admission.AdmissionController(self.store))
        self.port=(await self.server.start('127.0.0.1',0))[1]
        return dict(ready=True,port=self.port)

    async def settled(self):
        server=self.server;deadline=asyncio.get_running_loop().time()+5
        while server.peers or server.tasks or server.listener._pending or server.listener._clients:
            require(asyncio.get_running_loop().time()<deadline,'TLS sessions did not settle')
            await asyncio.sleep(.01)
        require(not server.rooms and not server.community.sessions and not server.community.lobbies,
                'connection check created game state')
        require(server.admission.pending==0 and not server.admission.verifications,'admission did not settle')
        require(not server.worker_cleanup and not server.retired and not list((self.folder/'profiles').iterdir()),
                'connection checks created profiles or workers')
        return dict(no_room_profile_or_worker_created=True)

    async def revoke(self):
        rows=self.store.list_public();require(len(rows)==1,'unexpected disposable store state')
        require(self.store.revoke(rows[0]['invite_id']),'disposable invite already revoked')
        return dict(revoked=True)

    async def close(self):
        if self.closed is not None:return self.closed
        report=dict(listener_sessions_and_admission_released=False,disposable_invites_revoked_and_handoffs_removed=False)
        clean=True
        if self.server is not None:
            try:
                server=self.server;await server.close()
                require(not server.peers and not server.tasks and not server.listener.sockets and
                    not server.listener._pending and not server.listener._clients and
                    not server.admission.pending and not server.admission.verifications,'server cleanup incomplete')
                if self.port is not None:
                    with socket.socket() as probe:
                        if hasattr(socket,'SO_EXCLUSIVEADDRUSE'):probe.setsockopt(socket.SOL_SOCKET,socket.SO_EXCLUSIVEADDRUSE,1)
                        probe.bind(('127.0.0.1',self.port))
                report['listener_sessions_and_admission_released']=True
            except BaseException:clean=False
        if self.store is not None:
            try:
                for row in self.store.list_public():self.store.revoke(row['invite_id'])
                require(not any(row['revoked_at'] is None for row in self.store.list_public()),'active disposable invite remains')
            except BaseException:clean=False
        path=self.folder/'host-private/issued.json'
        require(path.resolve().is_relative_to(self.folder),'owned cleanup path changed')
        try:path.unlink(missing_ok=True)
        except OSError:clean=False
        report['disposable_invites_revoked_and_handoffs_removed']=clean
        self.closed=report;return report


async def serve(package,folder,pki_folder,assets,*,preflight_only=False):
    from tools.package_integrity import verify,ordinary_file
    from server.assets import verify_assets
    from server.game_data import GameTemplate
    from server import credentials,tls_transport,admission
    from server.dedicated_server import DedicatedServer
    from server.profiles import ProfileStore
    package=Path(package).resolve();folder=Path(folder).resolve();assets=Path(assets).resolve()
    host=None;passed=False;metadata={};stage='package'
    def send(value):print(json.dumps(value,separators=(',',':')),flush=True)
    try:
        inventory=verify(package,'server')
        require(Path(sys.executable).resolve()==package/'program/runtime/python.exe','use server bundled Python')
        require(not folder.is_relative_to(package),'keep private output outside package')
        metadata['server_driver_sha256']=hashlib.sha256(Path(__file__).read_bytes()).hexdigest()
        metadata['production_modules']={}
        for name,module in list(sys.modules.items()):
            if not name.startswith(('server.','tools.')) or not getattr(module,'__file__',None):continue
            path=Path(module.__file__).resolve();require(path.is_relative_to(package/'program/app'),'server module outside bundle')
            digest=hashlib.sha256(path.read_bytes()).hexdigest()
            require(inventory['files'][path.relative_to(package).as_posix()]['sha256']==digest,'server module differs')
            metadata['production_modules'][name]=digest
        verify_assets(assets)
        template=GameTemplate.load(assets/'map-1v1.pb.gz',catalog_path=assets/'unit-catalog.json',descriptors_path=assets/'descriptors')
        metadata['asset_manifest_sha256']=hashlib.sha256((assets/'asset-manifest.json').read_bytes()).hexdigest()
        pki={name:ordinary_file(Path(pki_folder),leaf) for name,leaf in dict(cert='server.pem',key='server.key').items()}
        tls_transport.load_server_context(pki['cert'],pki['key'])
        if preflight_only:passed=True
        else:
            stage='private_issue';host=Host(folder,pki,template)
            send(dict(await host.start(),metadata=metadata))
            while True:
                stage='command'
                line=await asyncio.to_thread(sys.stdin.readline,1024)
                if not line:break
                request=json.loads(line)
                require(type(request) is dict and set(request)=={'command'},'invalid public command')
                command=request['command']
                require(command in ('settled','revoke','close'),'unknown public command')
                if command=='close':passed=True;break
                result=await getattr(host,command)();send(dict(ok=True,**result))
    except (Exception,KeyboardInterrupt) as error:
        metadata['error_type']=type(error).__name__;metadata['stage']=stage
    finally:
        if preflight_only:
            send(dict(preflight_only=True,private_api_attempted=False,read_only_preflight_passed=passed,metadata=metadata))
        else:
            cleanup=await host.close() if host is not None else {}
            try:
                verify(package,'server');verify_assets(assets)
                cleanup['server_package_and_assets_unchanged']=True
            except Exception:passed=False
            passed=passed and bool(cleanup) and all(cleanup.values())
            send(dict(closed=True,passed=passed,cleanup=cleanup,metadata=metadata))
    return 0 if passed else 2


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    for name in ('package','folder','pki','assets'):parser.add_argument('--'+name,type=Path,required=True)
    parser.add_argument('--preflight-only',action='store_true',help='read-only package/assets/PKI checks; no private API or listener')
    args=parser.parse_args()
    try:result=asyncio.run(serve(args.package,args.folder,args.pki,args.assets,preflight_only=args.preflight_only))
    except (Exception,KeyboardInterrupt):
        print('{"closed":true,"passed":false,"error_type":"driver_failure"}',flush=True);result=2
    raise SystemExit(result)
