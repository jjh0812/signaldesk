"""Local thesis cache only. No SEC client, contact settings or network operations."""
from __future__ import annotations
import json
import os
import re
import time
from datetime import date, datetime, timezone
from pathlib import Path
from .evidence_store import _safe_path

def stamp() -> str:
    return datetime.now(timezone.utc).isoformat()


def day(value):
    try:
        return date.fromisoformat(value) if isinstance(value, str) and re.fullmatch(r'\d{4}-\d{2}-\d{2}', value) else None
    except ValueError:
        return None


def age(value):
    try:
        parsed = datetime.fromisoformat(value)
        return time.time() - parsed.timestamp() if parsed.tzinfo else float('inf')
    except (ValueError, TypeError):
        return float('inf')


def clean(value):
    return re.sub(r'\s+', ' ', value).strip()


class WatchStore:
    """Allowlisted per-project storage. Cache reads never cause external requests."""
    def __init__(self, root: Path):
        self.root = root

    def path(self, name):
        if not re.fullmatch(r'[A-Za-z0-9_.-]{1,100}\.json', name):
            raise ValueError('Invalid watch filename')
        return _safe_path(self.root, '.cache/stock-watch110/' + name)

    def read(self, name, limit=12_000_000):
        p = self.path(name)
        try:
            if p.stat().st_size > limit:
                return None
            result = json.loads(p.read_text(encoding='utf-8'))
            return result if isinstance(result, dict) else None
        except (OSError, UnicodeError, ValueError):
            return None

    def save(self, name, value):
        p = self.path(name)
        p.parent.mkdir(parents=True, exist_ok=True)
        tmp = p.with_name(p.name + '.' + os.urandom(5).hex() + '.tmp')
        try:
            tmp.write_text(json.dumps(value, ensure_ascii=False, allow_nan=False), encoding='utf-8')
            os.replace(tmp, p)
        finally:
            tmp.unlink(missing_ok=True)

