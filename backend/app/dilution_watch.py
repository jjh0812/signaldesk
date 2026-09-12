"""Bounded, opt-in SEC filing signal scan, not a prediction or issuance ledger.

Metadata != issuance. Pattern matches are always labelled as unverified signals.
No issuer hardcodes, arbitrary URLs, automatic retries, or paid provider requests.
"""
from __future__ import annotations

import copy
from email.utils import parsedate_to_datetime
import hashlib
import json
import os
import re
import threading
import time
from datetime import date, datetime, timedelta, timezone
from html.parser import HTMLParser
from pathlib import Path
from urllib.parse import urljoin
from zoneinfo import ZoneInfo

import httpx

from .evidence_store import _safe_path
from .fundamentals import FundamentalsStore
from .provider import normalize_symbol
from .research import ResearchError

VERSION = 'dilution-watch-1.1.0'
MAX_PRIMARY = 8
MAX_DOCUMENT_REQUESTS = 12
MAX_BYTES = 6 * 1024 * 1024
LOOKBACK_DAYS = 180
REGISTRATION_FORMS = {'S-1', 'S-1/A', 'S-3', 'S-3/A', 'S-3ASR', 'F-1', 'F-1/A', 'F-3', 'F-3/A', 'F-3ASR'}
CURRENT_FORMS = {'8-K', '8-K/A', '6-K', '6-K/A'}
RELEVANT_FORMS = REGISTRATION_FORMS | CURRENT_FORMS | {'S-8', 'S-8/A', '424B1', '424B2', '424B3', '424B4', '424B5', '424B7', 'EFFECT', 'RW', 'RW WD'}
TICKERS_URL = 'https://www.sec.gov/files/company_tickers.json'
SUBMISSION_URL = re.compile(r'^https://data\.sec\.gov/submissions/CIK\d{10}\.json$')
DOCUMENT_URL = re.compile(r'^https://www\.sec\.gov/Archives/edgar/data/\d{1,10}/\d{18}/[A-Za-z0-9_.-]{1,180}\.(?:html?|txt)$')
EMAIL_RE = re.compile(r'[A-Za-z0-9._+\-]{1,128}@[A-Za-z0-9.-]{1,160}\.[A-Za-z]{2,24}')


def stamp() -> str:
    return datetime.now(timezone.utc).isoformat()


def day(value):
    try:
        return date.fromisoformat(value) if isinstance(value, str) and re.fullmatch(r'\d{4}-\d{2}-\d{2}', value) else None
    except ValueError:
        return None


def age(value):
    try:
        parsed = datetime.fromisoformat(value)
        return time.time() - parsed.timestamp() if parsed.tzinfo else float('inf')
    except (ValueError, TypeError):
        return float('inf')


def clean(value):
    return re.sub(r'\s+', ' ', value).strip()


class WatchStore:
    """Allowlisted per-project storage. Cache reads never cause external requests."""
    def __init__(self, root: Path):
        self.root = root

    def path(self, name):
        if not re.fullmatch(r'[A-Za-z0-9_.-]{1,100}\.json', name):
            raise ValueError('Invalid watch filename')
        return _safe_path(self.root, '.cache/stock-watch110/' + name)

    def read(self, name, limit=12_000_000):
        p = self.path(name)
        try:
            if p.stat().st_size > limit:
                return None
            result = json.loads(p.read_text(encoding='utf-8'))
            return result if isinstance(result, dict) else None
        except (OSError, UnicodeError, ValueError):
            return None

    def save(self, name, value):
        p = self.path(name)
        p.parent.mkdir(parents=True, exist_ok=True)
        tmp = p.with_name(p.name + '.' + os.urandom(5).hex() + '.tmp')
        try:
            tmp.write_text(json.dumps(value, ensure_ascii=False, allow_nan=False), encoding='utf-8')
            os.replace(tmp, p)
        finally:
            tmp.unlink(missing_ok=True)

    def contact(self):
        value = (self.read('contact.json', 4096) or {}).get('email', '')
        if isinstance(value, str) and EMAIL_RE.fullmatch(value):
            return value
        # Reuse the user's existing SEC identification without exposing its value.
        return FundamentalsStore(self.root).contact()

    def cooldown(self):
        value = self.read('cooldown.json', 4096) or {}
        until = value.get('until', 0)
        remaining = max(0, int(until - time.time()) + 1) if type(until) in (int, float) and 0 < until < 9999999999 else 0
        return {'active': remaining > 0, 'retry_at_epoch': until if remaining else None,
                'remaining_seconds': remaining, 'http_status': value.get('http_status') if value.get('http_status') in (403, 429) else None}

    def set_contact(self, value):
        if not isinstance(value, str) or not EMAIL_RE.fullmatch(value.strip()):
            raise ResearchError('SEC_CONTACT_INVALID', 'SEC 요청 식별용 이메일 주소를 확인하세요. API 키를 넣지 마세요.', 422)
        self.save('contact.json', {'email': value.strip()})


class SecClient:
    """One process-wide rate gate and a persistent cooldown. Fixed SEC origins only."""
    _gate = threading.Lock()
    _last = 0.0

    def __init__(self, store: WatchStore):
        self.store = store
        self.requests = 0
        self.deadline = time.monotonic() + 90

    def get(self, url: str, *, json_result=False):
        if url != TICKERS_URL and not SUBMISSION_URL.fullmatch(url) and not DOCUMENT_URL.fullmatch(url):
            raise ResearchError('SEC_URL_BLOCKED', '허용된 SEC 주소가 아닙니다.', 422)
        email = self.store.contact()
        if not email:
            raise ResearchError('SEC_CONTACT_REQUIRED', '최초 1회 SEC 요청 식별용 이메일을 입력하세요. 키·결제 설정이 아닙니다.', 400)
        with self._gate:
            cooldown = (self.store.read('cooldown.json', 2048) or {}).get('until', 0)
            if type(cooldown) in (int, float) and cooldown > time.time():
                raise ResearchError('SEC_COOLDOWN', 'SEC 접근 제한 대기 중입니다. 반복 요청하지 말고 잠시 후 확인하세요.', 429)
            remaining = self.deadline - time.monotonic()
            if remaining <= 1:
                raise ResearchError('SEC_SCAN_TIME_LIMIT', '이번 SEC 조회 시간 한도에 도달했습니다. 확보한 범위만 표시합니다.', 504)
            time.sleep(max(0, .4 - (time.monotonic() - type(self)._last)))
            type(self)._last = time.monotonic()
            self.requests += 1
            try:
                with httpx.Client(timeout=httpx.Timeout(min(12, remaining), connect=min(8, remaining)), follow_redirects=False, trust_env=False) as client:
                    with client.stream('GET', url, headers={'User-Agent': f'SignalDesk/1.1.0 {email}', 'Accept': 'application/json' if json_result else 'text/html, text/plain'}) as response:
                        if response.status_code != 200:
                            if response.status_code in (403, 429):
                                retry = response.headers.get('retry-after', '')
                                delay = 600
                                if retry.isdigit() and len(retry) < 9:
                                    delay = max(600, int(retry))
                                elif retry:
                                    try:
                                        retry_date = parsedate_to_datetime(retry)
                                        if retry_date.tzinfo:
                                            delay = max(600, int(retry_date.timestamp() - time.time()) + 1)
                                    except (ValueError, TypeError, OverflowError):
                                        pass
                                self.store.save('cooldown.json', {'until': time.time() + delay, 'http_status': response.status_code})
                            raise ResearchError('SEC_HTTP_' + str(response.status_code), f'SEC HTTP {response.status_code}: 자료 확보가 중단됐습니다. 거절을 우회하거나 자동 재시도하지 않습니다.', 502)
                        chunks = bytearray()
                        for piece in response.iter_bytes():
                            chunks.extend(piece)
                            if len(chunks) > MAX_BYTES:
                                raise ResearchError('SEC_SIZE_LIMIT', 'SEC 문서가 크기 한도를 초과했습니다. 원문에서 확인하세요.', 502)
                            if time.monotonic() > self.deadline:
                                raise ResearchError('SEC_SCAN_TIME_LIMIT', 'SEC 조회 시간이 초과되었습니다.', 504)
                if json_result:
                    result = json.loads(chunks)
                    if not isinstance(result, dict):
                        raise ValueError('not an object')
                    return result
                if chunks[:5] == b'%PDF-':
                    raise ResearchError('SEC_TEXT_UNAVAILABLE', '이 문서는 HTML 본문 분석 범위 밖입니다.', 422)
                return bytes(chunks).decode('utf-8', errors='replace')
            except ResearchError:
                raise
            except (httpx.HTTPError, ValueError, UnicodeError):
                raise ResearchError('SEC_READ_FAILED', 'SEC 자료를 읽지 못했습니다. 네트워크·응답 형식을 확인하세요.', 502) from None


def issuer(store: WatchStore, client, symbol):
    saved = store.read('issuer-' + symbol + '.json', 12000) or {}
    cik = saved.get('cik')
    if not isinstance(cik, str) or not re.fullmatch(r'\d{10}', cik):
        directory = store.read('directory.json') or {}
        if not 0 <= age(directory.get('fetched_at')) < 86400:
            directory = {'fetched_at': stamp(), 'data': client.get(TICKERS_URL, json_result=True)}
            store.save('directory.json', directory)
        rows = directory.get('data', {})
        matches = [r for r in rows.values() if isinstance(r, dict) and str(r.get('ticker', '')).upper().replace('.', '-') == symbol] if isinstance(rows, dict) else []
        if len(matches) != 1 or not str(matches[0].get('cik_str', '')).isdigit():
            raise ResearchError('SEC_ISSUER_UNRESOLVED', 'SEC 목록에서 이 티커의 기업을 고유하게 연결하지 못했습니다. 다른 기업으로 대체하지 않았습니다.', 422)
        cik = str(int(matches[0]['cik_str'])).zfill(10)
    if len(cik) != 10 or int(cik) <= 0:
        raise ResearchError('SEC_ISSUER_UNRESOLVED', '기업 식별 번호가 유효하지 않습니다.', 422)
    submission = client.get(f'https://data.sec.gov/submissions/CIK{cik}.json', json_result=True)
    tickers = submission.get('tickers')
    if not isinstance(tickers, list) or symbol not in {str(t).upper().replace('.', '-') for t in tickers} or str(submission.get('cik', '')).lstrip('0') != cik.lstrip('0'):
        raise ResearchError('SEC_ISSUER_MISMATCH', 'SEC 기업 번호·티커가 일치하지 않습니다. 다른 회사 공시를 섞지 않았습니다.', 422)
    record = {'symbol': symbol, 'cik': cik, 'company_name': str(submission.get('name', symbol))[:200], 'matched_at': stamp(), 'share_class_warning': len(tickers) > 1}
    store.save('issuer-' + symbol + '.json', record)
    return record, submission


def filing_rows(submission, cik, today: date):
    recent = submission.get('filings', {}).get('recent')
    columns = ('accessionNumber', 'form', 'filingDate', 'primaryDocument')
    if not isinstance(recent, dict) or any(not isinstance(recent.get(k), list) for k in columns):
        raise ResearchError('SEC_LIST_INVALID', 'SEC 제출 목록 형식을 확인하지 못했습니다.', 502)
    n = len(recent['accessionNumber'])
    if any(len(recent[k]) != n for k in columns):
        raise ResearchError('SEC_LIST_INVALID', 'SEC 제출 목록의 열 길이가 다릅니다.', 502)
    cutoff = today - timedelta(days=LOOKBACK_DAYS)
    result, invalid = [], 0
    seen = set()
    for i in range(min(n, 5000)):
        form, filed, acc, doc = (recent[k][i] for k in ('form', 'filingDate', 'accessionNumber', 'primaryDocument'))
        if not day(filed) or day(filed) > today:
            invalid += 1
            continue
        if day(filed) < cutoff or form not in RELEVANT_FORMS:
            continue
        if not isinstance(acc, str) or not re.fullmatch(r'\d{10}-\d{2}-\d{6}', acc) or acc in seen:
            invalid += 1
            continue
        seen.add(acc)
        url = f'https://www.sec.gov/Archives/edgar/data/{int(cik)}/{acc.replace("-", "")}/{doc}'
        items = recent.get('items', [])
        item_text = str(items[i]) if len(items) > i else ''
        result.append({'accession': acc, 'form': form, 'filing_date': filed, 'url': url if DOCUMENT_URL.fullmatch(url) else None,
                       'index_url': f'https://www.sec.gov/Archives/edgar/data/{int(cik)}/{acc.replace("-", "")}/{acc}-index.html',
                       'items': item_text[:200]})
    result.sort(key=lambda r: (r['filing_date'], r['accession']), reverse=True)
    dates = [day(d) for d in recent['filingDate'] if day(d)]
    older_files = submission.get('filings', {}).get('files') or []
    window_complete = not older_files or bool(dates and min(dates) <= cutoff)
    return result, {'metadata_rows': n, 'invalid_rows': invalid, 'window_metadata_complete': window_complete and invalid == 0 and n <= 5000,
                    'from_date': cutoff.isoformat(), 'through_date': today.isoformat(), 'historical_files_fetched': False}


class FilingHTML(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.parts, self.links, self.skip = [], [], 0
    def handle_starttag(self, tag, attrs):
        if tag in ('script', 'style', 'noscript'):
            self.skip += 1
        if tag in ('p', 'div', 'tr', 'br', 'li', 'h1', 'h2', 'h3'):
            self.parts.append('\n')
        if tag == 'a':
            self.links.append(dict(attrs).get('href', ''))
    def handle_endtag(self, tag):
        if tag in ('script', 'style', 'noscript'):
            self.skip = max(0, self.skip - 1)
        if tag in ('p', 'div', 'tr', 'li'):
            self.parts.append('\n')
    def handle_data(self, data):
        if not self.skip:
            self.parts.append(data + ' ')


def extract_html(raw, base_url):
    parser = FilingHTML()
    parser.feed(raw)
    text = '\n'.join(clean(line) for line in ''.join(parser.parts).splitlines() if clean(line))
    limit = 1_000_000
    directory = base_url.rsplit('/', 1)[0] + '/'
    links = []
    for link in parser.links:
        url = urljoin(base_url, link)
        # Only a likely press-release exhibit in the exact same filing directory.
        if DOCUMENT_URL.fullmatch(url) and url.startswith(directory) and url != base_url and re.search(r'(?:ex|exhibit)[-_]?99|99[-_.]?1|press', url.rsplit('/', 1)[-1], re.I):
            if url not in links:
                links.append(url)
    return text[:limit], links[:1], len(text) > limit


# Pattern evidence stays a candidate. "Closed" etc is NOT an automatically verified status.
PATTERNS = [
    ('COMPLETION_LANGUAGE', '발행 완료 관련 문구', r'\b(?:closed|completed|consummated)\s+(?:the\s+|a\s+|its\s+)?(?:\w+\s+){0,4}(?:offering|private placement)|\bissued and sold\b', '발행 완료를 가리키는 문구가 있습니다. 거래일·수량·대상 거래를 원문에서 확인하세요.'),
    ('OFFERING_TERMS', '공모·사모 발행 조건 관련 문구', r'\b(?:pricing of|priced|registered direct offering|private placement|securities purchase agreement|underwriting agreement|public offering)\b', '신규 발행 조건 또는 관련 계약 문구입니다. 과거 사례·제안·확정 거래를 구분해야 합니다.'),
    ('ATM_FACILITY', 'ATM·주식 매각 프로그램 관련 문구', r'\bat[ -]the[ -]market\s+(?:offering|sales?|equity|issuance|program)|\bequity distribution agreement\b', '수시 주식 매각 구조를 확인할 단서입니다. 한도 전액이 이미 발행됐다는 뜻은 아닙니다.'),
    ('CONVERTIBLE', '전환증권 관련 문구', r'\bconvertible\s+(?:senior\s+|secured\s+|unsecured\s+)?(?:notes?|debt|debentures?|preferred|bonds?)\b', '주식 전환 가능성이 있는 증권입니다. 현금 상환·전환가·리픽싱·전환 조건 확인이 필요합니다.'),
    ('WARRANT', '워런트·선납형 워런트 관련 문구', r'\bpre[ -]funded warrants?\b|\bwarrants?\s+to\s+purchase\b|\bwarrant\s+(?:exercise|inducement)\b', '잠재 주식 발행 권리를 확인할 단서입니다. 행사 여부·현금 없는 행사·수량 중복을 확인해야 합니다.'),
    ('RESALE', '재판매 등록 관련 문구', r'\bselling\s+(?:stock|share)holders?\b|\bresale of\b', '기존 보유자 재판매가 포함될 수 있습니다. 재판매 등록 수량을 신규 발행량으로 더하지 않습니다.'),
    ('REVERSE_SPLIT', '주식 병합 관련 문구', r'\breverse\s+(?:stock\s+|share\s+)?split\b', '주식 병합 자체는 지분 희석이 아닙니다. 과거·현재 주식 수 비교 기준을 조정해야 합니다.'),
]


def metadata_signal(row):
    form = row['form']
    if form in REGISTRATION_FORMS:
        return 'REGISTRATION', '증권 등록 서류', '등록·발행 준비 단계의 공시입니다. 등록 효력·실제 신규 발행·재판매 여부는 별도 확인해야 합니다.'
    if form.startswith('424B'):
        return 'PROSPECTUS', '추가 투자설명서', '발행 또는 재판매의 구체적인 조건이 담길 수 있습니다. 제출만으로 발행 완료를 확정하지 않습니다.'
    if form.startswith('S-8'):
        return 'COMPENSATION_PLAN', '임직원 보상계획 등록', '보상용 증권 등록입니다. 등록 수량 전부가 즉시 발행되는 것은 아닙니다.'
    if form == 'EFFECT':
        return 'EFFECTIVENESS', '등록 효력 통지', '등록 효력 관련 통지입니다. 주식 발행·자금 유입 완료 통지가 아닙니다.'
    if form.startswith('RW'):
        return 'WITHDRAWAL', '등록 철회 관련 서류', '철회 대상과 범위를 확인해야 합니다. 다른 등록·ATM의 종료까지 뜻하지 않습니다.'
    if form.startswith('8-K') and re.search(r'(?:^|[,\s])3\.02(?:$|[,\s])', row.get('items', '')):
        return 'UNREGISTERED_SALES_ITEM', '미등록 증권 매각 항목', '8-K Item 3.02가 포함됐습니다. 증권 종류·발행일·수량은 원문 확인이 필요합니다.'
    return None


def classify_filing(row, documents):
    signals = []
    meta = metadata_signal(row)
    if meta:
        signals.append({'kind': meta[0], 'label': meta[1], 'meaning': meta[2], 'basis': 'FILING_METADATA', 'quote': None, 'url': row['url'] or row['index_url']})
    for code, label, expression, explanation in PATTERNS:
        found = False
        for doc in documents:
            for paragraph in doc.get('text', '').split('\n'):
                # Skip generic forward-looking language, negations and explicit hypotheticals.
                for sentence in re.split(r'(?<=[.!?])\s+(?=[A-Z])', paragraph):
                    match = re.search(expression, sentence, re.I)
                    if not match:
                        continue
                    before = sentence[:match.start()]
                    if re.search(r'\b(?:may|might|could|would|if|will|expect(?:s|ed)?\s+to|intends?\s+to)\b', before[-160:], re.I) or re.search(r'\b(?:not|no|never)\b', before[-70:], re.I):
                        continue
                    if re.search(r'forward[ -]looking|risk factors|safe harbor', sentence[:120], re.I):
                        continue
                    start = max(0, match.start() - 110)
                    quote = sentence[start:min(len(sentence), match.end() + 180)]
                    signals.append({'kind': code, 'label': label, 'meaning': explanation, 'basis': 'TEXT_PATTERN_NOT_VERIFIED', 'quote': ('…' if start else '') + quote, 'url': doc['url']})
                    found = True
                    break
                if found:
                    break
            if found:
                break
    if not signals:
        return None
    return {**row, 'id': row['accession'], 'signals': signals, 'new_since_previous': False,
            'issuance_status': 'NOT_INDEPENDENTLY_VERIFIED', 'estimated_dilution_pct': None,
            'percentage_note': '발행 전 주식 수·실제 신규 발행량·동일 주식종류를 검증하지 않아 희석률은 계산하지 않았습니다.'}


class DilutionService:
    def __init__(self, root: Path, client_factory=SecClient):
        self.store = WatchStore(root)
        self.client_factory = client_factory
        self.lock = threading.Lock()

    def cached(self, symbol):
        value = self.store.read('dilution-' + symbol + '.json')
        if not value or value.get('symbol') != symbol or value.get('version') != VERSION:
            return None
        value['stale'] = not 0 <= age(value.get('checked_at')) < 900
        value['cache_hit'] = True
        return value

    def scan(self, symbol, allow_public_fetch):
        symbol = normalize_symbol(symbol)
        if not allow_public_fetch:
            raise ResearchError('PUBLIC_CONSENT_REQUIRED', 'SEC 공개자료 조회 동의가 필요합니다. AI 호출은 없습니다.', 400)
        if not self.store.contact():
            raise ResearchError('SEC_CONTACT_REQUIRED', 'SEC 요청 식별용 이메일을 최초 1회 입력하세요.', 400)
        if not self.lock.acquire(blocking=False):
            raise ResearchError('SEC_SCAN_BUSY', '다른 SEC 조회가 진행 중입니다. 중복 요청하지 않았습니다.', 409)
        try:
            previous = self.cached(symbol)
            attempt = self.store.read('attempt-' + symbol + '.json', 4096) or {}
            if 0 <= age(attempt.get('attempted_at')) < 60:
                raise ResearchError('SEC_LOCAL_COOLDOWN', 'SEC 확인은 종목당 최소 60초 간격입니다. 새 요청은 보내지 않았습니다.', 429)
            self.store.save('attempt-' + symbol + '.json', {'attempted_at': stamp(), 'outcome': 'RUNNING'})
            client = self.client_factory(self.store)
            try:
                company, submission = issuer(self.store, client, symbol)
                today = datetime.now(ZoneInfo('America/New_York')).date()
                rows, coverage = filing_rows(submission, company['cik'], today)
                rows_to_display = rows[:120]
                coverage.update(relevant_filings=len(rows), listed_filings=len(rows_to_display), primary_documents_checked=0,
                                document_http_requests=0, pending_documents=0, documents_truncated=0, errors=[])
                alerts, fetch_count = [], 0
                budget = MAX_DOCUMENT_REQUESTS
                for row in rows_to_display:
                    documents = []
                    cache_key = 'document-' + hashlib.sha256((company['cik'] + row['accession']).encode()).hexdigest()[:30] + '.json'
                    stored = self.store.read(cache_key)
                    if stored and stored.get('url') == row['url'] and stored.get('complete') is True:
                        documents = stored.get('documents', [])
                    elif row['url'] and fetch_count < MAX_PRIMARY and budget > 0:
                        fetch_count += 1
                        budget -= 1
                        coverage['document_http_requests'] += 1
                        try:
                            raw = client.get(row['url'])
                            text, links, truncated = extract_html(raw, row['url'])
                            documents.append({'url': row['url'], 'text': text, 'truncated': truncated})
                            complete = True
                            for url in links:
                                if budget <= 0:
                                    complete = False
                                    break
                                budget -= 1
                                coverage['document_http_requests'] += 1
                                try:
                                    extra = client.get(url)
                                    txt, _, trunc = extract_html(extra, url)
                                    documents.append({'url': url, 'text': txt, 'truncated': trunc})
                                except ResearchError as exc:
                                    complete = False
                                    coverage['errors'].append({'accession': row['accession'], 'code': exc.code, 'scope': 'EXHIBIT'})
                            self.store.save(cache_key, {'url': row['url'], 'documents': documents, 'complete': complete})
                        except ResearchError as exc:
                            coverage['errors'].append({'accession': row['accession'], 'code': exc.code, 'scope': 'PRIMARY'})
                            if exc.code in {'SEC_HTTP_403', 'SEC_HTTP_429', 'SEC_COOLDOWN', 'SEC_SCAN_TIME_LIMIT'}:
                                budget = 0
                    if documents:
                        coverage['primary_documents_checked'] += 1
                        coverage['documents_truncated'] += sum(bool(d.get('truncated')) for d in documents)
                    else:
                        coverage['pending_documents'] += 1
                    alert = classify_filing(row, documents)
                    if alert:
                        alerts.append(alert)
                # Persist only successful list-based results; failed list requests keep previous results.
                old_by_id = {a['id']: a for a in (previous or {}).get('alerts', [])}
                old_seen = set((previous or {}).get('seen_accessions', []))
                for alert in alerts:
                    old_codes = {s['kind'] for s in old_by_id.get(alert['id'], {}).get('signals', [])}
                    codes = {s['kind'] for s in alert['signals']}
                    alert['new_since_previous'] = bool(previous) and (alert['id'] not in old_seen or bool(codes - old_codes))
                partial = bool(coverage['errors'] or coverage['pending_documents'] or coverage['documents_truncated'] or len(rows) > 120 or not coverage['window_metadata_complete'])
                result = {'version': VERSION, 'symbol': symbol, 'company_name': company['company_name'], 'cik': company['cik'], 'checked_at': stamp(),
                          'previous_checked_at': (previous or {}).get('checked_at'), 'status': 'PARTIAL' if partial else 'SCANNED',
                          'alerts': alerts, 'new_count': sum(a['new_since_previous'] for a in alerts), 'first_scan': not bool(previous),
                          'coverage': coverage, 'seen_accessions': [r['accession'] for r in rows_to_display], 'network_requests': client.requests,
                          'ai_calls': 0, 'cache_hit': False, 'stale': False, 'share_class_warning': company['share_class_warning'],
                          'limits': ['최근 180일 목록의 최신 관련 서류 최대 120개 + 한 번에 새 본문 최대 8개·문서 HTTP 최대 12회. 첨부·과거 공시 전량 검토가 아닙니다.',
                                     '문구 탐지에는 과거 거래·다른 거래·재판매·미래 조건이 섞일 수 있습니다. 원문 확인 전 발행 확정으로 사용하지 마세요.',
                                     '미공개 증자 예측·24시간 실시간 경보·주가 하락 확률·현금소진 추정은 제공하지 않습니다.']}
                self.store.save('dilution-' + symbol + '.json', result)
                self.store.save('attempt-' + symbol + '.json', {'attempted_at': stamp(), 'outcome': 'OK'})
                return result
            except ResearchError as exc:
                self.store.save('attempt-' + symbol + '.json', {'attempted_at': stamp(), 'outcome': 'FAILED', 'error_code': exc.code})
                raise
        finally:
            self.lock.release()
