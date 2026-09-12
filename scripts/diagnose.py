"""Read-only local diagnostics. Does not inspect .env files or send secrets."""
from pathlib import Path
import importlib.metadata
import json
import platform
import sys
import urllib.request
ROOT = Path(__file__).resolve().parents[1]
print("PYTHON:", platform.python_version())
print("PLATFORM:", platform.platform())
print("PROJECT:", ROOT)
for package in ['fastapi','uvicorn','yfinance','pandas','httpx','tzdata']:
    try: print(package + ':', importlib.metadata.version(package))
    except importlib.metadata.PackageNotFoundError: print(package + ': MISSING')
print('FRONTEND:', 'BUILT' if (ROOT/'frontend/out/index.html').is_file() else 'NOT BUILT')
try:
    with urllib.request.urlopen('http://127.0.0.1:8017/api/health',timeout=2) as r:
        print('LOCAL HEALTH:',json.load(r))
except Exception as e: print('LOCAL HEALTH: NOT RUNNING OR UNREACHABLE',type(e).__name__)
print('No API keys or environment file contents were read.')
