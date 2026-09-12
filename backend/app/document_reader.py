"""0.6.1: explicit public-document retrieval, separate from paid AI research.

Input URLs come from same-symbol cached source LEADS (not authenticated facts).
Public HTTPS only; DNS addresses are validated then pinned for TLS connections.
No API credential, cookies, proxy or environment credential is read or forwarded.
HTML/PDF parsing is bounded and isolated. OCR/JS-rendering/login bypass absent.
"""
from __future__ import annotations
import hashlib
import http.client
import ipaddress
import json
import os
from pathlib import Path
import re
import socket
import ssl
import subprocess
import sys
import tempfile
import time
from urllib.parse import urljoin, urlsplit, urlunsplit

READER_VERSION = 'document-reader-0.6.1'
MAX_BYTES = 6 * 1024 * 1024
MAX_DOCS = 3
MAX_PASSAGES = 24
READ_BUDGET_SECONDS = 60

class DocumentError(Exception):
    def __init__(self, code: str):
        self.code = code
        super().__init__(code)


def checked_url(value: str) -> str:
    try:
        if not isinstance(value, str) or len(value) > 2400 or re.search(r'[\x00-\x20\\]', value):
            raise ValueError()
        p = urlsplit(value)
        if p.scheme != 'https' or not p.hostname or p.username or p.password or p.port not in (None,443):
            raise ValueError()
        host = p.hostname.encode('idna').decode('ascii').lower().rstrip('.')
        if '.' not in host or host.endswith(('.localhost','.local','.internal','.test','.example','.invalid')):
            raise ValueError()
        if re.search(r'(?i)(?:^|&)(?:api[_-]?key|access[_-]?token|token|password|authorization|sig|signature)=',p.query):
            raise ValueError()
        try:
            ip = ipaddress.ip_address(host)
        except ValueError:
            ip = None
        if ip is not None and not ip.is_global:
            raise ValueError()
        return urlunsplit(('https',host,p.path or '/',p.query,''))
    except (ValueError, UnicodeError, AttributeError):
        raise DocumentError('URL_REJECTED') from None


def public_addresses(host: str) -> list[str]:
    try:
        infos=socket.getaddrinfo(host,443,type=socket.SOCK_STREAM)
        addresses=list(dict.fromkeys(i[4][0] for i in infos))
        if not addresses or any(not ipaddress.ip_address(x).is_global for x in addresses):
            raise DocumentError('NETWORK_ADDRESS_REJECTED')
        return addresses
    except (socket.gaierror, ValueError):
        raise DocumentError('DNS_FAILED') from None


class PinnedHTTPS(http.client.HTTPSConnection):
    def __init__(self, host: str, ip: str, timeout: float):
        super().__init__(host,port=443,timeout=timeout,context=ssl.create_default_context())
        self._target_ip=ip
    def connect(self):
        # Numeric address: do not resolve the untrusted name a second time.
        sock=socket.create_connection((self._target_ip,443),self.timeout)
        try:
            self.sock=self._context.wrap_socket(sock,server_hostname=self.host)
        except BaseException:
            sock.close();raise


def fetch_document(url: str, deadline: float | None = None) -> dict:
    current=checked_url(url); original=current
    deadline=deadline or time.monotonic()+20
    for redirect in range(4):
        if time.monotonic() >= deadline: raise DocumentError('READ_TIMEOUT')
        p=urlsplit(current); addresses=public_addresses(p.hostname)
        remaining=max(.5,min(8,deadline-time.monotonic()))
        conn=PinnedHTTPS(p.hostname,addresses[0],remaining)
        try:
            conn.request('GET',urlunsplit(('', '', p.path or '/',p.query,'')),headers={
                'User-Agent':'SignalDesk/0.6.1 (personal document research)',
                'Accept':'text/html, application/pdf, text/plain;q=0.8',
                'Accept-Encoding':'identity', 'Connection':'close'})
            response=conn.getresponse()
            if response.status in (301,302,303,307,308):
                target=response.getheader('Location')
                if not target or redirect==3:raise DocumentError('REDIRECT_LIMIT')
                current=checked_url(urljoin(current,target)); continue
            if response.status!=200:raise DocumentError('HTTP_'+str(response.status))
            try: length=int(response.getheader('Content-Length') or 0)
            except ValueError:raise DocumentError('INVALID_LENGTH') from None
            if length>MAX_BYTES:raise DocumentError('DOCUMENT_TOO_LARGE')
            encoding=(response.getheader('Content-Encoding') or 'identity').lower()
            if encoding not in ('identity',''):raise DocumentError('ENCODING_UNSUPPORTED')
            content_type=(response.getheader('Content-Type') or '').split(';')[0].lower()
            chunks=[]; n=0
            while True:
                if time.monotonic()>=deadline:raise DocumentError('READ_TIMEOUT')
                if conn.sock:conn.sock.settimeout(max(.1,min(5,deadline-time.monotonic())))
                chunk=response.read(65536)
                if not chunk:break
                n+=len(chunk)
                if n>MAX_BYTES:raise DocumentError('DOCUMENT_TOO_LARGE')
                chunks.append(chunk)
            body=b''.join(chunks)
            if not body:raise DocumentError('EMPTY_DOCUMENT')
            is_pdf=body.startswith(b'%PDF-')
            if not is_pdf and content_type not in ('text/html','application/xhtml+xml','text/plain'):
                raise DocumentError('DOCUMENT_TYPE_UNSUPPORTED')
            return {'requested_url':original,'url':current,'mime':'application/pdf' if is_pdf else content_type,
                    'bytes':body,'sha256':hashlib.sha256(body).hexdigest()}
        except (OSError,ssl.SSLError,http.client.HTTPException):
            raise DocumentError('NETWORK_FAILED') from None
        finally:conn.close()
    raise DocumentError('REDIRECT_LIMIT')


def parse_isolated(download: dict) -> dict:
    with tempfile.TemporaryDirectory(prefix='signaldesk-document-') as temp:
        root=Path(temp);path=root/'document.bin';out=root/'text.json'
        path.write_bytes(download['bytes'])
        try:
            result=subprocess.run([sys.executable,'-I',str(Path(__file__).with_name('document_worker.py')),
                str(path),str(out),download['mime']],stdin=subprocess.DEVNULL,stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,timeout=12,check=False,
                env={**{k:v for k,v in os.environ.items() if k.upper() in {'SYSTEMROOT','WINDIR','TEMP','TMP','TMPDIR'}},
                     'PYTHONUTF8':'1','PYTHONIOENCODING':'utf-8'})
            if result.returncode or not out.is_file() or out.stat().st_size>2_000_000:
                raise DocumentError('TEXT_EXTRACTION_FAILED')
            data=json.loads(out.read_text(encoding='utf-8'))
            if not isinstance(data.get('pages'),list) or not any(p.get('text','').strip() for p in data['pages']):
                raise DocumentError('NO_SEARCHABLE_TEXT')
            return data
        except subprocess.TimeoutExpired:raise DocumentError('PARSER_TIMEOUT') from None
        except (OSError,ValueError):raise DocumentError('TEXT_EXTRACTION_FAILED') from None


MONTHS={m:i for i,m in enumerate(['january','february','march','april','may','june','july','august','september','october','november','december'],1)}
_MONTH=r'(?:January|February|March|April|May|June|July|August|September|October|November|December|Jan\.?|Feb\.?|Mar\.?|Apr\.?|Jun\.?|Jul\.?|Aug\.?|Sep\.?|Sept\.?|Oct\.?|Nov\.?|Dec\.?)'
DATE_PATTERN=re.compile(r'(?<![\w])(?:(?P<iso>20\d{2}-\d{2}-\d{2})|(?P<month>'+_MONTH+r')\s+(?P<day>\d{1,2})(?:st|nd|rd|th)?(?:(?:,\s*|\s+)(?P<year>20\d{2}))?)(?!\w)',re.I)
SCHEDULE_WORDS=re.compile(r'(?i)next\s+(?:earnings|quarter|call)|schedul|upcoming|conference|keynote|webcast|calendar|participat|launch|출시|실적\s*발표|컨퍼런스|예정|일정')
FUTURE_WORDS=re.compile(r'(?i)\bwill\b|schedul|upcoming|next\s+(?:earnings|quarter|call)|예정|다가오는|개최')
RISK_WORDS=re.compile(r'(?i)liquidity|commitment|contingenc|guarantee|risk\s+factor|export\s+control|debt|재무|보증|유동성')


def _month_number(s: str) -> int:
    s=s.lower().rstrip('.')
    return next(i for m,i in MONTHS.items() if m.startswith(s))


def date_tokens(text: str) -> list[dict]:
    from datetime import date
    out=[]
    for m in DATE_PATTERN.finditer(text):
        try:
            if m['iso']:
                d=date.fromisoformat(m['iso']);year=d.year;month=d.month;day=d.day
            else:
                month=_month_number(m['month']);day=int(m['day']);year=int(m['year']) if m['year'] else None
                date(year or 2000,month,day)
            out.append({'text':m.group(0),'month':month,'day':day,'explicit_year':year,
                        'iso_date':date(year,month,day).isoformat() if year else None,
                        'offset':m.start()})
        except (ValueError,StopIteration):continue
    return out


def schedule_passages(pages: list[dict], scope: str = 'catalysts') -> list[dict]:
    """Text candidates only. No issuer authenticity, causal or date-confirmation claims."""
    result=[];seen=set()
    for page in pages:
        text=re.sub(r'\s+',' ',str(page.get('text',''))).strip()
        patterns=SCHEDULE_WORDS if scope=='catalysts' else RISK_WORDS
        for match in patterns.finditer(text):
            left=max(0,match.start()-180);right=min(len(text),match.end()+460)
            excerpt=text[left:right]
            # Skip repeating adjacent windows, not other occurrences of the same date.
            if any(pg==page['page'] and abs(start-left)<220 for pg,start in seen):continue
            if scope=='catalysts' and not date_tokens(excerpt):continue
            seen.add((page['page'],left))
            result.append({'page':page['page'],'start':left,'text':excerpt,'dates':date_tokens(excerpt),
                           'future_word_found':bool(FUTURE_WORDS.search(excerpt)),
                           'kind':'TEXT_CANDIDATE_NOT_VERIFIED'})
    # Forward-schedule paragraphs have priority; late pages included, never just page 1.
    result.sort(key=lambda p:(not p['future_word_found'], -p['page'],p['start']))
    return result[:MAX_PASSAGES]


def prepare_document(source: dict, index: int, *, deadline: float, fetcher=None) -> dict:
    fetcher=fetcher or fetch_document
    base={'document_id':f'd{index}','requested_url':source['url'],'title':source.get('title','')[:300],
          'source_role_claim':source.get('role','UNKNOWN'),'published_date_claim':source.get('published_date'),
          'source_classification_verified':False}
    try:
        download=fetcher(source['url'],deadline);parsed=parse_isolated(download)
        passages=schedule_passages(parsed['pages'],'catalysts')
        for j,p in enumerate(passages,1):p['passage_id']=f'd{index}.p{p["page"]}.s{j}'
        return {**base,'status':'TEXT_EXTRACTED','url':download['url'],'sha256':download['sha256'],
                'mime':download['mime'],'pages_total':parsed['pages_total'],
                'pages_extracted':len(parsed['pages']),'text_truncated':parsed.get('truncated',False),
                'header_text':re.sub(r'\s+',' ',parsed['pages'][0]['text'])[:700] if parsed['pages'] else '',
                'passages':passages,'characters_extracted':sum(len(x['text']) for x in parsed['pages'])}
    except DocumentError as exc:return {**base,'status':exc.code,'passages':[]}


def evidence_bundle(sources: list[dict], symbol: str, *, fetcher=None) -> dict:
    from datetime import datetime,timezone
    deadline=time.monotonic()+READ_BUDGET_SECONDS
    documents=[]
    for i,s in enumerate(sources[:MAX_DOCS],1):
        if time.monotonic()>=deadline:
            documents.append({'document_id':f'd{i}','requested_url':s['url'],'status':'TOTAL_BUDGET_REACHED','passages':[]});continue
        documents.append(prepare_document(s,i,deadline=min(deadline,time.monotonic()+18),fetcher=fetcher))
    return {'version':READER_VERSION,'symbol':symbol,'generated_at':datetime.now(timezone.utc).isoformat(),
            'api_calls':0,'document_requests_planned':min(MAX_DOCS,len(sources)), 'documents':documents,
            'notice':'저장 출처에서 추출한 원문 후보입니다. 새 웹 검색·최신 일정 확인·회사 공식성 검증을 수행한 결과가 아닙니다. 연도가 없는 월일은 임의로 연도를 붙이지 않습니다.'}
