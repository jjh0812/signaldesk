// Deterministic display helpers only. Horizon filters NEVER invoke AI.
export const scopeLabel={catalysts:'다가오는 이벤트',risks:'핵심 위험'};
export const timingLabel={ANNOUNCED_DATE:'회사·기관 발표일정',ANNOUNCED_WINDOW:'회사·기관 발표기간',ESTIMATED:'예상 일정 · 미확정',UNCONFIRMED:'날짜 미확인'};
export const stateLabel={EXPOSURE:'지속 노출',REALIZED:'발생 사실 보고',CONDITIONAL:'조건부 위험',UNKNOWN:'상태 미확인'};
export const areaLabel={IR_CALENDAR:'공식 행사 달력',LATEST_EARNINGS:'최근 실적 발표',CALL_FORWARD_SCHEDULE:'실적발표 대담의 향후 일정',BUSINESS_MILESTONES:'사업·제품·규제 일정',ANNUAL_RISKS:'연차보고서 위험요인',QUARTERLY_MDA:'분기보고서·자금 사정',FINANCIAL_NOTES:'재무제표 주석·조건부 의무',RECENT_UPDATES:'최근 공시·규제 변경'};
export const coverageLabel={FOUND:'자료 연결',NOT_FOUND:'이번 검색에서 못 찾음',UNAVAILABLE:'확인하지 못함',NOT_APPLICABLE:'분석 대상 아님'};
export const publicationLabel={BEFORE_PRICE_DATE:'가격 기준일 이전 공개',AFTER_PRICE_DATE:'가격 기준일 이후 공개 · 당시 종가 반영 여부 미확인',SAME_DATE_TIME_UNKNOWN:'종가와 같은 날짜 · 공개 시각 미확인',UNKNOWN:'공개일 미확인'};
export function outlookMatches(report,context,scope){return Boolean(report&&context&&report.analysis_mode==='FORWARD_CATALYST_RISK'&&report.symbol===context.symbol&&report.context_id===context.context_id&&report.scope===scope);}
export function filterCatalysts(items=[],horizon=90){
  if(horizon==='unknown')return items.filter(x=>x.bucket==='UNKNOWN');
  const allowed=horizon===30?['D30']:horizon===90?['D30','D90']:horizon===180?['D30','D90','D180']:[];
  return items.filter(x=>allowed.includes(x.bucket));
}
export function scheduleText(item){
  if(item.timing==='UNCONFIRMED'||item.bucket==='UNKNOWN')return '날짜를 아직 확인하지 못했습니다';
  const period=item.event_date||(item.window_start&&item.window_end?`${item.window_start} ~ ${item.window_end}`:null);
  if(!period)return '날짜 미확인';
  return item.timing==='ESTIMATED'?`예상 · ${period}`:period;
}
export function countdownText(item){
  if(item.timing==='ESTIMATED'||item.timing==='UNCONFIRMED')return null;
  if(item.window_overlaps_today)return '기간 진행 중 · 발생 여부 별도 확인';
  if(!Number.isInteger(item.days_to_start)||item.days_to_start<0)return null;
  if(item.days_to_start===0)return '오늘 · 시각/진행 여부 확인';
  return `${item.event_date?'D':'기간 시작 D'}-${item.days_to_start}`;
}
export function missingScopes(reports={},context){return ['catalysts','risks'].filter(scope=>!outlookMatches(reports?.[scope],context,scope));}

// Build 06: evidence/freshness labels never promise semantic verification.
export const QUALITY_VERSION='outlook-quality-v0.6.0';
export const temporalLabel={RECENT_SOURCE_LINKED:'최근 자료 연결 · 현재성 원문 확인',OLDER_SOURCE_LINKED:'오래된 자료 · 최신 상황 재확인',OLDER_OBSERVATION:'오래된 관찰 · 최근 사실로 오해 주의',CURRENT_UNCONFIRMED:'현재 상황 미확인'};
export function hasQualityReview(report){return Boolean(report&&[QUALITY_VERSION,'outlook-quality-v0.6.1'].includes(report.quality_version));}
export function qualityMessages(report){
  if(!report)return [];
  if(!hasQualityReview(report)&&Array.isArray(report.quality_warnings)&&report.quality_warnings.length)return report.quality_warnings;
  if(!hasQualityReview(report))return ['이전 형식의 저장본입니다. 일정 근거 위치·위험의 과거/최신 구분은 아직 점검하지 않았습니다. 새 조사는 직접 동의한 경우에만 실행됩니다.'];
  return Array.isArray(report.quality_warnings)?report.quality_warnings:[];
}
export function earningsCheckLabel(value){return {DATED:'다음 실적 일정 연결',UNDATED:'다음 실적 · 날짜 미확인',NOT_FOUND:'다음 실적 일정 미확보',NOT_APPLICABLE:'기업 실적일 점검 대상 아님'}[value]??'다음 실적 점검 전';}
export function riskDisplay(item,report){
  if(!hasQualityReview(report))return {kind:'LEGACY',text:item.fact,label:'기존 보고서 · 시점 분리 전',source_ids:item.source_ids??[]};
  if(item.latest_observation)return {kind:'LATEST',text:item.latest_observation.text,label:'최근 상황에 대한 AI 설명',source_ids:item.latest_observation.source_ids??[]};
  return {kind:'UNCONFIRMED',text:'현재 상황을 확인할 근거가 부족합니다. 아래의 기존·과거 사례를 최신 변화로 해석하지 마세요.',label:'현재 상황 미확인',source_ids:[]};
}

export function readTraceLabel(value){return {OPEN_ACTION_RECORDED:'웹 열람 동작 기록 · 사실 검증 아님',LOCAL_TEXT_PROVIDED:'서버 추출 원문 제공 · 사실 검증 아님'}[value]??'본문 확보 기록 부족';}
export function candidateDateLabel(item){const c=item?.date_candidate;if(!c)return null;const text=c.event_date||(c.window_start&&c.window_end?`${c.window_start} ~ ${c.window_end}`:null);return text?`검사에서 보류한 날짜 후보: ${text} · 확정 일정 아님`:null;}
