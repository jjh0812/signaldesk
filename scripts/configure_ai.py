"""Configure THIS project's key without echo, command-line argument, or network call."""
from __future__ import annotations
import argparse
import getpass
import os
import re
import sys
import warnings
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))
from app.research import read_settings


def main() -> int:
    parser=argparse.ArgumentParser()
    parser.add_argument('--replace-key',action='store_true')
    args=parser.parse_args()
    path=ROOT/'.env.signaldesk'
    settings=read_settings(ROOT)
    print('\n--- SIGNALDESK AI KEY SETUP ---')
    print('ChatGPT subscription and OpenAI API billing are separate.')
    print('No paid API call is made by this setup. Only the browser AI button can send one.')
    print('The key stays in this project, in .env.signaldesk (plaintext, Git-ignored).')
    print('Do NOT paste a key into chat, screenshots, or a command-line argument.')
    if settings.configured and not args.replace_key:
        print('PROJECT KEY: PRESENT (value hidden; provider validity not yet tested)')
        print('Use Configure-AI.ps1 -ReplaceKey to change it.')
        return 0
    ignore=ROOT/'.gitignore'
    try:
        text=ignore.read_text(encoding='utf-8-sig')
    except (OSError,UnicodeError):
        print('STOP: .gitignore could not be read. No key was saved.');return 1
    if '.env.*' not in text.splitlines() and '.env.signaldesk' not in text.splitlines():
        print('STOP: local key file is not Git-ignored. No key was saved.');return 1
    for _ in range(3):
        try:
            with warnings.catch_warnings():
                warnings.simplefilter('error',getpass.GetPassWarning)
                key=getpass.getpass('OpenAI API key (hidden input; press Enter to skip): ').strip()
        except (EOFError,KeyboardInterrupt):
            print('\nKEY SETUP: SKIPPED. Charts still work.');return 0
        except getpass.GetPassWarning:
            print('STOP: hidden input is unavailable. Open an interactive PowerShell terminal.');return 1
        if not key:
            print('KEY SETUP: SKIPPED. You can run Configure-AI.ps1 later.');return 0
        if not re.fullmatch(r'[A-Za-z0-9_-]{20,512}',key):
            print('Key format was not accepted. Paste only the API key, or press Enter to skip.');continue
        tmp=path.with_name('.env.signaldesk.tmp')
        try:
            # Open with a restrictive mode on POSIX. Windows uses the project filesystem ACL.
            fd=os.open(tmp,os.O_CREAT|os.O_WRONLY|os.O_TRUNC,0o600)
            with os.fdopen(fd,'w',encoding='utf-8',newline='\n') as f:
                f.write('# SignalDesk local credential. Never commit or share this file.\n')
                f.write('OPENAI_API_KEY='+key+'\n')
                f.write('SIGNALDESK_AI_MODEL='+settings.model+'\n')
            os.replace(tmp,path)
        except OSError:
            try:tmp.unlink(missing_ok=True)
            except OSError:pass
            print('KEY SAVE: FAILED. The value was not printed.');return 1
        finally:
            key=''
        print('PROJECT KEY: SAVED (value hidden; provider validity not yet tested)')
        print('No network/API request was sent. In the browser, refresh AI status then click Analyze.')
        return 0
    print('KEY SETUP: SKIPPED after invalid input. Run Configure-AI.ps1 later.');return 1


if __name__=='__main__':raise SystemExit(main())
