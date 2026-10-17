# Shared by the launcher and config checks. Loading never starts the game.
function Read-ClientConfig {
    param([Parameter(Mandatory=$true)][string]$Path)
    $configuration = Get-Content -LiteralPath $Path -Raw -ErrorAction Stop | ConvertFrom-Json -ErrorAction Stop
    if ($configuration.schema -ne 1) { throw 'Unsupported client config schema; expected 1.' }
    $allowed = @('schema','game_directory','server_host','server_port','player_id','display_name','room')
    foreach ($property in $configuration.PSObject.Properties) {
        if ($property.Name -notin $allowed) { throw "Unknown client config setting: $($property.Name)" }
    }
    foreach ($key in @('game_directory','server_host','player_id','display_name','room')) {
        if ($configuration.$key -isnot [string]) { throw "Client config $key must be a string." }
    }
    if ($configuration.server_port -isnot [int] -and $configuration.server_port -isnot [long]) { throw 'server_port must be an integer.' }
    if ($configuration.server_port -lt 1 -or $configuration.server_port -gt 65535) { throw 'server_port must be in 1..65535.' }
    if ($configuration.game_directory -match '["\x00-\x1f]') { throw 'Invalid game_directory in client config.' }
    Assert-ServerHost $configuration.server_host
    Assert-PlayerSettings $configuration.player_id $configuration.display_name $configuration.room
    return $configuration
}

function Assert-ServerHost {
    param([string]$HostName)
    if (-not $HostName -or $HostName.Length -gt 253 -or $HostName -notmatch '^[A-Za-z0-9.-]+$') {
        throw 'server_host must be an IPv4 address or DNS hostname, without a port or URL prefix.'
    }
    if ($HostName -match '^[0-9.]+$') {
        $address = $null
        if ($HostName -notmatch '^\d{1,3}(\.\d{1,3}){3}$' -or -not [System.Net.IPAddress]::TryParse($HostName, [ref]$address) -or $address.AddressFamily -ne [System.Net.Sockets.AddressFamily]::InterNetwork) {
            throw 'Invalid IPv4 server address.'
        }
    } else {
        foreach ($label in $HostName.TrimEnd('.').Split('.')) {
            if ($label.Length -lt 1 -or $label.Length -gt 63 -or $label -notmatch '^[A-Za-z0-9]([A-Za-z0-9-]*[A-Za-z0-9])?$') { throw 'Invalid DNS server hostname.' }
        }
    }
}

function Assert-PlayerSettings {
    param([string]$PlayerId,[string]$DisplayName,[string]$Room)
    foreach ($key in @($PlayerId,$Room)) {
        if ($key -notmatch '^[A-Za-z0-9_-]{1,48}$') { throw 'player_id and room require 1..48 letters, numbers, dashes or underscores. Initialize a personal config first.' }
    }
    if (-not $DisplayName -or $DisplayName.Length -gt 32 -or $DisplayName -match '["\\\x00-\x1f\x7f]') { throw 'display_name requires 1..32 printable characters without quotes or backslashes.' }
}

function Resolve-ServerAddress {
    param([string]$HostName,[int]$Port)
    Assert-ServerHost $HostName
    if ($Port -lt 1 -or $Port -gt 65535) { throw 'Server port must be in 1..65535.' }
    $addresses = @([System.Net.Dns]::GetHostAddresses($HostName) | Where-Object AddressFamily -eq ([System.Net.Sockets.AddressFamily]::InterNetwork))
    if (-not $addresses.Count) { throw 'The configured server has no IPv4 address.' }
    return "$($addresses[0].IPAddressToString):$Port"
}
