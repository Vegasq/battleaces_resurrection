param([Parameter(Mandatory=$true)][string]$OutputDirectory)
$ErrorActionPreference = 'Stop'
$repo = Split-Path -Parent $PSScriptRoot
$target = [IO.Path]::GetFullPath($OutputDirectory)
$local = [IO.Path]::GetFullPath((Join-Path $repo 'local')) + [IO.Path]::DirectorySeparatorChar
if (-not $target.StartsWith($local, [StringComparison]::OrdinalIgnoreCase) -or
    (Split-Path -Leaf $target) -notmatch '^adscaller_[0-9a-f]{12}$' -or (Test-Path -LiteralPath $target)) {
    throw 'Fresh owned local/adscaller_<12hex> directory required'
}
$vswhere = Join-Path ${env:ProgramFiles(x86)} 'Microsoft Visual Studio/Installer/vswhere.exe'
$installation = & $vswhere -latest -products '*' -requires Microsoft.VisualStudio.Component.VC.Tools.x86.x64 -property installationPath
if (-not $installation) { throw 'Existing MSVC compiler required' }
$compiler = (Get-ChildItem -LiteralPath (Join-Path $installation 'VC/Tools/MSVC') -Directory | Sort-Object Name -Descending | Select-Object -First 1).FullName
$sdk = Join-Path ${env:ProgramFiles(x86)} 'Windows Kits/10'
$version = (Get-ChildItem -LiteralPath (Join-Path $sdk 'Include') -Directory | Where-Object { Test-Path -LiteralPath (Join-Path $_.FullName 'um/Windows.h') } | Sort-Object Name -Descending | Select-Object -First 1).Name
$oldInclude=$env:INCLUDE; $oldLib=$env:LIB
$sources=Join-Path $repo 'tests/fixtures/ads_caller181'
New-Item -ItemType Directory -Path $target | Out-Null
Push-Location $target
try {
    $env:INCLUDE="$compiler/include;$sdk/Include/$version/ucrt;$sdk/Include/$version/shared;$sdk/Include/$version/um"
    $env:LIB="$compiler/lib/x64;$sdk/Lib/$version/ucrt/x64;$sdk/Lib/$version/um/x64"
    & "$compiler/bin/Hostx64/x64/ml64.exe" /nologo /c /Fo callback.obj (Join-Path $sources 'callback.asm')
    if ($LASTEXITCODE) { throw 'Fixture assembly failed' }
    & "$compiler/bin/Hostx64/x64/link.exe" /nologo /dll /noentry /dynamicbase /fixed:no /export:Fixture /out:UnityPlayer.dll callback.obj
    if ($LASTEXITCODE) { throw 'Fixture link failed' }
    & "$compiler/bin/Hostx64/x64/cl.exe" /nologo /MT /EHsc /O2 /W4 /std:c++17 /Fe:'Battle Aces.exe' (Join-Path $sources 'host.cpp')
    if ($LASTEXITCODE) { throw 'Fixture host compilation failed' }
    $files = @('Battle Aces.exe','UnityPlayer.dll')
    $hashes = [ordered]@{}
    foreach ($file in $files) { $hashes[$file]=(Get-FileHash -LiteralPath (Join-Path $target $file) -Algorithm SHA256).Hash.ToLowerInvariant() }
    $sourceHashes = [ordered]@{}
    foreach ($file in @('host.cpp','callback.asm')) { $sourceHashes[$file]=(Get-FileHash -LiteralPath (Join-Path $sources $file) -Algorithm SHA256).Hash.ToLowerInvariant() }
    [ordered]@{authored_fixture=$true;game_code=$false;compiler=$compiler;sdk=$version;files=$hashes;sources=$sourceHashes} | ConvertTo-Json -Depth 4 | Set-Content -LiteralPath (Join-Path $target 'build.json')
} finally { Pop-Location; $env:INCLUDE=$oldInclude; $env:LIB=$oldLib }
