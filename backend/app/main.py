"""Local-only FastAPI API and exported Next.js frontend."""
from __future__ import annotations

import logging
import os
import hashlib
import json
from datetime import datetime
from pathlib import Path
from typing import Literal
from urllib.parse import urlsplit
from zoneinfo import ZoneInfo

from fastapi import FastAPI, HTTPException, Query, Request
from pydantic import BaseModel, ConfigDict, Field, StrictBool
from fastapi.middleware.trustedhost import TrustedHostMiddleware
from fastapi.responses import HTMLResponse, JSONResponse
from fastapi.staticfiles import StaticFiles

from .engine import build_dashboard
from .provider import ProviderError, YahooProvider, normalize_symbol
from .research import ResearchError, ResearchService
from .price_context import build_price_context

ROOT = Path(__file__).resolve().parents[2]
provider = YahooProvider(ROOT / ".cache" / "market")
research = ResearchService(ROOT)
RELEASE_VERSION = "1.2.0"
UI_BUILD_ID = "SD-120-THESIS-ENGINE"
BACKEND_COMPAT_VERSION = "0.6.2"

app = FastAPI(
    title="SignalDesk",
    version=BACKEND_COMPAT_VERSION,
    description="Local US equity research: price anomalies, events, company-specific drivers and bounded SEC dilution signals.",
)
app.add_middleware(TrustedHostMiddleware, allowed_hosts=["127.0.0.1", "localhost", "testserver"])


@app.middleware("http")
async def security_headers(request, call_next):
    response = await call_next(request)
    response.headers["X-Content-Type-Options"] = "nosniff"
    response.headers["Referrer-Policy"] = "same-origin"
    response.headers["X-Frame-Options"] = "DENY"
    if not request.url.path.startswith("/_next/"):
        response.headers["Cache-Control"] = "no-store"
    return response


@app.exception_handler(ProviderError)
async def provider_error_handler(request, exc: ProviderError):
    return JSONResponse(status_code=exc.status, content={"error": {"code": exc.code, "message": exc.message}})


@app.get("/api/health")
def health():
    try:
        frontend_id = json.loads((ROOT / "frontend" / "out" / "build-info.json").read_text(encoding="utf-8")).get("build_id")
    except (OSError, ValueError):
        frontend_id = None
    return {
        "app": "signaldesk",
        "version": BACKEND_COMPAT_VERSION,
        "release_version": RELEASE_VERSION,
        "ui_build_id": UI_BUILD_ID,
        "frontend_build_id": frontend_id,
        "server_pid": os.getpid(),
        "runtime_launch_id": getattr(app.state, "runtime_launch_id", None),
        "project_fingerprint": hashlib.sha256(os.path.normcase(str(ROOT.resolve())).encode("utf-8")).hexdigest()[:16],
        "status": "ok",
        "ai_implemented": True,
        "ai_enabled": research.status()["configured"],
    }


@app.get("/api/v1/market/{ticker}")
def market(ticker: str, period: Literal["1mo", "3mo", "6mo", "1y", "3y"] = Query("1y")):
    symbol = normalize_symbol(ticker)
    as_of = datetime.now(ZoneInfo("America/New_York")).date()
    bars, meta = provider.load(symbol, as_of)
    warnings = list(meta.get("warnings", []))
    benchmark_meta = None
    if symbol == "SPY":
        benchmark, benchmark_meta = bars, dict(meta)
    else:
        try:
            benchmark, benchmark_meta = provider.load("SPY", as_of)
            if benchmark_meta["cache_status"] == "STALE_CACHE":
                warnings.append("SPY 비교 데이터가 이전 저장본입니다. 벤치마크 수집 시각을 확인하세요.")
        except ProviderError:
            benchmark = []
            warnings.append("SPY 데이터를 확보하지 못해 시장 대비 차이는 계산하지 않았습니다.")
    if (as_of - datetime.fromisoformat(bars[-1].date).date()).days > 7:
        warnings.append("가장 최근 일봉이 7일 이상 지났습니다. 거래 중단·상장 상태·제공처 누락 여부를 확인하세요.")
    meta = {**meta, "warnings": warnings, "benchmark_meta": benchmark_meta}
    try:
        dashboard = build_dashboard(bars, benchmark, symbol=symbol, period=period, as_of=as_of, meta=meta)
        dashboard["price_context"] = build_price_context(bars, benchmark, symbol=symbol, as_of=as_of, meta=meta)
        # The quantitative response itself contains NO AI conclusions.
        dashboard["research_snapshot_id"] = research.snapshots.add(dashboard)
        dashboard["meta"]["research_available"] = True
        dashboard["meta"]["cause_status"] = "AVAILABLE_ON_DEMAND"
        dashboard["meta"]["ai_analysis_included"] = False
        dashboard["method"]["limitations"][-1] = "Quant scan contains no causal conclusions; AI research is a separate, manually requested retrospective report."
        return dashboard
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc



@app.exception_handler(ResearchError)
async def research_error_handler(request, exc: ResearchError):
    return JSONResponse(status_code=exc.status, content={"error": {"code": exc.code, "message": exc.message}})


class AnalyzeRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    snapshot_id: str = Field(min_length=20, max_length=128, pattern=r"^[A-Za-z0-9_-]+$")
    event_date: str = Field(pattern=r"^\d{4}-\d{2}-\d{2}$")
    allow_paid: StrictBool = False
    refresh_report: StrictBool = False


@app.get("/api/v1/ai/status")
def ai_status():
    return research.status()


@app.get("/api/v1/ai/cache")
def ai_cached(snapshot_id: str = Query(min_length=20, max_length=128),
              event_date: str = Query(pattern=r"^\d{4}-\d{2}-\d{2}$")):
    # This route NEVER invokes a paid provider.
    return {"result": research.cached(snapshot_id, event_date)}


@app.post("/api/v1/ai/analyze")
def ai_analyze(body: AnalyzeRequest, request: Request):
    validate_ai_request(request)
    return research.analyze(body.snapshot_id, body.event_date, body.allow_paid, body.refresh_report)



def validate_ai_request(request: Request):
    # Custom header + same-origin validation prevent blind browser-origin paid calls.
    if request.headers.get("x-signaldesk-ai") != research.csrf_token:
        raise ResearchError("LOCAL_TOKEN_REQUIRED", "화면을 새로고침한 뒤 다시 시도하세요.", 403)
    origin = request.headers.get("origin")
    if origin and origin != f"{request.url.scheme}://{request.url.netloc}":
        raise ResearchError("CROSS_ORIGIN_REJECTED", "다른 사이트에서 보낸 분석 요청은 허용하지 않습니다.", 403)
    if request.headers.get("sec-fetch-site") == "cross-site":
        raise ResearchError("CROSS_SITE_REJECTED", "다른 사이트에서 보낸 분석 요청은 허용하지 않습니다.", 403)


class PriceAnalyzeRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    snapshot_id: str = Field(min_length=20, max_length=128, pattern=r"^[A-Za-z0-9_-]+$")
    allow_paid: StrictBool = False
    refresh_report: StrictBool = False


@app.get("/api/v1/ai/price/cache")
def price_cached(snapshot_id: str = Query(min_length=20, max_length=128)):
    # Cache inspection only, never a provider request.
    return {"result": research.cached_price(snapshot_id)}


@app.post("/api/v1/ai/price/analyze")
def price_analyze(body: PriceAnalyzeRequest, request: Request):
    validate_ai_request(request)
    return research.analyze_price(body.snapshot_id, body.allow_paid, body.refresh_report)


class OutlookAnalyzeRequest(PriceAnalyzeRequest):
    scope: Literal["catalysts", "risks"]


@app.get("/api/v1/ai/outlook/cache")
def outlook_cached(snapshot_id: str = Query(min_length=20, max_length=128)):
    return research.cached_outlook(snapshot_id)


@app.post("/api/v1/ai/outlook/analyze")
def outlook_analyze(body: OutlookAnalyzeRequest, request: Request):
    validate_ai_request(request)
    return research.analyze_outlook(body.snapshot_id, body.scope, body.allow_paid, body.refresh_report)


# Explicit, non-AI document retrieval. No paid provider call on these routes.
class EvidenceReadRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    symbol: str = Field(min_length=1,max_length=12)
    allow_public_fetch: StrictBool = False

@app.get("/evidence", response_class=HTMLResponse)
def evidence_page():
    return HTMLResponse(Path(__file__).with_name('evidence_page.html').read_text(encoding='utf-8'),
                        headers={"Cache-Control":"no-store","Content-Security-Policy":"default-src 'self'; script-src 'self' 'unsafe-inline'; style-src 'self' 'unsafe-inline'; connect-src 'self'; object-src 'none'; base-uri 'none'; frame-ancestors 'none'"})

@app.get("/api/v1/evidence/sources")
def evidence_sources(symbol: str = Query(min_length=1,max_length=12)):
    from .evidence_store import read_reports,source_candidates,load_bundle
    from .document_reader import DocumentError
    symbol=normalize_symbol(symbol)
    try:
        reports=read_reports(ROOT,symbol)
        return {"symbol":symbol,"sources":source_candidates(reports),"bundle":load_bundle(ROOT,symbol,require_fresh=False),
                "csrf_token":research.csrf_token,"api_calls":0}
    except DocumentError as exc:
        raise ResearchError(exc.code,"로컬 저장 출처를 읽지 못했습니다. 키 파일은 보내지 마세요.",422) from None

@app.post("/api/v1/evidence/read")
def evidence_read(body: EvidenceReadRequest, request: Request):
    from .evidence_store import inspect_sources
    from .document_reader import DocumentError
    validate_ai_request(request)
    symbol=normalize_symbol(body.symbol)
    if not body.allow_public_fetch:
        raise ResearchError("DOCUMENT_CONSENT_REQUIRED","공개 자료 수집 동의가 필요합니다. AI 호출은 없습니다.",400)
    if not research._active.acquire(blocking=False):
        raise ResearchError("AI_BUSY","다른 작업이 진행 중입니다. 이번 요청은 실행하지 않았습니다.",409)
    try:
        return inspect_sources(ROOT,symbol)
    except DocumentError as exc:
        messages={"NO_CACHED_DOCUMENT_LEADS":"저장된 출처를 찾지 못했습니다. 자동 유료 검색은 하지 않았습니다."}
        raise ResearchError(exc.code,messages.get(exc.code,"문서 확인이 중단됐습니다. "+exc.code+" · API 호출 없음"),422) from None
    finally:
        research._active.release()

@app.get("/api/v1/evidence/schedule")
def evidence_schedule(symbol: str = Query(min_length=1,max_length=12)):
    """Read ONLY cached extracted text: no OpenAI, HTTP fetch, DB writes or key reads."""
    from .source_schedule import stored_source_schedule
    from .document_reader import DocumentError
    symbol=normalize_symbol(symbol)
    try:
        return stored_source_schedule(ROOT,symbol,datetime.now(ZoneInfo("America/New_York")).date())
    except DocumentError as exc:
        raise ResearchError(exc.code,"저장 원문을 읽지 못했습니다. 유료 재조사는 실행하지 않았습니다.",422) from None

from .valuation_api import install_routes as install_decision_routes
install_decision_routes(app, ROOT, research)

from .watch_api import install_routes as install_watch_routes
install_watch_routes(app, ROOT, research, validate_ai_request)

# Unrecognized API routes must not fall through to an HTML page.
@app.get("/api/{unmatched:path}")
def api_not_found(unmatched: str):
    raise HTTPException(status_code=404, detail="Unknown API route")


web_dir = ROOT / "frontend" / "out"
if (web_dir / "index.html").is_file():
    app.mount("/", StaticFiles(directory=str(web_dir), html=True), name="frontend")
else:
    @app.get("/", response_class=HTMLResponse)
    def not_built():
        return HTMLResponse("<h1>SignalDesk frontend is not built</h1><p>Run Install-SignalDesk.ps1 or Build-Frontend.ps1.</p>", status_code=503)
