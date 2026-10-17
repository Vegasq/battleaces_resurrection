param(
    [Parameter(Mandatory=$true)][string]$GameDirectory,
    [ValidateSet(0,1)][int]$Slot = 0,
    [string]$Address = '127.0.0.1:47623',
    [string]$PlayerId = '',
    [string]$Room = 'local',
    [string]$RunName = 'dedicated-client',
    [switch]$AutoReady,
    [switch]$Smoke,
    [switch]$DeckSmoke,
    [switch]$SurrenderSmoke,
    [ValidateRange(200,10000)][int]$SurrenderFrame = 600,
    [switch]$Batch,
    [switch]$ExportCatalog,
    [switch]$PassThru
)
$ErrorActionPreference = 'Stop'
$root = (Resolve-Path -LiteralPath $GameDirectory).Path
if ((Split-Path -Leaf $root) -eq 'BattleAcesBeta_untouched') { throw 'Use a working copy; the untouched recovery installation is read-only.' }
if ($Address -notmatch '^\d{1,3}(\.\d{1,3}){3}:\d{1,5}$') { throw 'Address must be IPv4:port.' }
if (-not $PlayerId) { $PlayerId = "player$Slot" }
foreach ($key in @($PlayerId,$Room,$RunName)) { if ($key -notmatch '^[A-Za-z0-9_-]{1,48}$') { throw 'Player, room and run names require1..48 letters, numbers, dashes or underscores.' } }
$manifestPath = Join-Path $root '.battleaces-resurrection/patch-manifest.json'
$manifest = Get-Content -LiteralPath $manifestPath -Raw | ConvertFrom-Json
foreach ($item in @(@('GameAssembly.dll','patched_sha256'),@('BattleAcesOffline.dll','helper_sha256'))) {
    if ((Get-FileHash -LiteralPath (Join-Path $root $item[0]) -Algorithm SHA256).Hash.ToLowerInvariant() -ne $manifest.($item[1])) { throw 'Client/helper hash does not match patch manifest.' }
}
$runtime = Join-Path $root 'investigation/runtime'
New-Item -ItemType Directory -Force -Path $runtime | Out-Null
$gameArgs = @('-offline-lan', "-dedicated-server=$Address", "-lan-slot=$Slot", "-player-id=$PlayerId", "-room=$Room", '-lan-audit', '-screen-fullscreen','0','-screen-width','960','-screen-height','540','-logFile',('"' + (Join-Path $runtime "$RunName-player$Slot.log") + '"'))
if ($AutoReady) { $gameArgs += '-dedicated-auto-ready' }
if ($Smoke) { $gameArgs += '-lan-smoke' }
if ($DeckSmoke) { $gameArgs += '-dedicated-deck-smoke' }
if ($SurrenderSmoke) { $gameArgs += @('-dedicated-surrender-smoke',"-dedicated-surrender-frame=$SurrenderFrame") }
if ($ExportCatalog) { $gameArgs += '-export-unit-catalog' }
if ($Batch) { $gameArgs += @('-batchmode','-nographics') }
$style = if ($Batch) { 'Hidden' } else { 'Normal' }
$game = Start-Process -FilePath (Join-Path $root 'Battle Aces.exe') -ArgumentList $gameArgs -WorkingDirectory $root -WindowStyle $style -PassThru
if ($PassThru) { return $game }
Write-Host "Client $Slot started as $PlayerId (PID $($game.Id)). Select your eight units in the deck builder, then press Play."
