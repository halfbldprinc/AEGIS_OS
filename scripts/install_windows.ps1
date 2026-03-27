$ErrorActionPreference = "Stop"

$Root = Split-Path -Parent $PSScriptRoot
Set-Location $Root

if (-not (Test-Path ".venv")) {
    py -3 -m venv .venv
}

$Py = Join-Path $Root ".venv\Scripts\python.exe"
& $Py -m pip install --upgrade pip
& $Py -m pip install -e ".[api]"

Write-Host "[AegisOS] Base install complete"
Write-Host "Run API: .venv\Scripts\python.exe -m aegis.cli api --host 127.0.0.1 --port 8000"
