param(
    [Parameter(Mandatory=$true)][string]$PythonExecutable,
    [Parameter(Mandatory=$true)][string]$ConfigPath,
    [string]$RenderPreview = ''
)
$ErrorActionPreference = 'Stop'
Add-Type -AssemblyName System.Windows.Forms
Add-Type -AssemblyName System.Drawing
[System.Windows.Forms.Application]::EnableVisualStyles()

# Values are passed as native argv, never evaluated as PowerShell or cmd text.
function Quote-Argument([string]$Value) {
    '"' + [regex]::Replace([regex]::Replace($Value, '(\\*)"', '$1$1\"'), '(\\+)$', '$1$1') + '"'
}
function Add-Label([string]$Text, [int]$X, [int]$Y, [int]$Width, [int]$Height = 28) {
    $control = New-Object System.Windows.Forms.Label
    $control.Text = $Text; $control.Location = New-Object System.Drawing.Point($X,$Y)
    $control.Size = New-Object System.Drawing.Size($Width,$Height)
    $form.Controls.Add($control); return $control
}
function Add-Text([int]$X, [int]$Y, [int]$Width) {
    $control = New-Object System.Windows.Forms.TextBox
    $control.Location = New-Object System.Drawing.Point($X,$Y)
    $control.Size = New-Object System.Drawing.Size($Width,28)
    $control.MaxLength = 32767; $form.Controls.Add($control); return $control
}
function Add-Button([string]$Text, [int]$X, [int]$Y, [int]$Width) {
    $control = New-Object System.Windows.Forms.Button
    $control.Text = $Text; $control.Location = New-Object System.Drawing.Point($X,$Y)
    $control.Size = New-Object System.Drawing.Size($Width,34)
    $form.Controls.Add($control); return $control
}
function Set-Status([string]$Text, [bool]$Failed = $false) {
    $status.Text = $Text
    $status.ForeColor = if ($Failed) { [System.Drawing.Color]::FromArgb(160,30,25) } else { [System.Drawing.Color]::FromArgb(30,60,85) }
}
function Set-Busy([bool]$Busy) {
    foreach ($control in $script:interactive) { $control.Enabled = -not $Busy }
    $check.Enabled = -not $Busy -and $script:saved -and -not $script:dirty
    $play.Enabled = $check.Enabled
    if ($script:gameTransport -and -not $script:gameTransport.HasExited) { $install.Enabled = $false; $play.Enabled = $false }
    $form.UseWaitCursor = $Busy
}
function Mark-Changed {
    if ($script:loadingSettings) { return }
    $script:dirty = $true
    Set-Busy ($null -ne $script:pending)
    Set-Status 'Unsaved changes. Save the connection before testing or playing.'
}
function Test-SavedSettings {
    if (-not $script:saved -or $script:dirty) { Set-Status 'Save these settings before testing or playing.' $true; return $false }
    try {
        if ((Get-FileHash -LiteralPath $ConfigPath -Algorithm SHA256).Hash.ToLowerInvariant() -ne $script:expectedConfig) {
            Set-Status 'Saved settings changed outside this window. Close and reopen setup.' $true; return $false
        }
    } catch { Set-Status 'Saved settings are unavailable. Close and reopen setup.' $true; return $false }
    return $true
}
function Select-File([System.Windows.Forms.TextBox]$Target, [string]$Title, [string]$Filter) {
    $dialog = New-Object System.Windows.Forms.OpenFileDialog
    try {
        $dialog.Title = $Title; $dialog.Filter = $Filter; $dialog.CheckFileExists = $true
        if ($dialog.ShowDialog($form) -eq [System.Windows.Forms.DialogResult]::OK) { $Target.Text = $dialog.FileName }
    } finally { $dialog.Dispose() }
}
function Start-Backend([string[]]$Arguments, [scriptblock]$Finished, [string]$RequestFile = '') {
    if ($script:pending) { return }
    $info = New-Object System.Diagnostics.ProcessStartInfo
    $info.FileName = $PythonExecutable
    $info.Arguments = (@('-I','-B','-m','tools.package_client') + $Arguments | ForEach-Object { Quote-Argument $_ }) -join ' '
    $info.UseShellExecute = $false; $info.CreateNoWindow = $true
    $info.RedirectStandardOutput = $true; $info.RedirectStandardError = $true
    $process = New-Object System.Diagnostics.Process
    $process.StartInfo = $info
    try {
        [void]$process.Start()
        $script:pending = @{Process=$process; Output=$process.StandardOutput.ReadToEndAsync(); Error=$process.StandardError.ReadToEndAsync(); Finished=$Finished; Request=$RequestFile; Start=[DateTime]::UtcNow; Installing=($Arguments[0] -eq 'install'); SlowNotice=$false}
        Set-Busy $true
    } catch {
        $process.Dispose()
        if ($RequestFile -and (Test-Path -LiteralPath $RequestFile)) { Remove-Item -LiteralPath $RequestFile -ErrorAction SilentlyContinue }
        Set-Status 'Could not start setup. Verify the extracted package and its bundled runtime.' $true
    }
}
function Load-Settings {
    Start-Backend @('setup-data','--config',$ConfigPath) {
        param($result)
        $values = $result.result
        $script:loadingSettings = $true
        try {
            $game.Text = $values.game_directory; $display.Text = $values.display_name
            $address.Text = $values.server_host; $port.Value = $values.server_port
            $identity.Text = $values.server_name; $room.Text = $values.room
            $ca.Text = $values.ca_source; $invite.Text = $values.invite_source
            $expected.Text = $values.expected_ca_sha256
            $actual.Text = $values.expected_ca_sha256
        } finally { $script:loadingSettings = $false }
        $script:expectedConfig = $values.expected_config_sha256
        $script:saved = $null -ne $script:expectedConfig; $script:dirty = $false
        Set-Busy $false
        Set-Status $(if ($script:saved) { 'Saved connection loaded. Test it or launch the game.' } else { 'Choose your patched game and the connection details supplied by your host.' })
    }
}

$form = New-Object System.Windows.Forms.Form
$form.Text = 'Battle Aces Resurrection - Connection Setup'
$form.ClientSize = New-Object System.Drawing.Size(960,730)
$form.FormBorderStyle = [System.Windows.Forms.FormBorderStyle]::FixedDialog
$form.MaximizeBox = $false; $form.StartPosition = 'CenterScreen'
$form.AutoScaleMode = [System.Windows.Forms.AutoScaleMode]::Dpi
$form.Font = New-Object System.Drawing.Font('Segoe UI',10)
$form.BackColor = [System.Drawing.Color]::FromArgb(246,248,251)
$title = Add-Label 'Connect to a community server' 20 18 920 40
$title.Font = New-Object System.Drawing.Font('Segoe UI',18,[System.Drawing.FontStyle]::Bold)
[void](Add-Label 'Save a connection, check your private invite, then play with your friends.' 22 64 915 28)

[void](Add-Label 'Working game folder' 20 109 165)
$game = Add-Text 188 105 530
$browseGame = Add-Button 'Browse...' 728 101 90
$install = Add-Button 'Install patch' 824 101 116
[void](Add-Label 'Display name' 20 151 165)
$display = Add-Text 188 147 300; $display.MaxLength = 32
[void](Add-Label 'Room' 530 151 65)
$room = Add-Text 600 147 340; $room.MaxLength = 48
[void](Add-Label 'Server address' 20 193 165)
$address = Add-Text 188 189 600; $address.MaxLength = 253
[void](Add-Label 'Port' 806 193 45)
$port = New-Object System.Windows.Forms.NumericUpDown
$port.Location = New-Object System.Drawing.Point(855,189)
$port.Size = New-Object System.Drawing.Size(85,28); $port.Minimum = 1; $port.Maximum = 65535; $port.Value = 47623
$form.Controls.Add($port)
[void](Add-Label 'Certificate server name' 20 235 165)
$identity = Add-Text 188 231 752; $identity.MaxLength = 253
[void](Add-Label 'Host CA certificate' 20 277 165)
$ca = Add-Text 188 273 642
$browseCA = Add-Button 'Browse...' 840 269 100
[void](Add-Label 'Your invite file' 20 319 165)
$invite = Add-Text 188 315 642
$browseInvite = Add-Button 'Browse...' 840 311 100

[void](Add-Label 'Selected CA file SHA256' 20 365 660)
$showHash = Add-Button 'Read fingerprint' 770 355 170
$actual = Add-Text 20 394 920; $actual.ReadOnly = $true
$actual.Font = New-Object System.Drawing.Font('Consolas',10)
[void](Add-Label 'CA file SHA256 supplied by your host' 20 437 920)
$expected = Add-Text 20 466 920; $expected.MaxLength = 64
$expected.Font = New-Object System.Drawing.Font('Consolas',10)
$trustNote = Add-Label 'Get this hash from your host through a trusted channel. Saving requires an exact match. Only this connection trusts the certificate; Windows trust settings stay unchanged.' 20 509 920 46
$trustNote.Font = New-Object System.Drawing.Font('Segoe UI',9)

$save = Add-Button 'Save connection' 20 568 180
$check = Add-Button 'Test connection' 212 568 180
$play = Add-Button 'Play multiplayer' 740 568 200
$status = Add-Label '' 20 619 920 53
$status.Font = New-Object System.Drawing.Font('Segoe UI',10,[System.Drawing.FontStyle]::Bold)
$footer = Add-Label 'The original invite file is kept. Imported copies are private to your Windows account.' 20 689 920 26
$footer.Font = New-Object System.Drawing.Font('Segoe UI',9)
$script:interactive = @($game,$browseGame,$install,$display,$room,$address,$port,$identity,$ca,$browseCA,$invite,$browseInvite,$showHash,$expected,$save,$check,$play)
$script:pending = $null; $script:expectedConfig = $null; $script:saved = $false; $script:gameTransport = $null
$script:dirty = $false; $script:loadingSettings = $false
foreach ($field in @($game,$display,$room,$address,$identity,$ca,$invite,$expected)) { $field.Add_TextChanged({ Mark-Changed }) }
$port.Add_ValueChanged({ Mark-Changed })
$ca.Add_TextChanged({ $actual.Text = '' })
Set-Busy $false

$browseGame.Add_Click({
    $dialog = New-Object System.Windows.Forms.FolderBrowserDialog
    try { $dialog.Description = 'Choose the working copy you want to patch and play'; if ($dialog.ShowDialog($form) -eq 'OK') { $game.Text = $dialog.SelectedPath } }
    finally { $dialog.Dispose() }
})
$browseCA.Add_Click({ Select-File $ca 'Choose the public CA file supplied by your host' 'PEM certificates (*.pem)|*.pem|All files (*.*)|*.*'; $actual.Text = '' })
$browseInvite.Add_Click({ Select-File $invite 'Choose your private invite received from the host' 'JSON invite (*.json)|*.json|All files (*.*)|*.*' })
$showHash.Add_Click({
    Set-Status 'Reading the selected public certificate...'
    Start-Backend @('ca-fingerprint','--file',$ca.Text) { param($result) $actual.Text = $result.result.sha256; Set-Status 'Compare this file hash with the value your host gave you.' }
})
$install.Add_Click({
    Set-Status 'Checking the supported build and installing the patch. Close the game before installation.'
    Start-Backend @('install','--game',$game.Text) { param($result) Set-Status 'Patch installed. Originals were preserved for restore.' }
})
$save.Add_Click({
    $requestFile = ''; $requestCreated = $false
    try {
        $request = [ordered]@{schema=1;game_directory=$game.Text;server_host=$address.Text;server_port=[int]$port.Value;server_name=$identity.Text;display_name=$display.Text;room=$room.Text;ca_source=$ca.Text;invite_source=$invite.Text;expected_ca_sha256=$expected.Text.Trim();expected_config_sha256=$script:expectedConfig}
        $parent = [System.IO.Path]::GetDirectoryName([System.IO.Path]::GetFullPath($ConfigPath))
        $requestFile = Join-Path $parent ('.setup-request-'+[Guid]::NewGuid().ToString('N')+'.json')
        $bytes = [System.Text.Encoding]::UTF8.GetBytes(($request | ConvertTo-Json -Compress))
        $stream = [System.IO.File]::Open($requestFile,[System.IO.FileMode]::CreateNew,[System.IO.FileAccess]::Write,[System.IO.FileShare]::None)
        $requestCreated = $true
        try { $stream.Write($bytes,0,$bytes.Length); $stream.Flush($true) } finally { $stream.Dispose() }
        Set-Status 'Verifying trust and saving a protected local invite copy...'
        Start-Backend @('enroll','--request',$requestFile,'--config',$ConfigPath) {
            param($result)
            # Use the new private paths for future edits, so deleting the
            # downloaded transfer file cannot break a later display-name save.
            $script:saved = $false; $script:dirty = $false
            Set-Status 'Connection saved. Loading its protected local copies...'
            Load-Settings
        } $requestFile
    } catch {
        if ($requestCreated -and -not $script:pending) { Remove-Item -LiteralPath $requestFile -ErrorAction SilentlyContinue }
        Set-Status 'Could not prepare setup. Choose an existing writable config directory and valid local files.' $true
    }
})
$check.Add_Click({
    if (-not (Test-SavedSettings)) { return }
    Set-Status 'Checking the saved connection and invite. Please wait...'
    Start-Backend @('check','--config',$ConfigPath) { param($result) Set-Status ('Connected and authenticated with '+$result.result.tls+'. Ready to play.') }
})
$play.Add_Click({
    if (-not (Test-SavedSettings)) { return }
    if ($script:gameTransport -and -not $script:gameTransport.HasExited) { Set-Status 'The game is already starting or running.'; return }
    try {
        $info = New-Object System.Diagnostics.ProcessStartInfo
        $info.FileName = $PythonExecutable
        $info.Arguments = (@('-I','-B','-m','tools.package_client','launch','--config',$ConfigPath) | ForEach-Object { Quote-Argument $_ }) -join ' '
        $info.UseShellExecute = $false; $info.CreateNoWindow = $true
        $script:gameTransport = [System.Diagnostics.Process]::Start($info)
        Set-Busy $false
        Set-Status 'Starting the game. You can close this setup window; the game connection keeps running.'
    } catch { Set-Status 'Could not launch. Verify the installed patch and test the saved connection.' $true }
})

$timer = New-Object System.Windows.Forms.Timer
$timer.Interval = 100
$timer.Add_Tick({
    if ($script:gameTransport -and $script:gameTransport.HasExited) {
        $gameExit = $script:gameTransport.ExitCode
        $script:gameTransport.Dispose(); $script:gameTransport = $null
        Set-Busy ($null -ne $script:pending)
        if ($gameExit -ne 0) { Set-Status 'The game or its connection stopped. Test the connection and verify the installed patch before retrying.' $true }
        elseif (-not $script:pending) { Set-Status 'The game has closed. Your saved connection is ready for another launch.' }
    }
    if (-not $script:pending) { return }
    $job = $script:pending
    if (-not $job.Process.HasExited) {
        if (([DateTime]::UtcNow-$job.Start).TotalSeconds -gt 90) {
            if ($job.Installing) {
                # Full bundle verification can take longer on a slow drive.
                # Never kill a patch transaction while it is replacing files.
                if (-not $job.SlowNotice) {
                    Set-Status 'Checking game content and installing the patch. Verification can take several minutes on a slow drive; please keep this window open.'
                    $job.SlowNotice = $true
                }
            } else {
                try { $job.Process.Kill() } catch { } # It may have exited between ticks.
                Set-Status 'Setup exceeded its time limit. Close and reopen setup to check saved settings before retrying.' $true
            }
        }
        return
    }
    if (-not $job.Output.IsCompleted -or -not $job.Error.IsCompleted) { return }
    $script:pending = $null; Set-Busy $false
    try {
        if ($job.Request -and (Test-Path -LiteralPath $job.Request)) { Remove-Item -LiteralPath $job.Request }
        $output = $job.Output.Result | ConvertFrom-Json
        if ($job.Process.ExitCode -ne 0 -or ($null -ne $output.ok -and -not $output.ok)) {
            if ($output.error) { Set-Status ([string]$output.error) $true }
            else { Set-Status 'Operation failed. Check the selected paths, permissions and supported game build.' $true }
        } else { & $job.Finished $output }
    } catch { Set-Status 'Operation failed. Verify local files and permissions, then retry.' $true }
    finally { $job.Process.Dispose() }
})
$form.Add_FormClosing({ param($sender,$eventArgs) if ($script:pending) { $eventArgs.Cancel = $true; Set-Status 'Please wait for the current setup operation to finish.' } })
$form.Add_Shown({ Load-Settings })

try {
    if ($RenderPreview) {
        # Developer rendering only: no backend, file imports, network or game.
        $game.Text = '<choose your working game folder>'; $display.Text = 'Player'; $room.Text = 'friends'
        $address.Text = 'server.example'; $identity.Text = 'server.example'
        $ca.Text = '<public certificate from your host>'; $invite.Text = '<your invite from the host>'
        $actual.Text = 'Read the selected certificate to display its file hash.'
        Set-Status 'Choose your patched game and the connection details supplied by your host.'
        $form.CreateControl(); $form.PerformLayout()
        $bitmap = New-Object System.Drawing.Bitmap($form.ClientSize.Width,$form.ClientSize.Height)
        $graphics = [System.Drawing.Graphics]::FromImage($bitmap)
        try {
            $graphics.Clear($form.BackColor)
            # Hidden forms omit child controls in Form.DrawToBitmap. Render our
            # authored controls individually; no window is shown or captured.
            foreach ($control in $form.Controls) {
                [void]$control.Handle
                $control.DrawToBitmap($bitmap,$control.Bounds)
                foreach ($child in $control.Controls) {
                    [void]$child.Handle
                    $bounds = New-Object System.Drawing.Rectangle(($control.Left+$child.Left),($control.Top+$child.Top),$child.Width,$child.Height)
                    $child.DrawToBitmap($bitmap,$bounds)
                }
            }
            $bitmap.Save([System.IO.Path]::GetFullPath($RenderPreview),[System.Drawing.Imaging.ImageFormat]::Png)
        } finally { $graphics.Dispose(); $bitmap.Dispose() }
    } else { $timer.Start(); [void]$form.ShowDialog() }
} finally { $timer.Stop(); $timer.Dispose(); $form.Dispose() }
