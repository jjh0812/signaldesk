"""Source-first corporate-filing reading, 0.8.0.

A quotation hit is NOT full entailment verification. Rules intentionally cover
only narrow, inspectable disclosure patterns. No issuer-specific conclusions,
no calls to any external service, and no modifications to valuation inputs.
"""
from __future__ import annotations
from copy import deepcopy
from datetime import date
import hashlib
import json
import math
import re

VERSION = 'filing-risk-0.8.0'
TOPICS = ('CONTROLS','DEBT','GUARANTEES','EXPORT','SUPPLY')
LABELS = {'CONTROLS':'내부통제 평가','DEBT':'차입·상환 부담','GUARANTEES':'보증·조건부 현금 부담',
          'EXPORT':'판매 제한·수출통제','SUPPLY':'공급망 의존'}
STATE_LABELS = {'REPORTED_FACT':'문서에 기재된 발생 사실','CONDITIONAL':'조건부 위험',
                'EXPOSURE':'지속 노출','ASSESSMENT':'기준일의 통제 평가','GENERAL':'일반적인 주의사항',
                'NEEDS_REVIEW':'문장 해석 필요','CONFLICT':'같은 문서의 표현 충돌'}
TOPIC_RE = {
 'CONTROLS':re.compile(r'internal control|material weakness|disclosure controls',re.I),
 'DEBT':re.compile(r'\bdebt\b|senior (?:unsecured )?notes|unsecured (?:senior )?notes|\bbonds?\b|\bnotes\b.{0,35}\b(?:issued|issuance|due)\b',re.I),
 'GUARANTEES':re.compile(r'\bguarantee(?:s)?\b|payment obligations.{0,70}defaults',re.I),
 'EXPORT':re.compile(r'export control|export (?:licen[cs]e|restriction)|\bBIS\b|H20.{0,80}(?:charge|licen[cs])',re.I),
 'SUPPLY':re.compile(r'foundr(?:y|ies)|third.party (?:manufactur|assembl)|supply (?:chain|constraint)|contract manufacturer',re.I),
}
NUM = re.compile(r'\$\s*([\d,]+(?:\.\d+)?)\s*(billion|million)\b',re.I)
CONDITIONAL = re.compile(r'\b(?:if|could|may|might|would|potential|upon|in the event|subject to)\b',re.I)
NEGATIVE = re.compile(r'\b(?:not|never|no)\b|\bhave not\b|\bdid not\b',re.I)


def clean(value):
    return re.sub(r'\s+',' ',str(value or '')).strip()


def ident(value):
    return hashlib.sha256(json.dumps(value,sort_keys=True,ensure_ascii=False).encode()).hexdigest()


def finite(value):
    return type(value) in (int,float) and math.isfinite(value)


def _sentence_before(text, match):
    dot=text.rfind('. ',0,match.start());newline=text.rfind('\n',0,match.start())
    start=max(dot+2 if dot>=0 else 0,newline+1 if newline>=0 else 0)
    return text[start:match.start()]


def _reported(pattern,text):
    """No promotion of negated or hypothetical actions. See negative fixtures."""
    for m in re.finditer(pattern,text,re.I):
        prefix=_sentence_before(text,m)
        # An 'if' earlier in the same sentence or negation inside match changes meaning.
        if not CONDITIONAL.search(prefix) and not NEGATIVE.search(m.group(0)):
            return m
    return None


def classify(topic,text):
    t=clean(text)
    if topic=='CONTROLS':
        effective=_reported(r'our (?:management concluded that our )?internal control over financial reporting (?:was|is) effective\b',t)
        ineffective=re.search(r'our internal control over financial reporting (?:was|is) (?:not effective|ineffective)\b',t,re.I)
        weakness=_reported(r'\bwe (?:have )?(?:identified|discovered|reported) (?:a |one or more |\d+ )?material weakness(?:es)?\b',t)
        negative_weakness=re.search(r'\b(?:no material weakness(?:es)? (?:was|were) identified|we (?:have |did )?not (?:identified|identify|discover(?:ed)?) (?:any |a )?material weakness)',t,re.I)
        if effective and (ineffective or weakness):return 'CONFLICT','MIXED','MIXED_CONTROL_LANGUAGE'
        if effective:return 'ASSESSMENT','NEUTRAL','CONTROL_EFFECTIVE'
        if ineffective or weakness:
            m=ineffective or weakness
            if not CONDITIONAL.search(_sentence_before(t,m)):return 'REPORTED_FACT','NEGATIVE','CONTROL_WEAKNESS_REPORTED'
        if negative_weakness:return 'ASSESSMENT','NEUTRAL','NO_WEAKNESS_REPORTED'
        if CONDITIONAL.search(t) or re.search(r'inherent limit|reasonable assurance|prevent all',t,re.I):
            return 'GENERAL','INSUFFICIENT','CONTROL_GENERAL_LIMITATION'
    if topic=='DEBT':
        issuance=_reported(r'\bwe (?:have )?issued\b.{0,100}?(?:senior (?:unsecured )?notes|unsecured (?:senior )?notes|bonds)\b',t)
        if issuance:return 'REPORTED_FACT','MIXED','DEBT_ISSUED'
        distress=_reported(r'\bwe (?:have )?(?:defaulted|failed to repay|breached (?:our |the )?debt covenants)\b',t)
        if distress:return 'REPORTED_FACT','NEGATIVE','DEBT_DEFAULT_REPORTED'
        if re.search(r'\b(?:may|could|if|would)\b',t,re.I):return 'CONDITIONAL','NEGATIVE','DEBT_CONDITIONAL'
    if topic=='GUARANTEES':
        if re.search(r'\bguarantee(?:s)?\b',t,re.I) and re.search(r'\bdefault(?:s)?\b|\btrigger(?:ed)?\b',t,re.I):
            return 'CONDITIONAL','NEGATIVE','GUARANTEE_TRIGGER'
        if re.search(r'\b(?:we have entered|we entered|our guarantees|we provide)\b',t,re.I):
            return 'EXPOSURE','INSUFFICIENT','GUARANTEE_EXPOSURE'
    if topic=='EXPORT':
        if _reported(r'\bwe (?:have )?(?:recorded|recognized|incurred)\b.{0,160}?(?:charge|loss|expense)',t):
            return 'REPORTED_FACT','NEGATIVE','EXPORT_COST_REPORTED'
        if CONDITIONAL.search(t):return 'CONDITIONAL','NEGATIVE','EXPORT_CONDITIONAL'
        if re.search(r'\brequir(?:es?|ed)\b|\brestrict(?:ed|ions?)\b|\bprohibit',t,re.I):
            return 'EXPOSURE','NEGATIVE','EXPORT_RESTRICTION'
    if topic=='SUPPLY':
        if re.search(r'\b(?:rely|depend|reliance|dependent)\b',t,re.I):
            return 'EXPOSURE','NEGATIVE','SUPPLY_DEPENDENCE'
        if CONDITIONAL.search(t):return 'CONDITIONAL','NEGATIVE','SUPPLY_CONDITIONAL'
    return 'NEEDS_REVIEW','INSUFFICIENT','UNCLASSIFIED'


def passages_from_pages(pages):
    """Bounded paragraph selection with neighbors; not only search snippets.
    Headings/paragraph indices, not invented PDF page numbers for HTML.
    """
    selected=[]
    for page in pages:
        text=str(page.get('text',''))
        paragraphs=[clean(x) for x in re.split(r'\n\s*\n|\n',text) if len(clean(x))>20]
        if len(paragraphs)<5:  # a flat extracted page: bounded sentence windows
            paragraphs=[clean(x) for x in re.split(r'(?<=[.!?])\s+(?=[A-Z])',text) if len(clean(x))>20]
        heading='본문'
        for i,paragraph in enumerate(paragraphs):
            if len(paragraph)<130 and re.search(r'^(?:Item\s+\d|Note\s+\d|Controls|Guarantees|Internal Control|Risk Factors)',paragraph,re.I):heading=paragraph
            for topic,pat in TOPIC_RE.items():
                if not pat.search(paragraph):continue
                before=paragraphs[i-1][-800:] if i else ''
                after=paragraphs[i+1][:800] if i+1<len(paragraphs) else ''
                # Do not arbitrarily cut a long paragraph into an apparently complete quotation.
                clipped=len(paragraph)>4500
                selected.append({'topic':topic,'text':paragraph[:4500],
                    'context_before':before,'context_after':after,'page':page.get('page',1),
                    'locator':f'{heading} · 문단 {i+1}', 'truncated':clipped,
                    'paragraph_index':i+1})
    # Keep differing assessments as well as concrete/conditional disclosures.
    weights={'ASSESSMENT':0,'REPORTED_FACT':1,'CONDITIONAL':2,'EXPOSURE':3,'GENERAL':4,'NEEDS_REVIEW':5,'CONFLICT':0}
    result=[]
    for topic in TOPICS:
        hits=[p for p in selected if p['topic']==topic]
        hits.sort(key=lambda p:(weights[classify(topic,p['text'])[0]],p['page'],p['paragraph_index']))
        seen=set()
        for p in hits:
            fingerprint=clean(p['text']).lower()
            if fingerprint in seen:continue
            result.append(p);seen.add(fingerprint)
            if len(seen)>=8:break
    return result


def amounts(text):
    out=[]
    for m in NUM.finditer(text):
        number=float(m[1].replace(',',''))*(1000 if m[2].lower()=='billion' else 1)
        out.append({'raw':m[0],'usd_million':number})
    return out


def evidence_for(document,p):
    return {'id':ident([document['id'],p['text'],p.get('locator')])[:20],
        'document_id':document['id'],'url':document['url'],'title':document['title'],
        'period_end':document.get('period_end'),'filing_date':document.get('filing_date'),
        'locator':p.get('locator'),'page':p.get('page'),
        'quote':p['text'],'context_before':p.get('context_before',''),'context_after':p.get('context_after',''),
        'origin':document.get('origin'),'scope':document.get('scope'),
        'sha256':document.get('sha256'),'partial_quote':p.get('truncated',False)}


def _wording(rule):
    # These are disclosed-pattern explanations, not an AI forecast of this issuer.
    wording={
      'DEBT_ISSUED':('채권 발행: 현금 확보와 상환 부담을 함께 보기','채권을 발행했다는 문장이 있습니다. 발행 자체를 유동성 위기로 해석하지 않습니다.',
        '자금을 확보하는 장점과 이자·만기 상환 부담이 함께 생깁니다.',
        '만기별 상환액, 이자 부담, 자금 사용 목적, 현금흐름을 함께 확인하세요.',
        'DEBT','MEDIUM','발행 사실은 구체적입니다. 위기 여부나 주가 변동폭까지 확인한 것은 아닙니다.'),
      'GUARANTEE_TRIGGER':('보증: 상대방 불이행 때 현금 부담이 생길 수 있음','보증의 지급 조건에 상대방의 불이행이 연결돼 있습니다. 지금 손실이 발생했다는 문장은 아닙니다.',
        '상대방이 약속을 지키지 못하면 회사 현금이 필요해질 수 있습니다.',
        '보증 한도, 효력 개시, 실제 지급 조건과 종료·완화 조건을 함께 확인하세요.',
        'CASH','INSUFFICIENT','현금 부담의 경로는 있지만, 선택 문구만으로 규모·확률을 다 알 수 없습니다.'),
      'CONTROL_EFFECTIVE':('통제 평가: 효과적이라는 문구','해당 기준일에 내부통제가 효과적이었다고 평가한 문장이 있습니다.',
        '이 문장은 같은 기준일에 약점을 발견했다는 이전 설명을 뒷받침하지 않습니다. 과거 또는 이후 모든 문제가 없다는 뜻은 아닙니다.',
        '감사 범위와 기준일, 더 최근의 통제 평가와 정정 공시를 확인하세요.',
        'NONE','LOW','확인된 통제 평가이지 새로운 매출 증가나 주가 상승 신호는 아닙니다.'),
      'NO_WEAKNESS_REPORTED':('중대한 약점 미발견이라는 평가 문구','해당 문장에서는 중대한 약점을 발견하지 않았다고 설명합니다.',
        '통제 실패가 실제 발생했다는 주장과 구분해야 합니다.',
        '평가 범위와 기준일, 감사의견을 확인하세요.','NONE','LOW','문장의 부정 표현을 보존한 분류입니다.'),
      'CONTROL_WEAKNESS_REPORTED':('내부통제 결함의 발생 보고 후보','내부통제의 비효과성 또는 중대한 약점 식별을 직접 서술한 문장이 있습니다.',
        '재무보고 신뢰성과 개선 비용을 점검할 이유가 됩니다. 오류나 사기의 규모를 자동 추정하지 않습니다.',
        '결함의 범위, 정정 재무와 개선 계획, 감사의견을 확인하세요.','DISCOUNT_RATE','HIGH','직접적인 통제 결함 서술이 있어 우선 대조할 항목입니다.'),
      'CONTROL_GENERAL_LIMITATION':('통제의 일반적인 한계 설명','모든 오류를 막을 수 없다는 일반론 또는 조건부 문구입니다.',
        '이 문구만으로 실제 중대한 약점이 발견됐다고 바꿔 말하지 않습니다.',
        '같은 문서의 경영진 평가·감사의견을 함께 확인하세요.','NONE','INSUFFICIENT','발생 사실의 근거로 사용하지 않습니다.'),
      'DEBT_DEFAULT_REPORTED':('차입금 상환·약정 위반 보고 후보','상환 실패 또는 약정 위반을 직접 서술한 문장이 있습니다.',
        '현금과 차입 조건에 즉각적인 영향을 줄 가능성을 우선 점검해야 합니다.',
        '위반 일시, 면제·유예 여부, 상환 요구액과 이후 정정 공시를 확인하세요.','DEBT','HIGH','발생 서술이 있으므로 원문 맥락을 우선 확인합니다.'),
      'EXPORT_COST_REPORTED':('수출 관련 비용: 발생 기간과 현재 상태 구분','수출 관련 문단에서 비용·손실을 인식했다는 문장이 있습니다.',
        '해당 기간의 이익 영향을 설명할 수 있지만, 같은 손실이 다시 생긴다는 뜻은 아닙니다.',
        '비용 발생 기간과 환입·판매 허용 등 이후 변화를 확인하세요.','MARGIN','MEDIUM','과거 비용과 앞으로의 위험은 구분합니다.'),
      'SUPPLY_DEPENDENCE':('공급망 의존: 성장에 필요한 공급의 조건','제조·공급 파트너에 대한 의존을 서술한 문장이 있습니다.',
        '공급 차질이 생기면 출하 지연이나 비용 증가로 성장·이익률 가정이 흔들릴 수 있습니다.',
        '대체 공급, 생산능력, 계약 조건과 실제 중단 여부를 확인하세요.','REVENUE','MEDIUM','의존 노출과 실제 공급 중단은 다릅니다.'),
    }
    if rule in wording:return wording[rule]
    topic='EXPORT' if rule.startswith('EXPORT') else 'GUARANTEES' if rule.startswith('GUARANTEE') else 'DEBT' if rule.startswith('DEBT') else 'SUPPLY'
    return (LABELS.get(topic,'공시 문구 점검'), '조건 또는 노출을 설명하는 원문이 있습니다. 발생 사실로 올리지 않습니다.',
      '조건이 현실화되면 매출·비용·현금에 영향을 줄 수 있습니다.',
      '조건의 충족 여부, 규모와 기간, 완화 근거를 원문에서 확인하세요.',
      'REVENUE' if topic in ('EXPORT','SUPPLY') else 'CASH','INSUFFICIENT','정확한 규모와 최신 상태를 추가로 확인해야 합니다.')


def make_card(document,p):
    state,direction,rule=classify(p['topic'],p['text'])
    # An incomplete paragraph should never receive a confident factual promotion.
    if p.get('truncated'):state,direction,rule='NEEDS_REVIEW','INSUFFICIENT','UNCLASSIFIED'
    title,fact,meaning,watch,channel,importance,importance_reason=_wording(rule)
    if rule=='UNCLASSIFIED':
        title=LABELS[p['topic']]+' · 문장 해석 필요';fact='관련 원문은 찾았지만 지원하는 분류 규칙으로 의미를 정하지 못했습니다.'
        meaning='원문을 확인하기 전까지 사실·조건부 위험을 구분하지 않습니다.'
    if state=='CONFLICT':
        title='같은 문서의 통제 평가 표현을 대조해야 합니다';fact='서로 다른 평가 시점이나 상반된 표현이 같은 후보에 나타납니다.'
        meaning='어느 한 문장만 골라 정상·결함으로 결론 내리지 않습니다.';importance='INSUFFICIENT';channel='NONE'
    ev=evidence_for(document,p)
    return {'id':ident([ev['id'],p['topic'],rule])[:24],'topic':p['topic'],'state':state,'state_label':STATE_LABELS[state],
      'rule':rule,'direction':direction,'importance':importance,'importance_reason':importance_reason,
      'title':title,'fact_reading':fact,'why_it_matters':meaning,'watch':watch,
      'economic_channel':channel,'amounts':amounts(p['text']) if rule in ('DEBT_ISSUED','EXPORT_COST_REPORTED') else [],
      'evidence':[ev],'period_end':document.get('period_end'),'filing_date':document.get('filing_date'),
      'assessment_origin':'RULE_BASED_READING_NOT_AI','latest_changes_checked':False,
      'limit':'인용 문구의 규칙 기반 해석입니다. 최신성·공시 전체·문장 의미의 독립 검증 완료가 아닙니다.'}


def build_cards(documents):
    cards=[];unclassified=[]
    for d in documents:
        for p in d.get('passages',[]):
            if p.get('topic') not in TOPICS or not clean(p.get('text')):continue
            c=make_card(d,p)
            (unclassified if c['state'] in ('GENERAL','NEEDS_REVIEW') else cards).append(c)
    # Do not merge different guarantees or periods; only exact duplicate text within one document.
    unique={}
    for c in cards:
        key=(c['evidence'][0]['document_id'],c['rule'],c['evidence'][0]['quote'])
        unique.setdefault(key,c)
    cards=list(unique.values())
    # For controls keep one result per document/rule; opposing results stay visible.
    limited=[];counts={}
    order={'REPORTED_FACT':0,'CONDITIONAL':1,'EXPOSURE':2,'ASSESSMENT':3,'CONFLICT':0}
    cards.sort(key=lambda c:(order[c['state']],c['topic'],c['period_end'] or '',c['id']))
    for c in cards:
        key=(c['evidence'][0]['document_id'],c['rule'])
        limit=1 if c['topic']=='CONTROLS' else 2
        if counts.get(key,0)>=limit:continue
        counts[key]=counts.get(key,0)+1;limited.append(c)
    return limited[:16],unclassified[:12]


def old_claim_checks(old_report,cards):
    """Narrowly contrast an actual-weakness claim with its cited dated document.
    Other matching topics are retrieval hints, not whole-claim validation.
    """
    src={s.get('id'):s for s in old_report.get('sources',[]) if isinstance(s,dict)}
    out=[]
    for r in old_report.get('risks',[]):
        if not isinstance(r,dict):continue
        urls={src[s].get('url') for s in r.get('evidence_ids',[]) if s in src}
        linked=[c for c in cards if any(e['url'] in urls for e in c['evidence'])]
        claim=clean(r.get('current_state',''))
        asserted=bool(re.search(r'(?:중대한\s*약점|material weakness).{0,30}(?:식별했|발견했|보고했|identified|discovered)',claim,re.I))
        effective=[c for c in linked if c['rule']=='CONTROL_EFFECTIVE']
        adverse=[c for c in linked if c['rule'] in ('CONTROL_WEAKNESS_REPORTED','MIXED_CONTROL_LANGUAGE')]
        if asserted and effective and not adverse:
            status='CONTRARY_DISCLOSURE';reason='인용한 문서는 해당 기준일에 통제가 효과적이었다고 평가합니다. 이전의 약점 발견 주장을 그대로 재사용하지 않습니다.';refs=[c['id'] for c in effective]
        elif asserted and effective and adverse:
            status='CONTEXT_CONFLICT';reason='관련 문구의 시점·범위가 달라 추가 대조가 필요합니다.';refs=[c['id'] for c in effective+adverse]
        else:
            topic='DEBT' if re.search('채권|만기',r.get('risk_title','')) else 'GUARANTEES' if re.search('보증|약정',r.get('risk_title','')) else 'EXPORT' if re.search('수출',r.get('risk_title','')) else 'SUPPLY' if re.search('공급|파운드리',r.get('risk_title','')) else 'CONTROLS'
            refs=[c['id'] for c in linked if c['topic']==topic]
            status='RELATED_TEXT' if refs else 'NO_MATCHED_PASSAGE'
            reason='관련 원문을 확보했습니다. 기존 주장 전체의 사실·규모·시점을 검증한 것은 아닙니다.' if refs else '해당 주장에 대응하는 원문을 아직 확보하지 못했습니다.'
        out.append({'risk_id':r.get('risk_id'),'title':r.get('risk_title',''), 'status':status,'reason':reason,'card_ids':refs,
                    'original_claim':claim,'original_is_not_evidence':True})
    return out


def price_channel(card,valuation):
    f=(valuation or {}).get('financials',{});reverse=(valuation or {}).get('reverse',{})
    g=reverse.get('growth') if reverse.get('status')=='SOLVED' else None
    if card['economic_channel']=='NONE':
        text='통제 평가를 매출 증가나 할인율 하락으로 자동 반영하지 않습니다.'
    elif card['economic_channel']=='DEBT':
        text='차입은 현금 확보와 상환 의무가 함께 생깁니다. 기존 부채에 포함된 발행액을 다시 차감하지 않습니다.'
    elif card['economic_channel']=='CASH':
        text='조건 충족으로 실제 현금 지출이 생기면 주주가치에 부담이 될 수 있습니다. 한도 전체를 손실로 계산하지 않습니다.'
    elif card['economic_channel']=='MARGIN':
        text='비용이 반복되면 이익률 가정을 검토해야 합니다. 이미 과거 이익에 반영된 비용을 또 차감하지 않습니다.'
    elif card['economic_channel']=='REVENUE':
        text='판매·출하 제약은 성장 가정을 약화시킬 수 있습니다.'
        if finite(g):text+=f' 현재 모형의 성장 요구는 연 {g*100:.1f}%이며 달성 예상치는 아닙니다.'
    else:text='이 원문만으로 모형 가정을 자동 변경하지 않습니다.'
    scale=None
    if card['rule']=='DEBT_ISSUED' and len(card['amounts'])==1 and finite(f.get('operating_cash_flow')) and f['operating_cash_flow']>0:
        amount=card['amounts'][0]['usd_million']
        scale={'value':amount/f['operating_cash_flow'], 'label':'발행 원금 / 입력 최근 12개월 영업현금흐름',
               'note':'재무 기준이 다른 두 크기의 참고 비교입니다. 상환능력·만기 보장·손실률이 아닙니다.',
               'period_end':f.get('period_end'),'amount_million':amount,'denominator_million':f['operating_cash_flow']}
    return {'text':text,'model_changed':False,'quantified_price_effect':None,'scale':scale,
            'verdict':'미평가' if not valuation else valuation.get('verdict_label'),'price_date':f.get('price_date')}


def render_report(documents,valuation=None,old_report=None):
    cards,pending=build_cards(documents)
    for c in cards:c['price_connection']=price_channel(c,valuation)
    return {'version':VERSION,'cards':cards,'additional_passages':pending,
      'old_claim_checks':old_claim_checks(old_report or {},cards),
      'coverage':{'documents':len(documents),'topics_found':sorted({c['topic'] for c in cards}),
        'topics_not_found':[x for x in TOPICS if x not in {c['topic'] for c in cards}],
        'full_filings':sum(d.get('scope')=='FULL_DOCUMENT' for d in documents),
        'selected_excerpts':sum(d.get('scope')=='SELECTED_EXCERPTS' for d in documents)},
      'new_api_calls':0,'new_external_requests':0,
      'valuation_unchanged':True,'valuation_ready':bool((valuation or {}).get('decision_ready')),
      'sources':[ {k:d.get(k) for k in ('id','url','title','cik','form','period_end','filing_date','scope','origin','collected_at','sha256','truncated','pages_extracted','characters')} for d in documents]}
