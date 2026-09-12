"""Actual localhost HTTP check, with no nested subprocess or process termination.

Windows venv's launcher PID can differ from the Python interpreter PID. The
old checker equated Popen.pid with os.getpid() in a nested process. This one
runs the real server in this interpreter on an exclusively reserved socket,
checks its actual PID + launch nonce + build + project, and closes it in finally.
Only /api/health, static pages and static assets are requested. No paid/market API.
"""
from __future__ import annotations

import hashlib
import json
import os
import re
import secrets
import socket
import sys
import threading
import time
import urllib.request
from pathlib import Path
from urllib.parse import unquote, urlsplit

from verify_frontend import BUILD_ID, VERSION, validate_export

PUBLIC_FIELDS = ('app', 'server_pid', 'runtime_launch_id', 'ui_build_id',
                 'frontend_build_id', 'project_fingerprint')


class RuntimeCheckError(RuntimeError):
    pass


def expected_identity(root: Path, launch_id: str) -> dict:
    return {
        'app': 'signaldesk', 'server_pid': os.getpid(), 'runtime_launch_id': launch_id,
        'ui_build_id': BUILD_ID, 'frontend_build_id': BUILD_ID,
        'project_fingerprint': hashlib.sha256(
            os.path.normcase(str(root.resolve())).encode('utf-8')).hexdigest()[:16],
    }


def identity_mismatches(body, expected: dict) -> dict:
    if not isinstance(body, dict):
        return {'response': {'expected': 'JSON object', 'observed': type(body).__name__}}
    return {k: {'expected': v, 'observed': body.get(k)} for k, v in expected.items()
            if body.get(k) != v or (k == 'server_pid' and type(body.get(k)) is not int)}


def assert_identity(body, expected: dict) -> None:
    differences = identity_mismatches(body, expected)
    if differences:
        raise RuntimeCheckError('IDENTITY_MISMATCH: ' + json.dumps(differences, ensure_ascii=True))


def verify_served_pages(root: Path, base: str, opener) -> tuple[int, int]:
    """Verify served HTML byte-for-byte too, then every linked local asset."""
    out = (root / 'frontend/out').resolve()
    assets = set()
    for urlpath, filename in (('/', 'index.html'), ('/advanced/', 'advanced/index.html')):
        with opener.open(base + urlpath, timeout=5) as response:
            content = response.read()
            if 'no-store' not in response.headers.get('Cache-Control', ''):
                raise RuntimeCheckError('HTML_CACHE_GUARD_MISSING: ' + urlpath)
        if content != (out / filename).read_bytes():
            raise RuntimeCheckError('HTML_BYTES_MISMATCH: ' + urlpath)
        html = content.decode('utf-8')
        if BUILD_ID not in html:
            raise RuntimeCheckError('OLD_HTML_BUILD: ' + urlpath)
        for bad in ('이 가격, 무엇을 기대하고 있나?', '가정·자료 설정', 'desk-price'):
            if bad in html:
                raise RuntimeCheckError('REMOVED_VALUATION_STILL_SERVED: ' + urlpath)
        page_assets = re.findall(r'(?:src|href)="(/_next/[^"?]+)', html)
        if not page_assets:
            raise RuntimeCheckError('HTML_ASSETS_MISSING: ' + urlpath)
        assets.update(page_assets)
    for asset in sorted(assets):
        parsed = urlsplit(asset)
        if parsed.scheme or parsed.netloc or not parsed.path.startswith('/_next/'):
            raise RuntimeCheckError('INVALID_ASSET_URL')
        local = (out / unquote(parsed.path).lstrip('/')).resolve()
        if not local.is_relative_to(out) or not local.is_file():
            raise RuntimeCheckError('INVALID_ASSET_PATH: ' + parsed.path)
        with opener.open(base + asset, timeout=5) as response:
            served = response.read()
        if hashlib.sha256(served).digest() != hashlib.sha256(local.read_bytes()).digest():
            raise RuntimeCheckError('ASSET_BYTES_MISMATCH: ' + parsed.path)
    return 2, len(assets)


def wait_ready(server, thread, errors: list, timeout: float) -> None:
    end = time.monotonic() + timeout
    while not server.started:
        if errors:
            raise RuntimeCheckError('SERVER_START_FAILED: ' + errors[0])
        if not thread.is_alive():
            raise RuntimeCheckError('SERVER_EXITED_BEFORE_READY')
        if time.monotonic() >= end:
            raise RuntimeCheckError('SERVER_START_TIMEOUT')
        time.sleep(.05)


def stop_owned_server(server, thread, sock) -> None:
    """No kill/taskkill/PID lookup: stop just this Uvicorn object."""
    server.should_exit = True
    if thread.ident is not None:
        thread.join(timeout=8)
        if thread.is_alive():
            server.force_exit = True
            thread.join(timeout=3)
    sock.close()
    if thread.is_alive():
        raise RuntimeCheckError('TEST_SERVER_SHUTDOWN_TIMEOUT')


def check(root: Path, timeout: float = 30) -> dict:
    root = root.resolve()
    validate_export(root)
    # run.py is a shared factory, not another executable or process.
    import run as runner
    if runner.ROOT.resolve() != root:
        raise RuntimeCheckError('RUNNER_ROOT_MISMATCH')
    launch_id = secrets.token_hex(24)
    expected = expected_identity(root, launch_id)
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
    sock = socket.socket()
    server = None
    thread = None
    errors = []
    observed = None
    port = None
    record = {'release_version': VERSION, 'build_id': BUILD_ID, 'status': 'FAIL'}
    try:
        if os.name == 'nt' and hasattr(socket, 'SO_EXCLUSIVEADDRUSE'):
            sock.setsockopt(socket.SOL_SOCKET, socket.SO_EXCLUSIVEADDRUSE, 1)
        sock.bind(('127.0.0.1', 0))
        port = sock.getsockname()[1]
        base = f'http://127.0.0.1:{port}'
        server = runner.make_server(port, launch_id=launch_id, quiet=True)
        def serve():
            try:
                server.run(sockets=[sock])
            except BaseException as exc:
                errors.append(type(exc).__name__ + ': ' + str(exc))
        thread = threading.Thread(target=serve, name='signaldesk-local-check', daemon=True)
        thread.start()
        wait_ready(server, thread, errors, timeout)
        with opener.open(base + '/api/health', timeout=5) as response:
            observed = json.load(response)
        assert_identity(observed, expected)
        pages, assets = verify_served_pages(root, base, opener)
        # Read-only feature probe: no SEC fetch, no paid call, no cached result logging.
        with opener.open(base + '/api/v1/watch/state?symbol=SPY', timeout=5) as response:
            feature = json.load(response)
        if feature.get('symbol') != 'SPY' or feature.get('ai_calls') != 0 or feature.get('network_requests') != 0:
            raise RuntimeCheckError('STOCK_WATCH_READONLY_PROBE_FAILED')
        if errors:
            raise RuntimeCheckError('SERVER_ERROR: ' + errors[0])
        record.update(status='PASS', pages_checked=pages, assets_checked=assets)
    except Exception as exc:
        record['error'] = str(exc)
        if observed is not None:
            record['identity_mismatches'] = identity_mismatches(observed, expected)
        raise
    finally:
        try:
            if server is not None and thread is not None:
                stop_owned_server(server, thread, sock)
            else:
                sock.close()
        except Exception as exc:
            record.update(status='FAIL', cleanup_error=str(exc))
            raise
        finally:
            # Fixed allowlist, not full health/env/AI status. No API key is recorded.
            if isinstance(observed, dict):
                record['observed_identity'] = {k: observed.get(k) for k in PUBLIC_FIELDS}
            record['test_port'] = port
            try:
                logs = root / 'logs'
                logs.mkdir(exist_ok=True)
                (logs / 'runtime-check-120.json').write_text(
                    json.dumps(record, ensure_ascii=True, indent=2), encoding='utf-8')
            except OSError:
                pass  # Log disk errors don't disguise the actual check result.
    print(f'LOCAL RUNTIME CHECK: PASS / {BUILD_ID} '
          f"({record['pages_checked']} pages, {record['assets_checked']} assets; server stopped)")
    return record


if __name__ == '__main__':
    try:
        check(Path(__file__).resolve().parents[1])
    except Exception as exc:
        print('LOCAL RUNTIME CHECK FAILED:', exc)
        raise SystemExit(1)
