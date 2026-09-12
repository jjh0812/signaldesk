[CmdletBinding()]
param([switch]$ReplaceKey)
$ErrorActionPreference = 'Stop'
$env:PYTHONUTF8 = '1'
$env:PYTHONIOENCODING = 'utf-8'
$python = Join-Path $PSScriptRoot '.venv\Scripts\python.exe'
if (-not (Test-Path -LiteralPath $python)) { throw 'SignalDesk Python environment was not found.' }
$arguments = @((Join-Path $PSScriptRoot 'scripts\configure_ai.py'))
if ($ReplaceKey) { $arguments += '--replace-key' }
& $python @arguments
if ($LASTEXITCODE -ne 0) { throw 'Key setup did not finish. No key value was printed. See the message above.' }
