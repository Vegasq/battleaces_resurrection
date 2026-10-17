param(
    [Parameter(Mandatory=$true)][string]$GameDirectory,
    [string]$AssetDirectory = '',
    [ValidateRange(1024,65535)][int]$Port = 47623,
    [string]$RunName = 'local-match',
    [string]$ClientConfig0 = '',
    [string]$ClientConfig1 = '',
    [switch]$AutoReady,
    [switch]$Smoke,
    [switch]$DeckSmoke,
    [switch]$SurrenderSmoke,
    [switch]$RematchSmoke,
    [ValidateRange(200,10000)][int]$SurrenderFrame = 600,
    [ValidateRange(0,3600)][int]$DurationSeconds = 0
)
$ErrorActionPreference = 'Stop'
$repo = Split-Path -Parent $PSScriptRoot
$gameRoot = (Resolve-Path -LiteralPath $GameDirectory).Path
if ($RunName -notmatch '^[A-Za-z0-9_-]{1,48}$') { throw 'Invalid run name.' }
if ([bool]$ClientConfig0 -ne [bool]$ClientConfig1) { throw 'Supply both client configs or neither.' }
$clientConfigs = @($ClientConfig0,$ClientConfig1)
if ($ClientConfig0) { $clientConfigs = @($clientConfigs | ForEach-Object { (Resolve-Path -LiteralPath $_).Path }) }
if (-not $AssetDirectory) { $AssetDirectory = Join-Path $repo 'local/assets/build-37822' }
$AssetDirectory = (Resolve-Path -LiteralPath $AssetDirectory).Path
$run = Join-Path $repo "local/matches/$RunName"
if (Test-Path -LiteralPath $run) { throw 'Run directory already exists; choose a fresh name.' }
New-Item -ItemType Directory -Force -Path $run | Out-Null
$service = $null
$games = @()
try {
    $arguments = @('-u','-m','server.dedicated_server','--host','127.0.0.1','--port',"$Port",
        '--assets',('"'+$AssetDirectory+'"'),'--dll',('"'+(Join-Path $AssetDirectory 'Simulation.dll')+'"'),
        '--data',('"'+$run+'"'),'--audit-state')
    $service = Start-Process -FilePath (Get-Command python -ErrorAction Stop).Source -ArgumentList $arguments -WorkingDirectory $repo -WindowStyle Hidden -RedirectStandardOutput (Join-Path $run 'server.log') -RedirectStandardError (Join-Path $run 'server-error.log') -PassThru
    $deadline = (Get-Date).AddSeconds(15)
    do {
        if ($service.HasExited) { throw 'Server failed; see server-error.log.' }
        $ready = Select-String -LiteralPath (Join-Path $run 'server.log') -Pattern "^Dedicated server listening on 127\.0\.0\.1:$Port" -Quiet -ErrorAction SilentlyContinue
        if (-not $ready) { Start-Sleep -Milliseconds 200 }
    } while (-not $ready -and (Get-Date) -lt $deadline)
    if (-not $ready) { throw 'Server startup timeout.' }
    foreach ($slot in 0,1) {
        $clientOptions = if ($ClientConfig0) { @{Config=$clientConfigs[$slot]} } else { @{Slot=$slot;Address="127.0.0.1:$Port"} }
        $games += & (Join-Path $repo 'client_patch/launcher/Launch-Client.ps1') @clientOptions -GameDirectory $gameRoot -RunName $RunName -AutoReady:$AutoReady -Smoke:$Smoke -DeckSmoke:$DeckSmoke -SurrenderSmoke:$SurrenderSmoke -RematchSmoke:$RematchSmoke -SurrenderFrame $SurrenderFrame -PassThru
    }
    Copy-Item -LiteralPath (Join-Path $gameRoot '.battleaces-resurrection/patch-manifest.json') -Destination (Join-Path $run 'patch-manifest.json')
    [pscustomobject]@{RunName=$RunName;Started=(Get-Date).ToString('o');ServerPid=$service.Id;GamePids=@($games|ForEach-Object Id);DataDirectory=$run;AutoReady=[bool]$AutoReady;Smoke=[bool]$Smoke;DeckSmoke=[bool]$DeckSmoke;SurrenderSmoke=[bool]$SurrenderSmoke;RematchSmoke=[bool]$RematchSmoke;Batch=$false} | ConvertTo-Json | Set-Content -LiteralPath (Join-Path $run 'processes.json')
    Write-Output "Server PID $($service.Id), clients $($games[0].Id)/$($games[1].Id), evidence $run"
    $deadline = if ($DurationSeconds) { (Get-Date).AddSeconds($DurationSeconds) } else { [DateTime]::MaxValue }
    while ((Get-Date) -lt $deadline -and @($games | Where-Object { -not $_.HasExited }).Count -gt 0) {
        Start-Sleep -Seconds 1
    }
} finally {
    foreach ($game in $games) {
        if (-not $game.HasExited) { Stop-Process -Id $game.Id -ErrorAction SilentlyContinue; Wait-Process -Id $game.Id -Timeout 10 -ErrorAction SilentlyContinue }
    }
    if ($service -and -not $service.HasExited) { Stop-Process -Id $service.Id -ErrorAction SilentlyContinue; Wait-Process -Id $service.Id -Timeout 10 -ErrorAction SilentlyContinue }
}
