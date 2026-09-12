/** Read-only display rules. No paid calls, quote invention or predicted price direction.
 * A pending event never becomes confirmed good/bad news just from its category.
 */
import {safeSourceUrl} from './research.mjs';
import {dayNumber, dateStatus, eventDateText, normalizedSourceUrl} from './unified-catalysts.mjs';
const array = value => Array.isArray(value) ? value : [];
const text = value => typeof value === 'string' ? value.trim() : '';
export function sourcesForEvent(entry, report) {
  const ids = new Set([...array(entry?.ai?.source_ids), ...array(entry?.ai?.date_source_ids)]);
  const candidates = array(entry?.candidates).map(c => ({url:c.source_url, title:c.title || '저장 원문', date:c.source_document_date}));
  const linked = array(report?.sources).filter(s => ids.has(s.id));
  const seen = new Set();
  return [...candidates, ...linked].flatMap(s => {
    const url = safeSourceUrl(s?.url), key = normalizedSourceUrl(url);
    if (!url || !key || seen.has(key)) return [];
    seen.add(key); return [{...s,url}];
  });
}

function kindOf(entry) {
  // Titles identify a stage, not whether its outcome has happened or succeeded.
  const title = text(entry?.title);
  if (/전체\s*생존|overall\s+survival/i.test(title) || (/\bOS\b/i.test(title) && /임상|clinical|phase\s*[123]|생존|survival/i.test(title))) return 'CLINICAL_OS';
  if (/FDA|\bs?NDA\b|\bBLA\b/i.test(title) && /접수|acceptance|수락|filing|refuse.to.file/i.test(title)) return 'FDA_FILING';
  if (/임상|clinical|phase\s*[123]|평가변수|top.line/i.test(title)) return 'CLINICAL';
  if (entry?.category === 'REGULATORY' && /FDA|\bs?NDA\b|\bBLA\b|PDUFA/i.test(title)) return 'FDA_DECISION';
  return text(entry?.category) || 'OTHER';
}

const RULES = {
  FDA_FILING: {
    name:'FDA 심사 접수', label:'결과 대기 · 접수 ≠ 승인',
    why:'심사를 시작할 수 있는지 보는 단계입니다. 접수됐다는 사실만으로 판매 허가를 받은 것은 아닙니다.',
    positive:'심사 접수와 공식 검토 일정 확인 → 허가 검토 절차 진전. 최종 승인과는 별개입니다.',
    negative:'접수 거절 또는 서류 보완·재제출 필요 → 심사 시작이 늦어질 수 있습니다.'
  },
  FDA_DECISION: {
    name:'FDA 허가 심사', label:'양방향 · 허가 결과 대기',
    why:'공식 허가 여부와 승인 조건을 확인해야 합니다. 심사 일정만으로 승인 가능성을 수치화하지 않습니다.',
    positive:'신청한 적응증의 허가와 수용 가능한 조건 확인 → 판매·상업화 근거 확보.',
    negative:'미승인 통지나 추가 시험 요구 → 허가 지연과 개발 비용 부담.'
  },
  CLINICAL_OS: {
    name:'임상 · 생존 데이터', label:'양방향 · 데이터 결과 대기',
    why:'전체생존(OS)은 환자의 생존 기간을 보는 지표입니다. 데이터 발표 전에는 개선 여부를 알 수 없습니다.',
    positive:'사전에 정한 분석에서 생존 개선과 수용 가능한 안전성 확인 → 약효 근거 강화.',
    negative:'생존 개선을 입증하지 못하거나 안전성 악화 → 임상 근거와 허가 기대에 부담.'
  },
  CLINICAL: {
    name:'임상 데이터', label:'양방향 · 데이터 결과 대기',
    why:'정해진 주요 평가변수와 안전성 결과가 핵심입니다. 단순 발표 예고는 임상 성공이 아닙니다.',
    positive:'사전에 정한 주요 평가변수 달성과 수용 가능한 안전성 → 개발 근거 강화.',
    negative:'주요 평가변수 미달이나 안전성 문제 → 후속 개발·허가 진행에 부담.'
  },
  EARNINGS: {
    name:'실적', label:'양방향 · 실적 내용 확인 필요',
    why:'매출·영업손익·현금흐름과 회사의 기존 전망을 비교해야 합니다. 발표일 자체는 호재가 아닙니다.',
    positive:'매출·수익성·현금흐름 개선 또는 회사 전망 상향 → 사업 기대를 뒷받침.',
    negative:'실적 악화·현금소진 확대 또는 회사 전망 하향 → 사업·자금 사정에 부담.'
  },
  FINANCING: {
    name:'자금조달', label:'양방향 · 조달 조건 확인 필요',
    why:'확보하는 현금과 새로 발행할 주식·이자 부담을 함께 봐야 합니다.',
    positive:'충분한 현금을 낮은 희석·이자 부담으로 확보 → 자금 불확실성 완화.',
    negative:'큰 할인 발행·워런트·높은 금리 → 기존 주주 희석 또는 이자 부담 확대.'
  },
  DEBT: {
    name:'부채·만기', label:'양방향 · 상환·차환 조건 확인',
    why:'만기 일정만으로 위험 현실화를 단정하지 않습니다. 상환 재원과 차환 조건이 필요합니다.',
    positive:'상환 재원 확보 또는 유리한 차환 조건 확정 → 만기 부담 완화.',
    negative:'상환 재원 부족·차환 실패·조건 악화 → 유동성 압박 확대.'
  },
  PRODUCT: {
    name:'제품·사업', label:'양방향 · 출시·수요 확인 필요',
    why:'예정대로 출시되는지와 실제 고객 주문·매출 연결이 중요합니다.',
    positive:'출시 일정 준수와 실제 주문·고객 도입 확인 → 매출 근거 강화.',
    negative:'출시 지연·품질 문제·도입 부진 → 매출 전환과 비용에 부담.'
  },
  CONTRACT: {
    name:'계약', label:'양방향 · 계약 조건 확인 필요',
    why:'계약 확정 여부와 매출·수익성 기여를 확인해야 합니다. 논의 중이라는 사실만으로 수주가 아닙니다.',
    positive:'구속력 있는 계약과 이행 조건 확정 → 수주·매출 가시성 개선.',
    negative:'협상 결렬·계약 취소·수익성 낮은 조건 → 기대 매출이나 이익에 부담.'
  },
  CONFERENCE: {
    name:'투자자 행사', label:'중립 · 참석 자체는 호재 아님',
    why:'행사 참석과 새 사업 성과는 다릅니다. 새로운 발표가 없다면 방향 판단을 추가하지 않습니다.',
    positive:'새 계약·사업 진전처럼 확인 가능한 추가 사실 공개 → 해당 내용별로 재평가.',
    negative:'계획 지연·전망 하향처럼 불리한 추가 사실 공개 → 해당 내용별로 재평가.'
  },
  REGULATORY: {
    name:'규제·심사', label:'양방향 · 결정 내용 확인 필요',
    why:'규제 결정의 범위와 조건을 확인해야 사업 영향을 판단할 수 있습니다.',
    positive:'사업 진행을 허용하는 결정과 수용 가능한 조건 → 제약 완화.',
    negative:'제한·불허·추가 의무 부과 → 사업 진행 또는 비용에 부담.'
  }
};
function usefulCondition(value) {
  const s = text(value);
  if (s.length < 18 || s.length > 240) return null;
  if (/목표주가|상승\s*확률|하락\s*확률|\d+\s*%\s*(상승|하락)|무조건|확실히\s*오르|기대보다 좋으면 투자심리|기대에 못 미치면 투자심리/.test(s)) return null;
  return s;
}
export function eventInsight(entry, report) {
  const kind = kindOf(entry), links = sourcesForEvent(entry, report);
  const rule = RULES[kind];
  const basis = rule ? '이벤트 유형별 판단 기준 · 새 기업 분석 아님' : '판단 기준 미확보';
  const unknownDate = !entry?.eventDate && !entry?.windowStart;
  const missingNotice = kind === 'EARNINGS' && unknownDate && /미확인|미공개|부재|미등재|unconfirmed|not announced/i.test(text(entry?.title));
  const result = {
    kind, name:rule?.name || '이벤트', label:rule?.label || '판단 근거 부족',
    tone:kind === 'CONFERENCE' ? 'neutral' : 'pending',
    why:rule?.why || '무엇이 바뀌는지와 결과를 평가할 근거를 확보하지 못했습니다.',
    positive:rule?.positive || null, negative:rule?.negative || null,
    basis, links, dateText:eventDateText(entry), dateLabel:dateStatus(entry),
    unknownDate, fact: links.length ? text(entry?.ai?.fact) : '',
    originalTitle:text(entry?.title), title:text(entry?.title) || '제목 미확보',
    note:'호재·악재가 되는 조건이지 결과나 주가 상승·하락의 예측은 아닙니다.'
  };
  if (!rule && links.length && !entry?.conflict) {
    const positive=usefulCondition(entry?.ai?.positive_condition), negative=usefulCondition(entry?.ai?.negative_condition);
    if (positive && negative && positive !== negative) {
      Object.assign(result,{positive,negative,label:'양방향 · 결과 미확인',basis:'저장 AI 시나리오 · 원문 대조 필요',why:text(entry?.ai?.why_it_matters) || result.why});
    }
  }
  if (!links.length) {
    result.label='판단 근거 부족 · 원문 미연결'; result.tone='neutral';
    result.fact=''; result.note='원문 연결을 확보하지 못했습니다. 아래 조건은 일반적인 판단 기준일 뿐입니다.';
  }
  if (missingNotice) {
    result.title='다음 실적 발표 · 일정 미확인'; result.label='호재·악재 아님 · 공지 미확인'; result.tone='neutral';
    result.why='발표 날짜를 아직 찾지 못했다는 뜻입니다. 실적 악화나 회사의 일정 지연이 확인된 것은 아닙니다.';
  }
  if (entry?.conflict) {
    result.label='판단 보류 · 날짜 기록 충돌'; result.tone='neutral';
    result.why='서로 다른 날짜가 연결돼 있습니다. 어느 일정이 맞는지 먼저 원문에서 확인해야 합니다.';
    result.fact='';
  }
  return result;
}

export function selectBoardEvents(view, horizon='all', today=view?.researchDate) {
  const now=dayNumber(today), seen=new Set();
  return array(view?.entries).filter(e=> {
    if (now === null) return false;
    const start=dayNumber(e.eventDate || e.windowStart), end=dayNumber(e.eventDate || e.windowEnd);
    const unknown=start===null || end===null;
    if (e.conflict) return horizon==='review' || horizon==='all';
    if (horizon==='review') return false;
    if (!unknown && (end<now || start>now+180)) return false;
    if (horizon==='unknown' && !unknown) return false;
    if ([30,90,180].includes(horizon) && (unknown || start>now+horizon)) return false;
    const sourceKey=array(e.candidates).map(c=>normalizedSourceUrl(c.source_url)).filter(Boolean).sort().join('|') || array(e.ai?.source_ids).join('|');
    const key=[text(e.title).replace(/\s+/g,' ').toLowerCase(),e.eventDate,e.windowStart,e.windowEnd,sourceKey].join('|');
    if(seen.has(key))return false; seen.add(key); return true;
  }).sort((a,b)=>(a.eventDate||a.windowStart||'9999').localeCompare(b.eventDate||b.windowStart||'9999'));
}
export function splitNewsCards(cards) {
  const positive=[], negative=[], other=[], seen=new Set();
  for (const c of array(cards)) {
    const key=text(c?.id) || [text(c?.title),array(c?.evidence).map(e=>e.url).join('|')].join('|');
    if (!c || seen.has(key)) continue; seen.add(key);
    // A conditional benefit is not an already-realized positive fact.
    if(c.direction==='POSITIVE' && c.state==='REPORTED_FACT') positive.push(c);
    else if (c.direction!=='POSITIVE' && ['NEGATIVE','MIXED'].includes(c.direction)) negative.push(c);
    else other.push(c);
  }
  return {positive,negative,other};
}
