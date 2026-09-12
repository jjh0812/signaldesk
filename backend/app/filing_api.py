"""Same-origin, bounded endpoints for source-first filing review."""
from __future__ import annotations
import asyncio,json
from datetime import datetime
from zoneinfo import ZoneInfo
from fastapi import Request,Query
from pydantic import Field,StrictBool,ValidationError
from starlette.concurrency import run_in_threadpool
from .valuation import StrictModel,CalculateRequest,calculate
from .provider import normalize_symbol
from .research import ResearchError
from .document_reader import DocumentError
from .filing_store import FilingStore,MAX_UPLOAD
from .filing_ai import FilingAI

class ViewRequest(StrictModel):
    symbol:str=Field(min_length=1,max_length=12)
    calculation:CalculateRequest|None=None
class ReadRequest(StrictModel):
    symbol:str=Field(min_length=1,max_length=12)
    source_keys:list[str]=Field(min_length=1,max_length=2)
    allow_public_fetch:StrictBool=False
class FileItem(StrictModel):
    source_key:str=Field(min_length=24,max_length=24,pattern=r'^[a-f0-9]+$')
    filename:str=Field(min_length=1,max_length=200)
    content_base64:str=Field(min_length=4,max_length=8388700)
class ImportRequest(StrictModel):
    symbol:str=Field(min_length=1,max_length=12)
    files:list[FileItem]=Field(min_length=1,max_length=2)
    allow_local_import:StrictBool=False
class AIRequest(ViewRequest):
    allow_paid:StrictBool=False
    expected_corpus_hash:str=Field(min_length=64,max_length=64,pattern=r'^[a-f0-9]+$')

def install_filing_routes(app,root,research,check,checked_input):
    store=FilingStore(root);service=FilingAI(research)
    def calc(body,symbol):
        if not body:return None
        if body.financials.symbol!=symbol:raise ResearchError('FILING_SYMBOL_MISMATCH','가격 계산과 공시 종목이 다릅니다.',422)
        try:return calculate(checked_input(body),today=datetime.now(ZoneInfo('America/New_York')).date())
        except ValueError as exc:raise ResearchError('FILING_CALCULATION',str(exc),422) from None
    @app.get('/api/v1/filing-risk/state')
    def state(symbol:str=Query(min_length=1,max_length=12)):
        result=store.view(normalize_symbol(symbol));result['csrf_token']=research.csrf_token;return result
    @app.post('/api/v1/filing-risk/review')
    def review(body:ViewRequest,request:Request):
        check(request);symbol=normalize_symbol(body.symbol)
        return store.view(symbol,calc(body.calculation,symbol))
    @app.post('/api/v1/filing-risk/read')
    def read(body:ReadRequest,request:Request):
        check(request)
        if not body.allow_public_fetch:raise ResearchError('FILING_CONSENT','SEC 원문 접근 동의가 필요합니다. AI 비용은 없습니다.',400)
        if not research._active.acquire(blocking=False):raise ResearchError('AI_BUSY','다른 작업이 진행 중입니다.',409)
        try:return store.fetch(normalize_symbol(body.symbol),body.source_keys)
        finally:research._active.release()
    @app.post('/api/v1/filing-risk/import')
    async def import_files(request:Request):
        check(request)
        if request.headers.get('content-type','').split(';')[0]!='application/json':raise ResearchError('FILING_TYPE','JSON 파일 전송 요청만 받습니다.',415)
        if not research._active.acquire(blocking=False):raise ResearchError('AI_BUSY','다른 작업이 진행 중입니다.',409)
        try:
            chunks=[];size=0
            try:
                async with asyncio.timeout(25):
                    async for chunk in request.stream():
                        size+=len(chunk)
                        if size>MAX_UPLOAD:raise ResearchError('FILING_SIZE','공시 파일 전송 한도를 넘었습니다.',413)
                        chunks.append(chunk)
            except TimeoutError:raise ResearchError('FILING_UPLOAD_TIMEOUT','파일 전송 시간이 초과됐습니다.',408) from None
            try:
                def no_constant(_):raise ValueError('Nonfinite JSON')
                def unique(pairs):
                    d={}
                    for k,v in pairs:
                        if k in d:raise ValueError('Duplicate key')
                        d[k]=v
                    return d
                body=ImportRequest.model_validate(json.loads(b''.join(chunks),parse_constant=no_constant,object_pairs_hook=unique))
            except (ValueError,ValidationError,UnicodeError):raise ResearchError('FILING_UPLOAD_SCHEMA','파일 전송 형식을 확인하세요. 원문 내용은 오류에 노출하지 않습니다.',422) from None
            if not body.allow_local_import:raise ResearchError('FILING_LOCAL_CONSENT','이 PC 서버에 원문 파일을 저장하는 동의가 필요합니다.',400)
            try:return await run_in_threadpool(store.import_files,normalize_symbol(body.symbol),[x.model_dump() for x in body.files])
            except DocumentError as exc:raise ResearchError('FILING_'+exc.code,'공시 본문 추출을 완료하지 못했습니다. 기존 문서는 유지합니다.',422) from None
        finally:research._active.release()
    @app.post('/api/v1/filing-risk/interpret')
    def interpret(body:AIRequest,request:Request):
        check(request);symbol=normalize_symbol(body.symbol);valuation=calc(body.calculation,symbol)
        report=store.view(symbol,valuation)
        if report['corpus_hash']!=body.expected_corpus_hash:raise ResearchError('FILING_CORPUS_CHANGED','원문이 바뀌었습니다. 무료 원문 결과를 먼저 새로 읽으세요. 유료 요청은 보내지 않았습니다.',409)
        return service.analyze(report,valuation,body.allow_paid,root)
