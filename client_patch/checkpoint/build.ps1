param([Parameter(Mandatory=$true)][string]$OutputDirectory)
$ErrorActionPreference = 'Stop'
$vswhere = Join-Path ${env:ProgramFiles(x86)} 'Microsoft Visual Studio/Installer/vswhere.exe'
$installation = & $vswhere -latest -products '*' -requires Microsoft.VisualStudio.Component.VC.Tools.x86.x64 -property installationPath
if (-not $installation) { throw 'Existing Visual Studio C++ tools required.' }
$compiler = (Get-ChildItem -LiteralPath (Join-Path $installation 'VC/Tools/MSVC') -Directory | Sort-Object Name -Descending | Select-Object -First 1).FullName
$sdk = Join-Path ${env:ProgramFiles(x86)} 'Windows Kits/10'
$version = (Get-ChildItem -LiteralPath (Join-Path $sdk 'Include') -Directory | Where-Object { Test-Path -LiteralPath (Join-Path $_.FullName 'um/Windows.h') } | Sort-Object Name -Descending | Select-Object -First 1).Name
$source = Join-Path $PSScriptRoot 'arena.cpp'
$pages = Join-Path $PSScriptRoot 'page_checkpoint.hpp'
$roots = Join-Path $PSScriptRoot 'thread_state.hpp'
$entityGuard = Join-Path $PSScriptRoot 'entityguard.hpp'
$entityHooks = Join-Path $PSScriptRoot 'entityguard_hooks.hpp'
$before = (Get-FileHash -LiteralPath $source -Algorithm SHA256).Hash
$pagesBefore = (Get-FileHash -LiteralPath $pages -Algorithm SHA256).Hash
$rootsBefore = (Get-FileHash -LiteralPath $roots -Algorithm SHA256).Hash
$entityGuardBefore = (Get-FileHash -LiteralPath $entityGuard -Algorithm SHA256).Hash
$entityHooksBefore = (Get-FileHash -LiteralPath $entityHooks -Algorithm SHA256).Hash
$builderBefore = (Get-FileHash -LiteralPath $PSCommandPath -Algorithm SHA256).Hash
New-Item -ItemType Directory -Path $OutputDirectory -Force | Out-Null
$output = (Resolve-Path -LiteralPath $OutputDirectory).Path
if (Test-Path -LiteralPath (Join-Path $output 'BAHeap.dll')) { throw 'Use a fresh output directory.' }
$savedInclude = $env:INCLUDE
$savedLib = $env:LIB
Push-Location $output
try {
    $env:INCLUDE = "$compiler/include;$sdk/Include/$version/ucrt;$sdk/Include/$version/shared;$sdk/Include/$version/um"
    $env:LIB = "$compiler/lib/x64;$sdk/Lib/$version/ucrt/x64;$sdk/Lib/$version/um/x64"
    & (Join-Path $compiler 'bin/Hostx64/x64/cl.exe') /nologo /MT /EHsc /O2 /W4 /WX /std:c++17 /LD $source "/Fe:$output/BAHeap.dll"
    if ($LASTEXITCODE -ne 0) { throw 'Arena experiment build failed.' }
    if ((Get-FileHash -LiteralPath $source -Algorithm SHA256).Hash -ne $before) { throw 'Source changed during build.' }
    if ((Get-FileHash -LiteralPath $pages -Algorithm SHA256).Hash -ne $pagesBefore) { throw 'Page checkpoint source changed during build.' }
    if ((Get-FileHash -LiteralPath $roots -Algorithm SHA256).Hash -ne $rootsBefore) { throw 'Native root reader source changed during build.' }
    if ((Get-FileHash -LiteralPath $entityGuard -Algorithm SHA256).Hash -ne $entityGuardBefore) { throw 'Native entity observer source changed during build.' }
    if ((Get-FileHash -LiteralPath $entityHooks -Algorithm SHA256).Hash -ne $entityHooksBefore) { throw 'Native entity hook source changed during build.' }
    if ((Get-FileHash -LiteralPath $PSCommandPath -Algorithm SHA256).Hash -ne $builderBefore) { throw 'Arena build script changed during build.' }
    [ordered]@{ source_sha256=$before.ToLowerInvariant(); page_source_sha256=$pagesBefore.ToLowerInvariant(); root_source_sha256=$rootsBefore.ToLowerInvariant(); entity_guard_source_sha256=$entityGuardBefore.ToLowerInvariant(); entity_hooks_source_sha256=$entityHooksBefore.ToLowerInvariant(); entity_guard_abi=1; entity_guard_stats_bytes=96; build_script_sha256=$builderBefore.ToLowerInvariant(); dll_sha256=(Get-FileHash -LiteralPath (Join-Path $output 'BAHeap.dll') -Algorithm SHA256).Hash.ToLowerInvariant(); compiler=$compiler; sdk=$version; experimental=$true; foreign_event_abi=1; foreign_event_bytes=472; foreign_event_capacity=8; foreign_event_frames=16; root_bindings_abi=1; root_bindings_words=7; baseline_forget_abi=1; page_storage_abi=2 } | ConvertTo-Json | Set-Content -LiteralPath (Join-Path $output 'build.json') -Encoding UTF8
} finally {
    Pop-Location
    $env:INCLUDE = $savedInclude
    $env:LIB = $savedLib
}
