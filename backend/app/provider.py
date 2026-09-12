"""Yahoo Finance adapter. Personal/local research use; never fake a response."""
from __future__ import annotations

import json
import logging
import math
import os
import re
import threading
from dataclasses import asdict
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Any

from .engine import Bar, validate_bars

log = logging.getLogger("signaldesk.provider")
SYMBOL_RE = re.compile(r"^[A-Z][A-Z0-9]{0,9}(?:-[A-Z])?$")
CACHE_VERSION = 1


class ProviderError(Exception):
    def __init__(self, code: str, message: str, status: int = 502) -> None:
        super().__init__(message)
        self.code, self.message, self.status = code, message, status


def normalize_symbol(symbol: str) -> str:
    value = symbol.strip().upper()
    if not SYMBOL_RE.fullmatch(value):
        raise ProviderError("INVALID_SYMBOL", "미국 주식 티커를 입력해 주세요. 예: AAPL, NVDA, BRK-B", 422)
    return value


def bars_from_frame(frame: Any) -> tuple[list[Bar], int]:
    """Preserve provider session labels; do not convert midnight to UTC dates."""
    required = {"Close", "Volume"}
    if frame is None or frame.empty or not required.issubset(frame.columns):
        raise ProviderError("NO_DATA", "조회 가능한 일봉이 없습니다. 티커와 데이터 제공처 상태를 확인해 주세요.", 404)
    result: list[Bar] = []
    dropped = 0
    for timestamp, row in frame.iterrows():
        try:
            close, volume = float(row["Close"]), float(row["Volume"])
            split, dividend = float(row.get("Stock Splits", 0)), float(row.get("Dividends", 0))
            split = split if math.isfinite(split) else 0.0
            dividend = dividend if math.isfinite(dividend) else 0.0
            result.append(Bar(timestamp.strftime("%Y-%m-%d"), close, volume, split, dividend))
        except (ValueError, TypeError, OverflowError):
            dropped += 1
    result.sort(key=lambda b: b.date)
    try:
        validate_bars(result)
    except ValueError as exc:
        raise ProviderError("INVALID_PROVIDER_DATA", "시세 날짜가 중복되어 안전하게 계산할 수 없습니다.") from exc
    if not result:
        raise ProviderError("NO_VALID_DATA", "유효한 수정종가를 확보하지 못했습니다.", 404)
    # Missing/invalid sessions must not be silently bridged into '1D' returns.
    if dropped:
        raise ProviderError("INCOMPLETE_PROVIDER_DATA", "누락되거나 잘못된 일봉이 있어 계산을 중단했습니다. 데이터 제공처 확인이 필요합니다.")
    return result, dropped


class YahooProvider:
    """One-process cache; fail explicitly, or use clearly labeled <=7-day cache."""
    def __init__(self, cache_dir: Path) -> None:
        self.cache_dir = cache_dir
        self.lock = threading.Lock()

    def _read_cache(self, symbol: str) -> dict[str, Any] | None:
        path = self.cache_dir / f"{symbol}.json"
        try:
            if path.stat().st_size > 4_000_000:
                return None
            data = json.loads(path.read_text(encoding="utf-8"))
            if data["version"] != CACHE_VERSION or data["symbol"] != symbol:
                return None
            bars = [Bar(**row) for row in data["bars"]]
            validate_bars(bars)
            if not bars:
                return None
            data["parsed_bars"] = bars
            stamp = datetime.fromisoformat(data["fetched_at"])
            if stamp.tzinfo is None:
                return None
            data["age_seconds"] = (datetime.now(timezone.utc) - stamp).total_seconds()
            return data
        except (OSError, ValueError, KeyError, TypeError):
            return None

    def load(self, raw_symbol: str, as_of: date) -> tuple[list[Bar], dict[str, Any]]:
        symbol = normalize_symbol(raw_symbol)
        with self.lock:
            cache = self._read_cache(symbol)
            if cache and cache["as_of"] == as_of.isoformat() and 0 <= cache["age_seconds"] < 3600:
                return cache["parsed_bars"], self._meta(cache, "CACHE", [])
            try:
                fresh = self._fetch(symbol, as_of)
            except ProviderError:
                if cache and 0 <= cache["age_seconds"] <= 7 * 86400:
                    return cache["parsed_bars"], self._meta(cache, "STALE_CACHE", [
                        "시세 갱신에 실패하여 이전 저장 데이터를 표시합니다. 수집 시각과 마지막 거래일을 확인하세요."
                    ])
                raise
            warnings: list[str] = []
            try:
                self.cache_dir.mkdir(parents=True, exist_ok=True)
                target = self.cache_dir / f"{symbol}.json"
                temp = target.with_suffix(".tmp")
                temp.write_text(json.dumps(fresh, ensure_ascii=False, allow_nan=False), encoding="utf-8")
                os.replace(temp, target)
            except OSError:
                warnings.append("로컬 캐시 저장에 실패했습니다. 화면 데이터는 이번 조회 결과입니다.")
            return [Bar(**row) for row in fresh["bars"]], self._meta(fresh, "FETCHED", warnings)

    def _meta(self, data: dict[str, Any], status: str, warnings: list[str]) -> dict[str, Any]:
        return {
            "provider": "Yahoo Finance via yfinance",
            "currency": data["currency"],
            "exchange": data.get("exchange", "US"),
            "fetched_at": data["fetched_at"],
            "cache_status": status,
            "warnings": warnings,
        }

    def _fetch(self, symbol: str, as_of: date) -> dict[str, Any]:
        try:
            import yfinance as yf
        except ImportError as exc:
            raise ProviderError("DEPENDENCY_MISSING", "yfinance 설치가 필요합니다. 설치 스크립트를 다시 실행해 주세요.", 503) from exc
        try:
            ticker = yf.Ticker(symbol)
            frame = ticker.history(
                start=(as_of - timedelta(days=1260)).isoformat(),
                end=as_of.isoformat(), interval="1d", auto_adjust=True,
                actions=True, repair=False, timeout=15, raise_errors=True,
            )
            bars, _ = bars_from_frame(frame)
            metadata = ticker.history_metadata or {}
            currency = str(metadata.get("currency", "")).upper()
            tz = str(metadata.get("exchangeTimezoneName", ""))
            instrument = str(metadata.get("instrumentType", "")).upper()
            if currency != "USD" or tz != "America/New_York":
                raise ProviderError("UNSUPPORTED_MARKET", "첫 버전은 미국 시장 USD 일봉만 지원합니다. 종목·거래소 메타데이터를 확인해 주세요.", 422)
            if instrument and instrument not in {"EQUITY", "ETF"}:
                raise ProviderError("UNSUPPORTED_INSTRUMENT", "첫 버전은 미국 주식·ETF만 지원합니다.", 422)
            bars = [bar for bar in bars if bar.date < as_of.isoformat()]
            if len(bars) < 2:
                raise ProviderError("INSUFFICIENT_DATA", "분석에 필요한 완료 일봉이 부족합니다.", 404)
            return {
                "version": CACHE_VERSION, "symbol": symbol,
                "as_of": as_of.isoformat(),
                "fetched_at": datetime.now(timezone.utc).isoformat(),
                "currency": currency,
                "exchange": str(metadata.get("exchangeName", "US")),
                "bars": [asdict(b) for b in bars],
            }
        except ProviderError:
            raise
        except Exception as exc:
            # Log class only; no tokens, credentials or untrusted provider message.
            kind = type(exc).__name__
            log.warning("Market fetch failed: symbol=%s type=%s", symbol, kind)
            if "RateLimit" in kind:
                raise ProviderError("RATE_LIMITED", "데이터 제공처의 요청 제한에 걸렸습니다. 자동 재시도는 하지 않습니다. 잠시 후 다시 조회해 주세요.", 429) from exc
            raise ProviderError("DATA_PROVIDER_ERROR", "실제 시세를 가져오지 못했습니다. 인터넷 연결·티커·데이터 제공처 상태를 확인해 주세요. 가짜 데이터로 대체하지 않습니다.") from exc
