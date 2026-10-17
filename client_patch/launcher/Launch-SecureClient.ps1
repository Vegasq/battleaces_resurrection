param([Parameter(Mandatory=$true)][string]$Config, [switch]$CommunityExperimental)
$ErrorActionPreference = 'Stop'
$repo = Split-Path -Parent (Split-Path -Parent $PSScriptRoot)
$configuration = (Resolve-Path -LiteralPath $Config).Path
Push-Location $repo
try {
    $launchOptions = @('--config', $configuration)
    if ($CommunityExperimental) { $launchOptions += '--community-experimental' }
    & python -m client_patch.transport.launcher @launchOptions
    if ($LASTEXITCODE -ne 0) { throw 'Secure client launcher failed. Check the configuration and local diagnostics.' }
} finally {
    Pop-Location
}
