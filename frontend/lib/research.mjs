// UI-only helpers. No credentials or provider API calls in browser code.
export const REPORT_HEADINGS = new Set(['한 줄 해석','확인한 사건과 원인 후보','공개 시점 점검','가격을 해석할 때 주의할 점','아직 확인하지 못한 것','원인 미확인']);
export function safeSourceUrl(value) {
  if(typeof value !== 'string' || value.length > 4096 || /[\u0000-\u001f]/.test(value)) return null;
  try {
    const u=new URL(value);
    if(!['https:','http:'].includes(u.protocol) || u.username || u.password) return null;
    const h=u.hostname;
    if(!h.includes('.') || h==='localhost' || /\.(localhost|local|internal)$/.test(h)) return null;
    if(/^[0-9.]+$/.test(h) || h.includes(':') || (u.port && !['80','443'].includes(u.port))) return null;
    return u.href;
  } catch { return null; }
}
export function reportLines(segments=[]) {
  const lines=[[]];
  for (const seg of segments) {
    if (Number.isInteger(seg?.citation) && seg.citation > 0) lines.at(-1).push({citation:seg.citation});
    else if(typeof seg?.text==='string') {
      const pieces=seg.text.split('\n');
      pieces.forEach((part,i)=>{if(i)lines.push([]);if(part)lines.at(-1).push({text:part});});
    }
  }
  return lines;
}
export function reportMatches(result,symbol,date) {
  return Boolean(result && result.symbol===symbol && result.event_date===date);
}
export function friendlyApiError(body,fallback='AI 분석 요청에 실패했습니다.') {
  return typeof body?.error?.message==='string' ? body.error.message : typeof body?.detail==='string' ? body.detail : fallback;
}
