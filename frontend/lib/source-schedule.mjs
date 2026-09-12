/** Pure display helpers. Source candidates never become ANNOUNCED_DATE items. */
export function matchingSourceLedger(value,symbol){return value?.version==='source-schedule-0.6.2'&&value?.symbol===symbol&&Array.isArray(value?.candidates)?value:null;}
export function visibleSourceCandidates(ledger,horizon=90){
  return (ledger?.candidates??[]).filter(c=>horizon==='unknown'?c.horizon_state==='UNDATED':c.horizon_state==='UPCOMING'&&Number.isInteger(c.days_to_candidate)&&c.days_to_candidate>=0&&c.days_to_candidate<=Number(horizon));
}
export function sourceDateLabel(c){
  if(!c.event_date_candidate)return `${c.month_day_text??'월·일 미확인'} · 연도 미확인`;
  return `${c.event_date_candidate} · ${c.year_basis==='EXPLICIT_IN_SENTENCE'?'원문 날짜':'연도 문맥 추정'}`;
}
export function reportLinkState(c,report){
  if(!report)return 'AI 보고서 없음 · 이 원문 후보는 별도 표시';
  const matches=(report.items??[]).filter(i=>i.category===c.category);
  const same=matches.find(i=>i.event_date===c.event_date_candidate&&
    (c.category==='EARNINGS'||(c.title?.toLowerCase().split(/\s+/).filter(w=>w.length>3).some(w=>`${i.title??''} ${i.fact??''}`.toLowerCase().includes(w)))));
  if(same)return 'AI 카드에도 같은 날짜가 있음 · 독립 검증 아님';
  if(c.category==='EARNINGS')return matches.some(i=>i.event_date)?'AI 실적 날짜와 다름 · 원문 대조 필요':matches.length?'AI 보고서는 실적 날짜 미정 · 원문 후보는 아래 보존':'AI 보고서에 실적 카드 없음 · 원문 후보는 아래 보존';
  return 'AI 카드와의 연결 미확인 · 원문 후보 별도 보존';
}
