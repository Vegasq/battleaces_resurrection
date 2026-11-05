param(
    [switch] $Execute,
    [string] $Output = ''
)

# Stage one only. No game, installer, original endpoint or report queue runs.
$ErrorActionPreference = 'Stop'
$repo = (Resolve-Path (Join-Path $PSScriptRoot '..')).Path
$owned = [System.IO.Path]::GetFullPath((Join-Path $repo 'local'))
if (-not $Output) { $Output = Join-Path $owned 'privacy556-etw-smoke01' }
$target = [System.IO.Path]::GetFullPath($Output)
$prefix = $owned.TrimEnd('\') + '\'
if (-not $target.StartsWith($prefix,[StringComparison]::OrdinalIgnoreCase)) {
    throw 'Output must be a new directory under repository local.'
}
if (Test-Path -LiteralPath $target) { throw 'Single-use output already exists.' }
foreach ($name in @('logman.exe','tracerpt.exe','python.exe')) {
    if (-not (Get-Command $name -ErrorAction SilentlyContinue)) { throw "Missing $name" }
}
$providers = [ordered]@{
    net  = @{ guid='{7DD42A49-5329-4832-8DFD-43D979153A88}'; keyword='0x30' }
    file = @{ guid='{EDD08927-9CC4-4E65-B970-C2560FB5C289}'; keyword='0x1FF0' }
    proc = @{ guid='{22FB2CD6-0E7B-422B-A0C7-2FAD1FD0E716}'; keyword='0x470' }
}
if (-not $Execute) {
    Write-Output "PREFLIGHT ONLY: fresh output $target"
    Write-Output 'Execute from an elevated PowerShell under this same Windows account using -Execute.'
    Write-Output 'Three named ETW sessions; local synthetic socket/file/child; no game launch.'
    exit 0
}
$identity = [Security.Principal.WindowsIdentity]::GetCurrent()
$principal = [Security.Principal.WindowsPrincipal]::new($identity)
if (-not $principal.IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)) {
    throw 'Elevated administrator token required for kernel ETW providers.'
}
New-Item -ItemType Directory -Path $target -ErrorAction Stop | Out-Null
$suffix = [guid]::NewGuid().ToString('N').Substring(0,12)
$sessions = @()
$events = [System.Collections.Generic.List[object]]::new()
$success = $false
function Invoke-Recorded([string]$Program,[string[]]$Arguments) {
    $lines = @(& $Program @Arguments 2>&1 | ForEach-Object { $_.ToString() })
    $code = $LASTEXITCODE
    $events.Add([ordered]@{program=$Program;arguments=$Arguments;exit_code=$code;output=$lines})
    if ($code -ne 0) { throw "$Program failed with exit $code : $($lines -join ' ')" }
}
try {
    foreach ($kind in $providers.Keys) {
        $spec = $providers[$kind]
        $name = "BA_D5_556_${kind}_$suffix"
        $etl = Join-Path $target "$kind.etl"
        # -ets creates only a live session, not a persistent collector set.
        Invoke-Recorded 'logman.exe' @('create','trace',$name,'-ets','-p',
            $spec.guid,$spec.keyword,'4','-o',$etl,'-f','bin','-max','64',
            '-bs','64','-nb','16','64','-ct','system')
        $sessions += [ordered]@{kind=$kind;name=$name;etl=$etl;provider=$spec.guid;keyword=$spec.keyword}
        Invoke-Recorded 'logman.exe' @('query',$name,'-ets')
    }
    Invoke-Recorded 'python.exe' @((Join-Path $PSScriptRoot 'etw_synthetic_smoke556.py'),$target)
    Start-Sleep -Milliseconds 750
    foreach ($session in $sessions) {
        Invoke-Recorded 'logman.exe' @('query',$session.name,'-ets')
    }
    $success = $true
} catch {
    $events.Add([ordered]@{error=$_.Exception.Message})
} finally {
    foreach ($session in $sessions) {
        $lines = @(& logman.exe stop $session.name -ets 2>&1 | ForEach-Object { $_.ToString() })
        $code = $LASTEXITCODE
        $events.Add([ordered]@{program='logman.exe';arguments=@('stop',$session.name,'-ets');exit_code=$code;output=$lines})
        if ($code -ne 0) { $success = $false }
    }
    foreach ($session in $sessions) {
        if (Test-Path -LiteralPath $session.etl) {
            $xml = Join-Path $target "$($session.kind).xml"
            $summary = Join-Path $target "$($session.kind)-summary.txt"
            $lines = @(& tracerpt.exe $session.etl -o $xml -of XML -summary $summary -y 2>&1 | ForEach-Object { $_.ToString() })
            $code = $LASTEXITCODE
            $events.Add([ordered]@{program='tracerpt.exe';arguments=@($session.etl,'-o',$xml,'-of','XML','-summary',$summary,'-y');exit_code=$code;output=$lines})
            if ($code -ne 0) { $success = $false }
        } else { $success = $false }
    }
    $files = @()
    foreach ($file in Get-ChildItem -LiteralPath $target -File) {
        $files += [ordered]@{name=$file.Name;bytes=$file.Length;sha256=(Get-FileHash -LiteralPath $file.FullName -Algorithm SHA256).Hash.ToLowerInvariant()}
    }
    $receipt = [ordered]@{
        schema=1;scope='synthetic ETW provider/schema smoke only';
        collection_complete=$success;game_launched=$false;
        real_report_queue_touched=$false;session_suffix=$suffix;
        sessions=$sessions;commands=$events;files=$files;
        interpretation='Raw ETL/XML retained. No D5 or whole-wire PASS until event schema and loss review.'
    }
    $receipt | ConvertTo-Json -Depth 8 | Set-Content -LiteralPath (Join-Path $target 'capture.json') -Encoding utf8
}
if (-not $success) { throw "Synthetic capture failed; inspect $target\capture.json and any live BA_D5_556 sessions." }
& python.exe (Join-Path $PSScriptRoot 'review_etw_sensor_smoke556.py') $target
if ($LASTEXITCODE -ne 0) { throw "Structural review failed; inspect $target\capture.json." }
Write-Output "Synthetic capture retained at $target"
