"""Actual pure C# shortcut/result helpers; no COM, form, installer or game runs."""
import json
import os
from pathlib import Path
import subprocess
import unittest

from tests.test_credentials import private_test_folder, remove_test_folder

ROOT=Path(__file__).resolve().parents[1]
SHELL=Path(os.environ.get('SystemRoot',r'C:\Windows'))/'System32/WindowsPowerShell/v1.0/powershell.exe'

HARNESS=r'''
using System;
using System.Collections.Generic;
using System.IO;
using System.Reflection;
using System.Web.Script.Serialization;
public static class ShortcutHarness {
    public static void Run(string input, string output) {
        var serializer = new JavaScriptSerializer { MaxJsonLength = 1048576 };
        var requests = serializer.Deserialize<Dictionary<string,object>[]>(File.ReadAllText(input));
        var results = new List<object>();
        foreach (var row in requests) {
            try {
                string operation = (string)row["operation"], launcher = (string)row["launcher"];
                bool server = (bool)row["server"];
                object value;
                if (operation == "name") value = DesktopShortcut.Name(server, launcher);
                else if (operation == "message") value = DesktopShortcut.SuccessMessage(launcher, server);
                else if (operation == "marker") value = typeof(DesktopShortcut).GetMethod("Marker", BindingFlags.NonPublic | BindingFlags.Static).Invoke(null, new object[] { server, launcher });
                else if (operation == "payload") value = InstallerPayload.Root((string)row["directory"], server);
                else value = DesktopShortcut.InstalledLauncher((string)row["output"], (string)row["directory"], server);
                results.Add(new { ok = true, value = value });
            } catch (Exception error) { results.Add(new { ok = false, error = error.GetType().FullName }); }
        }
        File.WriteAllText(output, serializer.Serialize(results));
    }
}
'''


@unittest.skipUnless(os.name=='nt' and SHELL.is_file(),'Windows managed C# test host required')
class DesktopShortcutTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.folder=private_test_folder('shortcut-pure-')
        cls.addClassCleanup(remove_test_folder,cls.folder)
        cls.game=cls.folder/'chosen game';cls.game.mkdir()
        cls.other=cls.folder/'other game';cls.other.mkdir()
        cls.nested=cls.game/'nested';cls.nested.mkdir()
        for directory in (cls.game,cls.other,cls.nested):
            for name in ('Start Battle Aces.cmd','Start Prediction Client.cmd','Start Server.exe','Start Prediction Client.cmd.exe'):
                (directory/name).write_bytes(b'authored nonexecutable launcher fixture')
        cls.harness=cls.folder/'Harness.cs';cls.harness.write_text(HARNESS,encoding='utf-8')
        cls.script=cls.folder/'test.ps1';cls.script.write_text(r'''
param([string]$Source,[string]$Harness,[string]$Requests,[string]$Results)
$ErrorActionPreference='Stop'
Add-Type -Path @($Source,$Harness) -ReferencedAssemblies System.Web.Extensions.dll
[ShortcutHarness]::Run($Requests,$Results)
''',encoding='utf-8')

    def run_helpers(self,requests):
        source=self.folder/'input.json';target=self.folder/'output.json'
        source.write_text(json.dumps(requests),encoding='utf-8');target.unlink(missing_ok=True)
        result=subprocess.run([str(SHELL),'-NoProfile','-NonInteractive','-File',str(self.script),
            '-Source',str(ROOT/'client_patch/installer/DesktopShortcut.cs'),'-Harness',str(self.harness),
            '-Requests',str(source),'-Results',str(target)],capture_output=True,timeout=30,
            creationflags=subprocess.CREATE_NO_WINDOW)
        self.assertEqual(result.returncode,0,result.stderr.decode(errors='replace'))
        return json.loads(target.read_text(encoding='utf-8'))

    def request(self,operation,launcher,server=False,**extra):
        return dict(operation=operation,launcher=launcher,server=server,**extra)

    def result_request(self,launcher,server=False,**extra):
        output=json.dumps(dict(ok=True,result=dict(installed=True,launcher=launcher)))
        return self.request('validate',None,server,output=output,directory=str(self.game),**extra)

    def test_prediction_shortcut_is_distinct_and_server_and_ordinary_names_stay_unchanged(self):
        requests=[self.request('name',str(self.game/name),server) for name,server in (
            ('Start Battle Aces.cmd',False),('Start Prediction Client.cmd',False),
            ('START PREDICTION CLIENT.CMD',False),('Start Prediction Client.cmd.exe',False),
            ('Start Server.exe',True),('Start Prediction Client.cmd',True))]
        result=self.run_helpers(requests)
        self.assertEqual([x['value']for x in result],['Battle Aces Resurrection.lnk','Battle Aces Prediction Test.lnk',
            'Battle Aces Prediction Test.lnk','Battle Aces Resurrection.lnk','Battle Aces Server.lnk','Battle Aces Server.lnk'])

    def test_prediction_description_and_success_message_do_not_claim_an_ordinary_shortcut(self):
        names=('Start Battle Aces.cmd','Start Prediction Client.cmd','Start Server.exe')
        requests=[self.request(operation,str(self.game/name),name.endswith('.exe'))
            for operation in ('marker','message')for name in names]
        result=self.run_helpers(requests)
        self.assertEqual(len({x['value']for x in result[:3]}),3)
        self.assertEqual([x['value']for x in result[3:]],[
            'Installed. Battle Aces Resurrection shortcut created on your desktop.',
            'Installed. Battle Aces Prediction Test shortcut created on your desktop.',
            'Installed. Battle Aces Server shortcut created on your desktop.'])

    def test_successful_client_and_server_envelopes_select_only_the_returned_existing_launcher(self):
        names=('Start Battle Aces.cmd','Start Prediction Client.cmd','Start Server.exe')
        result=self.run_helpers([self.result_request(str(self.game/name),name.endswith('.exe'))for name in names])
        self.assertEqual([x['value']for x in result],[str(self.game/name)for name in names])

    def test_unexpected_external_nested_missing_relative_and_wrong_product_targets_are_rejected(self):
        requests=[self.result_request(str(path),server)for path,server in (
            (self.other/'Start Prediction Client.cmd',False),(self.nested/'Start Prediction Client.cmd',False),
            (self.game/'Start Prediction Client.cmd.exe',False),(self.game/'missing.cmd',False),
            (Path('Start Prediction Client.cmd'),False),(self.game/'Start Server.exe',False),
            (self.game/'Start Prediction Client.cmd',True))]
        self.assertTrue(all(not x['ok']for x in self.run_helpers(requests)))

    def test_failed_or_malformed_success_output_never_creates_a_launcher_result(self):
        launcher=str(self.game/'Start Prediction Client.cmd')
        outputs=['','{}','not JSON','[]',json.dumps(dict(ok=False,result=dict(installed=True,launcher=launcher))),
            json.dumps(dict(ok=1,result=dict(installed=True,launcher=launcher))),
            json.dumps(dict(ok=True,result=dict(installed=False,launcher=launcher))),
            json.dumps(dict(ok=True,result=dict(installed=True,launcher=42))),
            json.dumps(dict(ok=True,result=dict(installed=True))), ' '*131073]
        result=self.run_helpers([self.request('validate',None,output=x,directory=str(self.game))for x in outputs])
        self.assertTrue(all(not x['ok']for x in result))

    def test_embedded_payload_selects_one_valid_standard_or_prediction_root_and_keeps_exact_server_root(self):
        standard='battleaces-client-win64';prediction='battleaces-client-prediction-private-win64'
        cases={'standard':[standard],'prediction':[prediction],'ambiguous':[standard,prediction],
            'missing':['unexpected-client-root'],'incomplete':[],'valid_and_incomplete':[standard]}
        folders={}
        for label,names in cases.items():
            folder=self.folder/('payload-'+label);folder.mkdir();folders[label]=folder
            for name in names:
                package=folder/name;(package/'program/runtime').mkdir(parents=True)
                (package/'package-manifest.json').write_text('{}')
                (package/'program/runtime/python.exe').write_bytes(b'authored nonexecutable interpreter fixture')
            if label in ('incomplete','valid_and_incomplete'):
                package=folder/prediction;package.mkdir();(package/'package-manifest.json').write_text('{}')
        result=self.run_helpers([self.request('payload',None,directory=str(folders[label]))for label in cases]+
            [self.request('payload',None,True,directory=str(folders['ambiguous']))])
        self.assertEqual(result[0]['value'],str(folders['standard']/standard))
        self.assertEqual(result[1]['value'],str(folders['prediction']/prediction))
        self.assertTrue(all(not x['ok']for x in result[2:5]))
        self.assertEqual(result[5]['value'],str(folders['valid_and_incomplete']/standard))
        self.assertEqual(result[6]['value'],str(folders['ambiguous']/'battleaces-server-win64'))


if __name__=='__main__':unittest.main()
