param(
    [Parameter(Mandatory=$true)][string]$Root,
    [Parameter(Mandatory=$true)][string]$Output,
    [Parameter(Mandatory=$true)][string]$Ready,
    [Parameter(Mandatory=$true)][string]$Stop,
    [int]$TimeoutSeconds = 420
)

$ErrorActionPreference = 'Stop'
foreach ($path in @($Root, $Output, $Ready, $Stop)) {
    if (-not [System.IO.Path]::IsPathRooted($path)) { throw 'Absolute observer paths required' }
}
if (-not (Test-Path -LiteralPath $Root -PathType Container)) { throw 'SDK cache root must already exist' }
foreach ($path in @($Output, $Ready, $Stop)) {
    if (Test-Path -LiteralPath $path) { throw "Fresh observer path required: $path" }
}
$watcher = [System.IO.FileSystemWatcher]::new($Root)
$watcher.IncludeSubdirectories = $true
$watcher.NotifyFilter = [System.IO.NotifyFilters]::FileName -bor
    [System.IO.NotifyFilters]::DirectoryName -bor
    [System.IO.NotifyFilters]::LastWrite -bor
    [System.IO.NotifyFilters]::CreationTime -bor
    [System.IO.NotifyFilters]::Size
$watcher.InternalBufferSize = 65536
$events = @('Created', 'Changed', 'Deleted', 'Renamed', 'Error')
$ids = @{}
$counts = [ordered]@{ Created=0; Changed=0; Deleted=0; Renamed=0; Error=0 }
$started = (Get-Date).ToUniversalTime()
try {
    foreach ($name in $events) {
        $id = 'ba-sdk-' + $name
        Register-ObjectEvent -InputObject $watcher -EventName $name -SourceIdentifier $id | Out-Null
        $ids[$id] = $name
    }
    $watcher.EnableRaisingEvents = $true
    [System.IO.File]::WriteAllText($Ready, $started.ToString('o'))
    $deadline = $started.AddSeconds($TimeoutSeconds)
    do {
        $event = Wait-Event -Timeout 1
        if ($null -ne $event) {
            $name = $ids[$event.SourceIdentifier]
            if ($null -ne $name) { $counts[$name]++ }
            Remove-Event -EventIdentifier $event.EventIdentifier
        }
    } while (-not (Test-Path -LiteralPath $Stop) -and (Get-Date).ToUniversalTime() -lt $deadline)
    while ($event = Get-Event | Select-Object -First 1) {
        $name = $ids[$event.SourceIdentifier]
        if ($null -ne $name) { $counts[$name]++ }
        Remove-Event -EventIdentifier $event.EventIdentifier
    }
    $result = [ordered]@{
        scope = 'Read-only Windows FileSystemWatcher metadata notifications; no file content or SDK queue access'
        root = [System.IO.Path]::GetFullPath($Root)
        started_utc = $started.ToString('o')
        finished_utc = (Get-Date).ToUniversalTime().ToString('o')
        stopped_by_sentinel = (Test-Path -LiteralPath $Stop)
        counts = $counts
        buffer_bytes = $watcher.InternalBufferSize
    }
    [System.IO.File]::WriteAllText($Output, ($result | ConvertTo-Json -Depth 4))
    $result | ConvertTo-Json -Compress -Depth 4
} finally {
    $watcher.EnableRaisingEvents = $false
    foreach ($id in $ids.Keys) { Unregister-Event -SourceIdentifier $id -ErrorAction SilentlyContinue }
    $watcher.Dispose()
}
