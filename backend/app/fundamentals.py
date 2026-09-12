"""SEC companyfacts + completed-session Yahoo close, explicitly requested.
No API keys, no paid AI, no invented observations. Insufficient/unsupported
facts produce gaps. TTM = FY + current YTD - comparable prior YTD, not 4 YTD sums.
"""
from __future__ import annotations
import hashlib, json, math, os, re, ssl, threading, time
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
import httpx
from .provider import normalize_symbol
from .evidence_store import _safe_path

class FundamentalsError(Exception):
    def __init__(self,code,message,status=422):self.code,self.message,self.status=code,message,status;super().__init__(message)

TAGS={
 'revenue':['RevenueFromContractWithCustomerExcludingAssessedTax','RevenueFromContractWithCustomerIncludingAssessedTax','Revenues','SalesRevenueNet'],
 'operating_income':['OperatingIncomeLoss'],
 'net_income':['NetIncomeLoss','ProfitLoss'],
 'operating_cash_flow':['NetCashProvidedByUsedInOperatingActivities'],
 'capex':['PaymentsToAcquirePropertyPlantAndEquipment'],
 'stock_compensation':['ShareBasedCompensation'],
 'cash':['CashAndCashEquivalentsAtCarryingValue'],
}
ALLOWED_FORMS={'10-K','10-Q','10-K/A','10-Q/A'}

def iso(value):
    try:return date.fromisoformat(value) if isinstance(value,str) else None
    except ValueError:return None

def finite(value):return type(value) in (float,int) and math.isfinite(value)

def observations(facts,tag,unit,cutoff,namespace='us-gaap'):
    rows=facts.get('facts',{}).get(namespace,{}).get(tag,{}).get('units',{}).get(unit,[])
    latest={}
    for r in rows:
        if not isinstance(r,dict):continue
        filed,end,start=iso(r.get('filed')),iso(r.get('end')),iso(r.get('start'))
        if not filed or not end or filed>cutoff or end>cutoff or r.get('form') not in ALLOWED_FORMS or not finite(r.get('val')):continue
        if r.get('segment') or (start and start>end):continue
        key=(r.get('start'),r['end'])
        # Latest filing at cutoff. Companyfacts custom/segment facts are not mixed in.
        if key not in latest or (r['filed'],r.get('accn',''))>(latest[key]['filed'],latest[key].get('accn','')):
            latest[key]=dict(r,tag=tag,namespace=namespace,unit=unit)
    return list(latest.values())

def span(r):return (iso(r['end'])-iso(r['start'])).days+1 if r.get('start') else 0

def evidence(r,cik,sign=1):
    acc=r.get('accn','');url=None
    if re.fullmatch(r'\d{10}-\d{2}-\d{6}',acc):url=f'https://www.sec.gov/Archives/edgar/data/{int(cik)}/{acc.replace("-","")}/{acc}-index.html'
    return {k:r.get(k) for k in ['namespace','tag','unit','start','end','filed','form','accn','val']}|{'sign':sign,'url':url}

def ttm_for_tag(facts,tag,cutoff,cik,end=None):
    rows=[r for r in observations(facts,tag,'USD',cutoff) if 60<=span(r)<=380]
    ends=[end] if end else sorted({r['end'] for r in rows},reverse=True)
    for endpoint in ends:
        at=sorted([r for r in rows if r['end']==endpoint],key=lambda x:(span(x),x['filed']),reverse=True)
        for cur in at:
            days=span(cur)
            if 345<=days<=380:
                return {'value':cur['val']/1e6,'period_end':endpoint,'period_start':cur['start'],
                    'method':'ANNUAL','facts':[evidence(cur,cik)]}
            if not 65<=days<=295:continue
            annuals=sorted([r for r in rows if 345<=span(r)<=380 and 0<=(iso(cur['start'])-iso(r['end'])).days<=8],key=lambda r:r['filed'],reverse=True)
            for annual in annuals:
                priors=[r for r in rows if r['start']==annual['start'] and abs(span(r)-days)<=8 and 345<=(iso(cur['end'])-iso(r['end'])).days<=380]
                if not priors:continue
                prior=max(priors,key=lambda r:r['filed']);value=annual['val']+cur['val']-prior['val']
                return {'value':value/1e6,'period_end':endpoint,'period_start':(iso(prior['end'])+timedelta(days=1)).isoformat(),
                    'method':'FY_PLUS_YTD_MINUS_PRIOR_YTD','facts':[evidence(annual,cik),evidence(cur,cik),evidence(prior,cik,-1)]}
    return None

def ttm(facts,tags,cutoff,cik,end=None):
    found=[v for tag in tags if (v:=ttm_for_tag(facts,tag,cutoff,cik,end))]
    # Latest reporting end outranks taxonomy priority. Do not silently fall back
    # to stale old taxonomy when the firm changed tags.
    return max(found,key=lambda x:x['period_end']) if found else None

def instant(facts,tags,unit,cutoff,cik,end=None,namespace='us-gaap'):
    choices=[]
    for tag in tags:
        rows=[r for r in observations(facts,tag,unit,cutoff,namespace) if not r.get('start') and (end is None or r['end']==end)]
        if rows:
            r=max(rows,key=lambda x:(x['end'],x['filed']));choices.append({'value':r['val']/1e6,'period_end':r['end'],'method':'INSTANT','facts':[evidence(r,cik)]})
    return max(choices,key=lambda x:x['period_end']) if choices else None

def debt_at(facts,cutoff,cik,end):
    # Never sum a total and its component. Debt tagged differently is a visible gap.
    total=instant(facts,['LongTermDebtAndCapitalLeaseObligationsIncludingCurrentMaturities','LongTermDebtCurrentAndNoncurrent'],'USD',cutoff,cik,end)
    coverage='장기부채 총액 태그'
    if not total:
        cur=instant(facts,['LongTermDebtCurrent'],'USD',cutoff,cik,end)
        non=instant(facts,['LongTermDebtNoncurrent','LongTermDebt'],'USD',cutoff,cik,end)
        if cur and non:total={'value':cur['value']+non['value'],'period_end':end,'method':'CURRENT_PLUS_NONCURRENT','facts':cur['facts']+non['facts']};coverage='유동·비유동 장기부채 합'
        elif non:total=non;coverage='비유동 장기부채만 확보 · 유동부채 누락 가능'
    if not total:return None
    short=instant(facts,['ShortTermBorrowings'],'USD',cutoff,cik,end)
    # Short-term debt tags vary. Show what was and wasn't covered; user review required.
    if short:total=dict(total,value=total['value']+short['value'],facts=total['facts']+short['facts']);coverage+=' + 단기차입금'
    total['coverage']=coverage+' · 리스·우선주·기타 청구권 완전성 미검증'
    return total

def assemble(facts,submission,quote,symbol,cutoff):
    cik=str(facts.get('cik') or submission.get('cik') or '')
    if not cik.isdigit():raise FundamentalsError('SEC_IDENTITY','SEC 기업 식별자를 확인하지 못했습니다.')
    if submission.get('cik') is not None and canonical_cik(submission['cik']) != canonical_cik(cik):
        raise FundamentalsError('SEC_CIK_MISMATCH','제출기업과 재무 원자료의 기업 번호가 다릅니다.')
    tickers=[str(t).replace('.','-').upper() for t in submission.get('tickers',[])]
    if symbol not in tickers:raise FundamentalsError('SEC_SYMBOL_MISMATCH','요청 티커와 SEC 제출기업이 일치하지 않습니다.')
    if len(set(tickers))!=1:raise FundamentalsError('MULTIPLE_SHARE_CLASSES','여러 주식 종류가 있는 기업은 가격과 전체 주식 수가 맞지 않을 수 있어 자동 평가를 보류합니다.')
    sic=str(submission.get('sic',''))
    if sic.isdigit() and 6000<=int(sic)<=6999:raise FundamentalsError('UNSUPPORTED_INDUSTRY','은행·보험·REIT에는 별도 모형이 필요합니다. 이 FCFF 자동 평가를 적용하지 않습니다.')
    if 'us-gaap' not in facts.get('facts',{}):raise FundamentalsError('UNSUPPORTED_TAXONOMY','이번 자동 재무 연결은 US-GAAP 비금융 기업부터 지원합니다.')
    revenue=ttm(facts,TAGS['revenue'],cutoff,cik)
    if not revenue:raise FundamentalsError('REVENUE_TTM_MISSING','동일 기간의 최근 12개월 매출을 구성하지 못했습니다. 데이터를 만들어 채우지 않았습니다.')
    end=revenue['period_end'];metrics={'revenue':revenue}
    for key in ['operating_income','net_income','operating_cash_flow','capex','stock_compensation']:
        metrics[key]=ttm(facts,TAGS[key],cutoff,cik,end)
    metrics['cash']=instant(facts,TAGS['cash'],'USD',cutoff,cik,end)
    metrics['debt']=debt_at(facts,cutoff,cik,end)
    metrics['shares']=instant(facts,['EntityCommonStockSharesOutstanding'],'shares',cutoff,cik,namespace='dei') or instant(facts,['CommonStockSharesOutstanding'],'shares',cutoff,cik)
    gaps=[k for k in ['operating_income','cash','debt','shares'] if not metrics.get(k)]
    vals={k:v['value'] if v else None for k,v in metrics.items()}
    warnings=['자동 태그 연결은 원문 재무제표 감사가 아닙니다. 입력값·기간·부채 범위를 검토하세요.',
        '가격 날짜까지 공시된 자료를 사용하지만 같은 날짜의 장후 제출 여부는 구분하지 않았습니다.',
        'reported shares는 시점 주식 수이며 희석 EPS용 가중평균 주식 수가 아닙니다. 미래 주식발행·옵션은 별도 검토하세요.']
    if vals.get('operating_income') is not None and vals['operating_income']<=0:gaps.append('profitable_operating_income_required')
    if vals['revenue']<=0:gaps.append('positive_revenue_required')
    if vals.get('shares') is not None and vals['shares']<=0:gaps.append('positive_shares_required')
    for key in ['cash','debt','capex']:
        if vals.get(key) is not None and vals[key]<0:gaps.append(key+'_invalid_sign')
    if metrics['shares']:
        sharesdate=iso(metrics['shares']['period_end'])
        if (iso(quote['date'])-sharesdate).days>200:gaps.append('stale_share_count')
        relevant_splits=[s for s in quote.get('splits',[]) if sharesdate<iso(s['date'])<=iso(quote['date'])]
        if relevant_splits:gaps.append('split_since_share_count');warnings.append('보고 주식 수 이후 주식분할이 있습니다. 가격·주식 수 기준을 새로 맞춰야 합니다.')
    if metrics['debt']:warnings.append(metrics['debt']['coverage'])
    # YoY is comparable TTM, not a quarter growth compared with full-year sales.
    previous=[]
    for tag in TAGS['revenue']:
        for r in observations(facts,tag,'USD',cutoff):
            if 345<=(iso(end)-iso(r['end'])).days<=380:
                p=ttm(facts,TAGS['revenue'],cutoff,cik,r['end'])
                if p:previous.append(p)
    prior=max(previous,key=lambda x:x['period_end']) if previous else None
    yoy=revenue['value']/prior['value']-1 if prior and prior['value']>0 else None
    if prior:metrics['prior_revenue']=prior
    input_data={'symbol':symbol,'company_name':str(submission.get('name') or facts.get('entityName') or symbol)[:200],
        'price':quote['close'],'price_date':quote['date'],'period_end':end,
        **{k:vals.get(k) for k in ['revenue','operating_income','net_income','cash','debt','shares','operating_cash_flow','capex','stock_compensation']},
        'other_claims':0,'sic':sic,'revenue_growth_yoy':yoy,'input_kind':'SEC',
        'sources_note':f'SEC companyfacts CIK {int(cik)}; USD million; TTM end {end}. 개별 태그 출처는 조회 기록 참조.',
        'share_basis_checked':False,'claims_checked':False}
    return {'symbol':symbol,'status':'PARTIAL' if gaps else 'READY_FOR_REVIEW','input':input_data,'facts':metrics,
        'missing':gaps,'warnings':warnings,'cik':cik,'quote':quote,'financials_asof':cutoff.isoformat(),
        'generated_at':datetime.now(timezone.utc).isoformat(),'api_calls':0,
        'sources':[f'https://data.sec.gov/api/xbrl/companyfacts/CIK{int(cik):010d}.json',f'https://data.sec.gov/submissions/CIK{int(cik):010d}.json'],
        'consensus':{'status':'NOT_AVAILABLE'},'guidance':{'status':'NOT_AVAILABLE'},
        'share_change':{'status':'NOT_CALCULATED','note':'과거 주식 수의 분할·주식 종류 기준을 확정하지 않아 자동 희석률을 만들지 않습니다.'}}

# Retrieval v0.7.1: explicit issuer resolution and private-data-free diagnostics.
FETCH_VERSION = '0.7.1'
TICKER_URL = 'https://www.sec.gov/files/company_tickers.json'


def canonical_cik(value):
    """Only a CIK identifier is accepted; never a URL, API key or ticker guess."""
    if isinstance(value, int) and not isinstance(value, bool):
        value = str(value)
    if not isinstance(value, str) or not re.fullmatch(r'[0-9]{1,10}', value.strip()):
        raise FundamentalsError('SEC_CIK_INVALID', 'CIK는 SEC 기업 번호입니다. 1~10자리 숫자만 입력하세요.', 422)
    number = int(value.strip())
    if number <= 0:
        raise FundamentalsError('SEC_CIK_INVALID', 'CIK는 0보다 큰 SEC 기업 번호여야 합니다.', 422)
    return f'{number:010d}'


def endpoint_info(url):
    if url == TICKER_URL:
        return 'TICKER_DIRECTORY', '티커→기업 번호 목록', url
    if re.fullmatch(r'https://data\.sec\.gov/submissions/CIK[0-9]{10}\.json', url):
        return 'SUBMISSIONS', '제출기업·티커 확인', url
    if re.fullmatch(r'https://data\.sec\.gov/api/xbrl/companyfacts/CIK[0-9]{10}\.json', url):
        return 'COMPANYFACTS', '기업 재무 원자료', url
    raise FundamentalsError('SEC_URL_BLOCKED', '허용한 SEC 공식 JSON 주소 이외에는 요청하지 않습니다.', 422)


def validate_issuer(submission, symbol, requested_cik):
    """CIK is an input hint, not proof: verify it against SEC submissions."""
    if not isinstance(submission, dict):
        raise FundamentalsError('SEC_SUBMISSIONS_SCHEMA', 'SEC 제출기업 자료의 구조를 확인하지 못했습니다.', 502)
    actual = canonical_cik(submission.get('cik'))
    if actual != requested_cik:
        raise FundamentalsError('SEC_CIK_MISMATCH', '요청한 기업 번호와 SEC 제출기업 번호가 다릅니다. 재무를 사용하지 않았습니다.', 422)
    tickers = submission.get('tickers')
    if not isinstance(tickers, list) or not all(isinstance(t, str) for t in tickers):
        raise FundamentalsError('SEC_SUBMISSIONS_SCHEMA', 'SEC 제출기업의 티커 목록을 확인하지 못했습니다.', 502)
    tickers = {t.replace('.', '-').upper() for t in tickers}
    if symbol not in tickers:
        raise FundamentalsError('SEC_SYMBOL_MISMATCH', '입력한 CIK의 SEC 티커가 요청한 종목과 다릅니다. 다른 회사 재무를 섞지 않았습니다.', 422)
    if len(tickers) != 1:
        raise FundamentalsError('MULTIPLE_SHARE_CLASSES', '여러 주식 종류가 있는 기업은 별도 검토가 필요합니다. 자동 평가를 보류합니다.', 422)


class FundamentalsStore:
    def __init__(self, root: Path):
        self.root = root
        self.lock = threading.Lock()
        self.last_request = 0.
        self._local = threading.local()

    def _path(self, name):
        return _safe_path(self.root, '.cache/valuation07/' + name)

    def save(self, name, data):
        path = self._path(name)
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp = path.with_suffix('.tmp-' + os.urandom(4).hex())
        try:
            tmp.write_text(json.dumps(data, ensure_ascii=False, allow_nan=False), encoding='utf-8')
            os.replace(tmp, path)
        finally:
            tmp.unlink(missing_ok=True)

    def read(self, name, maxbytes=20000000):
        p = self._path(name)
        try:
            if not p.is_file() or p.stat().st_size > maxbytes:
                return None
            return json.loads(p.read_text(encoding='utf-8'))
        except (ValueError, OSError):
            return None

    def set_contact(self, email):
        if not isinstance(email, str) or not re.fullmatch(r'[A-Za-z0-9._+\-]{1,128}@[A-Za-z0-9.-]{1,160}\.[A-Za-z]{2,24}', email):
            raise FundamentalsError('SEC_CONTACT_INVALID', 'SEC 자동 접근용 연락 이메일 형식을 확인하세요. API 키는 입력하지 마세요.')
        self.save('sec_contact.json', {'email': email})

    def contact(self):
        c = self.read('sec_contact.json', 2048) or {}
        value = c.get('email', '')
        return value if isinstance(value, str) and re.fullmatch(r'[A-Za-z0-9._+\-]{1,128}@[A-Za-z0-9.-]{1,160}\.[A-Za-z]{2,24}', value) else ''

    def status(self):
        return {'contact_configured': bool(self.contact()), 'api_calls': 0,
                'contact_sent_to_openai': False, 'fetch_version': FETCH_VERSION}

    def _step(self, **step):
        report = getattr(self._local, 'report', None)
        if report is not None:
            report['steps'].append(step)

    def _remember_diagnostic(self, report):
        # Report fields are constructed below. Never store response bodies,
        # headers, raw exception text, user-agent, emails or local paths here.
        try:
            self.save('fetch-diagnostic-' + report['symbol'] + '.json', report)
        except OSError:
            report['diagnostic_saved'] = False
        print('[SIGNALDESK FINANCIALS] ' + json.dumps(report, ensure_ascii=False), flush=True)

    @staticmethod
    def _age(record):
        try:
            return time.time() - datetime.fromisoformat(record['generated_at']).timestamp()
        except (ValueError, KeyError, TypeError):
            return float('inf')

    def get_json(self, url):
        stage, label, public_url = endpoint_info(url)
        email = self.contact()
        if not email:
            raise FundamentalsError('SEC_CONTACT_REQUIRED', '먼저 SEC 연락 이메일을 저장하세요. OpenAI 키와 다르며 결제는 없습니다.', 400)
        with self.lock:
            cooldown = self.read('sec-cooldown.json', 1024) or {}
            remaining = cooldown.get('until', 0)
            if isinstance(remaining, (int, float)) and 0 < remaining - time.time() <= 86400:
                wait = int(remaining - time.time()) + 1
                self._step(stage=stage, url=public_url, outcome='COOLDOWN_NO_REQUEST', wait_seconds=wait)
                raise FundamentalsError('SEC_COOLDOWN', f'SEC 요청 제한 대기 중입니다. 약 {wait}초 뒤 확인하세요. 새 SEC 요청은 보내지 않았습니다.', 429)
            time.sleep(max(0, .30 - (time.monotonic() - self.last_request)))
            self.last_request = time.monotonic()
            started = time.monotonic()
            info = dict(stage=stage, url=public_url, outcome='STARTED', http_status=None)
            try:
                # Explicit identification; TLS verification stays on. No proxy
                # rotation, impersonation, redirect following or automatic retry.
                with httpx.Client(timeout=httpx.Timeout(30, connect=10), follow_redirects=False, trust_env=False) as client:
                    with client.stream('GET', url, headers={
                        'User-Agent': f'SignalDesk Research/{FETCH_VERSION} {email}',
                        'Accept': 'application/json',
                    }) as res:
                        info['http_status'] = res.status_code
                        if res.status_code != 200:
                            hints = {
                                403: '접근이 거절됐습니다. 주소 변경·브라우저 위장으로 자동 재시도하지 않습니다.',
                                404: '해당 자료를 찾지 못했습니다. 기업 번호와 자료 지원 여부를 확인하세요.',
                                429: '요청 제한 응답입니다. 대기한 뒤 확인하세요.',
                            }
                            if res.status_code == 429:
                                raw = res.headers.get('retry-after', '')
                                delay = max(60, min(int(raw), 86400)) if raw.isdigit() else 60
                                self.save('sec-cooldown.json', {'until': time.time() + delay})
                            message = f'{label} 단계: SEC HTTP {res.status_code}. ' + hints.get(res.status_code, '정상 JSON 응답을 받지 못했습니다. 자동 재시도하지 않습니다.')
                            raise FundamentalsError('SEC_HTTP_' + str(res.status_code), message, 502)
                        content = bytearray()
                        for chunk in res.iter_bytes():
                            content.extend(chunk)
                            if len(content) > 20_000_000:
                                raise FundamentalsError('SEC_SIZE_LIMIT', f'{label} 단계: SEC 응답이 20MB 제한을 초과했습니다.', 502)
                data = json.loads(content)
                if not isinstance(data, dict):
                    raise ValueError('Expected JSON object')
                info.update(outcome='OK', bytes_received=len(content))
                return data
            except FundamentalsError as exc:
                info.update(outcome='ERROR', error_code=exc.code)
                raise
            except httpx.TimeoutException:
                info.update(outcome='ERROR', error_code='SEC_TIMEOUT')
                raise FundamentalsError('SEC_TIMEOUT', f'{label} 단계: SEC 연결·읽기 시간이 초과됐습니다. 자동 재시도하지 않았습니다.', 502) from None
            except httpx.ConnectError as exc:
                # Inspect only to classify. Never export the exception string.
                cause, seen, tls = exc, set(), False
                while cause is not None and id(cause) not in seen:
                    seen.add(id(cause))
                    if isinstance(cause, ssl.SSLCertVerificationError) or 'CERTIFICATE_VERIFY_FAILED' in str(cause):
                        tls = True
                    cause = cause.__cause__ or cause.__context__
                code = 'SEC_TLS_CERTIFICATE' if tls else 'SEC_CONNECT_FAILED'
                info.update(outcome='ERROR', error_code=code)
                message = '보안 인증서 확인에 실패했습니다. 인증서 검증을 해제하지 않았습니다.' if tls else 'SEC에 연결하지 못했습니다. 네트워크 설정을 확인하세요.'
                raise FundamentalsError(code, f'{label} 단계: {message}', 502) from None
            except httpx.HTTPError:
                info.update(outcome='ERROR', error_code='SEC_TRANSPORT_ERROR')
                raise FundamentalsError('SEC_TRANSPORT_ERROR', f'{label} 단계: 통신 오류가 발생했습니다. 자동 재시도하지 않았습니다.', 502) from None
            except (ValueError, UnicodeError):
                info.update(outcome='ERROR', error_code='SEC_JSON_INVALID')
                raise FundamentalsError('SEC_JSON_INVALID', f'{label} 단계: HTTP 200 응답을 JSON 자료로 읽지 못했습니다. 수치로 대체하지 않았습니다.', 502) from None
            finally:
                info['elapsed_ms'] = round((time.monotonic() - started) * 1000)
                self._step(**info)

    def _issuer_number(self, symbol, cik_hint):
        if cik_hint:
            self._local.report['identity_mode'] = 'USER_CIK_VERIFY_WITH_SEC'
            return canonical_cik(cik_hint)
        # A past successful SEC submission match removes the unnecessary global
        # directory dependency. Revalidate the SEC submission on every fresh load.
        saved = self.read('issuer-' + symbol + '.json', 4096) or {}
        if saved.get('symbol') == symbol and saved.get('verified_by') == 'SEC_SUBMISSIONS':
            try:
                cik = canonical_cik(saved.get('cik'))
                self._local.report['identity_mode'] = 'PREVIOUS_MATCH_REVERIFY_WITH_SEC'
                return cik
            except FundamentalsError:
                pass
        self._local.report['identity_mode'] = 'SEC_TICKER_DIRECTORY'
        tick = self.read('tickers.json')
        today = date.today().isoformat()
        if not isinstance(tick, dict) or tick.get('date') != today or not isinstance(tick.get('data'), dict):
            tick = {'date': today, 'data': self.get_json(TICKER_URL)}
            self.save('tickers.json', tick)
        else:
            self._step(stage='TICKER_DIRECTORY', url=TICKER_URL, outcome='CACHE_NO_REQUEST', http_status=None)
        matches = [r for r in tick['data'].values() if isinstance(r, dict) and str(r.get('ticker', '')).replace('.', '-').upper() == symbol]
        if len(matches) != 1:
            raise FundamentalsError('SEC_TICKER_NOT_FOUND', 'SEC 목록에서 고유한 티커를 확인하지 못했습니다. 확인된 CIK를 입력하거나 지원 범위를 확인하세요.')
        return canonical_cik(matches[0].get('cik_str'))

    def _quote(self, symbol, refresh, loader):
        old = self.read('quote-' + symbol + '.json', 40000)
        if isinstance(old, dict) and old.get('symbol') == symbol and 0 <= self._age(old) < 900 and not refresh:
            quote = old.get('quote')
            if isinstance(quote, dict) and finite(quote.get('close')) and quote['close'] > 0 and iso(quote.get('date')):
                self._step(stage='VALUATION_QUOTE', outcome='CACHE_NO_REQUEST', quote_date=quote['date'])
                return quote
        self._local.report['yahoo_loader_calls'] += 1
        try:
            quote = loader(symbol)
            if not isinstance(quote, dict) or not finite(quote.get('close')) or quote['close'] <= 0 or not iso(quote.get('date')):
                raise FundamentalsError('VALUATION_QUOTE_FAILED', '가치평가용 종가 형식이 유효하지 않습니다.', 502)
            self.save('quote-' + symbol + '.json', {'symbol': symbol, 'generated_at': datetime.now(timezone.utc).isoformat(), 'quote': quote, 'api_calls': 0})
            self._step(stage='VALUATION_QUOTE', outcome='OK', quote_date=quote['date'])
            return quote
        except FundamentalsError as exc:
            self._step(stage='VALUATION_QUOTE', outcome='ERROR', error_code=exc.code)
            raise

    def load(self, symbol, *, refresh=False, quote_loader=None, cik_hint=None):
        symbol = normalize_symbol(symbol)
        hint = canonical_cik(cik_hint) if cik_hint not in (None, '') else None
        filename = symbol + '.json'
        cached = self.read(filename)
        same_identity = not hint or (isinstance(cached, dict) and str(cached.get('cik', '')).lstrip('0') == hint.lstrip('0'))
        if isinstance(cached, dict) and not refresh and same_identity and 0 <= self._age(cached) < 6 * 3600:
            return dict(cached, cache_hit=True)
        report = {'diagnostic_version': FETCH_VERSION, 'symbol': symbol,
                  'generated_at': datetime.now(timezone.utc).isoformat(),
                  'api_calls': 0, 'openai_calls': 0, 'yahoo_loader_calls': 0,
                  'automatic_retries': 0, 'steps': [], 'result': 'RUNNING',
                  'privacy': 'No keys, contact email, headers, response bodies, raw exception text or local paths.',
                  'note': 'This is a retrieval trace, not validation of financial accuracy. Yahoo HTTP subrequests are not counted.'}
        self._local.report = report
        quote = None
        try:
            if not self.contact():
                raise FundamentalsError('SEC_CONTACT_REQUIRED', '먼저 SEC 연락 이메일을 저장하세요. OpenAI 키와 다릅니다.', 400)
            # Preserve the independently obtained quote even if a later SEC step fails.
            quote = self._quote(symbol, refresh, quote_loader or yahoo_completed_quote)
            cik = self._issuer_number(symbol, hint)
            sub_url = f'https://data.sec.gov/submissions/CIK{cik}.json'
            submission = self.get_json(sub_url)
            validate_issuer(submission, symbol, cik)
            self.save('issuer-' + symbol + '.json', {'symbol': symbol, 'cik': cik,
                'verified_by': 'SEC_SUBMISSIONS', 'verified_at': datetime.now(timezone.utc).isoformat(), 'source_url': sub_url})
            facts = self.get_json(f'https://data.sec.gov/api/xbrl/companyfacts/CIK{cik}.json')
            if canonical_cik(facts.get('cik')) != cik:
                raise FundamentalsError('SEC_CIK_MISMATCH', '재무 원자료의 기업 번호가 제출기업과 다릅니다. 계산에 넣지 않았습니다.', 422)
            result = assemble(facts, submission, quote, symbol, iso(quote['date']))
            report['result'] = result['status']
            report['cik'] = cik
            report['missing'] = list(result.get('missing', []))
            report['sec_request_count'] = sum(s.get('http_status') is not None or s.get('outcome') == 'ERROR' and s.get('stage') != 'VALUATION_QUOTE' for s in report['steps'])
            result.update(cache_hit=False, retrieval=report)
            self.save(filename, result)
            self._remember_diagnostic(report)
            return result
        except FundamentalsError as exc:
            report.update(result='FAILED', error_code=exc.code)
            report['sec_request_count'] = sum(s.get('http_status') is not None or s.get('outcome') == 'ERROR' and s.get('stage') != 'VALUATION_QUOTE' for s in report['steps'])
            self._remember_diagnostic(report)
            exc.diagnostic = report
            exc.partial_quote = quote
            raise
        except OSError:
            report.update(result='FAILED', error_code='LOCAL_DATA_STORAGE')
            self._remember_diagnostic(report)
            exc = FundamentalsError('LOCAL_DATA_STORAGE', '로컬 재무 캐시 저장에 실패했습니다. 폴더 권한·저장 공간을 확인하세요.', 500)
            exc.diagnostic, exc.partial_quote = report, quote
            raise exc from None
        except (ValueError, TypeError, KeyError, AttributeError, OverflowError):
            report.update(result='FAILED', error_code='SEC_DATA_SCHEMA')
            self._remember_diagnostic(report)
            exc = FundamentalsError('SEC_DATA_SCHEMA', '받은 SEC 자료의 필수 필드나 구조를 확인하지 못했습니다. 수치를 만들어 채우지 않았습니다.', 502)
            exc.diagnostic, exc.partial_quote = report, quote
            raise exc from None
        finally:
            self._local.report = None


def yahoo_completed_quote(symbol):
    from zoneinfo import ZoneInfo
    today=datetime.now(ZoneInfo('America/New_York')).date()
    try:
        import yfinance as yf
        ticker=yf.Ticker(symbol)
        frame=ticker.history(start=(today-timedelta(days=400)).isoformat(),end=today.isoformat(),interval='1d',
            auto_adjust=False,actions=True,timeout=20,raise_errors=True)
        if frame is None or frame.empty:raise ValueError
        frame=frame[[t.date()<today for t in frame.index]]
        if frame.empty:raise ValueError
        meta=ticker.get_history_metadata()
        currency=meta.get('currency');instrument=meta.get('instrumentType')
        if currency!='USD' or instrument!='EQUITY':
            raise FundamentalsError('QUOTE_TYPE_UNSUPPORTED','USD 일반주식 가격인지 확인하지 못했습니다. 통화·주식 종류를 임의로 가정하지 않습니다.')
        close=float(frame['Close'].iloc[-1]);d=frame.index[-1].date()
        if not finite(close) or close<=0 or (today-d).days>7:raise ValueError
        splits=[{'date':idx.date().isoformat(),'ratio':float(row['Stock Splits'])} for idx,row in frame.iterrows() if finite(float(row.get('Stock Splits',0))) and float(row.get('Stock Splits',0)) not in (0,1)]
        return {'close':close,'date':d.isoformat(),'currency':'USD','basis':'PROVIDER_CLOSE_NO_DIVIDEND_ADJUSTMENT',
            'source':'Yahoo Finance via yfinance','url':f'https://finance.yahoo.com/quote/{symbol}/history/',
            'splits':splits,'note':'완료 일봉의 제공처 Close입니다. 배당수정 종가를 사용하지 않습니다. 실시간 호가가 아닙니다.'}
    except FundamentalsError:raise
    except Exception:raise FundamentalsError('VALUATION_QUOTE_FAILED','가치평가용 완료 일봉의 비배당수정 종가를 확보하지 못했습니다. 기존 차트 수정종가로 대체하지 않았습니다.',502) from None
