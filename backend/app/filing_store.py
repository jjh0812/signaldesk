"""Bounded filing corpus: saved SEC pages or explicitly selected public fetch.
No auto refresh, external fallback, browser impersonation, or paid requests.
"""
from __future__ import annotations
import base64
from datetime import datetime,timezone,date
from html.parser import HTMLParser
import hashlib,json,os,re,time
from pathlib import Path
from urllib.parse import urlsplit
from .evidence_store import _safe_path
from .fundamentals import FundamentalsStore
from .provider import normalize_symbol
from .research import ResearchError
from .document_reader import (checked_url,public_addresses,PinnedHTTPS,DocumentError,parse_isolated,MAX_BYTES)
from .filing_risk import ident,clean,passages_from_pages,render_report

VERSION='filing-risk-0.8.0'
SEC_PATH=re.compile(r'^/Archives/edgar/data/(?P<cik>[0-9]{1,10})/(?P<accn>[0-9]{18})/(?P<file>[A-Za-z0-9_.-]{1,160}\.(?:htm|html|pdf))$')
ALLOWED_FORMS={'10-K','10-Q','10-K/A','10-Q/A'}
MAX_UPLOAD=18*1024*1024


def sec_url(value):
    url=checked_url(value);p=urlsplit(url)
    if p.hostname!='www.sec.gov' or p.query or not SEC_PATH.fullmatch(p.path):
        raise ResearchError('FILING_URL','SEC 공시 원문 주소가 아닙니다. 입력 주소를 외부 요청하지 않았습니다.',422)
    return url,SEC_PATH.fullmatch(p.path)


def timestamp():return datetime.now(timezone.utc).isoformat()


class DEI(HTMLParser):
    def __init__(self):
        super().__init__();self.tags=[];self.current=None;self.parts=[];self.values={}
    def handle_starttag(self,tag,attrs):
        a=dict(attrs);name=a.get('name','').split(':')[-1]
        if tag.lower().startswith('ix:') and name in ('EntityCentralIndexKey','EntityRegistrantName','DocumentType','DocumentPeriodEndDate'):
            self.current=(tag,name);self.parts=[]
    def handle_data(self,data):
        if self.current:self.parts.append(data)
    def handle_endtag(self,tag):
        if self.current and self.current[0]==tag:
            self.values.setdefault(self.current[1],[]).append(clean(''.join(self.parts)));self.current=None;self.parts=[]


def extract_identity(raw,mime,parsed):
    vals={}
    if mime=='text/html':
        d=DEI();d.feed(raw.decode('utf-8',errors='replace'));vals=d.values
    def single(key):
        values=set(vals.get(key,[]))
        if len(values)>1:raise ResearchError('FILING_METADATA_CONFLICT','문서의 기업·기간 메타데이터가 충돌합니다. 저장하지 않았습니다.',422)
        return next(iter(values),None)
    cik=single('EntityCentralIndexKey');form=single('DocumentType');period=single('DocumentPeriodEndDate');company=single('EntityRegistrantName')
    if not cik:
        head=' '.join(p.get('text','') for p in parsed.get('pages',[])[:2])[:30000]
        ciks=set(re.findall(r'\bCIK\s*[:#]?\s*(\d{1,10})\b',head,re.I))
        if len(ciks)==1:cik=ciks.pop()
    if not form:
        head=' '.join(p.get('text','') for p in parsed.get('pages',[])[:2])[:30000]
        m=re.search(r'\bFORM\s+(10-[KQ](?:/A)?)\b',head,re.I)
        if m:form=m[1].upper()
    if cik and str(cik).isdigit():cik=str(int(cik))
    if period:
        try:date.fromisoformat(period)
        except ValueError:period=None
    return {'cik':cik,'form':form,'period_end':period,'company_name':company}


def prepared_document(raw,slot,origin,*,mime=None):
    if len(raw)>MAX_BYTES:raise ResearchError('FILING_SIZE','공시 파일은 각각 6 MiB까지 처리합니다.',413)
    if not raw:raise ResearchError('FILING_EMPTY','빈 파일은 저장하지 않습니다.',422)
    mime=mime or ('application/pdf' if raw.startswith(b'%PDF-') else 'text/html')
    if mime not in ('application/pdf','text/html'):raise ResearchError('FILING_TYPE','SEC HTML 또는 검색 가능한 PDF만 처리합니다.',422)
    parsed=parse_isolated({'bytes':raw,'mime':mime})
    meta=extract_identity(raw,mime,parsed)
    if not meta['cik'] or meta['cik']!=slot['cik']:
        raise ResearchError('FILING_CIK_MISMATCH','문서 본문에서 일치하는 CIK를 확인하지 못했습니다. PDF라면 SEC의 HTML 원문을 저장해 주세요.',422)
    if meta['form'] not in ALLOWED_FORMS or meta['form']!=slot['form']:
        raise ResearchError('FILING_FORM_MISMATCH','문서 종류가 선택한 공시와 다릅니다. 저장하지 않았습니다.',422)
    if not meta['period_end'] or meta['period_end']!=slot['period_end']:
        raise ResearchError('FILING_PERIOD_MISMATCH','본문의 재무기간이 선택한 공시와 일치하지 않습니다.',422)
    passages=passages_from_pages(parsed['pages'])
    doc={**slot,'id':ident([slot['url'],hashlib.sha256(raw).hexdigest()])[:24],
       'sha256':hashlib.sha256(raw).hexdigest(),'scope':'FULL_DOCUMENT',
       'origin':origin,'collected_at':timestamp(),'pages_extracted':len(parsed['pages']),
       'characters':sum(len(p.get('text','')) for p in parsed['pages']),
       'truncated':bool(parsed.get('truncated')),'passages':passages,
       'identity_check':'IN_DOCUMENT_CIK_FORM_PERIOD_MATCH; not a file authenticity signature',
       'mime':mime}
    if doc['truncated']:doc['scope']='PARTIAL_DOCUMENT'
    # Store a bounded normalized corpus, never serve/execute raw imported HTML.
    doc['pages']=parsed['pages']
    return doc


def fetch_sec(slot,email):
    """One SEC request. Existing HTTP restrictions are not bypassed."""
    url,m=sec_url(slot['url']);host='www.sec.gov'
    if not re.fullmatch(r'[A-Za-z0-9._+\-]{1,128}@[A-Za-z0-9.\-]{1,160}\.[A-Za-z]{2,24}',email):
        raise ResearchError('FILING_CONTACT','자동 SEC 접근에는 기존 연락 이메일 설정이 필요합니다. 로컬 파일은 이메일 없이 읽습니다.',422)
    conn=None
    try:
        ips=public_addresses(host);conn=PinnedHTTPS(host,ips[0],8)
        conn.request('GET',urlsplit(url).path,headers={'User-Agent':f'SignalDesk Research/0.8.0 {email}',
            'Accept':'text/html,application/pdf','Accept-Encoding':'identity','Connection':'close'})
        res=conn.getresponse()
        if res.status!=200:raise DocumentError('HTTP_'+str(res.status))
        if res.getheader('Content-Encoding','identity').lower() not in ('','identity'):raise DocumentError('ENCODING_UNSUPPORTED')
        raw=bytearray();deadline=time.monotonic()+18
        while True:
            if time.monotonic()>deadline:raise DocumentError('READ_TIMEOUT')
            chunk=res.read(65536)
            if not chunk:break
            raw.extend(chunk)
            if len(raw)>MAX_BYTES:raise DocumentError('DOCUMENT_TOO_LARGE')
        mime='application/pdf' if raw.startswith(b'%PDF-') else 'text/html'
        return prepared_document(bytes(raw),slot,'SEC_DIRECT_FETCH',mime=mime)
    except (OSError,TimeoutError):raise DocumentError('NETWORK_FAILED') from None
    finally:
        if conn:conn.close()


class FilingStore:
    def __init__(self,root):self.root=Path(root);self.fin=FundamentalsStore(self.root)
    def _path(self,symbol):return _safe_path(self.root,'.cache/filing08/'+ident(normalize_symbol(symbol))[:24]+'.json')
    def read(self,symbol):
        p=self._path(symbol)
        if not p.is_file():return {'symbol':symbol,'documents':[],'attempts':[]}
        if p.stat().st_size>6000000:raise ResearchError('FILING_CACHE_SIZE','원문 저장본 크기가 예상 범위를 넘었습니다.',422)
        try:value=json.loads(p.read_text('utf-8'))
        except (ValueError,OSError):raise ResearchError('FILING_CACHE_READ','원문 저장본을 읽지 못했습니다.',422) from None
        if not isinstance(value,dict) or value.get('symbol')!=symbol:raise ResearchError('FILING_CACHE_IDENTITY','저장본 종목이 일치하지 않습니다.',422)
        return value
    def save(self,symbol,value):
        p=self._path(symbol);p.parent.mkdir(parents=True,exist_ok=True)
        b=json.dumps(value,ensure_ascii=False,allow_nan=False).encode()
        if len(b)>6000000:raise ResearchError('FILING_CACHE_SIZE','원문 저장 한도를 넘었습니다. 기존 자료는 유지합니다.',413)
        temp=p.with_suffix('.tmp-'+os.urandom(6).hex())
        try:temp.write_bytes(b);os.replace(temp,p)
        finally:temp.unlink(missing_ok=True)
    def seed(self,symbol):
        path=self.root/'backend/data/filing_excerpt_examples080.json'
        if not path.is_file():return []
        data=json.loads(path.read_text('utf-8'))
        return [d for d in data['documents'] if d.get('symbol')==symbol]
    def previous(self,symbol):
        from copy import deepcopy
        original=deepcopy(self.fin.read('impact-'+symbol+'.json') or {})
        # Restore only hypotheses for the comparison view, never for fact/model inputs.
        known={r.get('risk_id') for r in original.get('risks',[])}
        for held in original.get('evidence_review',{}).get('quarantined_risks',[]):
            if held.get('risk_id') in known:continue
            r=dict(held.get('original_claim') or {},risk_id=held.get('risk_id'),risk_title=held.get('title'))
            original.setdefault('risks',[]).append(r);known.add(r['risk_id'])
        return original
    def registry(self,symbol):
        """Source leads only. Filing text must pass its own CIK/form/period check."""
        slots={};seed=self.seed(symbol)
        for d in seed:
            slots[d['url']]={k:d.get(k) for k in ('symbol','cik','form','period_end','filing_date','title','url')}
        pack=self.fin.read('local-'+symbol+'.json') or self.fin.read(symbol+'.json') or {}
        known_cik=str(int(pack['cik'])) if str(pack.get('cik','')).isdigit() else (seed[0]['cik'] if seed else None)
        if not known_cik:return []
        if any(d['cik']!=known_cik for d in slots.values()):
            raise ResearchError('FILING_ISSUER_CONFLICT','저장 재무와 공시의 기업 번호가 다릅니다. 섞어서 표시하지 않습니다.',422)
        report=self.previous(symbol)
        # Source title dates are not reused as filing dates.
        for s in report.get('sources',[]):
            try:url,m=sec_url(s.get('url'))
            except (ResearchError,DocumentError):continue
            cik=str(int(m['cik']))
            if known_cik and cik!=known_cik:continue
            form=re.search(r'\b(10-[KQ])\b',s.get('title',''),re.I)
            period=re.search(r'-(20\d{6})\.(?:htm|html)$',m['file'])
            if not form or not period:continue
            try:pdate=datetime.strptime(period[1],'%Y%m%d').date().isoformat()
            except ValueError:continue
            slots.setdefault(url,{'symbol':symbol,'cik':cik,'form':form[1].upper(),'period_end':pdate,
                'filing_date':None,'title':s.get('title','')[:300],'url':url})
        output=[]
        for d in slots.values():
            d['key']=ident(d['url'])[:24];output.append(d)
        # Only the newest annual and newest quarterly filing are automatic targets.
        chosen=[]
        for form in ('10-K','10-Q'):
            hits=[d for d in output if d['form']==form]
            if hits:chosen.append(sorted(hits,key=lambda d:d['period_end'],reverse=True)[0])
        return chosen
    def documents(self,symbol):
        result={d['url']:d for d in self.seed(symbol)}
        saved=self.read(symbol)
        for d in saved.get('documents',[]):
            if d.get('symbol')==symbol:result[d['url']]=d
        return list(result.values())
    def view(self,symbol,valuation=None):
        docs=self.documents(symbol);report=render_report(docs,valuation,self.previous(symbol))
        publicdocs=[{k:d.get(k) for k in ('url','origin','scope','collected_at','pages_extracted','characters','truncated')} for d in docs]
        report.update(symbol=symbol,registry=self.registry(symbol),document_status=publicdocs,
           attempts=self.read(symbol).get('attempts',[]),
           corpus_hash=ident([{k:d.get(k) for k in ('id','sha256','scope','passages','period_end')} for d in docs]),
           starter_note='같이 제공한 NVDA 발췌는 두 공시의 세 문구입니다. 전체 공시 자동 수집·최신성 검증을 뜻하지 않습니다.' if self.seed(symbol) else None)
        return report
    def import_files(self,symbol,items):
        slots={s['key']:s for s in self.registry(symbol)};docs=[];seen=set()
        for item in items:
            key=item['source_key']
            if key not in slots or key in seen:raise ResearchError('FILING_SLOT','중복 또는 다른 문서 슬롯입니다.',422)
            seen.add(key)
            try:raw=base64.b64decode(item['content_base64'],validate=True)
            except (ValueError,TypeError):raise ResearchError('FILING_FILE_ENCODING','파일 인코딩을 읽지 못했습니다.',422) from None
            docs.append(prepared_document(raw,slots[key],'USER_SAVED_SEC_FILE'))
        # Transactional batch: any validation failure leaves old corpus intact.
        saved=self.read(symbol);by={d['url']:d for d in saved.get('documents',[])}
        for d in docs:by[d['url']]=d
        saved['documents']=list(by.values())[-4:];saved['updated_at']=timestamp();self.save(symbol,saved)
        return self.view(symbol)
    def fetch(self,symbol,keys):
        slots={s['key']:s for s in self.registry(symbol)}
        if not keys or len(set(keys))!=len(keys) or any(k not in slots for k in keys):raise ResearchError('FILING_SLOT','선택된 공시를 확인하세요.',422)
        email=self.fin.contact()
        if not email:raise ResearchError('FILING_CONTACT','SEC 연락 이메일을 먼저 설정하거나 저장한 HTML 파일을 불러오세요.',422)
        saved=self.read(symbol);by={d['url']:d for d in saved.get('documents',[])};attempts=[]
        for key in keys:
            slot=slots[key]
            if attempts and attempts[-1]['status'] in ('HTTP_403','HTTP_429'):
                attempts.append({'key':key,'url':slot['url'],'status':'NOT_REQUESTED_AFTER_DENIAL','at':timestamp()});continue
            try:
                doc=fetch_sec(slot,email);by[slot['url']]=doc;status='TEXT_EXTRACTED'
            except (DocumentError,ResearchError) as exc:status=exc.code
            attempts.append({'key':key,'url':slot['url'],'status':status,'at':timestamp()})
            time.sleep(.35)
        saved.update(documents=list(by.values())[-4:],attempts=attempts,updated_at=timestamp());self.save(symbol,saved)
        result=self.view(symbol);result['new_external_requests']=sum(a['status']!='NOT_REQUESTED_AFTER_DENIAL' for a in attempts)
        return result
