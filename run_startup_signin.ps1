$ErrorActionPreference = "Stop"

Add-Type -AssemblyName System.Windows.Forms
Add-Type -AssemblyName System.Drawing

$Root = Split-Path -Parent $MyInvocation.MyCommand.Path
Set-Location $Root

$LogDir = Join-Path $Root "logs"
if (-not (Test-Path $LogDir)) {
    New-Item -ItemType Directory -Path $LogDir | Out-Null
}

$Stamp = Get-Date -Format "yyyyMMdd-HHmmss"
$LogPath = Join-Path $LogDir "signin-$Stamp.log"

function Write-LogLine {
    param([string]$Text)
    $Text | Tee-Object -FilePath $LogPath -Append | Out-Null
}

function Test-SigninNetwork {
    $hosts = @("zonai.skland.com", "api.kurobbs.com")
    foreach ($hostName in $hosts) {
        try {
            $client = [System.Net.Sockets.TcpClient]::new()
            $async = $client.BeginConnect($hostName, 443, $null, $null)
            $ok = $async.AsyncWaitHandle.WaitOne(3000, $false)
            if ($ok -and $client.Connected) {
                $client.EndConnect($async)
                $client.Close()
                return $true
            }
            $client.Close()
        }
        catch {
        }
    }
    return $false
}

function Set-TrayText {
    param([string]$Text)
    if ($Text.Length -gt 63) {
        $script:Tray.Text = $Text.Substring(0, 63)
    }
    else {
        $script:Tray.Text = $Text
    }
}

function Show-Balloon {
    param(
        [string]$Title,
        [string]$Text,
        [System.Windows.Forms.ToolTipIcon]$Icon = [System.Windows.Forms.ToolTipIcon]::Info
    )
    $script:Tray.BalloonTipTitle = $Title
    $script:Tray.BalloonTipText = $Text
    $script:Tray.BalloonTipIcon = $Icon
    $script:Tray.ShowBalloonTip(8000)
}

function Stop-SigninProcess {
    if ($script:Process -and -not $script:Process.HasExited) {
        try {
            $script:Process.Kill()
            $script:Process.WaitForExit(3000) | Out-Null
            Write-LogLine "[$(Get-Date -Format 'yyyy-MM-dd HH:mm:ss')] user requested exit; sign-in process killed"
        }
        catch {
            Write-LogLine "[$(Get-Date -Format 'yyyy-MM-dd HH:mm:ss')] failed to stop process: $($_.Exception.Message)"
        }
    }
}

function Quote-ProcessArg {
    param([string]$Arg)
    if ($Arg -notmatch '[\s"]') {
        return $Arg
    }
    return '"' + ($Arg -replace '"', '\"') + '"'
}

function Close-Tray {
    Stop-SigninProcess
    $script:Tray.Visible = $false
    $script:Tray.Dispose()
    [System.Windows.Forms.Application]::Exit()
}

$script:Tray = New-Object System.Windows.Forms.NotifyIcon
$script:Tray.Icon = [System.Drawing.SystemIcons]::Information
$script:Tray.Visible = $true
Set-TrayText "Auto sign-in: starting"

$menu = New-Object System.Windows.Forms.ContextMenuStrip
$exitItem = New-Object System.Windows.Forms.ToolStripMenuItem
$exitItem.Text = "Exit"
$exitItem.Add_Click({ Close-Tray })
[void]$menu.Items.Add($exitItem)
$script:Tray.ContextMenuStrip = $menu

Write-LogLine "[$(Get-Date -Format 'yyyy-MM-dd HH:mm:ss')] auto-signin tray task started"
Show-Balloon -Title "Auto sign-in" -Text "Waiting for network..."

$networkReady = $false
for ($i = 1; $i -le 36; $i++) {
    Set-TrayText "Auto sign-in: waiting network ($i/36)"
    [System.Windows.Forms.Application]::DoEvents()
    if (Test-SigninNetwork) {
        $networkReady = $true
        break
    }
    Start-Sleep -Seconds 5
}

if (-not $networkReady) {
    $message = "Network was not ready within 3 minutes. Sign-in was skipped."
    Write-LogLine $message
    Set-TrayText "Auto sign-in: skipped"
    Show-Balloon -Title "Auto sign-in skipped" -Text $message -Icon ([System.Windows.Forms.ToolTipIcon]::Warning)
    Start-Sleep -Seconds 8
    Close-Tray
    exit 2
}

$ExePath = Join-Path $Root "auto-signin-cli.exe"
if (Test-Path $ExePath) {
    $Runner = $ExePath
    $RunnerArgs = @("-c", "accounts.json", "sign")
}
else {
    $Runner = "python"
    $RunnerArgs = @("signin_tool.py", "-c", "accounts.json", "sign")
}

Set-TrayText "Auto sign-in: running"
Show-Balloon -Title "Auto sign-in" -Text "Signing in..."
Write-LogLine "[$(Get-Date -Format 'yyyy-MM-dd HH:mm:ss')] network ready, running signin"

$psi = New-Object System.Diagnostics.ProcessStartInfo
$psi.FileName = $Runner
$psi.Arguments = ($RunnerArgs | ForEach-Object { Quote-ProcessArg $_ }) -join " "
$psi.WorkingDirectory = $Root
$psi.UseShellExecute = $false
$psi.RedirectStandardOutput = $true
$psi.RedirectStandardError = $true
$psi.CreateNoWindow = $true

$script:Process = New-Object System.Diagnostics.Process
$script:Process.StartInfo = $psi
[void]$script:Process.Start()

while (-not $script:Process.HasExited) {
    [System.Windows.Forms.Application]::DoEvents()
    Start-Sleep -Milliseconds 250
}

$stdout = $script:Process.StandardOutput.ReadToEnd()
$stderr = $script:Process.StandardError.ReadToEnd()
$exitCode = $script:Process.ExitCode
$outputText = (($stdout + "`n" + $stderr) | Out-String).Trim()

Write-LogLine $outputText
Write-LogLine "[$(Get-Date -Format 'yyyy-MM-dd HH:mm:ss')] exit code: $exitCode"

if ([string]::IsNullOrWhiteSpace($outputText)) {
    $popupText = "No command output. See log: $LogPath"
}
elseif ($outputText.Length -gt 1400) {
    $popupText = $outputText.Substring(0, 1400) + "`n..."
}
else {
    $popupText = $outputText
}

if ($exitCode -eq 0 -and $outputText -notmatch "\[FAIL\]") {
    Set-TrayText "Auto sign-in: completed"
    Show-Balloon -Title "Auto sign-in completed" -Text $popupText
}
else {
    Set-TrayText "Auto sign-in: failures"
    Show-Balloon -Title "Auto sign-in has failures" -Text $popupText -Icon ([System.Windows.Forms.ToolTipIcon]::Warning)
}

Start-Sleep -Seconds 8
Close-Tray
exit $exitCode
