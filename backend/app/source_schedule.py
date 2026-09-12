"""Local source schedule ledger, independent of generated AI reports (0.6.2).

Pure extraction from previously downloaded text. No network, API, credentials or DB
writes. These are DOCUMENT-ANCHORED CANDIDATES, never a claim of current official
confirmation. The inference of a calendar year is always explicit in the output.
Initial grammar: English earnings-call schedules and conference/keynote sentences.
Unsupported phrasing is reported as a coverage limitation, not absence of events.
"""
from __future__ import annotations

import hashlib
import re
from datetime import date, datetime, timezone
from pathlib import Path
from .document_reader import READER_VERSION, date_tokens, checked_url, DocumentError

VERSION = 'source-schedule-0.6.2'
MONTHS = {name.lower(): i for i, name in enumerate(
    ['January','February','March','April','May','June','July','August','September','October','November','December'], 1)}
MONTHS.update({k[:3]:v for k,v in list(MONTHS.items())})
_MONTH = '(?:' + '|'.join(sorted(MONTHS, key=len, reverse=True)) + ')'
_HEADER_DATE = re.compile(r'\b(\d{1,2})\s*[- ]\s*('+_MONTH+r')\.?\s*[- ,]\s*((?:19|20)\d{2})\b',re.I)
_ISO_DATE = re.compile(r'\b((?:19|20)\d{2})-(\d{2})-(\d{2})\b')
_LONG_HEADER_DATE = re.compile(r'\b('+_MONTH+r')\.?\s+(\d{1,2})(?:st|nd|rd|th)?\s*,?\s*((?:19|20)\d{2})\b',re.I)
_FUTURE = re.compile(r"\b(?:will|shall|scheduled|slated|plans?\s+to|expect(?:s|ed)?\s+to|(?:he|she|we|they|it)'ll)\b",re.I)
_NEGATIVE = re.compile(r"\b(?:not|no longer|cancel(?:led|ed)|postponed|rescheduled|might|may|could|would|if|assuming|tentative(?:ly)?|rumou?red|denied)\b|n['’]t\b",re.I)


def calendar_anchor(header: str) -> tuple[date | None, str]:
    """Use an actual day/month/year in header TEXT, never fiscal year/title/URL."""
    if not isinstance(header,str):return None,'문서 머리글 날짜 없음'
    candidates = set()
    for m in _HEADER_DATE.finditer(header[:1600]):
        try:candidates.add(date(int(m[3]),MONTHS[m[2].lower().rstrip('.')],int(m[1])))
        except (ValueError,KeyError):pass
    for m in _LONG_HEADER_DATE.finditer(header[:1600]):
        try:candidates.add(date(int(m[3]),MONTHS[m[1].lower().rstrip('.')],int(m[2])))
        except (ValueError,KeyError):pass
    for m in _ISO_DATE.finditer(header[:1600]):
        try:candidates.add(date(int(m[1]),int(m[2]),int(m[3])))
        except ValueError:pass
    if len(candidates)==1:return next(iter(candidates)),'머리글에 적힌 달력 날짜'
    return None, '머리글 날짜가 여러 개여서 문서 날짜 보류' if candidates else '머리글에서 달력 날짜 미확인'


def _sentences(text: str) -> list[str]:
    text=re.sub(r'\s+',' ',text.replace('’',"'")).strip()
    # Split at speech sentence boundaries, not fiscal-year punctuation or decimals.
    return [s.strip(' .') for s in re.split(r'(?<=[.!?])\s+(?=[A-Z0-9])',text) if s.strip(' .')]


def _kind(sentence: str, token: dict) -> tuple[str,str] | None:
    prefix=sentence[:token['offset']]
    low=sentence.lower()
    if not _FUTURE.search(sentence) or _NEGATIVE.search(sentence):return None
    # Recognition requires the event and date in the SAME sentence, not in a
    # neighbouring paragraph that happens to mention an IPO or a past quarter.
    if re.search(r'\b(?:our|the|next)\s+(?:next\s+|quarterly\s+)?(?:earnings|results)\s+(?:conference\s+)?call\b',low) and re.search(r'\b(?:scheduled|slated)\s+(?:for|on)\s*$',prefix,re.I):
        return 'EARNINGS','실적 발표 콘퍼런스콜'
    if re.search(r'\b(?:conference|keynote|fireside chat)\b',low) and re.search(r'\bon\s*$',prefix,re.I):
        # Keep the event name in its source language; do not generate a new agenda.
        name=re.search(r'\bat\s+(?:the\s+)?(.+?)\s+on\s*$',prefix,re.I)
        if not name:return None
        title=name[1].strip()
        if not title or len(title)>180:return None
        suffix=' · 대담' if 'fireside chat' in low else ' · 기조연설' if 'keynote' in low else ' · 행사'
        return 'CONFERENCE',title+suffix
    return None


def _resolve(token: dict, anchor: date | None, today: date, published_claim, anchor_note: str) -> dict:
    base={'event_date_candidate':None,'year_basis':'UNRESOLVED','year_explanation':anchor_note}
    if anchor and anchor>today:
        return {**base,'year_explanation':'문서 기준일이 조사일 이후라 날짜 후보를 보류했습니다.'}
    if anchor and published_claim:
        try:published=date.fromisoformat(published_claim)
        except (ValueError,TypeError):published=None
        if published and published<anchor:
            return {**base,'year_explanation':'머리글 날짜가 저장된 공개일보다 늦어 문서 시점을 다시 확인해야 합니다.'}
    explicit=token.get('explicit_year')
    if explicit:
        try:value=date(explicit,token['month'],token['day'])
        except (ValueError,TypeError):return base
        return {**base,'event_date_candidate':value.isoformat(),'year_basis':'EXPLICIT_IN_SENTENCE',
                'year_explanation':'행사 문장에 연·월·일이 직접 적혀 있습니다. 최신 변경 여부는 별도 확인해야 합니다.'}
    if not anchor:return base
    # Resolve future tense against the document date, NOT today's year or FY number.
    options=[]
    for year in (anchor.year,anchor.year+1):
        try:day=date(year,token['month'],token['day'])
        except ValueError:continue
        if 0<=(day-anchor).days<=183:options.append(day)
    if len(options)!=1:
        return {**base,'year_explanation':'문서일 뒤 183일 안의 연도를 하나로 좁히지 못했습니다. 날짜를 추정하지 않습니다.'}
    value=options[0]
    return {**base,'event_date_candidate':value.isoformat(),'year_basis':'CONTEXT_YEAR_CANDIDATE',
            'year_explanation':f'문장에는 월·일만 있습니다. 문서일 {anchor.isoformat()}와 미래 일정 발언을 바탕으로 {value.year}년을 후보로 연결했습니다. 확정 연도·최신 일정 검증은 아닙니다.'}


def _status(day: str | None, today: date) -> tuple[str,int | None]:
    if not day:return 'UNDATED',None
    days=(date.fromisoformat(day)-today).days
    return ('PAST' if days<0 else 'BEYOND_180' if days>180 else 'UPCOMING'),days


def build_source_schedule(bundle: dict | None, symbol: str, today: date) -> dict:
    result={'version':VERSION,'symbol':symbol,'research_date':today.isoformat(),
            'api_calls':0,'external_requests':0,'database_writes':0,
            'status':'NO_LOCAL_TEXT','source_collected_at':None,'source_is_expired':False,
            'candidates':[],'document_checks':[],'notice':
            '저장 원문에서 규칙으로 연결한 일정 후보입니다. 회사 공식성·연도 추론·변경 여부를 독립 검증한 확정 일정이 아닙니다. AI 조사 결과와 별도로 표시합니다.',
            'limitations':['영문 실적콜의 명시적 예정 문장과 행사·기조연설 날짜만 우선 처리합니다. 제품·규제·계약 일정 전량 추출 기능은 아닙니다.',
                          '연도는 행사 문장의 직접 표기 또는 문서 머리글의 달력 날짜를 사용합니다. 회계연도를 행사 연도로 사용하지 않습니다.']}
    if not isinstance(bundle,dict) or bundle.get('symbol')!=symbol or bundle.get('version')!=READER_VERSION:return result
    result['source_collected_at']=bundle.get('generated_at')
    try:
        fetched=datetime.fromisoformat(str(bundle.get('generated_at')))
        if fetched.tzinfo is None:raise ValueError()
        age=(datetime.now(timezone.utc)-fetched).total_seconds()
        result['source_is_expired']=bool(bundle.get('expired')) or not -60<=age<=21600
    except (ValueError,TypeError):
        result['source_is_expired']=True
    result['status']='NO_SUPPORTED_SCHEDULE'
    unique={}
    for doc in bundle.get('documents',[])[:3]:
        if not isinstance(doc,dict):continue
        audit={'title':str(doc.get('title',''))[:300],'status':doc.get('status'), 'candidates_found':0,'reason':''}
        result['document_checks'].append(audit)
        if doc.get('status')!='TEXT_EXTRACTED':audit['reason']='본문을 읽지 못한 문서는 후보에 사용하지 않았습니다.';continue
        header=str(doc.get('header_text') or '')[:1600]
        # Requiring ticker evidence reduces accidental cross-company schedules.
        # Classification is still a source claim, not an authentication mechanism.
        if doc.get('source_role_claim') not in ('ISSUER','REGULATOR') or not re.search(r'(?<![A-Z0-9])'+re.escape(symbol)+r'(?![A-Z0-9])',header,re.I):
            audit['reason']='원문 머리글의 티커 또는 발행사 자료 분류를 확인하지 못해 자동 후보 연결에서 제외했습니다.';continue
        if not re.search(r'earnings\s+call|results\s+call|transcript',header,re.I):
            audit['reason']='현재 규칙이 지원하는 실적콜 원문 형식이 아닙니다.';continue
        try:
            url=checked_url(doc.get('requested_url') or doc.get('url'))
            final_url=checked_url(doc.get('url') or doc.get('requested_url'))
        except DocumentError:audit['reason']='원문 URL 형식 검사 실패';continue
        anchor,note=calendar_anchor(header)
        for passage in doc.get('passages',[])[:24]:
            if not isinstance(passage,dict) or not isinstance(passage.get('text'),str):continue
            text=passage['text'][:4000]
            for sentence in _sentences(text):
                if len(sentence)>1600:continue
                tokens=date_tokens(sentence)
                # Multi-date sentences need semantic pairing; don't guess which date belongs to which event.
                if len(tokens)!=1:continue
                token=tokens[0];kind=_kind(sentence,token)
                if not kind:continue
                category,title=kind
                resolved=_resolve(token,anchor,today,doc.get('published_date_claim'),note)
                state,days=_status(resolved['event_date_candidate'],today)
                ident=hashlib.sha256((url+'|'+category+'|'+title.lower()+'|'+token['text'].lower()).encode()).hexdigest()[:20]
                record={'id':'local-'+ident,'category':category,'title':title,
                        'month_day_text':token['text'],**resolved,'horizon_state':state,'days_to_candidate':days,
                        'source_document_date':anchor.isoformat() if anchor else None,
                        'document_title':audit['title'],'source_url':url,'downloaded_url':final_url,
                        'document_sha256':doc.get('sha256'),'page':passage.get('page'),
                        'passage_id':passage.get('passage_id'),'sentence':sentence,
                        'header_text':header,'issuer_authenticity_verified':False,'latest_change_checked':False,
                        'basis':'LOCAL_TEXT_RULE_CANDIDATE','original_passage_ids':[passage.get('passage_id')]}
                if ident in unique:
                    ids=unique[ident]['original_passage_ids']
                    if passage.get('passage_id') not in ids:ids.append(passage.get('passage_id'))
                else:
                    unique[ident]=record;audit['candidates_found']+=1
        audit['reason']='원문 문장과 날짜 후보를 연결했습니다. 최신 변경 공지는 조회하지 않았습니다.' if audit['candidates_found'] else '지원되는 예정 문장을 찾지 못했습니다. 일정이 없다는 뜻은 아닙니다.'
    candidates=sorted(unique.values(), key=lambda c:(0 if c['category']=='EARNINGS' else 1,c['event_date_candidate'] or '9999',c['title']))[:24]
    result['candidates']=candidates
    if candidates:result['status']='SOURCE_CANDIDATES_AVAILABLE'
    return result


def stored_source_schedule(root: Path, symbol: str, today: date) -> dict:
    from .evidence_store import load_bundle
    # Expiry is a visible warning, never an excuse to delete historically read text.
    return build_source_schedule(load_bundle(root,symbol,require_fresh=False),symbol,today)


def candidate_audit(ledger: dict, report: dict | None) -> dict:
    """Measure representation, not factual correctness. Never overwrite AI reports."""
    findings=[]
    for c in ledger.get('candidates',[]):
        if c['horizon_state']!='UPCOMING':continue
        matches=[]
        for item in (report or {}).get('items',[]):
            if item.get('category')!=c['category']:continue
            if c['category']!='EARNINGS':
                # Conservative label overlap: absence of a join is not proof of a missing fact.
                words=set(re.findall(r'[A-Za-z]{3,}',c['title'].lower()))-{'conference','keynote','fireside','chat','technology','the','and'}
                if not words or not any(w in (str(item.get('title',''))+' '+str(item.get('fact',''))).lower() for w in words):continue
            matches.append(item)
        if any(i.get('event_date')==c['event_date_candidate'] for i in matches):status='SAME_DATE_REPRESENTED'
        elif any(i.get('event_date') for i in matches):status='DIFFERENT_DATE_REVIEW'
        elif matches:status='REPORT_UNDATED'
        else:status='REPORT_NOT_LINKED'
        findings.append({'candidate_id':c['id'],'category':c['category'],'status':status})
    return {'local_candidate_count':len(ledger.get('candidates',[])),'findings':findings,
            'notice':'원문 후보와 보고서 카드의 연결 상태입니다. 출처 내용의 독립 검증 결과는 아닙니다.'}
