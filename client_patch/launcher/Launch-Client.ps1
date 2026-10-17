param(
    [string]$GameDirectory = '',
    [string]$Config = '',
    [ValidateSet(-1,0,1)][int]$Slot = -1,
    [string]$Address = '',
    [string]$PlayerId = '',
    [string]$DisplayName = '',
    [string]$Room = '',
    [string]$RunName = 'dedicated-client',
    [switch]$AutoReady,
    [switch]$Smoke,
    [switch]$DeckSmoke,
    [switch]$SurrenderSmoke,
    [switch]$RematchSmoke,
    [switch]$CommunityExperimental,
    [switch]$PracticeAIExperimental,
    [switch]$OfflinePractice,
    [ValidateSet(0,17,18,19)][int]$PracticeAIProfile = 0,
    [switch]$TelemetryAudit,
    [switch]$DiagnosticAudit,
    [ValidateRange(200,10000)][int]$SurrenderFrame = 600,
    [switch]$Batch,
    [switch]$ExportCatalog,
    [switch]$PassThru
)
$ErrorActionPreference = 'Stop'
. (Join-Path $PSScriptRoot 'ClientConfig.ps1')
$defaultConfig = Join-Path $PSScriptRoot 'client-config.json'
if (-not $OfflinePractice -and -not $Config -and $Slot -lt 0 -and (Test-Path -LiteralPath $defaultConfig)) { $Config = $defaultConfig }
if ($Config) {
    $settings = Read-ClientConfig $Config -OfflinePractice:$OfflinePractice
    if (-not $GameDirectory) { $GameDirectory = $settings.game_directory }
    if (-not $OfflinePractice -and -not $Address) { $Address = "$($settings.server_host):$($settings.server_port)" }
    if (-not $PlayerId) { $PlayerId = $settings.player_id }
    if (-not $DisplayName) { $DisplayName = $settings.display_name }
    if (-not $Room) { $Room = $settings.room }
    if (-not $PracticeAIProfile -and $settings.practice_ai_profile) { $PracticeAIProfile = $settings.practice_ai_profile }
}
if (-not $PracticeAIProfile) { $PracticeAIProfile = if ($OfflinePractice) { 18 } else { 17 } }
if (-not $GameDirectory) { throw 'Set game_directory in client-config.json or pass -GameDirectory.' }
if (-not $Address) { $Address = '127.0.0.1:47623' }
if (-not $Room) { $Room = 'local' }
if (-not $DisplayName) { $DisplayName = 'Player' }
if (-not $PlayerId -and $Slot -ge 0) { $PlayerId = "player$Slot" }
if (-not $PlayerId -and $OfflinePractice) { $PlayerId = 'offline_player' }
Assert-PlayerSettings $PlayerId $DisplayName $Room
if ($OfflinePractice -and ($CommunityExperimental -or $AutoReady -or $Slot -ge 0 -or $RematchSmoke)) { throw 'Offline practice does not use community presence, match seats or online matchmaking.' }
if (-not $OfflinePractice) {
    if ($Address -notmatch '^([^:]+):([0-9]{1,5})$') { throw 'Address must be IPv4:port or hostname:port.' }
    $resolvedAddress = Resolve-ServerAddress $Matches[1] ([int]$Matches[2])
}
$root = (Resolve-Path -LiteralPath $GameDirectory).Path
if ((Split-Path -Leaf $root) -eq 'BattleAcesBeta_untouched') { throw 'Use a working copy; the untouched recovery installation is read-only.' }
foreach ($key in @($PlayerId,$Room,$RunName)) { if ($key -notmatch '^[A-Za-z0-9_-]{1,48}$') { throw 'Player, room and run names require1..48 letters, numbers, dashes or underscores.' } }
$manifestPath = Join-Path $root '.battleaces-resurrection/patch-manifest.json'
$manifest = Get-Content -LiteralPath $manifestPath -Raw | ConvertFrom-Json
if ($manifest.state -eq 'restored') { throw 'Client is restored; install the patch before launching a private match.' }
if ($CommunityExperimental -and $manifest.community.native_scope -ne 'custom-match-prototype') {
    throw 'Install the current experimental community match patch into an isolated copy first.'
}
if ($CommunityExperimental -and ($Slot -ge 0 -or $AutoReady -or $RematchSmoke)) {
    throw 'Custom Game assigns seats after native Invite/Start; omit Slot, AutoReady and RematchSmoke.'
}
if ($OfflinePractice -and -not $manifest.practice.standalone) { throw 'Install a helper with standalone offline practice support first.' }
if (($PracticeAIExperimental -or $OfflinePractice) -and ((-not $CommunityExperimental -and -not $OfflinePractice) -or 'OfflinePracticeAIJoin' -notin @($manifest.call_hooks | ForEach-Object name))) {
    throw 'Practice AI requires the experimental community patch with the native AI join hook.'
}
foreach ($item in @(@('GameAssembly.dll','patched_sha256'),@('BattleAcesOffline.dll','helper_sha256'))) {
    if ((Get-FileHash -LiteralPath (Join-Path $root $item[0]) -Algorithm SHA256).Hash.ToLowerInvariant() -ne $manifest.($item[1])) { throw 'Client/helper hash does not match patch manifest.' }
}
if ($manifest.components) {
    foreach ($component in $manifest.components.PSObject.Properties) {
        if ((Get-FileHash -LiteralPath (Join-Path $root $component.Name) -Algorithm SHA256).Hash.ToLowerInvariant() -ne $component.Value.installed_sha256) { throw "Client component hash does not match manifest: $($component.Name)" }
    }
}
$runtime = Join-Path $root 'investigation/runtime'
New-Item -ItemType Directory -Force -Path $runtime | Out-Null
$gameArgs = @("-player-id=$PlayerId", ('-player-name="'+$DisplayName+'"'), '-screen-fullscreen','0','-screen-width','960','-screen-height','540','-logFile',('"' + (Join-Path $runtime "$RunName-$PlayerId.log") + '"'))
if ($OfflinePractice) { $gameArgs += '-offline-practice' }
else { $gameArgs += @('-offline-lan',"-dedicated-server=$resolvedAddress","-room=$Room") }
if ($DiagnosticAudit) { $gameArgs += '-lan-audit' }
if ($CommunityExperimental) { $gameArgs += '-dedicated-community' }
if ($PracticeAIExperimental -or $OfflinePractice) {
    $gameArgs += '-practice-ai-experimental'
    # A saved in-game choice wins over the launcher's initial default. An explicit
    # -PracticeAIProfile remains a diagnostic override; old helpers keep their ABI.
    if ($OfflinePractice -and $manifest.practice.difficulty_settings -and -not $PSBoundParameters.ContainsKey('PracticeAIProfile')) {
        $gameArgs += "-practice-ai-default-profile=$PracticeAIProfile"
    } else { $gameArgs += "-practice-ai-profile=$PracticeAIProfile" }
}
if ($Slot -ge 0) { $gameArgs += "-lan-slot=$Slot" }
if ($AutoReady) { $gameArgs += '-dedicated-auto-ready' }
if ($Smoke) { $gameArgs += '-lan-smoke' }
if ($DeckSmoke) { $gameArgs += '-dedicated-deck-smoke' }
if ($SurrenderSmoke) { $gameArgs += @('-dedicated-surrender-smoke',"-dedicated-surrender-frame=$SurrenderFrame") }
if ($RematchSmoke) { $gameArgs += @('-dedicated-rematch-smoke','-dedicated-auto-rematch') }
if ($TelemetryAudit) { $gameArgs += '-telemetry-audit' }
if ($ExportCatalog) { $gameArgs += '-export-unit-catalog' }
if ($Batch) { $gameArgs += @('-batchmode','-nographics') }
$style = if ($Batch) { 'Hidden' } else { 'Normal' }
$game = Start-Process -FilePath (Join-Path $root 'Battle Aces.exe') -ArgumentList $gameArgs -WorkingDirectory $root -WindowStyle $style -PassThru
if ($PassThru) { return $game }
if ($OfflinePractice) {
    Write-Host "Offline practice as $DisplayName (PID $($game.Id)). Open Edit Deck and press Try Deck vs AI."
} elseif ($PracticeAIExperimental) {
    Write-Host "Connecting to $Address as $DisplayName (PID $($game.Id)). Open Edit Deck and press Try Deck vs AI."
} elseif ($CommunityExperimental) {
    Write-Host "Connecting to $Address as $DisplayName (PID $($game.Id)). Open Custom Game, invite a connected player, then Start after acceptance."
} else {
    Write-Host "Connecting to $Address as $DisplayName (PID $($game.Id)). Select your eight units in the deck builder, then press Play."
}
