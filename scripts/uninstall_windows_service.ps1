$ErrorActionPreference = "SilentlyContinue"
$TaskName = "AegisOS-API"
Unregister-ScheduledTask -TaskName $TaskName -Confirm:$false
Write-Host "Removed Scheduled Task: $TaskName"
