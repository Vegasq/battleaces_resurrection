param(
    [Parameter(Mandatory=$true)][string]$PythonExecutable,
    [Parameter(Mandatory=$true)][string]$ConfigPath,
    [string]$RenderPreview = ''
)
$ErrorActionPreference = 'Stop'
Add-Type -AssemblyName System.Windows.Forms
Add-Type -AssemblyName System.Drawing
[System.Windows.Forms.Application]::EnableVisualStyles()
function Quote-Argument([string]$Value) {
    '"' + [regex]::Replace([regex]::Replace($Value, '(\\*)"', '$1$1\"'), '(\\+)$', '$1$1') + '"'
}
function Label([string]$Text,[int]$X,[int]$Y,[int]$Width,[int]$Height=28) {
    $c=New-Object System.Windows.Forms.Label
    $c.Text=$Text; $c.SetBounds($X,$Y,$Width,$Height); $form.Controls.Add($c); return $c
}
function TextBox([int]$X,[int]$Y,[int]$Width) {
    $c=New-Object System.Windows.Forms.TextBox
    $c.SetBounds($X,$Y,$Width,28); $form.Controls.Add($c); return $c
}
function Button([string]$Text,[int]$X,[int]$Y,[int]$Width) {
    $c=New-Object System.Windows.Forms.Button
    $c.Text=$Text; $c.SetBounds($X,$Y,$Width,36); $form.Controls.Add($c); return $c
}
function Status([string]$Text) { $status.Text=$Text }
function Busy([bool]$Value) {
    foreach ($control in $script:controls) { $control.Enabled=-not $Value }
    $form.UseWaitCursor=$Value
}
function Run-Backend([string[]]$Arguments,[scriptblock]$Done,[string]$Request='') {
    if ($script:pending) { return }
    $info=New-Object System.Diagnostics.ProcessStartInfo
    $info.FileName=$PythonExecutable
    $info.Arguments=(@('-I','-B','-m','tools.package_client')+$Arguments | ForEach-Object { Quote-Argument $_ }) -join ' '
    $info.UseShellExecute=$false; $info.CreateNoWindow=$true
    $info.RedirectStandardOutput=$true; $info.RedirectStandardError=$true
    $p=New-Object System.Diagnostics.Process; $p.StartInfo=$info
    try {
        [void]$p.Start()
        $script:pending=@{Process=$p;Output=$p.StandardOutput.ReadToEndAsync();Error=$p.StandardError.ReadToEndAsync();Done=$Done;Request=$Request;Start=[DateTime]::UtcNow}
        Busy $true
    } catch {
        $p.Dispose()
        if ($Request) { Remove-Item -LiteralPath $Request -ErrorAction SilentlyContinue }
        Status 'Could not start setup. Extract the complete client package to a writable folder.'
    }
}
function Load-Settings {
    Run-Backend @('rc-data','--config',$ConfigPath) {
        param($result)
        $game.Text=$result.result.game_directory
        $name.Text=$result.result.display_name
        $address.Text=$result.result.server_host
        $script:expected=$result.result.expected_config_sha256
        Status 'Choose your game folder. Enter a server IP for multiplayer, or leave it blank for offline play.'
    }
}
function Save-Settings {
    $requestPath=''
    try {
        $parent=[System.IO.Path]::GetDirectoryName([System.IO.Path]::GetFullPath($ConfigPath))
        [void][System.IO.Directory]::CreateDirectory($parent)
        $requestPath=Join-Path $parent ('.rc-request-'+[Guid]::NewGuid().ToString('N')+'.json')
        $request=@{game_directory=$game.Text;display_name=$name.Text;server_host=$address.Text;expected_config_sha256=$script:expected}
        $bytes=[System.Text.Encoding]::UTF8.GetBytes(($request | ConvertTo-Json -Compress))
        $stream=[System.IO.File]::Open($requestPath,[System.IO.FileMode]::CreateNew,[System.IO.FileAccess]::Write,[System.IO.FileShare]::None)
        try { $stream.Write($bytes,0,$bytes.Length); $stream.Flush($true) } finally { $stream.Dispose() }
        Status 'Saving client settings...'
        Run-Backend @('rc-save','--config',$ConfigPath,'--request',$requestPath) {
            param($result)
            $script:expected=$result.result.expected_config_sha256
            Status 'Saved. Use Start Client.cmd to play. Offline AI works without a server.'
        } $requestPath
    } catch {
        if ($requestPath -and -not $script:pending) { Remove-Item -LiteralPath $requestPath -ErrorAction SilentlyContinue }
        Status 'Could not save settings. Choose a writable extracted package folder.'
    }
}
$form=New-Object System.Windows.Forms.Form
$form.Text='Battle Aces Resurrection - Client Setup (RC1)'
$form.ClientSize=New-Object System.Drawing.Size(780,470)
$form.FormBorderStyle='FixedDialog'; $form.MaximizeBox=$false; $form.StartPosition='CenterScreen'
$form.AutoScaleMode='Dpi'; $form.Font=New-Object System.Drawing.Font('Segoe UI',10)
$form.BackColor=[System.Drawing.Color]::FromArgb(246,248,251)
$title=Label 'Battle Aces Resurrection' 24 22 730 40
$title.Font=New-Object System.Drawing.Font('Segoe UI',20,[System.Drawing.FontStyle]::Bold)
[void](Label 'Install once. Then use Start Client.cmd for online or offline play.' 26 70 730)
[void](Label 'Game folder' 24 124 130)
$game=TextBox 158 120 480
$browse=Button 'Browse...' 648 116 108
[void](Label 'Player name' 24 172 130)
$name=TextBox 158 168 598; $name.MaxLength=32
[void](Label 'Server IP' 24 220 130)
$address=TextBox 158 216 598; $address.MaxLength=253
[void](Label 'Optional for offline play. Default server port: 47623.' 158 250 598)
$install=Button 'Install / Update' 24 300 175
$save=Button 'Save settings' 211 300 162
$check=Button 'Test connection' 385 300 175
$restore=Button 'Restore original' 572 300 184
$status=Label '' 24 354 732 64
$status.ForeColor=[System.Drawing.Color]::FromArgb(30,60,85)
[void](Label 'RC1 uses encrypted transport without certificate verification. No CA or invite required.' 24 432 732 26)
$script:controls=@($game,$browse,$name,$address,$install,$save,$check,$restore)
$script:pending=$null; $script:expected=$null
$browse.Add_Click({
    $dialog=New-Object System.Windows.Forms.FolderBrowserDialog
    try { $dialog.Description='Choose your working Battle Aces folder'; if ($dialog.ShowDialog($form) -eq 'OK') { $game.Text=$dialog.SelectedPath } }
    finally { $dialog.Dispose() }
})
$install.Add_Click({
    Status 'Checking game content and installing the patch. This may take several minutes; keep setup open.'
    Run-Backend @('install','--game',$game.Text) { param($result) Save-Settings }
})
$save.Add_Click({ Save-Settings })
$restore.Add_Click({
    Status 'Restoring verified original game files. Saved decks and cosmetics are kept.'
    Run-Backend @('restore','--game',$game.Text) { param($result) Status 'Original game files restored. Personal saves are preserved.' }
})
$check.Add_Click({
    Status 'Checking saved settings and server connection...'
    Run-Backend @('rc-check','--config',$ConfigPath) { param($result) Status ('Connected with '+$result.result.tls+'. Ready for multiplayer.') }
})
$timer=New-Object System.Windows.Forms.Timer; $timer.Interval=200
$timer.Add_Tick({
    if (-not $script:pending) { return }
    $job=$script:pending
    if (-not $job.Process.HasExited) {
        $form.Text='Battle Aces Resurrection - Working ('+[int]([DateTime]::UtcNow-$job.Start).TotalSeconds+'s)'
        return
    }
    if (-not $job.Output.IsCompleted -or -not $job.Error.IsCompleted) { return }
    $script:pending=$null; Busy $false
    $form.Text='Battle Aces Resurrection - Client Setup (RC1)'
    try {
        if ($job.Request) { Remove-Item -LiteralPath $job.Request -ErrorAction SilentlyContinue }
        if ($job.Process.ExitCode -ne 0) { Status 'Operation failed. Check the game folder, server IP, saved settings and supported game build.'; return }
        $result=$job.Output.Result | ConvertFrom-Json
        if ($null -ne $result.ok -and -not $result.ok) { Status ([string]$result.error); return }
        & $job.Done $result
    } catch { Status 'Operation failed. Check local files and permissions, then retry.' }
    finally { $job.Process.Dispose() }
})
$form.Add_FormClosing({param($sender,$e) if ($script:pending) { $e.Cancel=$true; Status 'Please wait for the current operation to finish.' }})
$form.Add_Shown({ Load-Settings })
try {
    if ($RenderPreview) {
        $game.Text='D:\Battle Aces'; $name.Text='Player'; $address.Text='192.168.1.25'
        Status 'Choose your game folder, enter the server IP, then Install / Update.'
        $bitmap=New-Object System.Drawing.Bitmap($form.ClientSize.Width,$form.ClientSize.Height)
        $graphics=[System.Drawing.Graphics]::FromImage($bitmap)
        try {
            $graphics.Clear($form.BackColor)
            foreach ($control in $form.Controls) { [void]$control.Handle; $control.DrawToBitmap($bitmap,$control.Bounds) }
            $bitmap.Save([System.IO.Path]::GetFullPath($RenderPreview),[System.Drawing.Imaging.ImageFormat]::Png)
        } finally { $graphics.Dispose(); $bitmap.Dispose() }
    } else { $timer.Start(); [void]$form.ShowDialog() }
} finally { $timer.Stop(); $timer.Dispose(); $form.Dispose() }
