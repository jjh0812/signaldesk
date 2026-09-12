"""Deterministic, retrospective daily-bar screening. Not a causal model.

All baselines exclude the event day (strictly trailing 20 observations).
The price input MUST already be adjusted for splits/dividends by the provider.
No model confidence, trading signal, or causal claim is calculated here.
"""
from __future__ import annotations

import math
import statistics
from dataclasses import asdict, dataclass
from datetime import date, timedelta
from typing import Any

WINDOW = 20
Z_THRESHOLD = 3.0
MOVE_THRESHOLD = 0.05
LARGE_MOVE_THRESHOLD = 0.10
VOLUME_THRESHOLD = 2.0
PERIOD_DAYS = {"1mo": 30, "3mo": 90, "6mo": 182, "1y": 365, "3y": 1095}


@dataclass(frozen=True)
class Bar:
    date: str
    close: float
    volume: float
    split: float = 0.0
    dividend: float = 0.0

    def __post_init__(self) -> None:
        date.fromisoformat(self.date)
        if not math.isfinite(self.close) or self.close <= 0:
            raise ValueError("Close must be a finite positive adjusted price.")
        if not math.isfinite(self.volume) or self.volume < 0:
            raise ValueError("Volume must be finite and nonnegative.")
        if not math.isfinite(self.split) or self.split < 0:
            raise ValueError("Split ratio must be finite and nonnegative.")
        if not math.isfinite(self.dividend):
            raise ValueError("Dividend must be finite.")


def finite(value: float | None, digits: int = 8) -> float | None:
    return round(value, digits) if value is not None and math.isfinite(value) else None


def validate_bars(bars: list[Bar]) -> None:
    if any(a.date >= b.date for a, b in zip(bars, bars[1:])):
        raise ValueError("Bars must be strictly ascending with unique session dates.")


def observations(bars: list[Bar], benchmark: list[Bar] | None = None) -> list[dict[str, Any]]:
    """Compute flags using only information up through each input bar.

    The date matching check avoids comparing a multi-session stock move with
    a one-session benchmark move. A gap >4 calendar days is not auto-flagged.
    This is a conservative guard, NOT a complete exchange-calendar audit.
    """
    validate_bars(bars)
    benchmark = benchmark or []
    validate_bars(benchmark)
    benchmark_changes = {
        cur.date: (cur.close / prev.close - 1, prev.date)
        for prev, cur in zip(benchmark, benchmark[1:])
    }
    returns: list[float | None] = [None]
    returns.extend(b.close / a.close - 1 for a, b in zip(bars, bars[1:]))
    result: list[dict[str, Any]] = []
    for i, bar in enumerate(bars):
        r = returns[i]
        prior = returns[max(0, i - WINDOW):i]
        usable = [v for v in prior if v is not None and math.isfinite(v)]
        ready = len(usable) == WINDOW
        mu = statistics.mean(usable) if ready else None
        sigma = statistics.stdev(usable) if ready else None
        z = (r - mu) / sigma if r is not None and sigma is not None and sigma > 1e-8 else None
        prior_bars = bars[max(0, i - WINDOW):i]
        split_nearby = bar.split != 0 or any(b.split != 0 for b in prior_bars)
        vmean = statistics.mean(b.volume for b in prior_bars) if len(prior_bars) == WINDOW else None
        vr = bar.volume / vmean if vmean and not split_nearby else None
        gap = (date.fromisoformat(bar.date) - date.fromisoformat(bars[i-1].date)).days if i else 0
        split_day = bar.split != 0
        eligible = ready and not split_day and gap <= 4 and r is not None
        statistical = bool(eligible and z is not None and abs(z) >= Z_THRESHOLD - 1e-12 and abs(r) >= MOVE_THRESHOLD - 1e-12)
        large = bool(eligible and abs(r) >= LARGE_MOVE_THRESHOLD - 1e-12)
        bm = benchmark_changes.get(bar.date)
        bm_return = bm[0] if bm and i > 0 and bm[1] == bars[i - 1].date else None
        reasons: list[str] = []
        if statistical:
            reasons.append("STATISTICAL_MOVE")
        if large:
            reasons.append("LARGE_DAILY_MOVE")
        if (statistical or large) and vr is not None and vr >= VOLUME_THRESHOLD:
            reasons.append("HIGH_VOLUME")
        notes: list[str] = []
        if not ready:
            notes.append("INSUFFICIENT_BASELINE")
        if split_nearby:
            notes.append("VOLUME_SPLIT_WINDOW")
        if split_day:
            notes.append("SPLIT_DAY_REVIEW")
        if gap > 4:
            notes.append("LONG_DATE_GAP_REVIEW")
        if ready and z is None:
            notes.append("ZERO_BASELINE_VOLATILITY")
        if bm_return is None:
            notes.append("BENCHMARK_UNAVAILABLE")
        result.append({
            **asdict(bar),
            "return_1d": finite(r),
            "mean_20d": finite(mu),
            "volatility_20d": finite(sigma),
            "zscore": finite(z, 4),
            "volume_ratio": finite(vr, 4),
            "benchmark_return": finite(bm_return),
            "benchmark_spread": finite(r - bm_return if r is not None and bm_return is not None else None),
            "baseline_count": len(usable),
            "is_anomaly": statistical or large,
            "direction": "UP" if r is not None and r > 0 else "DOWN" if r is not None and r < 0 else "FLAT",
            "reasons": reasons,
            "notes": notes,
        })
    return result


def build_dashboard(bars: list[Bar], benchmark: list[Bar], *, symbol: str,
                    period: str, as_of: date, meta: dict[str, Any]) -> dict[str, Any]:
    if period not in PERIOD_DAYS:
        raise ValueError("Unsupported period.")
    # Never analyze the current exchange date or a later day, even if returned.
    cutoff = as_of.isoformat()
    bars = [b for b in bars if b.date < cutoff]
    benchmark = [b for b in benchmark if b.date < cutoff]
    if not bars:
        raise ValueError("No completed historical daily bars.")
    all_rows = observations(bars, benchmark)
    start = (as_of - timedelta(days=PERIOD_DAYS[period])).isoformat()
    rows = [row for row in all_rows if row["date"] >= start]
    if not rows:
        raise ValueError("No bars in the selected period.")
    last = rows[-1]
    year_start = (as_of - timedelta(days=365)).isoformat()
    year_bars = [b for b in bars if b.date >= year_start]
    high = max(b.close for b in year_bars)
    low = min(b.close for b in year_bars)
    anomalies = [row for row in rows if row["is_anomaly"]]
    return {
        "symbol": symbol,
        "period": period,
        "meta": {
            **meta,
            "price_basis": "split_dividend_adjusted_close",
            "exchange_timezone": "America/New_York",
            "current_session_excluded": True,
            "requested_start": start,
            "data_start": rows[0]["date"],
            "data_end": rows[-1]["date"],
            "scan_as_of": as_of.isoformat(),
            "ai_enabled": False,
            "cause_status": "NOT_IMPLEMENTED",
        },
        "summary": {
            "last_close": last["close"],
            "last_return": last["return_1d"],
            "range_return": finite(last["close"] / rows[0]["close"] - 1),
            "year_high_close": high,
            "year_low_close": low,
            "from_year_high": finite(last["close"] / high - 1),
            "year_observation_count": len(year_bars),
            "anomaly_count": len(anomalies),
            "up_count": sum(a["direction"] == "UP" for a in anomalies),
            "down_count": sum(a["direction"] == "DOWN" for a in anomalies),
        },
        "bars": rows,
        "anomalies": list(reversed(anomalies)),
        "method": {
            "version": "trailing-daily-v0.1.0",
            "lookback_sessions": WINDOW,
            "zscore_threshold": Z_THRESHOLD,
            "return_threshold": MOVE_THRESHOLD,
            "large_move_threshold": LARGE_MOVE_THRESHOLD,
            "rule": "20 prior returns required; (|return| >= 5% AND |z| >= 3) OR |return| >= 10%",
            "benchmark": "SPY",
            "benchmark_method": "same-session return subtraction; NOT beta- or sector-adjusted",
            "limitations": [
                "Heuristic screening, not calibrated anomaly probability or investment advice.",
                "Current-day bars are always excluded; not a real-time feed.",
                "Data are currently revised adjusted history, not a point-in-time archive.",
                "No complete trading-calendar/missing-session audit in v0.1.",
                "Split-day auto-alerts are suppressed; manual review remains available.",
                "No causal inference, news, filings or LLM analysis in this release.",
            ],
        },
    }
