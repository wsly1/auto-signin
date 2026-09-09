$StartupDir = [Environment]::GetFolderPath("Startup")
$ShortcutPath = Join-Path $StartupDir "AutoSignIn.lnk"

if (Test-Path $ShortcutPath) {
    Remove-Item -LiteralPath $ShortcutPath -Force
    Write-Host "Removed startup shortcut: $ShortcutPath"
}
else {
    Write-Host "Startup shortcut not found: $ShortcutPath"
}
