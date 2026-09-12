"""Explicit import of user-saved SEC JSON. No HTTP client or paid AI calls.

A local file is NOT a verified live SEC response. Metadata, unit, period and CIK
checks establish internal consistency only. Original remote caches are untouched.
"""
from __future__ import annotations
import hashlib
import json
from datetime import date, datetime, timezone, timedelta
from typing import Literal
from pydantic import Field, StrictBool
from .fundamentals import (FundamentalsStore, FundamentalsError, assemble,
                           canonical_cik, finite, iso, validate_issuer, ttm_for_tag, instant, observations, span)
from .provider import normalize_symbol
from .valuation import StrictModel

VERSION = '0.7.2'
SCHEMA = 'signaldesk-sec-local-bundle-1'
MAX_BUNDLE_BYTES = 16 * 1024 * 1024
MAX_REQUEST_BYTES = 20 * 1024 * 1024


class LocalQuote(StrictModel):
    close: float = Field(gt=0, le=1e7)
    date: date


class LocalImportRequest(StrictModel):
    symbol: str = Field(min_length=1, max_length=12)
    bundle_text: str = Field(min_length=2, max_length=MAX_BUNDLE_BYTES)
    allow_local_import: StrictBool = False
    quote_mode: Literal['SAVED', 'MANUAL'] = 'SAVED'
    manual_quote: LocalQuote | None = None


def fail(code, message, status=422):
    raise FundamentalsError(code, message, status)


def _pairs(items):
    obj = {}
    for key, value in items:
        if key in obj:
            fail('LOCAL_JSON_DUPLICATE', 'JSON에 중복 필드명이 있습니다. 임의로 한 값을 선택하지 않았습니다.')
        obj[key] = value
    return obj


def _constant(_):
    fail('LOCAL_JSON_NUMBER', 'NaN·Infinity는 재무 숫자로 허용하지 않습니다.')


def strict_json(text):
    try:
        data = json.loads(text.lstrip('\ufeff'), object_pairs_hook=_pairs, parse_constant=_constant)
    except (ValueError, UnicodeError, RecursionError):
        fail('LOCAL_JSON_INVALID', 'JSON 전체를 읽지 못했습니다. HTML·진단 파일이 아닌 SEC 묶음 파일을 선택하세요.')
    return data


def validated_bundle(text, symbol):
    if len(text.encode('utf-8')) > MAX_BUNDLE_BYTES:
        fail('LOCAL_FILE_TOO_LARGE', 'SEC 묶음 파일은 16 MiB 이하만 허용합니다.', 413)
    data = strict_json(text)
    if not isinstance(data, dict) or data.get('schema') != SCHEMA:
        fail('LOCAL_BUNDLE_REQUIRED', '기업정보와 재무 원자료가 함께 있는 SignalDesk SEC Bundle JSON을 선택하세요. companyfacts만으로 종목 연결을 확정하지 않습니다.')
    if data.get('symbol') != symbol:
        fail('LOCAL_SYMBOL_MISMATCH', '조회 중인 티커와 파일의 티커가 다릅니다. 해당 종목으로 전환한 후 불러오세요.')
    sub, facts = data.get('submission'), data.get('companyfacts')
    if not isinstance(sub, dict) or not isinstance(facts, dict):
        fail('LOCAL_BUNDLE_REQUIRED', 'submission·companyfacts 객체를 모두 확인해야 합니다.')
    cik = canonical_cik(facts.get('cik'))
    validate_issuer(sub, symbol, cik)
    if not isinstance(sub.get('name'), str) or not sub['name'].strip() or len(sub['name']) > 200:
        fail('LOCAL_IDENTITY_REQUIRED', '기업정보 파일의 회사명을 확인하지 못했습니다.')
    if not isinstance(facts.get('entityName'), str) or not facts['entityName'].strip():
        fail('LOCAL_IDENTITY_REQUIRED', '재무 파일의 회사명을 확인하지 못했습니다.')
    sic = str(sub.get('sic', ''))
    if not sic.isdigit() or len(sic) != 4:
        fail('LOCAL_INDUSTRY_REQUIRED', '비금융 기업인지 구분할 SIC 업종 코드가 필요합니다.')
    taxonomies = facts.get('facts')
    if not isinstance(taxonomies, dict) or not isinstance(taxonomies.get('us-gaap'), dict):
        fail('UNSUPPORTED_TAXONOMY', '이번 불러오기는 US-GAAP 비금융 기업 자료를 지원합니다.')
    # Validate all shapes before using the legacy extractor, avoiding unhandled 500s.
    total = 0
    for namespace, tags in taxonomies.items():
        if not isinstance(tags, dict) or len(tags) > 10000:
            fail('LOCAL_FACTS_SCHEMA', '재무 태그 구조가 유효하지 않습니다.')
        for tag, concept in tags.items():
            if not isinstance(concept, dict) or not isinstance(concept.get('units'), dict):
                fail('LOCAL_FACTS_SCHEMA', '재무 태그의 단위 목록을 읽지 못했습니다.')
            for unit, rows in concept['units'].items():
                if not isinstance(rows, list) or len(rows) > 50000:
                    fail('LOCAL_FACTS_SCHEMA', '재무 관측값 목록이 유효하지 않거나 너무 큽니다.')
                total += len(rows)
                if total > 200000:
                    fail('LOCAL_FACTS_LIMIT', '재무 관측값 수가 한도를 넘었습니다.', 413)
                seen = {}
                for r in rows:
                    if not isinstance(r, dict) or not finite(r.get('val')):
                        fail('LOCAL_FACT_VALUE', '유한한 숫자가 아닌 재무 관측값을 발견했습니다. 자동 변환하지 않았습니다.')
                    if not iso(r.get('end')) or not iso(r.get('filed')) or ('start' in r and not iso(r['start'])):
                        fail('LOCAL_FACT_DATE', '재무 관측값의 시작일·종료일·공시일을 확인하세요.')
                    if not isinstance(r.get('accn'), str) or not isinstance(r.get('form'), str):
                        fail('LOCAL_FACTS_SCHEMA', '재무 관측값의 공시 식별자·서식이 유효하지 않습니다.')
                    if r.get('segment'):
                        continue  # existing assembler deliberately excludes segmented facts
                    key = (r.get('start'), r['end'], r['filed'], r['accn'], r['form'])
                    if key in seen and seen[key] != r['val']:
                        fail('LOCAL_FACT_CONFLICT', '같은 태그·기간·공시 식별자에 상충하는 수치가 있습니다.')
                    seen[key] = r['val']
    # Retain only identity fields needed by the financial assembler; no bulk filing index export.
    submission = {k: sub.get(k) for k in ['cik', 'name', 'tickers', 'sic', 'entityType']}
    return facts, submission, cik


def _get_quote(store, req, today):
    if req.quote_mode == 'MANUAL':
        if req.manual_quote is None:
            fail('LOCAL_QUOTE_REQUIRED', '직접 확인한 USD 종가와 가격 기준일을 입력하세요.')
        q = {'close': req.manual_quote.close, 'date': req.manual_quote.date.isoformat(),
             'currency': 'USD', 'basis': 'USER_ENTERED_UNADJUSTED_CLOSE',
             'source': '사용자 직접 입력 · 외부 확인 없음', 'splits': [],
             'note': '가격·주식분할 기준과 주식 종류를 사용자가 확인해야 합니다.'}
        saved_at = None
    else:
        qp = store.read('quote-' + req.symbol + '.json', 40000) or {}
        q = qp.get('quote') if qp.get('symbol') == req.symbol else None
        saved_at = qp.get('generated_at')
        if not isinstance(q, dict):
            fail('LOCAL_QUOTE_REQUIRED', '가치평가용 저장 종가가 없습니다. 직접 입력을 선택해 가격·날짜를 넣으세요. 시세를 자동 요청하지 않았습니다.')
        if q.get('basis') != 'PROVIDER_CLOSE_NO_DIVIDEND_ADJUSTMENT':
            fail('LOCAL_QUOTE_BASIS', '저장 종가의 배당수정 기준을 확인하지 못했습니다. 차트 수정종가로 대체하지 않습니다.')
    d = iso(q.get('date'))
    if not finite(q.get('close')) or not 0 < q['close'] <= 1e7 or not d or d > today or q.get('currency') != 'USD':
        fail('LOCAL_QUOTE_INVALID', '가격·기준일·USD 통화 조건을 확인하세요. 미래 가격은 허용하지 않습니다.')
    splits = q.get('splits', [])
    if not isinstance(splits, list) or any(not isinstance(s, dict) or not iso(s.get('date')) or not finite(s.get('ratio')) or s['ratio'] <= 0 for s in splits):
        fail('LOCAL_QUOTE_SPLITS', '저장 가격의 주식분할 기록 형식이 유효하지 않습니다.')
    q = {k:q[k] for k in ['close','date','currency','basis','source','url','splits','note'] if k in q}
    return q, saved_at


def _audit_periods(pack, cutoff):
    ref = pack['facts']['revenue']
    for key, metric in pack['facts'].items():
        if not metric:
            continue
        for row in metric['facts']:
            if not finite(row.get('val')) or not iso(row.get('filed')) or iso(row['filed']) > cutoff:
                fail('LOCAL_PERIOD_AUDIT', '선택한 관측값의 숫자·공시일이 기준일 조건에 맞지 않습니다.')
        if key in ['revenue','operating_income','net_income','operating_cash_flow','capex','stock_compensation']:
            if metric['period_end'] != ref['period_end'] or metric['period_start'] != ref['period_start']:
                fail('LOCAL_PERIOD_AUDIT', '최근 12개월 지표의 기간이 서로 다릅니다. 혼합하지 않았습니다.')
            days = (iso(metric['period_end']) - iso(metric['period_start'])).days + 1
            if not 345 <= days <= 380:
                fail('LOCAL_PERIOD_AUDIT', '최근 12개월 지표의 기간 길이가 유효하지 않습니다.')
            if metric['method'] == 'FY_PLUS_YTD_MINUS_PRIOR_YTD':
                annual, current, prior = metric['facts']
                if (iso(current['start']) - iso(annual['end'])).days != 1:
                    fail('LOCAL_PERIOD_AUDIT', '연간 자료와 당해 누적 자료 사이에 공백·겹침이 있습니다.')
            summed = sum(row['val'] * row['sign'] for row in metric['facts']) / 1e6
            if abs(summed - metric['value']) > 1e-5:
                fail('LOCAL_PERIOD_AUDIT', '원문 수치와 최근 12개월 산식을 다시 확인하세요.')


def quarter_crosscheck(facts, metric, cutoff):
    """Independent 4-quarter check when direct quarters + FY-minus-9m exist.
    Never reconcile different reported values silently or call a difference rounding.
    """
    if not metric or not metric.get('facts'):
        return {'status':'NOT_AVAILABLE'}
    tags={x['tag'] for x in metric['facts']}
    if len(tags)!=1:
        return {'status':'NOT_AVAILABLE'}
    rows=observations(facts,next(iter(tags)),'USD',cutoff)
    quarters=[{'start':r['start'],'end':r['end'],'value':r['val']/1e6,'basis':'REPORTED_QUARTER'} for r in rows if 65<=span(r)<=110]
    for annual in [r for r in rows if 345<=span(r)<=380]:
        ytds=[r for r in rows if r.get('start')==annual['start'] and 250<=span(r)<=295 and 65<=(iso(annual['end'])-iso(r['end'])).days<=110]
        if ytds:
            nine=max(ytds,key=lambda r:r['filed'])
            quarters.append({'start':(iso(nine['end'])+timedelta(days=1)).isoformat(),'end':annual['end'],
                'value':(annual['val']-nine['val'])/1e6,'basis':'ANNUAL_MINUS_NINE_MONTHS'})
    pieces=[];cursor=metric['period_end']
    for _ in range(4):
        candidates=[q for q in quarters if q['end']==cursor]
        if not candidates:return {'status':'NOT_AVAILABLE'}
        # Prefer a reported standalone quarter over deriving the same period.
        chosen=next((q for q in candidates if q['basis']=='REPORTED_QUARTER'),candidates[0])
        pieces.append(chosen);cursor=(iso(chosen['start'])-timedelta(days=1)).isoformat()
    if pieces[-1]['start']!=metric['period_start']:return {'status':'NOT_AVAILABLE'}
    total=sum(q['value'] for q in pieces);difference=round(total-metric['value'],6)
    return {'status':'MATCH' if abs(difference)<1e-5 else 'SOURCE_DIFFERENCE',
        'four_quarter_sum':total,'selected_ttm':metric['value'],'difference_million_usd':difference,
        'quarters':list(reversed(pieces)),
        'note':'차이의 원인이 반올림·수정공시·원자료 불일치 중 무엇인지는 확인하지 않았습니다. 선택 산식은 FY+현재 누적−전년 동기 누적이며 원자료를 고치지 않습니다.'}


def import_bundle(store: FundamentalsStore, req: LocalImportRequest, *, today=None):
    """Only final valid pack is written to local-SYMBOL.json, never remote caches."""
    if not req.allow_local_import:
        fail('LOCAL_IMPORT_CONSENT', '로컬 파일을 현재 재무 입력에 반영하는 데 동의해 주세요.', 400)
    symbol = normalize_symbol(req.symbol)
    req = req.model_copy(update={'symbol': symbol})
    today = today or date.today()
    facts, submission, cik = validated_bundle(req.bundle_text, symbol)
    quote, quote_saved_at = _get_quote(store, req, today)
    cutoff = iso(quote['date'])
    try:
        pack = assemble(facts, submission, quote, symbol, cutoff)
        _audit_periods(pack, cutoff)
    except FundamentalsError:
        raise
    except (ValueError, TypeError, KeyError, AttributeError, OverflowError, RecursionError):
        fail('LOCAL_ASSEMBLY_FAILED', '저장 JSON에서 기간을 맞춘 재무 수치를 구성하지 못했습니다. 기존 저장본은 유지했습니다.')
    stamp = datetime.now(timezone.utc).isoformat()
    pack['input'].update(input_kind='SEC_LOCAL', share_basis_checked=False, claims_checked=False,
        sources_note=f'사용자 제공 SEC JSON · 자동 SEC 접근 복구 아님. CIK {cik}; 금액 백만 USD·주식 백만 주; TTM {pack["input"]["period_end"]}. 선택 관측값 출처는 조회 기록 참조.')
    pack.update(import_version=VERSION, import_mode='USER_SAVED_SEC_JSON',
        source_verified_online=False, external_requests=0, openai_calls=0, cache_hit=False,
        generated_at=stamp, financials_asof=cutoff.isoformat())
    pack['retrieval'] = {'diagnostic_version': VERSION, 'generated_at': stamp, 'symbol': symbol,
        'result': 'LOCAL_IMPORTED', 'api_calls': 0, 'openai_calls': 0, 'sec_request_count': 0,
        'yahoo_loader_calls': 0, 'external_requests': 0, 'automatic_retries': 0,
        'steps': [{'stage':'LOCAL_SEC_BUNDLE','outcome':'OK','http_status':None},
                  {'stage':'VALUATION_QUOTE','outcome':'CACHE_NO_REQUEST' if req.quote_mode=='SAVED' else 'USER_INPUT','http_status':None}]}
    pack['local_provenance'] = {'bundle_sha256':hashlib.sha256(req.bundle_text.encode('utf-8')).hexdigest(),
        'quote_mode':req.quote_mode, 'quote_saved_at':quote_saved_at,
        'latest_selected_filing':max(r['filed'] for m in pack['facts'].values() if m for r in m['facts']),
        'price_cutoff':cutoff.isoformat(),
        'notice':'파일 내용의 CIK·티커·단위·기간 일치 확인입니다. 파일 출처 진위·최신 공시 전량 확보를 독립 검증하지 않았습니다.'}
    warnings = [
        '로컬 JSON 불러오기입니다. SEC 403 자동 수집 문제를 해결하거나 최신 자료로 갱신한 결과가 아닙니다.',
        '파일을 받은 시각·불러온 시각은 공시일과 다릅니다. 가격 기준일 이후 공시는 계산에서 제외합니다.',
        '현금은 현금·현금성자산 태그만 사용하며 투자증권을 자동 합산하지 않습니다.',
        '리스·보증·우선주·기타 청구권의 포함 여부와 주식분할 기준은 별도 검토가 필요합니다.',
    ]
    if (today-cutoff).days > 7:
        warnings.append('보관 가격이 7일 이상 지났습니다. 최신 가격으로 표시하지 않으며 최종 평가를 보류합니다.')
    if req.quote_mode=='MANUAL':
        warnings.append('직접 입력 가격에는 자동 주식분할·통화·주식 종류 검증이 없습니다.')
    pack['warnings'] = warnings + pack['warnings']
    pack['source_consistency']={k:quarter_crosscheck(facts,pack['facts'].get(k),cutoff) for k in ['revenue','operating_income','net_income']}
    for key, check in pack['source_consistency'].items():
        if check.get('status')=='SOURCE_DIFFERENCE':
            pack['warnings'].append(f'{key}: 누적값 기반 TTM과 개별 분기 합계 사이에 {check["difference_million_usd"]:+g}백만 USD 차이가 있습니다. 차이 원인은 미확인이고 원자료를 수정하지 않았습니다.')
    pack['supplemental_facts'] = {}
    if pack['input'].get('capex') is None:
        broader = ttm_for_tag(facts,'PaymentsToAcquireProductiveAssets',cutoff,cik,pack['input']['period_end'])
        if broader:
            broader['note'] = '유형자산 외 소프트웨어·무형자산 등이 포함될 수 있어 기존 설비투자 칸과 동일 항목으로 자동 치환하지 않았습니다.'
            pack['supplemental_facts']['productive_assets_spend'] = broader
        pack['warnings'].append('설비투자 입력은 현재 태그 정의에서 미확보로 남았습니다. 영업현금흐름−설비투자 지표를 임의로 계산하지 않습니다.')
    leases = instant(facts,['OperatingLeaseLiability'],'USD',cutoff,cik,pack['input']['period_end'])
    if leases:
        leases['note'] = '운영리스 부채 참고값입니다. 현금흐름·부채 정의의 일관성 검토 없이 기존 부채에 자동 가산하지 않습니다.'
        pack['supplemental_facts']['operating_lease_liability'] = leases
    try:
        store.save('local-' + symbol + '.json', pack)
    except (OSError, ValueError):
        fail('LOCAL_IMPORT_SAVE', '로컬 저장에 실패했습니다. 파일 권한·저장 공간을 확인하세요.', 500)
    return pack


def displayed_pack(store, symbol):
    """Read only; choose last imported/fetched record, preserving source type."""
    choices = [store.read(symbol+'.json'), store.read('local-'+symbol+'.json')]
    choices = [p for p in choices if isinstance(p,dict) and p.get('symbol')==symbol and isinstance(p.get('input'),dict)]
    return max(choices,key=lambda p:p.get('generated_at','')) if choices else None
