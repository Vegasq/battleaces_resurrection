"""Inventory direct Python socket creation in the current private package pair."""
from __future__ import annotations

import argparse
import ast
import hashlib
import json
from pathlib import Path

from tools.build_windows_packages import CLIENT, SERVER
from tools.package_integrity import verify

ROOT=Path(__file__).resolve().parents[1]
SINKS={'socket','socketpair','open_connection','start_server','connect_accepted_socket',
       'sock_connect','bind','listen','connect','getaddrinfo','sendto','create_connection'}
EXPECTED={
    ('client_patch/transport/launcher.py',287,'socket.socketpair'),
    ('client_patch/transport/launcher.py',291,'asyncio.open_connection'),
    ('server/dedicated_server.py',676,'asyncio.start_server'),
    ('server/tls_listener.py',146,'loop.connect_accepted_socket'),
    ('server/tls_listener.py',201,'socket.socket'),
    ('server/tls_listener.py',209,'listener.bind'),
    ('server/tls_listener.py',210,'listener.listen'),
    ('server/tls_transport.py',170,'asyncio.open_connection'),
    ('server/web_dashboard.py',119,'asyncio.start_server'),
}
FORBIDDEN_IMPORTS={'urllib.request','http.client','requests','httpx','aiohttp',
                   'websocket','websockets'}


def sha(path):return hashlib.sha256(path.read_bytes()).hexdigest()


def inventory():
    rows=set();imports=set();dynamic=[]
    for name in sorted(set(SERVER+CLIENT)):
        path=ROOT/name
        if path.suffix!='.py':continue
        tree=ast.parse(path.read_text(encoding='utf-8'))
        for node in ast.walk(tree):
            if isinstance(node,ast.Import):
                imports.update(alias.name for alias in node.names)
            elif isinstance(node,ast.ImportFrom) and node.module:
                imports.add(node.module)
            elif isinstance(node,ast.Call):
                function=node.func
                if isinstance(function,ast.Attribute) and function.attr in SINKS:
                    rows.add((name,node.lineno,ast.unparse(function)))
                if isinstance(function,ast.Name) and function.id in {'eval','exec','__import__'}:
                    dynamic.append((name,node.lineno,function.id))
                if isinstance(function,ast.Attribute) and function.attr=='import_module':
                    dynamic.append((name,node.lineno,ast.unparse(function)))
    assert rows==EXPECTED,(sorted(rows-EXPECTED),sorted(EXPECTED-rows))
    assert not dynamic,dynamic
    assert not any(name in FORBIDDEN_IMPORTS or any(name.startswith(key+'.') for key in FORBIDDEN_IMPORTS)
                   for name in imports)
    return sorted(rows),sorted(imports)


def review(packages,case):
    build=json.loads((packages/'build-report.json').read_text(encoding='utf-8'))
    report=json.loads((case/'verification.json').read_text(encoding='utf-8'))
    assert report['passed'] and report['mode']==1 and report['humans']==2
    assert Path(report['packages']).resolve()==packages
    assert build['versions']['game_build']==37822
    copied={}
    for kind,names in (('client',CLIENT),('server',SERVER)):
        package=packages/f'battleaces-{kind}-win64'
        assert verify(package,kind)
        matched=0
        for name in names:
            if not Path(name).suffix in ('.py','.ps1'):continue
            source=ROOT/name; bundled=package/'program/app'/name
            assert source.read_bytes()==bundled.read_bytes(),name
            matched+=1
        copied[kind]=matched
        archive=build['packages'][kind]
        assert sha(packages/archive['archive'])==archive['sha256']
    sinks,imports=inventory()
    host=json.loads((case/'config/host.json').read_text(encoding='utf-8'))
    clients=[json.loads((case/f'config/client-{index}.json').read_text(encoding='utf-8'))
             for index in range(2)]
    assert host['listen_host']==host['dashboard_host']=='127.0.0.1'
    assert all(row['server_host']==host['listen_host'] and
               row['server_port']==host['listen_port'] for row in clients)
    tls=(ROOT/'server/tls_transport.py').read_text(encoding='utf-8')
    bridge=(ROOT/'client_patch/transport/bridge.py').read_text(encoding='utf-8')
    launcher=(ROOT/'client_patch/transport/launcher.py').read_text(encoding='utf-8')
    ps=(ROOT/'client_patch/launcher/ClientConfig.ps1').read_text(encoding='utf-8')
    page=(ROOT/'server/web_dashboard_page.py').read_text(encoding='utf-8')
    assert 'asyncio.open_connection(host, port, ssl=tls.context' in tls
    assert 'tls.open_verified_connection(remote.host, remote.port, remote.tls)' in bridge
    assert 'socket.socketpair(socket.AF_INET)' in launcher
    assert '[System.Net.Dns]::GetHostAddresses($HostName)' in ps
    assert "fetch('/api/status?page='+page" in page
    return dict(passed=True,scope='Direct socket-creation call sites in source-matched packaged Python modules and selected loopback fixture config; not whole-process/wire absence',
                package_build_sha256=sha(packages/'build-report.json'),
                connected_report_sha256=sha(case/'verification.json'),
                source_files_compared=copied,python_direct_socket_sinks=[
                    dict(path=path,line=line,call=call) for path,line,call in sinks],
                python_import_count=len(imports),dynamic_import_eval_calls=[],
                selected_server_host=host['listen_host'],selected_server_port=host['listen_port'],
                configuration_dns_possible=True,dashboard_relative_fetch=True,
                native_game_and_worker_egress_unclassified=True,
                all_thread_wire_qualified=False,full_d5_qualified=False)


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    for name in ('packages','case','output'):parser.add_argument('--'+name,type=Path,required=True)
    args=parser.parse_args()
    paths={name:getattr(args,name).resolve() for name in ('packages','case','output')}
    assert all(path.is_relative_to(ROOT/'local') for path in paths.values())
    result=review(paths['packages'],paths['case'])
    paths['output'].parent.mkdir(parents=True,exist_ok=True)
    assert not paths['output'].exists()
    paths['output'].write_text(json.dumps(result,indent=2)+'\n',encoding='utf-8')
    print(json.dumps({'passed':result['passed'],'sinks':len(result['python_direct_socket_sinks']),
                      'source_files_compared':result['source_files_compared']}))


if __name__=='__main__':main()
