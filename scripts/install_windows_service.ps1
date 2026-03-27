$ErrorActionPreference = "Stop"

$Root = Split-Path -Parent $PSScriptRoot
Set-Location $Root

$Py = Join-Path $Root ".venv\Scripts\python.exe"
if (-not (Test-Path $Py)) {
    throw "Virtual environment not found. Run scripts/install_windows.ps1 first."
}

$TaskName = "AegisOS-API"
$Action = New-ScheduledTaskAction -Execute $Py -Argument "-m aegis.cli api --host 127.0.0.1 --port 8000"
$Trigger = New-ScheduledTaskTrigger -AtLogOn
$Settings = New-ScheduledTaskSettingsSet -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries

Register-ScheduledTask -TaskName $TaskName -Action $Action -Trigger $Trigger -Settings $Settings -Description "AegisOS Local API" -Force
Start-ScheduledTask -TaskName $TaskName

Write-Host "Installed Scheduled Task: $TaskName"
