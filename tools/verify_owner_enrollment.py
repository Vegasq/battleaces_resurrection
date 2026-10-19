"""Normal-desktop packaged enrollment/TLS acceptance with disposable credentials.

Opens one temporary localhost-only production coordinator, but no game or native
worker. Uses separate client/server bundled runtimes and supplied authored test
PKI; changes no system trust or existing
configuration/ACL. This is not graphical setup, host.run, SCM or cross-PC proof.
"""
from __future__ import annotations
import argparse
import asyncio
import hashlib
import json
import os
from pathlib import Path
import secrets
import ssl
import subprocess
import sys
import time


def require(value, message):
    if not value: raise AssertionError(message)


def restricting_sids_present():
    # Narrow preflight only; actual private creation/readback decides acceptance.
    # IsTokenRestricted does not detect every form of token restriction.
    import ctypes as c
    from ctypes import wintypes as w
    k=c.WinDLL('kernel32',use_last_error=True);a=c.WinDLL('advapi32',use_last_error=True)
    k.GetCurrentProcess.restype=w.HANDLE;k.CloseHandle.argtypes=[w.HANDLE]
    a.OpenProcessToken.argtypes=[w.HANDLE,w.DWORD,c.POINTER(w.HANDLE)];a.OpenProcessToken.restype=w.BOOL
    a.IsTokenRestricted.argtypes=[w.HANDLE];a.IsTokenRestricted.restype=w.BOOL
    token=w.HANDLE()
    require(a.OpenProcessToken(k.GetCurrentProcess(),8,c.byref(token)),'process token query unavailable')
    try:
        c.set_last_error(0);restricted=bool(a.IsTokenRestricted(token));error=c.get_last_error()
        require(restricted or error==0,'restricting-SID query unavailable')
        return restricted
    finally:k.CloseHandle(token)


class HostProcess:
    """Public stdio control only; no authentication/privacy substitutions."""
    def __init__(self,package,folder,pki,assets,driver):
        self.package=package;self.folder=folder;self.pki=pki;self.assets=assets;self.driver=driver
        self.process=None;self.errors=None;self.closed=None;self.metadata={};self.port=None

    async def _receive(self):
        line=await asyncio.wait_for(self.process.stdout.readline(),20)
        require(0<len(line)<=65536,'missing or excessive server diagnostic reply')
        value=json.loads(line);require(isinstance(value,dict),'invalid server diagnostic reply');return value

    async def _errors(self):
        count=0
        while chunk:=await self.process.stderr.read(4096):count+=len(chunk)
        return count # Never retain or publish raw stderr.

    async def start(self):
        self.process=await asyncio.create_subprocess_exec(str(self.package/'program/runtime/python.exe'),
            '-I','-B',str(self.driver),'--package',str(self.package),'--folder',str(self.folder),
            '--pki',str(self.pki),'--assets',str(self.assets),stdin=asyncio.subprocess.PIPE,
            stdout=asyncio.subprocess.PIPE,stderr=asyncio.subprocess.PIPE,
            creationflags=subprocess.CREATE_NO_WINDOW if os.name=='nt' else 0)
        self.errors=asyncio.create_task(self._errors())
        ready=await self._receive();require(ready.get('ready') is True,'server failed before readiness')
        self.port=ready['port'];self.metadata=ready['metadata']
        require(self.metadata['server_driver_sha256']==hashlib.sha256(self.driver.read_bytes()).hexdigest(),
                'server driver source differs')

    async def _command(self,command):
        self.process.stdin.write((json.dumps(dict(command=command))+'\n').encode())
        await self.process.stdin.drain();reply=await self._receive()
        require(reply.get('ok') is True,'server command failed');return reply

    async def settled(self):return await self._command('settled')
    async def revoke(self):return await self._command('revoke')

    async def close(self):
        if self.closed is not None:return self.closed
        report=dict(listener_sessions_and_admission_released=False,
            disposable_invites_revoked_and_handoffs_removed=False,server_process_natural_exit=False)
        if self.process is None:return report
        try:
            if self.process.returncode is None:
                self.process.stdin.write(b'{"command":"close"}\n');await self.process.stdin.drain()
                reply=await self._receive()
                require(reply.get('closed') is True and reply.get('passed') is True,'server cleanup failed')
                report.update(reply['cleanup']);self.metadata=reply['metadata']
            self.process.stdin.close()
            require(await asyncio.wait_for(self.process.wait(),15)==0,'server process did not exit successfully')
            require(await asyncio.wait_for(self.errors,5)==0,'server diagnostic emitted stderr')
            report['server_process_natural_exit']=True
        except (Exception,asyncio.CancelledError):
            if self.process.returncode is None:
                self.process.stdin.close()
                try:await asyncio.wait_for(self.process.wait(),10)
                except asyncio.TimeoutError:
                    self.process.kill();await self.process.wait()
            if self.errors is not None:await self.errors
        self.closed=report;return report


async def exercise(folder,pki,report,host):
    """Production APIs throughout; tests explicitly mock only the OS privacy boundary."""
    from server import credentials as private, admission
    from client_patch.transport import enrollment as e, client
    folder=Path(folder).resolve();setup=folder/'setup';setup.mkdir()
    config=setup/'client.json';issued=host.folder/'host-private/issued.json'
    mismatch=folder/'identity-mismatch.json';negative=setup/'negative.json'
    clean=True
    try:
        report['stage']='private_read'
        original=issued.read_bytes();value=private.read_credential_file(issued)
        public=value
        baseline=client.defaults(folder/'no-game-launched')
        baseline.update(display_name='Owner Check',local_profile='owner_enrollment')
        config.write_text(json.dumps(baseline),encoding='utf-8')
        request=dict(schema=1,game_directory=str(folder/'no-game-launched'),server_host='127.0.0.1',
            server_port=host.port,server_name='localhost',display_name='Owner Check',room='ownercheck',
            ca_source=str(pki['ca']),invite_source=str(issued),
            expected_ca_sha256=hashlib.sha256(pki['ca'].read_bytes()).hexdigest(),
            expected_config_sha256=e.configuration_digest(config))
        report['stage']='enrollment'
        result=e.enroll(request,config);loaded=client.load_connection(config)
        require(result['player_id']==public['player_id'],'enrolled identity differs')
        for path in (config,loaded['ca_bundle'],loaded['credential_file']):private._assert_private_path(path)
        for path in (setup/'private',loaded['credential_file'].parent):private._assert_private_path(path,directory=True)
        require(private.read_credential_file(loaded['credential_file'])==value and issued.read_bytes()==original,
                'enrollment changed invite or source')
        require(client.prepare_settings(config)['local_profile']=='owner_enrollment','local profile lost')
        require(loaded['display_name']=='Owner Check' and value['token'].encode() not in config.read_bytes(),
                'public settings or secret boundary differs')
        report['protected_enrollment_and_profile_preserved']=True
        committed=config.read_bytes()
        report['stage']='transaction_refusals'
        for altered in (dict(request,expected_ca_sha256='0'*64,expected_config_sha256=e.configuration_digest(config)),request):
            try:e.enroll(altered,config)
            except e.EnrollmentError:pass
            else:raise AssertionError('mismatched trust or stale configuration accepted')
            require(config.read_bytes()==committed and issued.read_bytes()==original,'refusal changed config or source')
        report['wrong_fingerprint_and_stale_save_preserve_config']=True
        report['stage']='verified_tls_authentication'
        connected=await asyncio.wait_for(e.check_connection(config),10)
        require(connected['authenticated'] and connected['player_id']==public['player_id'] and
                connected['tls'] in ('TLSv1.2','TLSv1.3'),'TLS authentication differs')
        await host.settled();report['verified_tls_authentication_without_game']=True
        report['stage']='tls_refusals'
        saved=json.loads(committed)
        for change in (dict(server_name='wrong.invalid'),dict(ca_bundle=str(pki['unrelated_ca']))):
            private._write_file(negative,(json.dumps(dict(saved,**change))+'\n').encode())
            try:
                try:await asyncio.wait_for(e.check_connection(negative),10)
                except ssl.SSLCertVerificationError:pass
                else:raise AssertionError('wrong TLS trust or name accepted')
            finally:negative.unlink(missing_ok=True)
            await host.settled()
        report['wrong_ca_and_server_name_rejected']=True
        report['stage']='identity_refusal'
        wrong='p_'+('1' if public['player_id'][2]!='1' else '2')+public['player_id'][3:]
        private._write_file(mismatch,(json.dumps(dict(value,player_id=wrong))+'\n').encode())
        private._write_file(negative,(json.dumps(dict(saved,credential_file=str(mismatch)))+'\n').encode())
        try:await asyncio.wait_for(e.check_connection(negative),10)
        except e.EnrollmentError:pass
        else:raise AssertionError('authenticated identity mismatch accepted')
        await host.settled();report['authenticated_identity_mismatch_rejected']=True
        report['stage']='revoked_tls_refusal'
        require((await host.revoke())['revoked'],'disposable invite already revoked')
        try:await asyncio.wait_for(e.check_connection(config),10)
        except admission.AdmissionError:pass
        else:raise AssertionError('revoked TLS credential accepted')
        await host.settled();report['revoked_invite_rejected_over_tls']=True
        require(config.read_bytes()==committed and issued.read_bytes()==original,'connection checks changed inputs')
        report['no_room_profile_or_worker_created']=True
    finally:
        try:
            cleanup=await host.close();report.update(cleanup)
            require(all(cleanup.values()),'server cleanup incomplete')
        except BaseException:clean=False
        # Only this unique owned run, known leaves and enrollment-created bearer
        # handoffs. No recursive deletion or ACL change, even on failure.
        paths=[issued,mismatch,negative,config,*list((setup/'private').glob('enrollment-*/private-invite.json'))]
        for path in paths:
            require(path.resolve().is_relative_to(folder),'owned cleanup path changed')
            try:path.unlink(missing_ok=True)
            except OSError:clean=False
        report['disposable_invites_revoked_and_handoffs_removed']=clean
        require(clean,'owned cleanup incomplete')
    report['stage']='complete'


def run(package,server_package,output,pki_folder,assets,*,preflight_only=False):
    package=Path(package).resolve();output=Path(output).resolve();pki_folder=Path(pki_folder).resolve()
    require(os.name=='nt' and not str(output).startswith('\\\\'),'local Windows paths required')
    server_package=Path(server_package).resolve();assets=Path(assets).resolve()
    require(not output.is_relative_to(package) and not output.is_relative_to(server_package),'keep acceptance output outside packages')
    output.mkdir(parents=True,exist_ok=True);folder=output/('run_'+secrets.token_hex(8));folder.mkdir()
    started=time.monotonic();report=dict(passed=False,scope=__doc__,stage='package',private_api_attempted=False,
        preflight_only=preflight_only,operator_source_sha256=hashlib.sha256(Path(__file__).read_bytes()).hexdigest())
    try:
        from tools.package_integrity import verify,ordinary_file
        from client_patch.transport import enrollment
        inventory=verify(package,'client');verify(server_package,'server')
        require(Path(sys.executable).resolve()==package/'program/runtime/python.exe','use the client bundled Python')
        report['production_modules']={}
        for name,module in list(sys.modules.items()):
            if not name.startswith(('server.','client_patch.','tools.')) or not getattr(module,'__file__',None):continue
            path=Path(module.__file__).resolve()
            require(path.is_relative_to(package/'program/app'),'production module outside bundled app')
            digest=hashlib.sha256(path.read_bytes()).hexdigest()
            require(inventory['files'][path.relative_to(package).as_posix()]['sha256']==digest,'bundled module differs')
            report['production_modules'][name]=digest
        pki={name:ordinary_file(pki_folder,leaf) for name,leaf in
             dict(ca='ca.pem',cert='server.pem',key='server.key',unrelated_ca='unrelated.pem').items()}
        before={name:hashlib.sha256(path.read_bytes()).hexdigest() for name,path in pki.items()}
        report['test_ca_sha256']=before['ca'];report['stage']='token_query'
        report['restricting_sids_present']=restricting_sids_present()
        if preflight_only or report['restricting_sids_present']:
            report['stage']='preflight_only' if preflight_only else 'normal_desktop_required'
        else:
            report['private_api_attempted']=True
            driver=Path(__file__).with_name('owner_enrollment_host.py')
            async def check():
                host=HostProcess(server_package,folder/'host',pki_folder,assets,driver)
                try:
                    report['stage']='server_start';await host.start()
                    await asyncio.wait_for(exercise(folder,pki,report,host),45)
                finally:
                    cleanup=await host.close();report.update(cleanup);report['server']=host.metadata
                    require(all(cleanup.values()),'server process cleanup incomplete')
            asyncio.run(check())
            verify(package,'client');verify(server_package,'server')
            require(all(hashlib.sha256(path.read_bytes()).hexdigest()==before[name] for name,path in pki.items()),'test PKI changed')
            report['packages_and_test_pki_unchanged']=True;report['passed']=True
    except (Exception,KeyboardInterrupt) as error:
        report['error_type']=type(error).__name__ # No exception payload/traceback or bearer values.
    report['elapsed_seconds']=time.monotonic()-started
    encoded=json.dumps(report,indent=2)+'\n';(folder/'report.json').write_text(encoded,encoding='utf-8')
    temporary=output/('report_'+secrets.token_hex(8)+'.tmp');temporary.write_text(encoded,encoding='utf-8')
    temporary.replace(output/'last-report.json')
    print('Owner enrollment/TLS check: '+('PASS' if report['passed'] else 'NOT QUALIFIED')+'; stage='+report['stage'])
    print('Public report: '+str(output/'last-report.json'))
    return 0 if report['passed'] else 2


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    for name in ('package','server-package','output','pki','assets'):parser.add_argument('--'+name,type=Path,required=True)
    parser.add_argument('--preflight-only',action='store_true',help='module/token query only; no listener or protected file API')
    args=parser.parse_args();raise SystemExit(run(args.package,args.server_package,args.output,args.pki,args.assets,preflight_only=args.preflight_only))
