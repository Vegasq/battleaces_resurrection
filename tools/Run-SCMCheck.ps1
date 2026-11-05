param([Parameter(Mandatory=$true)][string]$Plan, [switch]$PreflightOnly)
$ErrorActionPreference = 'Stop'
Set-StrictMode -Version Latest
$planPath = (Resolve-Path -LiteralPath $Plan).Path
$check = Get-Content -LiteralPath $planPath -Raw | ConvertFrom-Json
$created = $false
$service = $null
$probe = $null
$serviceProcess = $null
$stage = 'preflight'
$report = [ordered]@{ passed=$false; registered=$false; removed=$false; reboot_tested=$false; cycles=@() }

function Write-Result {
    $report | ConvertTo-Json -Depth 15 | Set-Content -LiteralPath (Join-Path $check.output 'operator-report.json') -Encoding UTF8
}
function Assert-OwnedRegistration {
    $row = Get-CimInstance Win32_Service -Filter ("Name='" + $check.service_name + "'")
    if ($null -eq $row -or $row.PathName -cne $check.binary_path -or $row.StartMode -ne 'Manual') {
        throw 'Service registration no longer matches this prepared check.'
    }
    $account = [Security.Principal.NTAccount]::new($row.StartName)
    if ($account.Translate([Security.Principal.SecurityIdentifier]).Value -ne $check.owner_sid) {
        throw 'Service account differs from the owner of the prepared private files.'
    }
    return $row
}
function Wait-ProbeFile([string]$Path, [int]$Seconds) {
    $timer = [Diagnostics.Stopwatch]::StartNew()
    while (-not (Test-Path -LiteralPath $Path)) {
        if ($probe.HasExited) { throw 'Native peer probe ended before its readiness signal.' }
        if ($timer.Elapsed.TotalSeconds -ge $Seconds) { throw 'Native peer probe deadline exceeded.' }
        Start-Sleep -Milliseconds 50
    }
}
try {
    # Validate paths/hash pins in this wrapper before invoking any plan-selected program.
    $repo = Split-Path -Parent $PSScriptRoot
    $ownedRoot = [IO.Path]::GetFullPath((Join-Path $repo 'local')) + '\'
    if (-not $planPath.StartsWith($ownedRoot,[StringComparison]::OrdinalIgnoreCase) -or
        $check.service_name -notmatch '^BattleAcesDiag186_[a-f0-9]{12}$' -or
        $check.output -cne (Split-Path -Parent $planPath) -or
        $check.probe_script -cne (Join-Path $PSScriptRoot 'verify_scm_operator.py') -or
        $check.runtime -cne (Join-Path $check.package 'program\runtime\python.exe') -or
        -not $check.package.StartsWith($ownedRoot,[StringComparison]::OrdinalIgnoreCase)) {
        throw 'Unexpected prepared-check paths or service name.'
    }
    foreach ($pin in $check.source_sha256.PSObject.Properties) {
        if ((Get-FileHash -LiteralPath $pin.Name -Algorithm SHA256).Hash.ToLowerInvariant() -cne $pin.Value) {
            throw 'Prepared source changed; prepare a new check.'
        }
    }
    & $check.runtime -I -B $check.probe_script preflight --plan $planPath
    if ($LASTEXITCODE -ne 0) { throw 'Prepared package/config preflight failed.' }
    if ($PreflightOnly) { Write-Host 'Preflight PASS. No service registered or started.'; exit 0 }
    $current = [Security.Principal.WindowsIdentity]::GetCurrent()
    $principal = [Security.Principal.WindowsPrincipal]::new($current)
    if (-not $principal.IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)) {
        throw 'Run this prepared check from an administrator PowerShell.'
    }
    if ($current.User.Value -ne $check.owner_sid) { throw 'Run as the same Windows account that prepared this check.' }
    Write-Host ('Disposable MANUAL service: ' + $check.service_name)
    Write-Host ('Only diagnostic data: ' + $check.output)
    Write-Host 'Two short native matches will be stopped and restarted. No reboot or policy/ACL changes.'
    $stage = 'credential_prompt'
    $credential = Get-Credential -UserName $check.account -Message 'Service logon for this disposable check. Use your Windows password, not a PIN. Never paste it into chat.'
    if ($null -eq $credential) { throw 'Credential prompt cancelled.' }
    $credentialAccount = [Security.Principal.NTAccount]::new($credential.UserName)
    if ($credentialAccount.Translate([Security.Principal.SecurityIdentifier]).Value -ne $check.owner_sid) {
        throw 'Credential account differs from prepared owner.'
    }
    $stage = 'registration'
    $service = New-Service -Name $check.service_name -BinaryPathName $check.binary_path -DisplayName $check.service_name -Description 'Disposable Battle Aces native SCM acceptance check' -StartupType Manual -Credential $credential
    $created = $true; $report.registered = $true
    Remove-Variable credential
    foreach ($cycle in 1,2) {
        $stage = 'start_' + $cycle
        $null = Assert-OwnedRegistration
        $service.Start()
        $service.WaitForStatus('Running',[TimeSpan]::FromSeconds(75))
        $row = Assert-OwnedRegistration
        $serviceProcess = Get-Process -Id $row.ProcessId
        $null = $serviceProcess.Handle # Retain process identity through exit, not a later PID lookup.
        if ($serviceProcess.SessionId -ne 0 -or $serviceProcess.MainModule.FileName -ine $check.runtime) {
            throw 'SCM process image/session differs.'
        }
        $servicePid = $serviceProcess.Id
        $cyclePath = Join-Path $check.output ('cycle-' + $cycle)
        $stage = 'native_peers_' + $cycle
        $startInfo = [Diagnostics.ProcessStartInfo]::new()
        $startInfo.FileName = $check.runtime
        $startInfo.Arguments = '-I -B "' + $check.probe_script + '" probe --plan "' + $planPath + '" --cycle ' + $cycle
        $startInfo.WorkingDirectory = $check.output
        $startInfo.UseShellExecute = $false; $startInfo.CreateNoWindow = $true
        $probe = [Diagnostics.Process]::Start($startInfo)
        Wait-ProbeFile (Join-Path $cyclePath 'ready.json') 50
        Set-Content -LiteralPath (Join-Path $cyclePath 'request-stop') -Value 'stop' -Encoding ASCII
        Wait-ProbeFile (Join-Path $cyclePath 'stop-armed') 5
        $stage = 'stop_' + $cycle
        $null = Assert-OwnedRegistration
        $service.Stop()
        $service.WaitForStatus('Stopped',[TimeSpan]::FromSeconds(25))
        if (-not $serviceProcess.WaitForExit(5000) -or $serviceProcess.ExitCode -ne 0) {
            throw 'Service process did not exit cleanly.'
        }
        Set-Content -LiteralPath (Join-Path $cyclePath 'service-stopped') -Value 'stopped' -Encoding ASCII
        if (-not $probe.WaitForExit(10000) -or $probe.ExitCode -ne 0) { throw 'Native peer verification failed.' }
        $cycleResult = Get-Content -LiteralPath (Join-Path $cyclePath 'probe-report.json') -Raw | ConvertFrom-Json
        if (-not $cycleResult.passed) { throw 'Native peer report did not pass.' }
        $report.cycles += [ordered]@{ cycle=$cycle; service_pid=$servicePid; session=0; service_exit=0; probe=$cycleResult }
        $probe.Dispose(); $probe=$null; $serviceProcess.Dispose(); $serviceProcess=$null
    }
    $report.passed = $true; $stage = 'complete'
} catch {
    $report['error_type'] = $_.Exception.GetType().Name
    Write-Host ('Check failed at ' + $stage + '. No password or arbitrary exception text is logged.')
} finally {
    if (-not $PreflightOnly) {
        $report['stage'] = $stage
        if ($created) {
            try {
                $null = Assert-OwnedRegistration
                $service.Refresh()
                if ($service.Status -ne 'Stopped') {
                    $service.Stop()
                    $service.WaitForStatus('Stopped',[TimeSpan]::FromSeconds(25))
                }
                & "$env:SystemRoot\System32\sc.exe" delete $check.service_name | Out-Null
                if ($LASTEXITCODE -ne 0) { throw 'Owned registration removal failed.' }
                $service.Dispose(); $service=$null
                if ($null -ne (Get-Service -Name $check.service_name -ErrorAction SilentlyContinue)) {
                    throw 'Service remains registered or marked for deletion.'
                }
                $report.removed = $true
            } catch { $report.passed=$false; $report['cleanup_error_type']=$_.Exception.GetType().Name }
        }
        if ($null -ne $probe) {
            # Never force-kill a service/worker; the probe has a finite internal deadline.
            Set-Content -LiteralPath (Join-Path $check.output 'operator-abort') -Value 'abort' -Encoding ASCII
            if (-not $probe.WaitForExit(15000)) { $report.passed=$false; $report['probe_still_running']=$true }
            $probe.Dispose()
        }
        if ($null -ne $serviceProcess) { $serviceProcess.Dispose() }
        Write-Result
        Write-Host ('Report: ' + (Join-Path $check.output 'operator-report.json'))
    }
}
if (-not $report.passed) { exit 1 }
Write-Host 'SCM check PASS. Disposable service removed; test data retained.'
