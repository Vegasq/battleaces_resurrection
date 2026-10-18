param([string]$OutputDirectory = '', [string]$CompilerRoot = '', [string]$SdkVersion = '')
$ErrorActionPreference = 'Stop'
$repo = Split-Path -Parent $PSScriptRoot
if (-not $OutputDirectory) { $OutputDirectory = Join-Path $repo 'build/helper' }
if (-not $CompilerRoot) {
    $vswhere = Join-Path ${env:ProgramFiles(x86)} 'Microsoft Visual Studio/Installer/vswhere.exe'
    if (-not (Test-Path -LiteralPath $vswhere)) { throw 'Install Visual Studio C++ build tools or supply -CompilerRoot.' }
    $installation = & $vswhere -latest -products '*' -requires Microsoft.VisualStudio.Component.VC.Tools.x86.x64 -property installationPath
    if (-not $installation) { throw 'Visual Studio x64 C++ build tools were not found.' }
    $CompilerRoot = (Get-ChildItem -LiteralPath (Join-Path $installation 'VC/Tools/MSVC') -Directory | Sort-Object Name -Descending | Select-Object -First 1).FullName
}
$sdk = Join-Path ${env:ProgramFiles(x86)} 'Windows Kits/10'
if (-not $SdkVersion) {
    $SdkVersion = (Get-ChildItem -LiteralPath (Join-Path $sdk 'Include') -Directory | Where-Object { Test-Path -LiteralPath (Join-Path $_.FullName 'um/Windows.h') } | Sort-Object Name -Descending | Select-Object -First 1).Name
}
if (-not $SdkVersion) { throw 'Windows SDK headers were not found.' }
$savedInclude = $env:INCLUDE
$savedLib = $env:LIB
New-Item -ItemType Directory -Path $OutputDirectory -Force | Out-Null
$OutputDirectory = (Resolve-Path -LiteralPath $OutputDirectory).Path
Push-Location $OutputDirectory
try {
    $env:INCLUDE = "$CompilerRoot/include;$sdk/Include/$SdkVersion/ucrt;$sdk/Include/$SdkVersion/shared;$sdk/Include/$SdkVersion/um"
    $env:LIB = "$CompilerRoot/lib/x64;$sdk/Lib/$SdkVersion/ucrt/x64;$sdk/Lib/$SdkVersion/um/x64"
    & (Join-Path $CompilerRoot 'bin/Hostx64/x64/cl.exe') /nologo /MT /EHsc /O2 /W4 /std:c++17 (Join-Path $PSScriptRoot 'src/command_line_tests.cpp') "/Fe:$OutputDirectory/command_line_tests.exe"
    if ($LASTEXITCODE -ne 0) { throw 'Client argument-parser test build failed.' }
    & (Join-Path $OutputDirectory 'command_line_tests.exe')
    if ($LASTEXITCODE -ne 0) { throw 'Client argument-parser tests failed.' }
    & (Join-Path $CompilerRoot 'bin/Hostx64/x64/cl.exe') /nologo /MT /EHsc /O2 /W4 /std:c++17 (Join-Path $PSScriptRoot 'src/dedicated_wire_tests.cpp') "/Fe:$OutputDirectory/dedicated_wire_tests.exe"
    if ($LASTEXITCODE -ne 0) { throw 'Dedicated wire test build failed.' }
    & (Join-Path $OutputDirectory 'dedicated_wire_tests.exe')
    if ($LASTEXITCODE -ne 0) { throw 'Dedicated wire tests failed.' }
    & (Join-Path $CompilerRoot 'bin/Hostx64/x64/cl.exe') /nologo /MT /EHsc /O2 /W4 /std:c++17 (Join-Path $PSScriptRoot 'src/community_wire_tests.cpp') "/Fe:$OutputDirectory/community_wire_tests.exe"
    if ($LASTEXITCODE -ne 0) { throw 'Community wire test build failed.' }
    & (Join-Path $OutputDirectory 'community_wire_tests.exe')
    if ($LASTEXITCODE -ne 0) { throw 'Community wire tests failed.' }
    & (Join-Path $CompilerRoot 'bin/Hostx64/x64/cl.exe') /nologo /MT /EHsc /O2 /W4 /std:c++17 (Join-Path $PSScriptRoot 'src/community_transport_tests.cpp') "/Fe:$OutputDirectory/community_transport_tests.exe"
    if ($LASTEXITCODE -ne 0) { throw 'Community session test build failed.' }
    & (Join-Path $OutputDirectory 'community_transport_tests.exe')
    if ($LASTEXITCODE -ne 0) { throw 'Community session tests failed.' }
    & (Join-Path $CompilerRoot 'bin/Hostx64/x64/cl.exe') /nologo /MT /EHsc /O2 /W4 /std:c++17 (Join-Path $PSScriptRoot 'src/match_loading_state_tests.cpp') "/Fe:$OutputDirectory/match_loading_state_tests.exe"
    if ($LASTEXITCODE -ne 0) { throw 'Match loading state test build failed.' }
    & (Join-Path $OutputDirectory 'match_loading_state_tests.exe')
    if ($LASTEXITCODE -ne 0) { throw 'Match loading state tests failed.' }
    & (Join-Path $CompilerRoot 'bin/Hostx64/x64/cl.exe') /nologo /MT /EHsc /O2 /W4 /std:c++17 (Join-Path $PSScriptRoot 'src/secure_bridge_probe.cpp') "/Fe:$OutputDirectory/secure_bridge_probe.exe" /link ws2_32.lib
    if ($LASTEXITCODE -ne 0) { throw 'Native secure transport probe build failed.' }
    & (Join-Path $CompilerRoot 'bin/Hostx64/x64/cl.exe') /nologo /LD /MT /EHsc /O2 /W4 /std:c++17 (Join-Path $PSScriptRoot 'src/offline_client.cpp') /link "/OUT:$OutputDirectory/BattleAcesOffline.dll" kernel32.lib ws2_32.lib bcrypt.lib
    if ($LASTEXITCODE -ne 0) { throw 'Client helper build failed.' }
} finally {
    $env:INCLUDE = $savedInclude
    $env:LIB = $savedLib
    Pop-Location
}
Write-Output (Join-Path $OutputDirectory 'BattleAcesOffline.dll')
