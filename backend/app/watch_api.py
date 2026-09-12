"""Local same-origin endpoints for thesis research and SEC filing signal checks."""
from fastapi import Query, Request
from pydantic import BaseModel, ConfigDict, Field, StrictBool, StrictInt
from .dilution_watch import DilutionService
from .thesis_engine import ThesisService
from .provider import normalize_symbol
from .research import ResearchError


class DriverRequest(BaseModel):
    model_config = ConfigDict(extra='forbid')
    snapshot_id: str = Field(min_length=20, max_length=128, pattern=r'^[A-Za-z0-9_-]+$')
    allow_paid: StrictBool = False
    refresh: StrictBool = False
    max_paid_calls: StrictInt = Field(default=1, ge=1, le=2)
    reuse_research: StrictBool = False


class ScanRequest(BaseModel):
    model_config = ConfigDict(extra='forbid')
    symbol: str = Field(min_length=1, max_length=12)
    allow_public_fetch: StrictBool = False


class ContactRequest(BaseModel):
    model_config = ConfigDict(extra='forbid')
    email: str = Field(min_length=5, max_length=300)
    allow_save: StrictBool = False


def install_routes(app, root, research, validate):
    dilution, drivers = DilutionService(root), ThesisService(root, research)
    # Exposed for offline dependency-injected tests, not accessible via HTTP.
    app.state.dilution_watch, app.state.stock_drivers = dilution, drivers

    @app.get('/api/v1/watch/state')
    def state(symbol: str = Query(min_length=1, max_length=12)):
        symbol = normalize_symbol(symbol)
        return {'symbol': symbol, 'drivers': drivers.cached(symbol), 'dilution': dilution.cached(symbol),
                'last_sec_attempt': dilution.store.read('attempt-' + symbol + '.json', 4096),
                'research_draft': drivers.draft(symbol), 'last_thesis_attempt': drivers.last_attempt(symbol),
                'thesis_progress': drivers.progress(symbol), 'sec_cooldown': dilution.store.cooldown(),
                'contact_configured': bool(dilution.store.contact()), 'sec_busy': dilution.lock.locked(),
                'csrf_token': research.csrf_token, 'ai_calls': 0, 'network_requests': 0}

    @app.post('/api/v1/watch/contact')
    def contact(body: ContactRequest, request: Request):
        validate(request)
        if not body.allow_save:
            raise ResearchError('CONTACT_CONSENT_REQUIRED', 'SEC 요청 식별용 이메일 저장에 동의하세요.', 400)
        dilution.store.set_contact(body.email)
        return {'contact_configured': True, 'ai_calls': 0, 'network_requests': 0}

    @app.post('/api/v1/watch/drivers')
    def analyze(body: DriverRequest, request: Request):
        validate(request)
        return drivers.analyze(body.snapshot_id, body.allow_paid, body.refresh, body.max_paid_calls, body.reuse_research)

    @app.post('/api/v1/watch/dilution')
    def scan(body: ScanRequest, request: Request):
        validate(request)
        if not research._active.acquire(blocking=False):
            raise ResearchError('AI_BUSY', '다른 작업이 진행 중입니다. 완료 후 SEC를 확인하세요.', 409)
        try:
            return dilution.scan(body.symbol, body.allow_public_fetch)
        finally:
            research._active.release()
