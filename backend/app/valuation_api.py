"""Local API for the decision workbench. Read-only GETs; explicit consent writes.
Non-AI data requests are never silently turned into paid discovery calls.
"""
from __future__ import annotations
import asyncio
from datetime import datetime
from zoneinfo import ZoneInfo
from typing import Literal
from fastapi import Request,Query
from fastapi.responses import JSONResponse
from pydantic import Field,StrictBool,ValidationError
from starlette.concurrency import run_in_threadpool
from .valuation import StrictModel,CalculateRequest,FinancialInput,calculate,compare_peers,defaults
from .fundamentals import FundamentalsStore,FundamentalsError
from .decision import DecisionService,context,digest
from .decision_evidence import review_result, POLICY_VERSION
from .research import ResearchError
from .provider import normalize_symbol
from .local_financials import (LocalImportRequest, import_bundle, displayed_pack, strict_json, MAX_REQUEST_BYTES)

class DataRequest(StrictModel):
    symbol:str=Field(min_length=1,max_length=12)
    allow_public_fetch:StrictBool=False
    refresh:StrictBool=False
    cik:str|None=Field(default=None,min_length=1,max_length=10,pattern=r"^[0-9]{1,10}$")
class ContactRequest(StrictModel):
    email:str=Field(max_length=320)
class InterpretRequest(StrictModel):
    symbol:str=Field(min_length=1,max_length=12)
    calculation:CalculateRequest|None=None
    allow_paid:StrictBool=False
    refresh:StrictBool=False
    inclusions:dict[str,Literal['INCLUDED_BY_USER','NOT_INCLUDED_BY_USER','UNKNOWN']]=Field(default_factory=dict,max_length=8)
class ReviewRequest(StrictModel):
    symbol:str=Field(min_length=1,max_length=12)
    calculation:CalculateRequest|None=None

class PeerRequest(StrictModel):
    target:FinancialInput
    peers:list[FinancialInput]=Field(max_length=3)
class SaveRequest(StrictModel):
    calculation:CalculateRequest

def install_routes(app,root,research):
    store=FundamentalsStore(root);service=DecisionService(root,research)
    def today():return datetime.now(ZoneInfo('America/New_York')).date()
    def check(request):
        if request.headers.get('x-signaldesk-ai')!=research.csrf_token:raise ResearchError('LOCAL_TOKEN_REQUIRED','새로고침 후 다시 시도하세요.',403)
        origin=request.headers.get('origin')
        if origin and origin!=f'{request.url.scheme}://{request.url.netloc}':raise ResearchError('CROSS_ORIGIN_REJECTED','다른 사이트 요청은 허용하지 않습니다.',403)
        if request.headers.get('sec-fetch-site')=='cross-site':raise ResearchError('CROSS_SITE_REJECTED','다른 사이트 요청은 허용하지 않습니다.',403)
    def checked_input(body):
        # The browser cannot upgrade edited/manual data to an official SEC input.
        f=body.financials
        if f.input_kind in ('SEC', 'SEC_LOCAL'):
            filename=('local-' if f.input_kind=='SEC_LOCAL' else '')+f.symbol+'.json'
            saved=store.read(filename) or {};original=saved.get('input') or {}
            keys=['symbol','price','price_date','period_end','revenue','operating_income','cash','debt','shares','net_income','sic']
            if f.input_kind=='SEC_LOCAL':
                keys += ['other_claims','operating_cash_flow','capex','stock_compensation','revenue_growth_yoy']
            received=f.model_dump(mode='json')
            if original and not any(received.get(k)!=original.get(k) for k in keys) and saved.get('missing'):
                raise ResearchError('VALUATION_DATA_GAP','자동 재무에 미확보·분할 기준 문제가 남아 있습니다. 원문을 확인하고 해당 입력값을 수정한 뒤 계산하세요.',422)
            if any(received.get(k)!=original.get(k) for k in keys):
                f=f.model_copy(update={'input_kind':'USER','sources_note':'사용자 수정/입력값: 저장된 재무 입력과 같지 않습니다. '+f.sources_note})
                body=body.model_copy(update={'financials':f})
        return body
    @app.exception_handler(FundamentalsError)
    async def fundamental_error(request,exc):
        return JSONResponse(status_code=exc.status,content={'error':{'code':exc.code,'message':exc.message,
            'diagnostic':getattr(exc,'diagnostic',None),'partial_quote':getattr(exc,'partial_quote',None)}})
    @app.get('/api/v1/decision/state')
    def state(symbol:str=Query(min_length=1,max_length=12)):
        symbol=normalize_symbol(symbol);ctx=context(root,symbol,today())
        pack=displayed_pack(store,symbol);previous=store.read('impact-'+symbol+'.json')
        if previous and previous.get('context_hash')!=ctx['context_hash']:previous=None
        if previous:previous=review_result(previous,source_context=ctx)
        return {'symbol':symbol,'csrf_token':research.csrf_token,'data_settings':store.status(),
            'financial_pack':pack,'context':ctx,'defaults':defaults(),
            'financial_diagnostic':store.read('fetch-diagnostic-'+symbol+'.json',20000),
            'quote_pack':store.read('quote-'+symbol+'.json',40000),
            'history':store.read('history-'+symbol+'.json') or [],'latest_interpretation':previous,
            'api_calls':0,'external_requests':0}
    @app.post('/api/v1/decision/contact')
    def contact(body:ContactRequest,request:Request):
        check(request);store.set_contact(body.email);return store.status()
    @app.post('/api/v1/decision/financials')
    def financials(body:DataRequest,request:Request):
        check(request)
        if not body.allow_public_fetch:raise ResearchError('DATA_CONSENT_REQUIRED','SEC·시세 제공처의 공개 자료 수집 동의가 필요합니다. 유료 AI 호출은 없습니다.',400)
        if not research._active.acquire(blocking=False):raise ResearchError('AI_BUSY','다른 작업이 진행 중입니다. 중복 자료 수집을 시작하지 않았습니다.',409)
        try:return store.load(normalize_symbol(body.symbol),refresh=body.refresh,cik_hint=body.cik)
        finally:research._active.release()
    @app.post('/api/v1/decision/local-financials')
    async def local_financials(request:Request):
        check(request)
        if request.headers.get('content-type','').split(';')[0].strip().lower()!='application/json':
            raise FundamentalsError('LOCAL_CONTENT_TYPE','JSON 요청만 허용합니다.',415)
        raw_length=request.headers.get('content-length')
        if raw_length:
            try:
                if int(raw_length)>MAX_REQUEST_BYTES or int(raw_length)<0:
                    raise FundamentalsError('LOCAL_FILE_TOO_LARGE','파일 요청이 20 MiB 한도를 넘었습니다.',413)
            except ValueError:
                raise FundamentalsError('LOCAL_CONTENT_LENGTH','요청 길이가 유효하지 않습니다.',400) from None
        if not research._active.acquire(blocking=False):
            raise ResearchError('AI_BUSY','다른 작업이 진행 중입니다. 파일 가져오기를 중복 실행하지 않았습니다.',409)
        try:
            chunks=[];size=0
            try:
                async with asyncio.timeout(25):
                    async for chunk in request.stream():
                        size+=len(chunk)
                        if size>MAX_REQUEST_BYTES:
                            raise FundamentalsError('LOCAL_FILE_TOO_LARGE','파일 요청이 20 MiB 한도를 넘었습니다.',413)
                        chunks.append(chunk)
            except TimeoutError:
                raise FundamentalsError('LOCAL_UPLOAD_TIMEOUT','로컬 파일 전송 시간이 초과됐습니다. 기존 자료는 유지합니다.',408) from None
            try:
                payload=strict_json(b''.join(chunks).decode('utf-8-sig'))
                body=LocalImportRequest.model_validate(payload)
            except (UnicodeError,ValidationError) as exc:
                # Do NOT return the potentially large/raw file or Pydantic input values.
                raise FundamentalsError('LOCAL_REQUEST_SCHEMA','파일·티커·가격 입력 형식을 확인하세요. 원문 내용은 오류에 표시하지 않습니다.',422) from None
            return await run_in_threadpool(import_bundle,store,body,today=today())
        finally:
            research._active.release()

    @app.post('/api/v1/decision/calculate')
    def calc(body:CalculateRequest,request:Request):
        check(request)
        try:return calculate(checked_input(body),today=today())
        except ValueError as exc:raise ResearchError('VALUATION_INPUT',str(exc),422) from None
    @app.post('/api/v1/decision/peers')
    def peers(body:PeerRequest,request:Request):
        check(request);return compare_peers(body.target,body.peers)
    @app.post('/api/v1/decision/interpret')
    def interpret(body:InterpretRequest,request:Request):
        check(request);symbol=normalize_symbol(body.symbol)
        calcbody=checked_input(body.calculation) if body.calculation else None
        result=service.analyze(symbol,calcbody,body.allow_paid,body.refresh,body.inclusions,today())
        try:store.save('impact-'+symbol+'.json',result)
        except OSError:result.setdefault('validation_notes',[]).append('설명 저장 실패. 다시 요청하면 추가 비용이 들 수 있습니다.')
        return result
    @app.post('/api/v1/decision/review')
    def review_saved(body:ReviewRequest,request:Request):
        # Read-only local overlay. Do not reserve attempts, save cache or call any provider.
        check(request);symbol=normalize_symbol(body.symbol)
        cb=checked_input(body.calculation) if body.calculation else None
        if cb and cb.financials.symbol!=symbol:
            raise ResearchError('DECISION_SYMBOL_MISMATCH','계산과 근거의 종목이 다릅니다.',422)
        try:val=calculate(cb,today=today()) if cb else None
        except ValueError as exc:raise ResearchError('VALUATION_INPUT',str(exc),422) from None
        ctx=context(root,symbol,today())
        previous=store.read('impact-'+symbol+'.json')
        if previous and previous.get('symbol')!=symbol:previous=None
        report=previous or {'symbol':symbol,'events':[],'risks':[], 'sources':ctx['sources']}
        audit_ctx=ctx if not previous or previous.get('context_hash')==ctx.get('context_hash') else None
        result=review_result(report,val,source_context=audit_ctx)
        result['reviewed_at']=datetime.now(ZoneInfo('UTC')).isoformat()
        result['read_only_review']=True
        result['original_valuation_hash']=report.get('valuation_hash')
        result['valuation_hash']=digest(cb.model_dump(mode='json')) if cb else None
        result['new_api_calls']=0;result['new_external_requests']=0
        result['saved_report_present']=previous is not None
        return result

    @app.post('/api/v1/decision/save')
    def save(body:SaveRequest,request:Request):
        check(request);cb=checked_input(body.calculation)
        try:result=calculate(cb,today=today())
        except ValueError as exc:raise ResearchError('VALUATION_INPUT',str(exc),422) from None
        symbol=cb.financials.symbol;name='history-'+symbol+'.json';history=store.read(name) or []
        identity=digest(cb.model_dump(mode='json'));existing=next((x for x in history if x.get('input_hash')==identity),None)
        if not existing:
            stamp=datetime.now(ZoneInfo('UTC')).isoformat();history.append({'saved_at':stamp,'input_hash':identity,
                'price_date':cb.financials.price_date.isoformat(),'price':cb.financials.price,'period_end':cb.financials.period_end.isoformat(),
                'base_value':result['base']['fair_value'],'verdict':result['verdict_label'],'multiples':result['multiples'],
                'input_kind':cb.financials.input_kind,'model_assumptions':cb.assumptions.model_dump(mode='json'),
                'basis':'USER_SAVED_CURRENT_MODEL_NOT_POINT_IN_TIME_BACKTEST'})
            store.save(name,history[-100:])
        return {'history':history[-100:],'api_calls':0,'note':'저장 당시 모형 비교입니다. 과거 주가에 최신 재무를 대입한 백테스트가 아닙니다.'}

    from .filing_api import install_filing_routes
    install_filing_routes(app, root, research, check, checked_input)
