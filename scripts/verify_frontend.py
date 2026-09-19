"""Verify live UI source, static export, and exact file hashes without running JS.

1.1.1: compiled JS may spell the middle dot as \\xb7, not only \\u00b7.
Feature presence now uses ASCII identifiers attached to the actual JSX elements,
not translated labels. Escape-aware scans still reject removed valuation code.
This module never reads credentials, research caches, or external services.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import re
from pathlib import Path

BUILD_ID = 'SD-130-FORWARD-CATALYSTS'
VERSION = '1.3.0'
MANIFEST = 'build-info.json'
FORBIDDEN = ('이 가격, 무엇을 기대하고 있나?', '가치평가 자료가 아직 준비되지 않았습니다.',
             '가정·자료 설정', '/api/v1/watch/dilution', '/api/v1/watch/contact', 'sd-dilution-scan-action', 'watch-sec-email', 'DILUTION WATCH', '/api/v1/decision/state', '/api/v1/decision/calculate', 'desk-price')
SOURCE_DIRS = ('app', 'components', 'lib')
# These identifiers are emitted on real buttons/outcome nodes, not in an unused constant.
REQUIRED_FEATURE_IDS = ('sd-stock-drivers-action', 'sd-forward-catalysts-action',
                        'sd-event-upside-condition', 'sd-event-downside-condition',
                        'sd-thesis-summary', 'sd-thesis-bottlenecks', 'sd-thesis-funding', 'sd-thesis-resume-action')
# One pass, preserving escaped backslashes. Do NOT use unicode_escape on UTF-8 text,
# eval(), or a second recursive decode. That corrupts Korean or evaluates code.
_JS_ESCAPES = re.compile(r'\\(?:\\|x([0-9a-fA-F]{2})|u([0-9a-fA-F]{4})|u\{([0-9a-fA-F]{1,6})\})')


def digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def source_digest(root: Path) -> str:
    frontend = root / 'frontend'
    paths = []
    for folder in SOURCE_DIRS:
        paths += [p for p in (frontend / folder).rglob('*')
                  if p.is_file() and p.suffix in ('.mjs', '.jsx', '.js', '.css', '.json')]
    paths += [frontend / p for p in ('package.json', 'package-lock.json', 'next.config.mjs')
              if (frontend / p).is_file()]
    h = hashlib.sha256()
    for p in sorted(paths, key=lambda p: p.relative_to(frontend).as_posix()):
        h.update(p.relative_to(frontend).as_posix().encode('utf-8'))
        h.update(b'\0')
        h.update(bytes.fromhex(digest(p)))
    return h.hexdigest()


def validate_source(root: Path) -> None:
    frontend = root / 'frontend'
    live = [frontend / p for p in ('app/page.jsx', 'app/advanced/page.jsx',
            'components/DeskOverview.jsx', 'components/NewsEventBoard.jsx', 'components/StockWatch.jsx')]
    for p in live:
        content = p.read_text(encoding='utf-8')
        for bad in FORBIDDEN:
            if bad in content:
                raise RuntimeError(f'Removed valuation feature remains in {p.name}: {bad}')
        if re.search(r'import\s+.*\bValuation\b', content):
            raise RuntimeError('Valuation component is still imported')
    board = (frontend / 'components/NewsEventBoard.jsx').read_text(encoding='utf-8')
    for token in ('호재가 되는 조건', '악재가 되는 조건', 'data-direction',
                  'data-ui-feature="sd-event-upside-condition"',
                  'data-ui-feature="sd-event-downside-condition"'):
        if token not in board:
            raise RuntimeError(f'Direction UI is missing in source: {token}')
    watch = (frontend / 'components/StockWatch.jsx').read_text(encoding='utf-8')
    for token in ('id="sd-stock-drivers-action"',
                  '투자 논리 자동 분석', 'id="sd-thesis-summary"', 'id="sd-thesis-bottlenecks"'):
        if token not in watch:
            raise RuntimeError(f'Stock Watch UI is missing in source: {token}')
    page = (frontend / 'app/page.jsx').read_text(encoding='utf-8')
    if not re.search(r"import\s+StockWatch\s+from\s+['\"]\.\./components/StockWatch['\"]", page) or '<StockWatch ' not in page:
        raise RuntimeError('StockWatch is not connected to the main screen')
    desk = (frontend / 'components/DeskOverview.jsx').read_text(encoding='utf-8')
    if 'id="sd-forward-catalysts-action"' not in desk:
        raise RuntimeError('Forward catalyst action is missing')
    if '<NewsEventBoard ' not in desk:
        raise RuntimeError('NewsEventBoard is not connected to the screen')
    if BUILD_ID not in (frontend / 'lib/release.mjs').read_text(encoding='utf-8'):
        raise RuntimeError('Incorrect source build ID')


def export_contents(root: Path) -> dict[str, str]:
    out = root / 'frontend/out'
    return {p.relative_to(out).as_posix(): digest(p) for p in sorted(out.rglob('*'))
            if p.is_file() and p.name != MANIFEST}


def plain_js(value: str) -> str:
    """Normalize character escapes for a conservative text scan, not a JS parser."""
    def decode(match: re.Match) -> str:
        code = next((v for v in match.groups() if v is not None), None)
        if code is None:  # doubled backslash: do not convert a literal escape example
            return match.group(0)
        number = int(code, 16)
        return chr(number) if number <= 0x10FFFF else match.group(0)
    return _JS_ESCAPES.sub(decode, value)


def validate_export(root: Path, *, stamp: bool = False) -> dict:
    validate_source(root)
    out = root / 'frontend/out'
    for relative in ('index.html', 'advanced/index.html'):
        p = out / relative
        if not p.is_file():
            raise RuntimeError(f'Missing exported page: {relative}')
        html = p.read_text(encoding='utf-8')
        if BUILD_ID not in html:
            raise RuntimeError(f'Old HTML export detected: {relative}')
        for bad in FORBIDDEN:
            if bad in html:
                raise RuntimeError(f'Removed feature found in exported HTML: {bad}')
    jsfiles = list((out / '_next').rglob('*.js'))
    if not jsfiles:
        raise RuntimeError('Export has no JavaScript chunks')
    scripts = '\n'.join(plain_js(p.read_text(encoding='utf-8')) for p in jsfiles)
    missing = [token for token in (BUILD_ID, *REQUIRED_FEATURE_IDS) if token not in scripts]
    if missing:
        raise RuntimeError('UI feature identifiers missing from built JavaScript: ' + ', '.join(missing))
    for bad in FORBIDDEN:
        if bad in scripts:
            raise RuntimeError(f'Old valuation UI/API remains in built JavaScript: {bad}')
    actual = export_contents(root)
    if stamp:
        info = {'version': VERSION, 'build_id': BUILD_ID,
                'source_sha256': source_digest(root), 'feature_ids': list(REQUIRED_FEATURE_IDS), 'files': actual}
        (out / MANIFEST).write_text(json.dumps(info, ensure_ascii=False, indent=2), encoding='utf-8')
        return info
    p = out / MANIFEST
    if not p.is_file():
        raise RuntimeError('Build verification manifest missing. Run Build-Frontend.ps1.')
    info = json.loads(p.read_text(encoding='utf-8'))
    if info.get('build_id') != BUILD_ID or info.get('version') != VERSION:
        raise RuntimeError('Wrong build manifest version')
    if info.get('feature_ids') != list(REQUIRED_FEATURE_IDS):
        raise RuntimeError('Build manifest missing the feature checks. Run Build-Frontend.ps1.')
    if info.get('source_sha256') != source_digest(root):
        raise RuntimeError('Source changed after the last build. Run Build-Frontend.ps1.')
    if info.get('files') != actual:
        raise RuntimeError('Export differs from the verified build. Rebuild before starting.')
    return info


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--root', type=Path, default=Path(__file__).resolve().parents[1])
    parser.add_argument('--stamp', action='store_true')
    parser.add_argument('--source-only', action='store_true')
    args = parser.parse_args()
    try:
        if args.source_only:
            validate_source(args.root)
            print('SOURCE CHECK: PASS')
        else:
            info = validate_export(args.root, stamp=args.stamp)
            print(f"FRONTEND EXPORT VERIFIED: {info['build_id']} ({len(info['files'])} files)")
    except Exception as exc:
        print(f'FRONTEND VERIFICATION FAILED: {exc}')
        raise SystemExit(1)
