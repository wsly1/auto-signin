$TaskNames = @("AutoSignInDaily0600", "AutoSignInDaily1500")

foreach ($taskName in $TaskNames) {
    schtasks.exe /Query /TN $taskName 2>$null | Out-Null
    if ($LASTEXITCODE -eq 0) {
        schtasks.exe /Delete /TN $taskName /F | Out-Null
        Write-Host "Removed daily sign-in task: $taskName"
    }
    else {
        Write-Host "Daily sign-in task not found: $taskName"
    }
}
