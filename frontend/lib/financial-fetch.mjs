// No requests here. Keep API error codes and private-data-free retrieval traces.
export function financialApiError(payload, httpStatus) {
  let message = payload?.error?.message;
  if (!message && Array.isArray(payload?.detail)) {
    message = payload.detail.map(e => `${e.loc?.slice(1).join('.') ?? ''}: ${e.msg}`).join(' / ');
  }
  const code = typeof payload?.error?.code === 'string' ? payload.error.code : `HTTP_${httpStatus}`;
  const e = new Error(`[${code}] ${typeof message === 'string' ? message : '요청에 실패했습니다.'}`);
  e.code = code;
  e.diagnostic = payload?.error?.diagnostic ?? null;
  e.partialQuote = payload?.error?.partial_quote ?? null;
  return e;
}
export function cikInputValid(value) {
  const text = typeof value === 'string' ? value.trim() : '';
  return text === '' || (/^[0-9]{1,10}$/.test(text) && Number(text) > 0);
}
export function stepName(step) {
  return ({TICKER_DIRECTORY:'티커·기업번호 목록', SUBMISSIONS:'제출기업·티커 확인',
    LOCAL_SEC_BUNDLE:'저장 SEC JSON · 로컬 대조', COMPANYFACTS:'재무 원자료', VALUATION_QUOTE:'가치평가용 종가'})[step] ?? step;
}
export function stepStatus(step) {
  if (step.outcome === 'CACHE_NO_REQUEST') return '저장본 · 새 요청 없음';
  if (step.outcome === 'USER_INPUT') return '사용자 가격 입력 · 외부 요청 없음';
  if (step.outcome === 'COOLDOWN_NO_REQUEST') return '요청 제한 대기 · 새 요청 없음';
  if (step.http_status !== null && step.http_status !== undefined) return `HTTP ${step.http_status}${step.error_code ? ` · ${step.error_code}` : ''}`;
  return step.error_code ?? (step.outcome === 'OK' ? '확보' : step.outcome);
}
