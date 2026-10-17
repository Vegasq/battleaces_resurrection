param(
    [Parameter(Mandatory=$true)][string]$Config,
    [string]$RunName = ('manual-practice-' + (Get-Date -Format 'yyyyMMdd-HHmmss'))
)
# Visible standalone practice: native local deck storage, simulation and AI.
# No server process, server assets, address resolution or community connection.
$ErrorActionPreference = 'Stop'
$repo = Split-Path -Parent $PSScriptRoot
. (Join-Path $repo 'client_patch/launcher/ClientConfig.ps1')
$settings = Read-ClientConfig $Config -OfflinePractice
if ($RunName -notmatch '^[A-Za-z0-9_-]{1,48}$') { throw 'Invalid run name.' }
$gameRoot = (Resolve-Path -LiteralPath $settings.game_directory).Path
$run = Join-Path $repo "local/matches/$RunName"
if (Test-Path -LiteralPath $run) { throw 'Run already exists; choose a fresh name.' }
New-Item -ItemType Directory -Path $run -Force | Out-Null
$game = $null
try {
    $game = & (Join-Path $repo 'client_patch/launcher/Launch-Client.ps1') -Config $Config -RunName $RunName -OfflinePractice -PassThru
    Copy-Item -LiteralPath (Join-Path $gameRoot '.battleaces-resurrection/patch-manifest.json') -Destination (Join-Path $run 'patch-manifest.json')
    [pscustomobject]@{RunName=$RunName;Started=(Get-Date).ToString('o');ServerPid=$null;NetworkMode='offline-practice';GamePid=$game.Id;GameStarted=$game.StartTime.ToString('o');GameDirectory=$gameRoot;Config=(Resolve-Path -LiteralPath $Config).Path;PracticeAIExperimental=$true;Automation=$false;DiagnosticAudit=$false} | ConvertTo-Json | Set-Content -LiteralPath (Join-Path $run 'processes.json')
    Write-Host 'Open Edit Deck, choose your units, then press Try Deck vs AI.'
    Write-Host 'Build an army and play normally. Observe whether the bot produces units and fights.'
    Write-Host 'After winning or surrendering, press Continue. Keep this console open while playing.'
    Write-Host "Evidence: $run"
    while (-not $game.HasExited) { Start-Sleep -Seconds 1 }
} finally {
    if ($game -and -not $game.HasExited) { Stop-Process -Id $game.Id -ErrorAction SilentlyContinue; Wait-Process -Id $game.Id -Timeout 10 -ErrorAction SilentlyContinue }
    if ($game) {
        foreach ($name in @("dedicated-native-$($game.Id).log", "$RunName-$($settings.player_id).log")) {
            $source = Join-Path $gameRoot "investigation/runtime/$name"
            if (Test-Path -LiteralPath $source) { Copy-Item -LiteralPath $source -Destination (Join-Path $run $name) }
        }
    }
}
