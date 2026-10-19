"""Operator-run real Windows owner/SYSTEM credential check, using bundled modules.

Run from the normal desktop account, not a restricted automation token. This
external diagnostic opens no listener, changes no existing ACL/trust store and
does not qualify TLS, Connection Setup, SCM or another Windows account.
"""
from __future__ import annotations
import argparse
import hashlib
import json
import os
from pathlib import Path
import secrets
import sys
import time


def require(value,message):
    if not value:raise AssertionError(message)


def restricting_sids_present():
    """Narrow preflight only; FALSE does not prove every kind of token restriction.

    https://learn.microsoft.com/en-us/windows/win32/api/securitybaseapi/nf-securitybaseapi-istokenrestricted
    """
    import ctypes as c
    from ctypes import wintypes as w
    require(os.name=='nt','Windows desktop account required')
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


def exercise(private,folder,report):
    """Actual production issuance/import/auth/revoke; CLI never substitutes privacy APIs."""
    paths=[folder/'issued.json',folder/'enrolled/invite.json',folder/'unprotected-transfer.json',folder/'transferred/invite.json']
    store=None;issued=None;value=None;clean=True
    try:
        report['stage']='private_store';store=private.CredentialStore(folder/'store')
        report['stage']='issue';issued=store.issue_to_file(paths[0],label='Disposable owner acceptance check')
        value=private.read_credential_file(paths[0]);token=value['token'];original=paths[0].read_bytes()
        require(store.authenticate(token,expected_player_id=issued['player_id'])==issued['player_id'],'issued identity differs')
        require(token.encode() not in store.export_snapshot(),'store retained bearer token')
        report['issue_strict_read_and_store_authentication']=True
        report['stage']='identity_binding'
        wrong_player='p_'+('1' if issued['player_id'][2]!='1' else '2')+issued['player_id'][3:]
        try:store.authenticate(token,expected_player_id=wrong_player)
        except private.AuthenticationError:pass
        else:raise AssertionError('mismatched identity accepted')
        report['identity_mismatch_rejected']=True
        report['stage']='private_import';copied=private.import_credential_file(paths[0],paths[1],expected_sha256=hashlib.sha256(original).hexdigest())
        require(copied['player_id']==issued['player_id'] and private.read_credential_file(paths[1])==value,'private import differs')
        require(paths[0].read_bytes()==original,'import changed source')
        report['private_import_strict_readback']=True
        report['stage']='no_overwrite';before=store.export_snapshot()
        try:store.issue_to_file(paths[0],label='Must not overwrite')
        except (private.CredentialError,FileExistsError):pass
        else:raise AssertionError('existing handoff overwritten')
        require(store.export_snapshot()==before and paths[0].read_bytes()==original,'failed overwrite changed persisted state')
        report['existing_handoff_and_store_preserved']=True
        report['stage']='revoke';require(store.revoke(issued['invite_id']),'new credential already revoked')
        reopened=private.CredentialStore(folder/'store')
        try:reopened.authenticate(token)
        except private.AuthenticationError:pass
        else:raise AssertionError('revocation did not survive reopen')
        report['revocation_survives_reopen']=True
        # Transfer-format/ACL checks use an ALREADY REVOKED credential. The
        # ordinary transfer file never contains an active bearer credential.
        report['stage']='unprotected_transfer'
        with paths[2].open('xb') as stream:stream.write(original)
        try:private.read_credential_file(paths[2])
        except private.CredentialError:pass
        else:raise AssertionError('runtime accepted unprotected transferred file')
        private.import_credential_file(paths[2],paths[3],expected_sha256=hashlib.sha256(original).hexdigest())
        require(private.read_credential_file(paths[3])==value and paths[2].read_bytes()==original,'explicit transferred import differs')
        report['unprotected_runtime_read_rejected_explicit_import_succeeded']=True
        report['stage']='complete'
    finally:
        # Only this unique disposable store and explicitly created handoffs are
        # touched. Never alter an ACL or recursively delete a private directory.
        if store is not None:
            try:
                for record in store.list_public():store.revoke(record['invite_id'])
                require(not any(r['revoked_at'] is None for r in store.list_public()),'active disposable invite remains')
            except BaseException:clean=False
        for path in paths:
            require(path.resolve().is_relative_to(folder.resolve()),'owned cleanup path changed')
            try:path.unlink(missing_ok=True)
            except OSError:clean=False
        report['disposable_invites_revoked_and_handoffs_removed']=clean
        require(clean,'disposable credential cleanup incomplete')


def run(package,output,*,preflight_only=False):
    package=Path(package).resolve();output=Path(output).resolve()
    require(os.name=='nt' and not str(output).startswith('\\\\'),'local Windows paths required')
    output.mkdir(parents=True,exist_ok=True)
    folder=output/('run_'+secrets.token_hex(8));folder.mkdir()
    started=time.monotonic();report=dict(passed=False,scope=__doc__,stage='package',private_api_attempted=False,
        preflight_only=preflight_only,operator_source_sha256=hashlib.sha256(Path(__file__).read_bytes()).hexdigest())
    try:
        from tools.package_integrity import verify
        from server import credentials as private
        inventory=verify(package,'client')
        require(Path(sys.executable).resolve()==(package/'program/runtime/python.exe').resolve(),'use this client package bundled Python')
        report['production_modules']={}
        for module in (private,sys.modules['tools.package_integrity']):
            path=Path(module.__file__).resolve();require(path.is_relative_to(package/'program/app'),'module came from outside bundled app')
            digest=hashlib.sha256(path.read_bytes()).hexdigest()
            require(inventory['files'][path.relative_to(package).as_posix()]['sha256']==digest,'bundled module bytes differ')
            report['production_modules'][module.__name__]=digest
        report['stage']='token_query';report['restricting_sids_present']=restricting_sids_present()
        if preflight_only or report['restricting_sids_present']:
            report['stage']='preflight_only' if preflight_only else 'normal_desktop_required'
        else:
            report['private_api_attempted']=True;exercise(private,folder,report);report['passed']=True
    except (Exception,KeyboardInterrupt) as error:
        report['error_type']=type(error).__name__ # Never exception text/tracebacks or secret values.
    report['elapsed_seconds']=time.monotonic()-started
    encoded=json.dumps(report,indent=2)+'\n';(folder/'report.json').write_text(encoded,encoding='utf-8')
    temporary=output/('report_'+secrets.token_hex(8)+'.tmp')
    with temporary.open('x',encoding='utf-8') as stream:stream.write(encoded)
    temporary.replace(output/'last-report.json')
    print('Owner credential check: '+('PASS' if report['passed'] else 'NOT QUALIFIED')+'; stage='+report['stage'])
    print('Public report: '+str(output/'last-report.json'))
    return 0 if report['passed'] else 2


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--package',type=Path,required=True);parser.add_argument('--output',type=Path,required=True)
    parser.add_argument('--preflight-only',action='store_true',help='token/module checks ONLY; never attempt protected files')
    args=parser.parse_args();raise SystemExit(run(args.package,args.output,preflight_only=args.preflight_only))
