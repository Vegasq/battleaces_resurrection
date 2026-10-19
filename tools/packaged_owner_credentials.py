"""Real disposable owner credentials for opt-in packaged multiplayer acceptance.

No privacy/authentication fallback. Call only from a normal Windows desktop.
The restricted automation runner may use the read-only preflight, never issue.
"""
from __future__ import annotations
import hashlib
import json
import os
from pathlib import Path
import subprocess

from client_patch.transport import client,enrollment
from server import credentials as private


class OwnerCredentials:
    def __init__(self,root):
        self.root=Path(root).resolve();self.store=None;self.handoffs=[];self.enrolled=[];self.commands=[]

    def issue(self,count):
        if count not in (2,4):raise ValueError('unsupported owned player count')
        self.store=private.CredentialStore(self.root/'authored-private-store')
        private._ensure_private_directory(self.root/'protected-handoffs')
        identities=[]
        for index in range(count):
            path=self.root/'protected-handoffs'/f'player-{index}.json'
            self.handoffs.append(path)
            self.store.issue_to_file(path,label='Disposable packaged native acceptance')
            identities.append(private.read_credential_file(path))
        return identities

    def enroll(self,index,config,settings,ca,port,*,client_package=None):
        config=Path(config);source=self.handoffs[index];before=source.read_bytes()
        config.write_text(json.dumps(settings,indent=2)+'\n',encoding='utf-8')
        request=dict(schema=1,game_directory=settings['game_directory'],server_host='127.0.0.1',
            server_port=port,server_name='localhost',display_name=settings['display_name'],room=settings['room'],
            ca_source=str(ca),invite_source=str(source),expected_ca_sha256=hashlib.sha256(Path(ca).read_bytes()).hexdigest(),
            expected_config_sha256=enrollment.configuration_digest(config))
        if client_package is None:
            # Source lifecycle tests use the same backend directly, with their
            # explicitly mocked OS privacy boundary. Native operator runs use
            # the actual isolated packaged CLI below.
            enrollment.enroll(request,config)
        else:
            request_path=config.parent/f'enrollment-request-{index}.json'
            with request_path.open('x',encoding='utf-8') as stream:stream.write(json.dumps(request)+'\n')
            runtime=Path(client_package)/'program/runtime/python.exe'
            command=[str(runtime),'-I','-B','-m','tools.package_client','enroll','--request',str(request_path),'--config',str(config)]
            environment=os.environ.copy();environment['PATH']=str(Path(os.environ.get('SystemRoot',r'C:\Windows'))/'System32')
            try:
                result=subprocess.run(command,cwd=config.parent,env=environment,stdin=subprocess.DEVNULL,
                    stdout=subprocess.PIPE,stderr=subprocess.PIPE,timeout=60,
                    creationflags=subprocess.CREATE_NO_WINDOW if os.name=='nt' else 0)
                if result.returncode or result.stderr:raise AssertionError('packaged enrollment command failed')
                reply=json.loads(result.stdout)
                if reply.get('ok') is not True:raise AssertionError('packaged enrollment refused')
                self.commands.append(dict(command=command,exit_code=0,
                    request_sha256=hashlib.sha256(request_path.read_bytes()).hexdigest()))
            finally:request_path.unlink(missing_ok=True)
        loaded=client.load_connection(config);invite=loaded['credential_file'];self.enrolled.append(invite)
        for path in (config,loaded['ca_bundle'],invite):private._assert_private_path(path)
        actual=private.read_credential_file(invite)
        if source.read_bytes()!=before or actual!=private.read_credential_file(source):
            raise AssertionError('protected enrollment differs from issued invite')
        if client.prepare_settings(config)['local_profile']!=settings['local_profile']:
            raise AssertionError('enrollment lost local profile')
        if actual['token'].encode() in config.read_bytes():raise AssertionError('bearer token in public settings')
        return invite

    def dispose(self):
        clean=True
        if self.store is not None:
            try:
                for row in self.store.list_public():self.store.revoke(row['invite_id'])
                if any(row['revoked_at'] is None for row in self.store.list_public()):clean=False
            except Exception:clean=False
        # Include a transaction committed before a later readback failed. Only
        # this fresh run's known production enrollment handoff leaves qualify.
        paths=set(self.handoffs+self.enrolled+list((self.root/'config/private').glob('enrollment-*/private-invite.json')))
        for path in paths:
            if not path.resolve().is_relative_to(self.root):raise AssertionError('owned credential cleanup escaped run')
            try:path.unlink(missing_ok=True)
            except OSError:clean=False
        return dict(disposable_invites_revoked_and_handoffs_removed=clean)
