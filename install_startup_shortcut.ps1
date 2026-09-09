$ErrorActionPreference = "Stop"

$Root = Split-Path -Parent $MyInvocation.MyCommand.Path
$ScriptPath = Join-Path $Root "run_startup_signin.ps1"
$StartupDir = [Environment]::GetFolderPath("Startup")
$ShortcutPath = Join-Path $StartupDir "AutoSignIn.lnk"

if (-not (Test-Path $ScriptPath)) {
    throw "Startup script not found: $ScriptPath"
}

$Shell = New-Object -ComObject WScript.Shell
$Shortcut = $Shell.CreateShortcut($ShortcutPath)
$Shortcut.TargetPath = "powershell.exe"
$Shortcut.Arguments = "-NoProfile -STA -ExecutionPolicy Bypass -WindowStyle Hidden -File `"$ScriptPath`""
$Shortcut.WorkingDirectory = $Root
$Shortcut.WindowStyle = 7
$Shortcut.Description = "Auto sign-in after Windows logon"
$Shortcut.Save()

Write-Host "Installed startup shortcut: $ShortcutPath"
Write-Host "It does not depend on Codex. It runs: $ScriptPath"
