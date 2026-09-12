"""Foreground localhost runner shared with the actual HTTP smoke test."""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import secrets
import socket
import sys
import threading
import time
import urllib.request
import webbrowser
from pathlib import Path

from verify_frontend import BUILD_ID, VERSION, validate_export

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'backend'))
FINGERPRINT = hashlib.sha256(os.path.normcase(str(ROOT.resolve())).encode('utf-8')).hexdigest()[:16]
# Local identity checks must not pass through HTTP_PROXY/HTTPS_PROXY.
LOCAL_HTTP = urllib.request.build_opener(urllib.request.ProxyHandler({}))


def probe(url: str) -> dict:
    try:
        with LOCAL_HTTP.open(url + '/api/health', timeout=2) as response:
            body = json.load(response)
        return body if isinstance(body, dict) else {}
    except Exception:
        return {}


def matches(body: dict, pid: int | None = None, launch_id: str | None = None) -> bool:
    if not isinstance(body, dict):
        return False
    return (
        body.get('app') == 'signaldesk'
        and body.get('ui_build_id') == BUILD_ID
        and body.get('frontend_build_id') == BUILD_ID
        and body.get('project_fingerprint') == FINGERPRINT
        and (pid is None or (type(body.get('server_pid')) is int and body['server_pid'] == pid))
        and (launch_id is None or body.get('runtime_launch_id') == launch_id)
    )


def make_server(port: int, *, launch_id: str, quiet: bool = False):
    """One interpreter, no reload/workers; both run and smoke use this factory."""
    import uvicorn
    from app.main import app

    # Correlation only, not an API key/authentication credential.
    app.state.runtime_launch_id = launch_id
    config = uvicorn.Config(
        app, host='127.0.0.1', port=port, workers=1, reload=False,
        log_level='warning' if quiet else 'info', access_log=not quiet,
        timeout_graceful_shutdown=5,
    )
    return uvicorn.Server(config)


def open_when_ready(url: str, launch_id: str) -> None:
    for _ in range(120):
        if matches(probe(url), os.getpid(), launch_id):
            webbrowser.open(url + '/?build=' + BUILD_ID)
            return
        time.sleep(.3)
    print('The matching server did not become ready. No old browser page was opened.', flush=True)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument('--port', type=int, default=8017)
    parser.add_argument('--open-browser', action='store_true')
    args = parser.parse_args()
    if not 1024 <= args.port <= 65535:
        print('Invalid port')
        return 1
    try:
        validate_export(ROOT)
    except Exception as exc:
        print(f'Cannot start an unverified frontend: {exc}')
        return 1
    url = f'http://127.0.0.1:{args.port}'
    # Keep the socket reserved until Uvicorn receives it; no bind/rebind race.
    sock = socket.socket()
    try:
        if os.name == 'nt' and hasattr(socket, 'SO_EXCLUSIVEADDRUSE'):
            sock.setsockopt(socket.SOL_SOCKET, socket.SO_EXCLUSIVEADDRUSE, 1)
        sock.bind(('127.0.0.1', args.port))
    except OSError:
        sock.close()
        existing = probe(url)
        if matches(existing):
            print(f'VERIFIED SIGNALDESK ALREADY RUNNING: {url} [{BUILD_ID}]')
            if args.open_browser:
                webbrowser.open(url + '/?build=' + BUILD_ID)
            return 0
        print(f'PORT {args.port} belongs to another build/folder/app. No process was stopped.')
        print('Stop the old SignalDesk terminal with Ctrl+C, then start from this project again.')
        return 1
    try:
        launch_id = secrets.token_hex(24)
        server = make_server(args.port, launch_id=launch_id)
        print(f'\nSIGNALDESK {VERSION} / {BUILD_ID}\nPROJECT: {ROOT}\nOPEN: {url}\n'
              'Verified export. No automatic paid AI calls. Ctrl+C stops this server.\n', flush=True)
        if args.open_browser:
            threading.Thread(target=open_when_ready, args=(url, launch_id), daemon=True).start()
        try:
            server.run(sockets=[sock])
        except KeyboardInterrupt:
            pass
    finally:
        sock.close()
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
