[CmdletBinding()]
param([ValidateRange(1024,65535)][int]$Port = 8017, [switch]$NoBrowser)
$ErrorActionPreference = 'Stop'
$env:PYTHONUTF8 = '1'
$env:PYTHONIOENCODING = 'utf-8'
$python = Join-Path $PSScriptRoot '.venv\Scripts\python.exe'
if (-not (Test-Path -LiteralPath $python)) { throw 'SignalDesk is not installed. Run Install-SignalDesk.ps1 first.' }
$arguments = @((Join-Path $PSScriptRoot 'scripts\run.py'),'--port',[string]$Port)
if (-not $NoBrowser) { $arguments += '--open-browser' }
& $python @arguments
if ($LASTEXITCODE -ne 0) { throw "SignalDesk stopped with exit code $LASTEXITCODE. See the terminal output above." }
