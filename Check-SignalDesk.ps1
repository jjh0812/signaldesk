[CmdletBinding()]
param([ValidateRange(1024,65535)][int]$Port=8017)
$ErrorActionPreference='Stop'
$python=Join-Path $PSScriptRoot '.venv\Scripts\python.exe'
& $python (Join-Path $PSScriptRoot 'scripts\verify_frontend.py') --root $PSScriptRoot
if($LASTEXITCODE -ne 0){throw 'Source/export check failed. Rebuild the frontend.'}
$health=Invoke-RestMethod -Uri "http://127.0.0.1:$Port/api/health" -TimeoutSec 5
if($health.ui_build_id -ne 'SD-130-FORWARD-CATALYSTS' -or $health.frontend_build_id -ne 'SD-130-FORWARD-CATALYSTS'){
    throw 'An older server/export is active on this port.'
}
Write-Host 'SIGNALDESK v1.3.0 SOURCE + SERVED BUILD: PASS' -ForegroundColor Green
