$ErrorActionPreference = 'Stop'
$env:NEXT_TELEMETRY_DISABLED = '1'
$env:PYTHONUTF8 = '1'
$npm = Get-Command npm.cmd -ErrorAction Stop
$python = Join-Path $PSScriptRoot '.venv\Scripts\python.exe'
if (-not (Test-Path -LiteralPath $python)) { throw 'Project Python environment not found.' }
& $python (Join-Path $PSScriptRoot 'scripts\test_verify_frontend.py')
if ($LASTEXITCODE -ne 0) { throw 'Frontend export-check regression tests failed.' }
Push-Location (Join-Path $PSScriptRoot 'frontend')
try {
    & $npm.Source test
    if ($LASTEXITCODE -ne 0) { throw 'Frontend helper tests failed.' }
    & $npm.Source run build
    if ($LASTEXITCODE -ne 0) { throw 'Frontend build failed.' }
    & $python (Join-Path $PSScriptRoot 'scripts\verify_frontend.py') --root $PSScriptRoot --stamp
    if ($LASTEXITCODE -ne 0) { throw 'Export verification failed. An old or incomplete UI may have been built.' }
    Write-Host 'FRONTEND BUILD + EXPORT CHECK: PASS' -ForegroundColor Green
} finally { Pop-Location }
