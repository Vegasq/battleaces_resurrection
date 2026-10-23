import json,shutil,subprocess,unittest
from tools.frida_webview_process import COMMAND,build_source


class CommandMetadata(unittest.TestCase):
    path=r'E:\Game Folder\.battleaces-resurrection\profiles\nativestest_owned\webview-cache'
    def facts(self,command):
        code=COMMAND.replace('__CACHE__',json.dumps(self.path))
        driver="const fs=require('fs'),vm=require('vm'),v=JSON.parse(fs.readFileSync(0,'utf8')),ctx=vm.createContext({});vm.runInContext(v.source,ctx);try{process.stdout.write(JSON.stringify(vm.runInContext('webviewCommandFacts('+JSON.stringify(v.command)+')',ctx)));}catch(e){process.stdout.write(JSON.stringify({error:String(e)}));}"
        r=subprocess.run([shutil.which('node'),'-e',driver],input=json.dumps(dict(source=code,command=command)),text=True,capture_output=True,check=True,timeout=5)
        return json.loads(r.stdout)
    def test_quoted_owned_path_and_values_are_not_exposed(self):
        v=self.facts('"E:\\Game Folder\\Vuplex WebView.vuplex" "----vx-cache-path='+self.path+'" --type=renderer --license=DO_NOT_EMIT --pipe=PRIVATE_PIPE')
        self.assertTrue(v['ownedCacheMatches']);self.assertEqual(v['cacheFlagCount'],1);self.assertEqual(v['processType'],'renderer')
        text=json.dumps(v);self.assertNotIn('DO_NOT_EMIT',text);self.assertNotIn('PRIVATE_PIPE',text);self.assertNotIn('Game Folder',text)
    def test_duplicate_foreign_and_missing_cache_do_not_match(self):
        for value in ('app ----vx-cache-path=E:\\foreign','app','app "----vx-cache-path='+self.path+'" "----vx-cache-path='+self.path+'"', 'app "--vx-cache-path='+self.path+'"'):
            self.assertFalse(self.facts(value)['ownedCacheMatches'])
    def test_unknown_type_is_redacted_and_bad_quotes_reject(self):
        v=self.facts('app --type=PRIVATE_TYPE --token=PRIVATE_VALUE');self.assertEqual(v['processType'],'other')
        self.assertNotIn('PRIVATE',json.dumps(v));self.assertIn('error',self.facts('app "unclosed'))
    def test_builder_refuses_non_owned_cache(self):
        for value in ('relative',r'E:\foreign\webview-cache',None):
            with self.assertRaises(ValueError):build_source(dict(image=r'E:\Game Folder\Battle Aces.exe'),{},cache_path=value)
    def test_larger_budget_is_bounded_and_only_opt_in(self):
        from tools.frida_sdk_startup import ENTRIES,build_source as legacy
        config=dict(image=r'E:\Game Folder\Battle Aces.exe',runId='1'*32,eventLimit=16384,
            fileRoots=[r'E:\shared',self.path.rsplit('\\',1)[0]])
        cwd=dict(pid=17,pebAddress='0x1000')
        sdk=dict(module=r'E:\Game Folder\GameAssembly.dll',entries=[dict(name=k,rva=v,sha256='0'*64) for k,v in ENTRIES.items()])
        source=build_source(config,cwd,sdk,cache_path=self.path)
        self.assertIn('const config='+json.dumps(config)+', api=',source)
        self.assertIn("if(sequence>=config.eventLimit)",source)
        self.assertIn('Child command lines are parsed transiently',source)
        with self.assertRaises(ValueError):legacy(config,cwd,sdk)
        for value in (True,99,16385,None):
            with self.assertRaises(ValueError):build_source(dict(config,eventLimit=value),cwd,sdk,cache_path=self.path)
    def test_native_reader_accepts_long_command_and_refuses_unterminated(self):
        source=COMMAND.replace('__CACHE__',json.dumps(self.path))
        driver="const vm=require('vm'),fs=require('fs'),v=JSON.parse(fs.readFileSync(0,'utf8')),ctx=vm.createContext({});vm.runInContext(v.source,ctx);vm.runInContext(\"class P{constructor(s,o=0){this.s=s;this.o=o;}isNull(){return false;}add(n){return new P(this.s,this.o+n);}readU16(){return this.s.charCodeAt(this.o/2)||0;}}\",ctx);const a=vm.runInContext(\"webviewReadCommand(new P('x'.repeat(1024)),true).length\",ctx);let rejected=false;try{vm.runInContext(\"webviewReadCommand(new P('x'.repeat(32767)),true)\",ctx);}catch(e){rejected=true;}process.stdout.write(JSON.stringify([a,rejected]));"
        r=subprocess.run([shutil.which('node'),'-e',driver],input=json.dumps(dict(source=source)),text=True,capture_output=True,check=True,timeout=5)
        self.assertEqual(json.loads(r.stdout),[1024,True])


if __name__=='__main__':unittest.main()
