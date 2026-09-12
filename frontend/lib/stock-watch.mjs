/** View-only helpers. No fetch or investment advice. */
export function matchingWatchState(value, symbol) {
  if (!value || value.symbol !== symbol) return null;
  return {...value,
    drivers: value.drivers?.symbol === symbol ? value.drivers : null,
    dilution: value.dilution?.symbol === symbol ? value.dilution : null,
    research_draft: draftForSymbol(value.research_draft,symbol)};
}
export function driversBySide(report, symbol, side) {
  if (report?.symbol !== symbol || !['UPSIDE','DOWNSIDE'].includes(side)) return [];
  return (Array.isArray(report.drivers) ? report.drivers : []).filter(d => d?.side === side && Array.isArray(d.sources) && d.sources.length).slice(0,3);
}
export function scanHeadline(report) {
  if (!report) return {title:'아직 SEC를 확인하지 않았습니다.', tone:'unknown'};
  if (report.stale) return {title:'저장된 SEC 결과 · 새 확인 필요', tone:'unknown'};
  if (report.status === 'PARTIAL') return {title:'일부 공시만 확인 · 미검토 자료 있음', tone:'watch'};
  if (report.alerts?.length) return {title:'발행 관련 신호 있음 · 확정 여부는 원문 확인', tone:'watch'};
  return {title:'검토한 범위에서 발행 관련 신호 미탐지', tone:'unknown'};
}
export function canAutoScan({enabled, visible, working, externalBusy, serverBusy, contactConfigured, cooldown=0}) {
  return enabled === true && visible === true && !working && !externalBusy && !serverBusy && contactConfigured === true && cooldown === 0;
}
export const stageLabels={PENDING:'결과 대기',ANNOUNCED:'발표됨 · 다음 조건 확인',DELAYED:'지연 관련 근거',UNKNOWN:'단계 미확인'};

export const thesisAxes={DEMAND:'고객·수요',PRODUCT:'제품·검증',EXECUTION:'실행·운영',ECONOMICS:'매출·수익성',REGULATION:'규제·허가',FUNDING:'현금·자금조달'};
export const thesisPhase={RESEARCH:'1/2 공개자료 조사',STRUCTURE:'2/2 투자 논리 정리'};
export function thesisItems(report,symbol){
 if(report?.symbol!==symbol||report?.version!=='thesis-engine-1.2.0'||report?.identity_confirmed!==true)return [];
 return (Array.isArray(report.bottlenecks)?report.bottlenecks:[]).filter(d=>d?.milestone_status!=='COMPLETED'&&Array.isArray(d?.sources)&&d.sources.length>0).slice(0,3);
}
export function hasThesisBlock(block){return typeof block?.text==='string'&&block.text.trim().length>0&&Array.isArray(block.sources)&&block.sources.length>0;}
export function draftForSymbol(value,symbol){return value?.symbol===symbol&&value?.version==='thesis-engine-1.2.0'?value:null;}
export function cooldownSeconds(value,now=Date.now()){
 const t=value?.retry_at_epoch;
 return typeof t==='number'&&Number.isFinite(t)?Math.max(0,Math.ceil(t-now/1000)):0;
}
export function formatCooldown(seconds){const n=Math.max(0,Math.ceil(Number(seconds)||0));return `${Math.floor(n/60)}분 ${String(n%60).padStart(2,'0')}초`;}
export function canResumeDraft(draft,symbol,asOf){
 return Boolean(draftForSymbol(draft,symbol)&&!draft.stale&&draft.can_resume&&draft.research_date===asOf);
}
