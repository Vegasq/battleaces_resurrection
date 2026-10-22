import copy
import re
import unittest
from tools.frida_cache_startup import build_source,ENTRIES,ROOT_SHA
from tools.frida_attribution_cwd import build_source as legacy
from tools.telemetry_cache_startup_evidence import validate


class CacheStartupTests(unittest.TestCase):
    def setUp(self):
        self.config=dict(image=r'E:\owned\local\game\Battle Aces.exe',runId='1'*32,eventLimit=4096,
                         fileRoots=[r'C:\owned\shared',r'E:\owned\local\game\.battleaces-resurrection\profiles\nativestest_authored'])
        self.cwd=dict(pid=17,pebAddress='0x1000')
        self.cache=dict(root=self.config['fileRoots'][1]+r'\queue123'+'/Bugsnag',
                        module=r'E:\owned\local\game\GameAssembly.dll',rootSha=ROOT_SHA,
                        entries=[dict(name=k,rva=v,sha256='0'*64) for k,v in ENTRIES.items()])

    def test_replacement_is_explicit_and_legacy_remains_passive(self):
        source=build_source(self.config,self.cwd,self.cache)
        self.assertIn('EXPLICIT OWNED CACHE ISOLATION',source)
        self.assertNotIn('Interceptor.replace',legacy(self.config,self.cwd))
        self.assertIn('cache:cacheSnapshot()',source)

    def test_foreign_root_wrong_module_or_incomplete_witness_contract_rejects(self):
        changes=[]
        for field,value in [('root',r'C:\shared\Bugsnag'),('module',r'C:\other\GameAssembly.dll'),
                            ('rootSha','0'*64),('entries',self.cache['entries'][:-1])]:
            change=copy.deepcopy(self.cache);change[field]=value;changes.append(change)
        for field,value in [('name','arbitrary'),('rva',1),('sha256','bad')]:
            change=copy.deepcopy(self.cache);change['entries'][0][field]=value;changes.append(change)
        change=copy.deepcopy(self.cache);change['entries'][-1]=copy.deepcopy(change['entries'][0]);changes.append(change)
        for change in changes:
            with self.subTest(change=change),self.assertRaises(ValueError):build_source(self.config,self.cwd,change)

    def test_native_control_cannot_qualify_external_startup_or_full_removal(self):
        line='[100] TELEMETRY CACHESTARTUP probe passed: version=1 thread=17 originalGetters=3 sdkRootMatched=1 deviceFilenameMatched=1 staticConfigNull=1 generalUnityPathUnchanged=1 cacheInstanceConstructed=0 reportPayloadRead=0 expiryCalled=0 scopedIcallOverride=0 externalEarlyRootShimRequired=1'
        rows=[dict(event='OnConfirm.dispatch',tick=110,thread=17)]
        proof=validate(line,rows)
        self.assertFalse(proof['startup_queue_isolation_qualified'])
        self.assertFalse(proof['analytics_removal_qualified'])
        changes=['',line+'\n'+line,line+'\nTELEMETRY CACHESTARTUP probe failed: injected',line.replace('thread=17','thread=18'),line.replace('[100]','[111]')]
        for match in re.finditer(r'\b(\w+)=(\d+)',line):
            if match[1] not in ('version','thread'):
                changes.append(re.sub(r'\b'+match[1]+r'=\d+',match[1]+'='+('1' if match[2]=='0' else '0'),line))
        for change in changes:
            with self.subTest(change=change),self.assertRaises(AssertionError):validate(change,rows)
