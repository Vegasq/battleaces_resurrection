"""Own form rendering and actual Windows argv roundtrip; no desktop automation."""
import json
import os
from pathlib import Path
import subprocess
import sys
import unittest

from tests.test_credentials import private_test_folder, remove_test_folder

ROOT = Path(__file__).resolve().parents[1]


@unittest.skipUnless(os.name == 'nt', 'Windows PowerShell/WinForms setup')
class SetupArgumentsTests(unittest.TestCase):
    def test_native_argv_preserves_spaces_quotes_backslashes_and_shell_metacharacters(self):
        folder = private_test_folder('setup-argv-')
        try:
            values = ['', 'two words', 'quoted"value', 'one\\"two', 'C:\\directory with spaces\\',
                      '& whoami | echo %PATH%', '$env:USERNAME; `echo ignored`', 'Unicode \u00e9\u4e2d']
            (folder/'values.json').write_text(json.dumps(values), encoding='utf-8')
            (folder/'argv.py').write_text('import json,sys\nprint(json.dumps(sys.argv[1:]))\n')
            script = folder/'check.ps1'
            script.write_text(r'''
param([string]$Source,[string]$Python,[string]$Folder)
$ErrorActionPreference='Stop'
# Evaluate only the actual quoting function, without initializing WinForms or
# installing a UI synchronization context before launching the argv probe.
$tokens = $null; $parseErrors = $null
$ast = [System.Management.Automation.Language.Parser]::ParseFile($Source, [ref]$tokens, [ref]$parseErrors)
if ($parseErrors.Count -ne 0) { throw 'Setup source has PowerShell parse errors' }
$functions = @($ast.FindAll({ param($node)
    $node -is [System.Management.Automation.Language.FunctionDefinitionAst] -and $node.Name -eq 'Quote-Argument'
}, $true))
if ($functions.Count -ne 1) { throw 'Expected exactly one source Quote-Argument function' }
. ([scriptblock]::Create($functions[0].Extent.Text))
[Console]::Error.WriteLine('Argument probe: source function loaded')
$values = Get-Content -LiteralPath (Join-Path $Folder 'values.json') -Raw -Encoding UTF8 | ConvertFrom-Json
$info = New-Object System.Diagnostics.ProcessStartInfo
$info.FileName = $Python
$info.Arguments = (@('-I','-B',(Join-Path $Folder 'argv.py')) + $values | ForEach-Object { Quote-Argument $_ }) -join ' '
$info.UseShellExecute=$false; $info.CreateNoWindow=$true
$info.RedirectStandardOutput=$true; $info.RedirectStandardError=$true
$process = [System.Diagnostics.Process]::Start($info)
try {
    if (-not $process.WaitForExit(10000)) { $process.Kill(); throw 'Argument probe timed out' }
    # The authored child emits one small JSON line, safely below pipe capacity.
    $output = $process.StandardOutput.ReadToEnd(); $errors = $process.StandardError.ReadToEnd()
    if ($process.ExitCode -ne 0) { throw "Argument probe failed: $errors" }
    [Console]::Error.WriteLine('Argument probe: child completed')
    $output
} finally { $process.Dispose() }
''', encoding='utf-8')
            shell = Path(os.environ.get('SystemRoot', r'C:\Windows'))/'System32/WindowsPowerShell/v1.0/powershell.exe'
            result = subprocess.run([str(shell), '-NoProfile', '-STA', '-File', str(script),
                '-Source', str(ROOT/'client_patch/launcher/Configure-Client.ps1'),
                '-Python', sys.executable, '-Folder', str(folder)],
                capture_output=True, timeout=25, creationflags=subprocess.CREATE_NO_WINDOW)
            self.assertEqual(result.returncode, 0, result.stderr.decode(errors='replace'))
            self.assertEqual(json.loads(result.stdout), values)
        finally: remove_test_folder(folder)

    def test_full_setup_script_renders_preview(self):
        folder = private_test_folder('setup-preview-')
        try:
            shell = Path(os.environ.get('SystemRoot', r'C:\Windows'))/'System32/WindowsPowerShell/v1.0/powershell.exe'
            result = subprocess.run([str(shell), '-NoProfile', '-STA', '-File',
                str(ROOT/'client_patch/launcher/Configure-Client.ps1'),
                '-PythonExecutable', sys.executable, '-ConfigPath', str(folder/'client.json'),
                '-RenderPreview', str(folder/'preview.png')],
                capture_output=True, timeout=25, creationflags=subprocess.CREATE_NO_WINDOW)
            self.assertEqual(result.returncode, 0, result.stderr.decode(errors='replace'))
            self.assertTrue((folder/'preview.png').stat().st_size > 1000)
        finally: remove_test_folder(folder)


if __name__ == '__main__': unittest.main()
