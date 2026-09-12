"""Decision 0.7.3: provenance gate and read-only review, NOT a fact verifier.

A saved AI description/URL is a research lead, not a source excerpt. The current
reader supplies schedule excerpts only. It supplies no risk-document excerpts;
therefore archived risk assertions are quarantined rather than re-prompted.
All functions are pure: no file, HTTP, API, clock, or database access.
"""
from __future__ import annotations
from copy import deepcopy
import math
import re

POLICY_VERSION = 'decision-evidence-0.7.3'
_SCHEDULE_BASIS = 'LOCAL_TEXT_DATE_CANDIDATE'


def _list(value):
    return value if isinstance(value, list) else []


def _dict(value):
    return value if isinstance(value, dict) else {}


def _number(value):
    return isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(value)


def source_status(source):
    """Presence/provenance only. Does not establish truth, officiality or recency."""
    s = _dict(source)
    if not isinstance(s.get('text'), str) or not s['text'].strip():
        return 'NO_EXCERPT'
    if s.get('basis') != _SCHEDULE_BASIS:
        return 'PROVENANCE_NOT_ADMITTED'
    return 'SCHEDULE_EXCERPT_ONLY'


def _refs(item, key):
    return [x for x in _list(_dict(item).get(key)) if isinstance(x, str)]


def admitted_context(ctx):
    """Construct model input WITHOUT the withheld AI statements or their titles."""
    ctx = _dict(ctx)
    sources = [deepcopy(s) for s in _list(ctx.get('sources'))
               if isinstance(s, dict) and isinstance(s.get('id'), str)
               and source_status(s) == 'SCHEDULE_EXCERPT_ONLY']
    ids = {s['id'] for s in sources}
    by_id = {s['id']: s for s in sources}
    events = []
    for e in _list(ctx.get('events')):
        if not isinstance(e, dict):
            continue
        refs = [ref for ref in _refs(e, 'source_ids') if ref in ids]
        if not refs or e.get('category') not in ('EARNINGS', 'CONFERENCE'):
            continue
        event = deepcopy(e)
        event['source_ids'] = refs
        # Use only the actual source excerpt; never the previous AI's fact field.
        event['fact'] = '\n'.join(by_id[ref]['text'] for ref in refs)[:1600]
        event['calendar_only'] = True
        events.append(event)
    return {
        'symbol': ctx.get('symbol'), 'research_date': ctx.get('research_date'),
        'events': events, 'risks': [], 'sources': sources,
        'context_hash': ctx.get('context_hash'), 'evidence_policy': POLICY_VERSION,
        'withheld_counts': {'events': len(_list(ctx.get('events'))) - len(events),
                            'risks': len(_list(ctx.get('risks')))},
        'limitations': [
            'Provided schedule excerpts are not independently verified or updated.',
            'No risk source text is supplied by the current decision context adapter.',
            'No risk statements are sent for rewriting; missing evidence is not absence of risk.',
            'Context-derived year candidates MUST NOT become confirmed event years.',
        ],
    }


def numerical_brief(valuation):
    """Useful historical/model observations, not investment recommendations."""
    v = _dict(valuation); f = _dict(v.get('financials'))
    reverse = _dict(v.get('reverse')); base = _dict(v.get('base'))
    a = _dict(v.get('assumptions'))
    margin = (f['operating_income'] / f['revenue'] if
              _number(f.get('operating_income')) and _number(f.get('revenue')) and f['revenue'] > 0 else None)
    implied = reverse.get('growth') if reverse.get('status') == 'SOLVED' else None
    years = reverse.get('years')
    multiple = None
    if _number(implied) and _number(years) and -1 < implied <= 1 and 1 <= years <= 20:
        multiple = (1 + implied) ** years
    return {
        'basis': 'EXISTING_CALCULATION_NOT_NEW_VERIFICATION',
        'symbol': f.get('symbol') or v.get('symbol'), 'price': f.get('price'),
        'price_date': f.get('price_date'), 'period_end': f.get('period_end'),
        'historical_revenue_growth_yoy': f.get('revenue_growth_yoy'),
        'historical_operating_margin': margin, 'implied_revenue_cagr': implied,
        'years': years, 'required_revenue_multiple': multiple,
        'base_growth': base.get('growth'), 'base_value': base.get('fair_value'),
        'terminal_value_share': base.get('terminal_weight'),
        'discount_rate': a.get('discount_rate'),
        'sensitivity_present': bool(_dict(v.get('sensitivity')).get('values')),
        'consensus_available': any(_dict(x).get('kind') == 'CONSENSUS' and
             _dict(x).get('status') not in ('NOT_AVAILABLE', None) for x in _list(v.get('references'))),
        'guidance_available': any(_dict(x).get('kind') == 'GUIDANCE' and
             _dict(x).get('status') not in ('NOT_AVAILABLE', None) for x in _list(v.get('references'))),
        'decision_ready': bool(v.get('decision_ready')),
        'notes': [
            '과거 12개월 성장과 향후 여러 해의 성장 요구는 다른 기간입니다. 과거 성장으로 미래를 보장하지 않습니다.',
            '역산 성장률은 마진·재투자·할인율·장기 가정·주식 수를 고정한 모형 조건이며 시장 예상치가 아닙니다.',
            '할인율 민감도 표가 있다는 것과 선택한 할인율에 근거가 있다는 것은 다릅니다.',
            '이 점검은 업로드 재무의 진위·범위·최신성을 새로 검증하지 않습니다.',
        ],
    }


def _category(item, source_by_id):
    # Do not infer from the AI title. Use the admitted source excerpt itself.
    text = ' '.join(source_by_id[r]['text'] for r in _refs(item, 'evidence_ids')
                    if r in source_by_id).lower()
    if re.search(r'earnings\s+call', text) and 'scheduled' in text:
        return 'EARNINGS'
    if re.search(r'conference|keynote|fireside', text):
        return 'CONFERENCE'
    return None


def review_result(report, valuation=None, *, source_context=None):
    """Return a safe display overlay; never mutate/delete the archived report.

    Schedule type-priority is deterministic, not a fresh AI assessment. All risk
    assertions currently require an as-yet-unsupplied primary risk passage and
    claim-level entailment check; keep their original versions in quarantine.
    """
    original = _dict(report)
    # Permit repeated read-side guarding of a previously guarded result without
    # losing quarantine records. Never use a version flag to skip rechecking.
    rows = _list(original.get('sources'))
    sources = [deepcopy(s) for s in rows if isinstance(s, dict)]
    admitted = {s.get('id'): s for s in sources
                if isinstance(s.get('id'), str) and source_status(s) == 'SCHEDULE_EXCERPT_ONLY'}
    events = []; held_events = []
    existing_guard = _dict(original.get('evidence_review'))
    for item in _list(existing_guard.get('quarantined_events')):
        if isinstance(item, dict): held_events.append(deepcopy(item))
    for e in _list(original.get('events')):
        if not isinstance(e, dict): continue
        refs = [r for r in _refs(e, 'evidence_ids') if r in admitted]
        candidate = dict(e, evidence_ids=refs)
        category = _category(candidate, admitted)
        if not refs or not category:
            held_events.append({'event_id': e.get('event_id'), 'title': e.get('event_title') or e.get('event_id'),
                'reason': '원문 일정 발췌 연결 없음 · 이전 AI 해석을 새 사실로 사용하지 않습니다.',
                'original_claim': deepcopy(e), 'status': 'UNVERIFIED_NOT_FALSE'})
            continue
        # No quote supports product, earnings-result or price claims here. Replace
        # all generated schedule commentary with explicitly labeled type-based UI.
        earnings = category == 'EARNINGS'
        event = {k: deepcopy(e.get(k)) for k in ('event_id', 'event_title', 'model_inclusion')}
        event.update(direction='WAITING' if earnings else 'NEUTRAL', importance='HIGH' if earnings else 'LOW',
            reason=('실적·다음 전망을 확인할 일정입니다. 발표 예정 자체는 호재나 실제 실적 개선이 아닙니다.' if earnings else
                    '확보한 원문은 행사 참석·연설 안내입니다. 그 자체로 신규 매출·계약을 확인한 것은 아닙니다.'),
            economic_channel='REVENUE' if earnings else 'NONE', novelty='UNKNOWN',
            novelty_reason='최신 발표·기대 변화는 이 점검에서 확인하지 않았습니다.',
            positive_condition='실제 발표가 기존 성장·수익성 가정을 뒷받침하는 경우 다시 검토합니다.',
            negative_condition='실제 발표가 기존 성장·수익성 가정을 약화시키는 경우 다시 검토합니다.',
            watch='실제 발표 내용과 기존 예상·모형 가정의 차이를 확인하세요.',
            evidence_ids=refs, quantification='NOT_QUANTIFIED',
            uncertainty='문서 발췌 있음 · 연도 문맥 추정/최신 변경 여부는 원래 일정 카드의 상태를 유지합니다.',
            analysis_origin='RULE_BASED_SCHEDULE_NOT_NEW_AI',
            evidence_status='EXCERPT_PRESENT_NOT_ENTAILMENT_VERIFIED')
        if event.get('model_inclusion') not in ('INCLUDED_BY_USER','NOT_INCLUDED_BY_USER','UNKNOWN'):
            event['model_inclusion'] = 'UNKNOWN'
        events.append(event)
    held_risks = [deepcopy(r) for r in _list(existing_guard.get('quarantined_risks')) if isinstance(r, dict)]
    for r in _list(original.get('risks')):
        if not isinstance(r, dict): continue
        held_risks.append({'risk_id': r.get('risk_id'), 'title': r.get('risk_title') or r.get('risk_id'),
            'reason': '관련 위험의 원문 문장·발생/조건부 여부를 검증하지 못했습니다. 사실로 재사용하지 않습니다.',
            'original_claim': deepcopy(r), 'status': 'UNVERIFIED_NOT_FALSE'})
    ctx = _dict(source_context)
    recorded_risks = {r.get('risk_id') for r in held_risks}
    for r in _list(ctx.get('risks')):
        if isinstance(r, dict) and r.get('risk_id') not in recorded_risks:
            held_risks.append({'risk_id': r.get('risk_id'), 'title': r.get('title'),
                'status': 'UNVERIFIED_NOT_FALSE',
                'reason': '저장 AI 설명만 있으며 위험 원문을 검증하지 않았습니다. 새 모델 입력에서 제외했습니다.',
                'original_claim': {'current_state': r.get('fact'), 'evidence_ids': r.get('source_ids', [])}})
    recorded_events = {e.get('event_id') for e in events + held_events}
    admitted_ids = {e.get('event_id') for e in admitted_context(ctx)['events']}
    for e in _list(ctx.get('events')):
        if isinstance(e, dict) and e.get('event_id') not in recorded_events and e.get('event_id') not in admitted_ids:
            held_events.append({'event_id': e.get('event_id'), 'title': e.get('title'),
                'status': 'UNVERIFIED_NOT_FALSE',
                'reason': '해당 사건의 원문 발췌가 없어 이전 AI 해석을 새 모델 입력에서 제외했습니다.',
                'original_claim': {'reason': e.get('fact'), 'evidence_ids': e.get('source_ids', [])}})
    def unique(items, key):
        found = {}; anonymous = []
        for item in items:
            ident = item.get(key)
            if isinstance(ident, str): found[ident] = item
            else: anonymous.append(item)
        return list(found.values()) + anonymous
    held_risks = unique(held_risks, 'risk_id'); held_events = unique(held_events, 'event_id')
    brief = numerical_brief(valuation)
    if valuation is None:
        headline = '재무 기반 가격 계산 전입니다. 원문 보유 상태와 일정만 점검했습니다.'
    elif not _dict(valuation).get('decision_ready'):
        headline = '가정 검토 전 · 평가 보류. 계산된 성과 요구와 미검증 주장을 구분했습니다.'
    else:
        headline = str(_dict(valuation).get('verdict_label') or '입력 가정의 조건부 계산') + ' · 가정의 적절성·뉴스 근거는 별도 검토 대상입니다.'
    growth = brief.get('implied_revenue_cagr')
    limit = (f"같은 모형 조건에서 필요한 매출 성장률은 연 {growth*100:.2f}%입니다. 실제 컨센서스가 아닙니다."
             if _number(growth) else '현재 가격에 필요한 성장률을 하나의 수치로 제시할 계산 근거가 없습니다.')
    if valuation is None and original.get('valuation_hash'):
        limit = '저장 보고서에는 다른 계산 조건이 연결돼 있습니다. 현재 가정의 계산값을 먼저 확인하세요.'
    coverage = [{'id': s.get('id'), 'title': s.get('title'), 'url': s.get('url'),
                 'status': source_status(s), 'basis': s.get('basis'),
                 'source_date': s.get('source_date')} for s in sources]
    result = deepcopy(original)
    # Unsafe free-form conclusions are not retained as the current verdict.
    result.update(events=events, risks=[], assumption_review=[],
        price_reading=headline, market_expectation_limit=limit,
        next_check='원문 일정 카드를 확인하세요. 연도 추정·최신 변경 여부를 확정 정보로 올리지 않습니다.',
        sources=sources, numerical_brief=brief,
        evidence_review={
            'version': POLICY_VERSION, 'new_api_calls': 0, 'new_external_requests': 0,
            'source_count': len(sources), 'excerpt_count': len(admitted),
            'no_excerpt_count': sum(x['status']=='NO_EXCERPT' for x in coverage),
            'risk_claims_quarantined': len(held_risks),
            'quarantined_risks': held_risks, 'quarantined_events': held_events,
            'source_coverage': coverage,
            'note': '원문 보유 여부 점검입니다. 진위·의미 일치·최신성 검증 완료가 아닙니다. 위험을 보류했다는 것은 위험이 없다는 뜻이 아닙니다.',
            'scope': 'DECISION_PANEL_ONLY; original catalyst/risk research remains separately unverified',
        },
        display_mode='LOCAL_EVIDENCE_REVIEW',
        validation_notes=['원문 없이 전달된 이전 AI 주장을 현재 사실·주가 영향 판단에서 분리했습니다. 원래 저장본은 삭제하지 않았습니다.'])
    result['symbol'] = original.get('symbol') or brief.get('symbol') or _dict(source_context).get('symbol')
    return result
