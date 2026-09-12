/** Read-only presentation model, v0.6.3.
 * No network, paid calls, report writes or factual upgrades.
 * Merge ONLY one-to-one, event-specific matches; preserve ambiguous and
 * conflicting records. Source claims, date candidates and AI opinions differ.
 */
import {safeSourceUrl} from './research.mjs';
import {matchingSourceLedger} from './source-schedule.mjs';

const DAY = 86400000;
const list = value => Array.isArray(value) ? value : [];
const text = value => typeof value === 'string' ? value : '';
const GENERIC = new Set('conference technology technologies keynote fireside chat presentation investor investors relations annual event events summit forum the and with from for inc corp corporation san francisco attends attending participation earnings results next quarter fiscal'.split(' '));
export const categoryName = {
  EARNINGS:'실적 발표', CONFERENCE:'경영진 행사', PRODUCT:'제품·사업',
  REGULATORY:'규제·심사', FINANCING:'자금 조달', MNA:'인수·합병', CORPORATE_ACTION:'주주 일정', OTHER:'기타 일정',
};

export function dayNumber(value) {
  if(typeof value !== 'string' || !/^\d{4}-\d{2}-\d{2}$/.test(value)) return null;
  const stamp = Date.parse(value+'T00:00:00Z');
  if(!Number.isFinite(stamp) || new Date(stamp).toISOString().slice(0,10)!==value) return null;
  return stamp / DAY;
}
export function normalizedSourceUrl(value) {
  const safe = safeSourceUrl(value); if(!safe) return null;
  try { const u = new URL(safe); u.hash='';
    // Tracking only. Content-bearing query parameters and paths are NOT dropped.
    for(const k of [...u.searchParams.keys()]) if(/^utm_/i.test(k)) u.searchParams.delete(k);
    return u.href;
  } catch { return null; }
}
function sourceAliases(c) {
  return [c.source_url,c.downloaded_url].map(normalizedSourceUrl).filter(Boolean);
}
function sharedSource(c,item,report) {
  const refs=new Set([...list(item.source_ids),...list(item.date_source_ids),...list(item.schedule_evidence?.source_ids)]);
  const urls=list(report?.sources).filter(s=>refs.has(s.id)).map(s=>normalizedSourceUrl(s.url)).filter(Boolean);
  return sourceAliases(c).some(url=>urls.includes(url));
}
function words(value) { return new Set((text(value).toLowerCase().match(/[a-z][a-z0-9-]{2,}/g)||[]).filter(w=>!GENERIC.has(w))); }
function distinctiveMatch(a,b) {
  const x=words(a),y=words(b),overlap=[...x].filter(w=>y.has(w));
  return overlap.length>=2 && overlap.length/Math.min(x.size,y.size)>=0.6;
}
function fiscalPeriod(value) {
  const s=text(value).toLowerCase(); let m;
  if((m=s.match(/\bq([1-4])\s*(?:fy|fiscal\s*)?\s*(20\d{2}|\d{2})\b/))) return `${m[2].length===2?'20':''}${m[2]}Q${m[1]}`;
  if((m=s.match(/\b(?:fy|fiscal\s*)(20\d{2}|\d{2})\s*q([1-4])\b/))) return `${m[1].length===2?'20':''}${m[1]}Q${m[2]}`;
  if((m=s.match(/\b(first|second|third|fourth) quarter of fiscal (20\d{2})\b/))) return `${m[2]}Q${{first:1,second:2,third:3,fourth:4}[m[1]]}`;
  if((m=s.match(/(20\d{2})\s*(?:회계연도|회계년도|회계년)?\s*([1-4])분기/))) return `${m[1]}Q${m[2]}`;
  return null;
}
function isNextTitle(item) { return /다음\s*(?:분기|실적)|next\s+(?:quarter|quarterly|earnings|results)/i.test(text(item.title)); }
function aiDate(item) {
  // A date previously withheld by validation is NOT promoted back into the calendar.
  if(item.timing==='UNCONFIRMED'||item.bucket==='UNKNOWN') return null;
  return dayNumber(item.event_date)!==null?item.event_date:null;
}
function namedSameEvent(c,item,report,candidateGroups,aiItems) {
  if(c.category!==item.category) return false;
  // A month/day-only source must not silently acquire an AI-proposed year.
  if(dayNumber(c.event_date_candidate)===null && aiDate(item)) return false;
  const a=fiscalPeriod(c.sentence),b=fiscalPeriod(item.title);
  if(c.category==='EARNINGS') {
    if(a && b && a!==b) return false;
    // Do not join release-date records with a call only on the category/date.
    if(/실적\s*발표(일|\s*일정)|earnings\s+release/i.test(text(item.title))&&!isNextTitle(item)&&!/콜|call/i.test(text(item.title))) return false;
    const one=candidateGroups.filter(g=>g.candidates[0].category==='EARNINGS').length===1 && aiItems.filter(i=>i.category==='EARNINGS').length===1;
    return sharedSource(c,item,report) && ((a && b && a===b) || (one && isNextTitle(item)) ||
      (one && aiDate(item)===c.event_date_candidate && /콜|call/i.test(text(item.title))));
  }
  // Conference names must have more than one distinctive shared word.
  return distinctiveMatch(c.title,item.title) && (sharedSource(c,item,report) || aiDate(item)===c.event_date_candidate);
}
function sourceGroups(candidates) {
  const groups=new Map();
  for(const c of candidates) {
    const period=c.category==='EARNINGS'?fiscalPeriod(c.sentence):null;
    // No merge of unspecified fiscal periods from different source sentences.
    const event=period||text(c.title).toLowerCase()+'|'+text(c.sentence).toLowerCase();
    const key=[c.category,event,c.event_date_candidate||c.month_day_text||c.id].join('|');
    if(!groups.has(key))groups.set(key,{candidates:[]});
    groups.get(key).candidates.push(c);
  }
  return [...groups.values()];
}
export const basicQuestion = category => ({
  EARNINGS:'실적과 다음 분기 전망이 기존의 성장 기대를 뒷받침하는지 확인하세요.',
  CONFERENCE:'사업 전망을 바꿀 새로운 발표나 일정 변경이 있는지 확인하세요. 새 발표가 없을 수도 있습니다.',
  PRODUCT:'출시·공급 일정과 실제 고객 도입이 계획대로 진행되는지 확인하세요.',
  REGULATORY:'심사·규제 결과와 사업에 적용되는 조건이 무엇인지 확인하세요.',
  FINANCING:'조달 조건, 현금 사용 계획과 기존 주주에게 미치는 영향을 확인하세요.',
}[category]||'발표 내용이 기존 계획과 어떻게 달라졌는지, 다음에 확인할 근거가 무엇인지 살펴보세요.');

function makeEntry(group,item,report,index) {
  const candidates=group?.candidates??[],c=candidates[0];
  const reportDay=aiDate(item??{}),sourceDay=dayNumber(c?.event_date_candidate)!==null?c.event_date_candidate:null;
  const date=sourceDay||reportDay;
  const conflict=Boolean(sourceDay && reportDay && sourceDay!==reportDay);
  const periodConflict=Boolean(c && dayNumber(item?.window_start)!==null && dayNumber(item?.window_end)!==null && dayNumber(sourceDay)!==null &&
    (dayNumber(sourceDay)<dayNumber(item.window_start)||dayNumber(sourceDay)>dayNumber(item.window_end)));
  const entry={
    id:c?c.id:`ai-${index}`,category:c?.category??item?.category??'OTHER',
    title:c?.title??text(item?.title),candidates,ai:item??null,
    mode:c?(item?'MERGED':'SOURCE_ONLY'):'AI_ONLY',
    sourceDate:sourceDay??null,aiDate:reportDay,
    eventDate:conflict||periodConflict?null:date??null,
    windowStart:!c&&dayNumber(item?.window_start)!==null?item.window_start:null,
    windowEnd:!c&&dayNumber(item?.window_end)!==null?item.window_end:null,
    conflict:conflict||periodConflict,
    inferred:Boolean(c&&c.year_basis!=='EXPLICIT_IN_SENTENCE'),
    candidate:Boolean(c),
    // Unconfirmed/contradictory AI text remains in the audit fold, not the headline.
    usesAIQuestion:Boolean(item?.watch && (!c || (!conflict&&!periodConflict&&reportDay===sourceDay))),
    matchNotice:c&&item?(conflict||periodConflict?'DATE_CONFLICT':reportDay?'SAME_DATE':'REPORT_UNDATED'):null,
  };
  if(item?.timing==='UNCONFIRMED'||item?.bucket==='UNKNOWN') { entry.windowStart=null;entry.windowEnd=null; }
  entry.question=entry.usesAIQuestion?item.watch:basicQuestion(entry.category);
  entry.questionLabel=entry.usesAIQuestion?'이번에 볼 질문 · AI 제안':'이번에 볼 질문 · 기본 점검';
  return entry;
}

export function buildCatalystView({ledger,report,symbol,researchDate}={}) {
  const source=matchingSourceLedger(ledger,symbol);
  const goodReport=report?.symbol===symbol&&report?.scope==='catalysts'&&
    report?.analysis_mode==='FORWARD_CATALYST_RISK'&&
    (!researchDate||report?.context?.research_date===researchDate)?report:null;
  const groups=sourceGroups(list(source?.candidates).filter(c=>c&&typeof c.id==='string'&&c.basis==='LOCAL_TEXT_RULE_CANDIDATE'));
  const aiItems=list(goodReport?.items),proposals=groups.map(g=>aiItems.map((i,n)=>
    namedSameEvent(g.candidates[0],i,goodReport,groups,aiItems)?n:-1).filter(n=>n>=0));
  const used=new Set(),entries=[];
  groups.forEach((g,n)=>{
    const p=proposals[n];
    // No greedy category matching. Multiple plausible links remain separate.
    const index=p.length===1&&proposals.filter(row=>row.includes(p[0])).length===1?p[0]:null;
    if(index!==null)used.add(index);
    entries.push(makeEntry(g,index===null?null:aiItems[index],goodReport,n));
  });
  aiItems.forEach((item,n)=>{if(!used.has(n))entries.push(makeEntry(null,item,goodReport,n));});
  entries.sort((a,b)=>Number(b.category==='EARNINGS')-Number(a.category==='EARNINGS')||
    (a.eventDate||a.sourceDate||a.aiDate||a.windowStart||'9999').localeCompare(b.eventDate||b.sourceDate||b.aiDate||b.windowStart||'9999')||a.title.localeCompare(b.title));
  const today=researchDate||source?.research_date||goodReport?.context?.research_date;
  return {entries,report:goodReport,ledger:source,researchDate:today,
    unknownCount:entries.filter(e=>!e.conflict&&!e.eventDate&&!e.windowStart).length,
    conflictCount:entries.filter(e=>e.conflict).length,
    linkedCount:entries.filter(e=>e.mode==='MERGED').length,
    sourceCount:entries.filter(e=>e.candidates.length).length,
    inputMismatch:Boolean(report&&!goodReport),
  };
}
export function visibleCatalysts(view,horizon=90) {
  const today=dayNumber(view.researchDate);if(today===null)return [];
  if(horizon==='review')return view.entries.filter(e=>e.conflict);
  if(horizon==='unknown')return view.entries.filter(e=>!e.conflict&&!e.eventDate&&!e.windowStart);
  if(![30,90,180].includes(horizon))return [];
  return view.entries.filter(e=>{
    const start=dayNumber(e.eventDate||e.windowStart),end=dayNumber(e.eventDate||e.windowEnd);
    // A conflict is never silently given a primary date or hidden behind confidence.
    if(e.conflict)return [e.sourceDate,e.aiDate].some(d=>dayNumber(d)!==null&&dayNumber(d)>=today&&dayNumber(d)<=today+horizon);
    return start!==null&&end!==null&&end>=today&&start<=today+horizon;
  });
}
export function eventDateText(entry) {
  if(entry.conflict)return '날짜 불일치 · 확인 필요';
  if(entry.eventDate)return entry.eventDate;
  if(entry.windowStart&&entry.windowEnd)return `${entry.windowStart} ~ ${entry.windowEnd}`;
  return entry.candidates[0]?.month_day_text?`${entry.candidates[0].month_day_text} · 연도 미확인`:'날짜 미확인';
}
export function dateStatus(entry) {
  if(entry.conflict)return '원문·AI 날짜가 다름';
  if(entry.candidate)return entry.eventDate?(entry.inferred?'연도 문맥 기준':'원문에 연·월·일 표기'):'월·일만 확보';
  return {ANNOUNCED_DATE:'발표 일정 · AI 추출',ANNOUNCED_WINDOW:'발표 기간 · AI 추출',ESTIMATED:'예상 일정 · 미확정'}[entry.ai?.timing]||'날짜 미확인';
}
export function eventCountdown(entry,researchDate) {
  if(entry.conflict||entry.inferred||entry.ai?.timing==='ESTIMATED')return null;
  const a=dayNumber(entry.eventDate),b=dayNumber(researchDate);if(a===null||b===null||a<b)return null;
  return a===b?'오늘 · 진행 여부 미확인':`D-${a-b}`;
}
export function nextEarningsSummary(view) {
  const items=view.entries.filter(e=>e.category==='EARNINGS' && (e.conflict||e.eventDate===null||dayNumber(e.eventDate)>=dayNumber(view.researchDate)));
  if(items.some(e=>e.conflict))return {kind:'conflict',text:'다음 실적 날짜에 서로 다른 기록이 있습니다. 해당 카드의 두 날짜를 대조하세요.'};
  if(items.some(e=>e.candidate&&e.eventDate))return {kind:'source',text:'실적 일정의 원문 후보를 확보했습니다. 연도 근거와 최신 변경 여부는 카드에서 확인하세요.'};
  if(items.some(e=>e.eventDate))return {kind:'ai',text:'실적 일정이 AI 보고서에 있습니다. 날짜 근거는 원문과 대조하세요.'};
  return {kind:'missing',text:'다음 실적의 날짜를 아직 확보하지 못했습니다. 이벤트가 없다는 뜻은 아닙니다.'};
}
