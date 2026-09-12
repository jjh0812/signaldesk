$ErrorActionPreference = 'Stop'
$python = Join-Path $PSScriptRoot '.venv\Scripts\python.exe'
Write-Host "PROJECT: $PSScriptRoot"
if (-not (Test-Path -LiteralPath $python)) { Write-Host 'VENV: MISSING'; exit 1 }
& $python (Join-Path $PSScriptRoot 'scripts\diagnose.py')
