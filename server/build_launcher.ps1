param([string]$OutputDirectory = '', [string]$CompilerRoot = '', [string]$SdkVersion = '')
$ErrorActionPreference = 'Stop'
$repo = Split-Path -Parent $PSScriptRoot
if (-not $OutputDirectory) { $OutputDirectory = Join-Path $repo 'build/server-launcher' }
function Get-LauncherSources {
    $result = [ordered]@{}
    $paths = @($PSCommandPath) + @(Get-ChildItem -LiteralPath (Join-Path $PSScriptRoot 'launcher') -File | Select-Object -ExpandProperty FullName)
    foreach ($sourcePath in ($paths | Sort-Object)) {
        $relative = $sourcePath.Substring($repo.Length + 1).Replace('\','/')
        $result[$relative] = (Get-FileHash -LiteralPath $sourcePath -Algorithm SHA256).Hash.ToLowerInvariant()
    }
    return $result
}
$sourcesBefore = Get-LauncherSources
if (-not $CompilerRoot) {
    $vswhere = Join-Path ${env:ProgramFiles(x86)} 'Microsoft Visual Studio/Installer/vswhere.exe'
    $installation = & $vswhere -latest -products '*' -requires Microsoft.VisualStudio.Component.VC.Tools.x86.x64 -property installationPath
    if (-not $installation) { throw 'Visual Studio x64 C++ build tools were not found.' }
    $CompilerRoot = (Get-ChildItem -LiteralPath (Join-Path $installation 'VC/Tools/MSVC') -Directory | Sort-Object Name -Descending | Select-Object -First 1).FullName
}
$sdk = Join-Path ${env:ProgramFiles(x86)} 'Windows Kits/10'
if (-not $SdkVersion) {
    $SdkVersion = (Get-ChildItem -LiteralPath (Join-Path $sdk 'Include') -Directory | Where-Object { Test-Path -LiteralPath (Join-Path $_.FullName 'um/Windows.h') } | Sort-Object Name -Descending | Select-Object -First 1).Name
}
$savedInclude = $env:INCLUDE; $savedLib = $env:LIB
New-Item -ItemType Directory -Path $OutputDirectory -Force | Out-Null
$OutputDirectory = (Resolve-Path -LiteralPath $OutputDirectory).Path
$receiptPath = Join-Path $OutputDirectory 'launcher-build.json'
if (Test-Path -LiteralPath $receiptPath) { Remove-Item -LiteralPath $receiptPath }
Push-Location $OutputDirectory
try {
    $env:INCLUDE = "$CompilerRoot/include;$sdk/Include/$SdkVersion/ucrt;$sdk/Include/$SdkVersion/shared;$sdk/Include/$SdkVersion/um"
    $env:LIB = "$CompilerRoot/lib/x64;$sdk/Lib/$SdkVersion/ucrt/x64;$sdk/Lib/$SdkVersion/um/x64"
    $compiler = Join-Path $CompilerRoot 'bin/Hostx64/x64/cl.exe'
    & $compiler /nologo /MT /EHsc /O2 /W4 /WX /std:c++17 (Join-Path $PSScriptRoot 'launcher/launch_args_tests.cpp') "/Fe:$OutputDirectory/launch_args_tests.exe" /link shell32.lib
    if ($LASTEXITCODE -ne 0) { throw 'Launcher argument test build failed.' }
    & (Join-Path $OutputDirectory 'launch_args_tests.exe')
    if ($LASTEXITCODE -ne 0) { throw 'Launcher argument tests failed.' }
    & $compiler /nologo /MT /EHsc /O2 /W4 /WX /std:c++17 (Join-Path $PSScriptRoot 'launcher/console_launcher.cpp') "/Fe:$OutputDirectory/Start Server.exe" /link /DYNAMICBASE /NXCOMPAT /HIGHENTROPYVA
    if ($LASTEXITCODE -ne 0) { throw 'Console launcher build failed.' }
    $sourcesAfter = Get-LauncherSources
    if (($sourcesBefore | ConvertTo-Json -Compress) -ne ($sourcesAfter | ConvertTo-Json -Compress)) { throw 'Launcher sources changed during build.' }
    [ordered]@{schema=1;launcher_sha256=(Get-FileHash -LiteralPath (Join-Path $OutputDirectory 'Start Server.exe') -Algorithm SHA256).Hash.ToLowerInvariant();source_sha256=$sourcesAfter;argument_tests_passed=$true} | ConvertTo-Json -Depth 5 | Set-Content -LiteralPath $receiptPath -Encoding utf8
    Write-Output (Join-Path $OutputDirectory 'Start Server.exe')
} finally { $env:INCLUDE=$savedInclude; $env:LIB=$savedLib; Pop-Location }
