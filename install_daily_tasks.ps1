$ErrorActionPreference = "Stop"

$Root = Split-Path -Parent $MyInvocation.MyCommand.Path
$ScriptPath = Join-Path $Root "run_startup_signin.ps1"
$TaskPrefix = "AutoSignInDaily"
$Times = @("06:00", "15:00")

if (-not (Test-Path $ScriptPath)) {
    throw "Signin script not found: $ScriptPath"
}

$TaskCommand = "powershell.exe"
$TaskArgs = "-NoProfile -STA -ExecutionPolicy Bypass -WindowStyle Hidden -File `"$ScriptPath`""
$TaskRun = "`"$TaskCommand`" $TaskArgs"

foreach ($time in $Times) {
    $safeTime = $time.Replace(":", "")
    $taskName = "$TaskPrefix$safeTime"
    schtasks.exe /Create /TN $taskName /SC DAILY /ST $time /TR $TaskRun /F | Out-Null
    $settings = New-ScheduledTaskSettingsSet `
        -AllowStartIfOnBatteries `
        -DontStopIfGoingOnBatteries `
        -StartWhenAvailable `
        -ExecutionTimeLimit (New-TimeSpan -Minutes 10)
    Set-ScheduledTask -TaskName $taskName -Settings $settings | Out-Null
    Write-Host "Installed daily sign-in task: $taskName at $time"
}

Write-Host "Daily auto sign-in tasks installed. They do not depend on Codex."
