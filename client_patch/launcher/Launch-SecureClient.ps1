param([Parameter(Mandatory=$true)][string]$Config)
$ErrorActionPreference = 'Stop'
$repo = Split-Path -Parent (Split-Path -Parent $PSScriptRoot)
$configuration = (Resolve-Path -LiteralPath $Config).Path
Push-Location $repo
try {
    & python -m client_patch.transport.launcher --config $configuration
    if ($LASTEXITCODE -ne 0) { throw 'Secure client launcher failed. Check the configuration and local diagnostics.' }
} finally {
    Pop-Location
}
