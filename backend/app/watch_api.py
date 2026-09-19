"""Local thesis endpoints. SEC dilution/contact endpoints were removed in 1.3.0."""
from fastapi import Query, Request
from pydantic import BaseModel, ConfigDict, Field, StrictBool, StrictInt
from .thesis_engine import ThesisService
from .provider import normalize_symbol

class DriverRequest(BaseModel):
    model_config = ConfigDict(extra='forbid')
    snapshot_id: str = Field(min_length=20, max_length=128, pattern=r'^[A-Za-z0-9_-]+$')
    allow_paid: StrictBool = False
    refresh: StrictBool = False
    max_paid_calls: StrictInt = Field(default=1, ge=1, le=2)
    reuse_research: StrictBool = False

def install_routes(app, root, research, validate):
    drivers = ThesisService(root, research)
    app.state.stock_drivers = drivers

    @app.get('/api/v1/watch/state')
    def state(symbol: str = Query(min_length=1, max_length=12)):
        symbol = normalize_symbol(symbol)
        return {'symbol': symbol, 'drivers': drivers.cached(symbol),
                'research_draft': drivers.draft(symbol), 'last_thesis_attempt': drivers.last_attempt(symbol),
                'thesis_progress': drivers.progress(symbol), 'csrf_token': research.csrf_token,
                'ai_calls': 0, 'network_requests': 0}

    @app.post('/api/v1/watch/drivers')
    def analyze(body: DriverRequest, request: Request):
        validate(request)
        return drivers.analyze(body.snapshot_id, body.allow_paid, body.refresh,
                               body.max_paid_calls, body.reuse_research)
