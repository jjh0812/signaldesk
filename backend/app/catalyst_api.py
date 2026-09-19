"""Forward catalyst API using the existing source/date-validated outlook engine.

GET reads local cache only. POST requires explicit paid consent and same-origin
validation. The research date is today in New York, not a selected historical bar.
No direct SEC HTTP fetch, silent paid retry, price target or trading instruction.
"""
from fastapi import Query, Request
from pydantic import BaseModel, ConfigDict, Field, StrictBool
from .research import ResearchError

class CatalystRequest(BaseModel):
    model_config = ConfigDict(extra='forbid')
    snapshot_id: str = Field(min_length=20, max_length=128, pattern=r'^[A-Za-z0-9_-]+$')
    allow_paid: StrictBool = False
    refresh_report: StrictBool = False

def install_routes(app, root, research, validate):
    @app.get('/api/v1/catalysts/state')
    def state(snapshot_id: str = Query(min_length=20, max_length=128, pattern=r'^[A-Za-z0-9_-]+$')):
        result = research.cached_outlook(snapshot_id)
        # Keep the familiar response contract but expose only this purpose's report.
        return {**result, 'reports': {'catalysts': result.get('reports', {}).get('catalysts')},
                'ai_calls': 0, 'network_requests': 0}

    @app.post('/api/v1/catalysts/analyze')
    def analyze(body: CatalystRequest, request: Request):
        validate(request)
        if not body.allow_paid:
            raise ResearchError('PAID_CONSENT_REQUIRED', '미래 촉매 조사에는 유료 API 사용 동의가 필요합니다.', 400)
        return research.analyze_outlook(body.snapshot_id, 'catalysts', True, body.refresh_report)
