export const directionLabels={POSITIVE:'긍정',NEGATIVE:'부정 경로',MIXED:'혼합',NEUTRAL:'중립',INSUFFICIENT:'판단 자료 부족'};
export const importanceLabels={HIGH:'높음',MEDIUM:'중간',LOW:'낮음',INSUFFICIENT:'규모 평가 전'};
export const claimLabels={CONTRARY_DISCLOSURE:'기존 주장과 상충하는 문구',CONTEXT_CONFLICT:'시점·범위 대조 필요',RELATED_TEXT:'관련 원문 확보 · 전체 주장 검증 아님',NO_MATCHED_PASSAGE:'대응 원문 미확보'};
export const sourceOriginLabels={BUNDLED_REVIEWED_WEB_EXCERPT:'함께 제공한 짧은 발췌',USER_SAVED_SEC_FILE:'사용자가 저장한 공시 파일',SEC_DIRECT_FETCH:'직접 확보한 SEC 원문'};
export function reportSummary(report){
 const cards=report?.cards??[];
 return {facts:cards.filter(c=>c.state==='REPORTED_FACT').length,conditional:cards.filter(c=>['CONDITIONAL','EXPOSURE'].includes(c.state)).length,
 assessments:cards.filter(c=>c.state==='ASSESSMENT').length,conflicts:(report?.old_claim_checks??[]).filter(c=>c.status==='CONTRARY_DISCLOSURE').length};
}
export function commentsByCard(report,interpretation){
 if(!report||interpretation?.corpus_hash!==report.corpus_hash)return {};
 const known=new Set(report.cards.map(c=>c.id));
 return Object.fromEntries((interpretation?.items??[]).filter(x=>known.has(x.card_id)).map(x=>[x.card_id,x]));
}
export function errorText(body,status){return body?.error?.message??`요청을 완료하지 못했습니다 (${status}). 유료 버튼으로 재시도하지 마세요.`;}
export function safeFilingUrl(value){
 try{const u=new URL(value);return u.protocol==='https:'&&u.hostname==='www.sec.gov'&&!u.username&&!u.password&&!u.search&&/^\/Archives\/edgar\/data\/\d+\/\d{18}\/[-\w.]+\.(?:htm|html|pdf)$/.test(u.pathname)?u.href:null;}catch{return null;}
}
export async function readFilingFile(file,sourceKey){
 if(!file||!Number.isFinite(file.size)||file.size<=0||file.size>6*1024*1024)throw new Error('공시 HTML/PDF 파일 하나는 6 MiB 이하로 선택하세요.');
 if(!/\.(?:htm|html|pdf)$/i.test(file.name))throw new Error('재무 JSON이 아니라 공시 HTML 또는 PDF 파일을 선택하세요.');
 if(!/^[a-f0-9]{24}$/.test(sourceKey))throw new Error('공시 연결 정보가 잘못됐습니다. 무료 저장본 읽기를 눌러 주세요.');
 const data=new Uint8Array(await file.arrayBuffer());let binary='';for(let i=0;i<data.length;i+=8192)binary+=String.fromCharCode(...data.subarray(i,i+8192));
 return {source_key:sourceKey,filename:file.name.slice(0,200),content_base64:btoa(binary)};
}
export function labelAttempt(status){return {TEXT_EXTRACTED:'본문 추출 완료',HTTP_403:'SEC 접근 거절 · 자동 재시도 없음',HTTP_429:'SEC 요청 제한 · 자동 재시도 없음',NOT_REQUESTED_AFTER_DENIAL:'앞선 거절로 요청하지 않음',NETWORK_FAILED:'통신 실패',FILING_CIK_MISMATCH:'기업 식별 불일치',FILING_PERIOD_MISMATCH:'공시기간 불일치'}[status]??status;}
