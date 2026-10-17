param(
    [Parameter(Mandatory=$true)][string]$GameDirectory,
    [string]$ServerHost = '127.0.0.1',
    [ValidateRange(1,65535)][int]$ServerPort = 47623,
    [string]$DisplayName = 'Player',
    [string]$Room = 'friends',
    [string]$Config = (Join-Path $PSScriptRoot 'client-config.json')
)
$ErrorActionPreference = 'Stop'
. (Join-Path $PSScriptRoot 'ClientConfig.ps1')
if (Test-Path -LiteralPath $Config) { throw 'Config already exists; edit it to change the server address.' }
$gameRoot = (Resolve-Path -LiteralPath $GameDirectory).Path
$playerId = [Guid]::NewGuid().ToString('N')
Assert-ServerHost $ServerHost
Assert-PlayerSettings $playerId $DisplayName $Room
$configuration = [ordered]@{schema=1;game_directory=$gameRoot;server_host=$ServerHost;server_port=$ServerPort;player_id=$playerId;display_name=$DisplayName;room=$Room}
$configuration | ConvertTo-Json | Set-Content -LiteralPath $Config -Encoding UTF8
Write-Output "Created $Config. Edit server_host and server_port to select the community server."
