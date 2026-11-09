param([Parameter(Mandatory=$true)][string]$OutputDirectory)
$ErrorActionPreference = 'Stop'
$vswhere = Join-Path ${env:ProgramFiles(x86)} 'Microsoft Visual Studio/Installer/vswhere.exe'
$installation = & $vswhere -latest -products '*' -requires Microsoft.VisualStudio.Component.VC.Tools.x86.x64 -property installationPath
if (-not $installation) { throw 'Existing Visual Studio C++ tools required.' }
$compiler = (Get-ChildItem -LiteralPath (Join-Path $installation 'VC/Tools/MSVC') -Directory | Sort-Object Name -Descending | Select-Object -First 1).FullName
$sdk = Join-Path ${env:ProgramFiles(x86)} 'Windows Kits/10'
$version = (Get-ChildItem -LiteralPath (Join-Path $sdk 'Include') -Directory | Where-Object { Test-Path -LiteralPath (Join-Path $_.FullName 'um/Windows.h') } | Sort-Object Name -Descending | Select-Object -First 1).Name
$source = Join-Path $PSScriptRoot 'cooperative.cpp'
$before = (Get-FileHash -LiteralPath $source -Algorithm SHA256).Hash
New-Item -ItemType Directory -Path $OutputDirectory -Force | Out-Null
$output = (Resolve-Path -LiteralPath $OutputDirectory).Path
if (Test-Path -LiteralPath (Join-Path $output 'PredictionCooperative.dll')) { throw 'Use a fresh output directory.' }
$savedInclude = $env:INCLUDE
$savedLib = $env:LIB
Push-Location $output
try {
    $env:INCLUDE = "$compiler/include;$sdk/Include/$version/ucrt;$sdk/Include/$version/shared;$sdk/Include/$version/um"
    $env:LIB = "$compiler/lib/x64;$sdk/Lib/$version/ucrt/x64;$sdk/Lib/$version/um/x64"
    & (Join-Path $compiler 'bin/Hostx64/x64/cl.exe') /nologo /MT /EHsc /O2 /W4 /WX /std:c++17 /LD $source "/Fe:$output/PredictionCooperative.dll"
    if ($LASTEXITCODE -ne 0) { throw 'Cooperative experiment build failed.' }
    if ((Get-FileHash -LiteralPath $source -Algorithm SHA256).Hash -ne $before) { throw 'Source changed during build.' }
    [ordered]@{ source_sha256=$before.ToLowerInvariant(); dll_sha256=(Get-FileHash -LiteralPath (Join-Path $output 'PredictionCooperative.dll') -Algorithm SHA256).Hash.ToLowerInvariant(); compiler=$compiler; sdk=$version; experimental=$true } | ConvertTo-Json | Set-Content -LiteralPath (Join-Path $output 'build.json') -Encoding UTF8
} finally {
    Pop-Location
    $env:INCLUDE = $savedInclude
    $env:LIB = $savedLib
}
