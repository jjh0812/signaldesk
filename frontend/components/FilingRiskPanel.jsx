'use client';
import {useEffect,useRef,useState} from 'react';
import {safeJsonDownload,percent} from '../lib/decision.mjs';
import {seoulTime} from '../lib/format.mjs';
import {directionLabels,importanceLabels,claimLabels,sourceOriginLabels,reportSummary,commentsByCard,errorText,safeFilingUrl,readFilingFile,labelAttempt} from '../lib/filing-risk.mjs';

function Evidence({e}){const url=safeFilingUrl(e.url);return <div className="f08-evidence"><p className="f08-meta">{e.title} · {e.locator} {e.page&&e.scope!=='SELECTED_EXCERPTS'?`· 추출 페이지 ${e.page}`:''}</p><blockquote>{e.quote}</blockquote>{(e.context_before||e.context_after)&&<details><summary>앞뒤 맥락</summary>{e.context_before&&<p>{e.context_before}</p>}{e.context_after&&<p>{e.context_after}</p>}</details>}<p className="f08-meta">재무기간 끝 {e.period_end??'미확인'} · 제출일 {e.filing_date??'미확인'} · {sourceOriginLabels[e.origin]??e.origin}</p>{url&&<a href={url} target="_blank" rel="noopener noreferrer">공시 원문 열기 ↗</a>}</div>;}
function RiskCard({card,ai}){return <article className={`f08-card f08-${card.direction.toLowerCase()}`}>
 <div className="f08-badges"><span>{card.state_label}</span><strong>{directionLabels[card.direction]}</strong><span>검토 중요도 · {importanceLabels[card.importance]}</span></div>
 <h4>{card.title}</h4><p className="f08-fact">{card.fact_reading}</p>
 {card.amounts?.length>0&&<p className="f08-amount">문구에 나온 금액: {card.amounts.map(x=>x.raw).join(' · ')}</p>}
 <div className="f08-meaning"><b>그래서 왜 중요한가?</b><p>{ai?.why_it_matters??card.why_it_matters}</p></div>
 <div className="f08-connection"><b>지금 가격과 연결하면</b><p>{ai?.price_connection??card.price_connection?.text}</p>{card.price_connection?.scale&&<small>{card.price_connection.scale.label}: <b>{percent(card.price_connection.scale.value,1)}</b>. {card.price_connection.scale.note}</small>}</div>
 <p className="f08-watch"><b>다음 확인</b> {ai?.watch??card.watch}</p>
 <p className="f08-meta">{ai?'AI 해석 · 제공 원문 한정 · 새 웹 검색 없음':'규칙 기반 문장 해석 · 새 AI 분석 아님'} · 중요도는 예상 수익률이 아닙니다.</p>
 <details className="f08-fold"><summary>근거 · 판단이 바뀌는 조건</summary>
   <p>{card.importance_reason}</p>{ai&&<div className="f08-sides"><p><b>긍정 조건</b><br/>{ai.upside_condition}</p><p><b>부정 조건</b><br/>{ai.downside_condition}</p></div>}
   {card.evidence.map(e=><Evidence e={e} key={e.id}/>)}<p className="f08-meta">{card.limit} 최신 변경은 확인하지 않았고 기존 가치 계산은 바꾸지 않았습니다.</p>
 </details>
 </article>;}
export default function FilingRiskPanel({symbol,calculation,csrf,disabled=false}){
 const [report,setReport]=useState(null),[ai,setAi]=useState(null),[busy,setBusy]=useState(''),[error,setError]=useState(''),[publicConsent,setPublicConsent]=useState(false),[localConsent,setLocalConsent]=useState(false),[paidConsent,setPaidConsent]=useState(false),[files,setFiles]=useState({});
 const active=useRef(false),mount=useRef(true),generation=useRef(0);const bodyKey=JSON.stringify(calculation??null);
 async function parse(res){const b=await res.json();if(!res.ok)throw new Error(errorText(b,res.status));return b;}
 async function post(path,body,signal){return parse(await fetch(path,{method:'POST',headers:{'Content-Type':'application/json','X-SignalDesk-AI':csrf},body:JSON.stringify(body),signal}));}
 async function review(signal){return post('/api/v1/filing-risk/review',{symbol,calculation:calculation??null},signal);}
 useEffect(()=>{mount.current=true;generation.current++;setAi(null);setError('');const ac=new AbortController();let live=true;
  if(!csrf)return ()=>{live=false;ac.abort();};
  const timer=setTimeout(()=>review(ac.signal).then(r=>{if(live)setReport(r);}).catch(e=>{if(live&&e.name!=='AbortError')setError(e.message);}),300);
  return()=>{live=false;clearTimeout(timer);ac.abort();};
 },[symbol,csrf,bodyKey]);
 useEffect(()=>()=>{mount.current=false;generation.current++;},[]);
 async function task(label,fn){if(active.current)return;active.current=true;const seq=++generation.current;setBusy(label);setError('');try{await fn(seq);}catch(e){if(mount.current)setError(e.message);}finally{active.current=false;if(mount.current)setBusy('');}}
 async function reload(){await task('저장 원문 읽기',async(seq)=>{const r=await review();if(mount.current&&seq===generation.current){setReport(r);setAi(null);}});}
 async function readOnline(){await task('공시 본문 확보',async(seq)=>{await post('/api/v1/filing-risk/read',{symbol,allow_public_fetch:publicConsent,source_keys:report.registry.map(s=>s.key)});const r=await review();if(mount.current&&seq===generation.current){setReport(r);setAi(null);}});}
 async function importFiles(){await task('저장 공시 읽기',async(seq)=>{const items=[];for(const [key,file]of Object.entries(files)){if(file)items.push(await readFilingFile(file,key));}if(!items.length)throw new Error('공시 파일을 먼저 선택하세요.');await post('/api/v1/filing-risk/import',{symbol,files:items,allow_local_import:localConsent});const r=await review();if(mount.current&&seq===generation.current){setReport(r);setAi(null);setLocalConsent(false);}});}
 async function interpret(){await task('원문 기반 AI 해석',async(seq)=>{if(!window.confirm('표시된 원문과 현재 계산을 OpenAI로 보내는 별도 유료 요청입니다. 새 웹 검색은 없고 동일 입력 저장본은 재사용합니다. 진행할까요?'))return;const r=await post('/api/v1/filing-risk/interpret',{symbol,calculation:calculation??null,expected_corpus_hash:report.corpus_hash,allow_paid:paidConsent});if(mount.current&&seq===generation.current)setAi(r);});}
 const locked=disabled||!!busy||!csrf,summary=reportSummary(report),comments=commentsByCard(report,ai);
 return <section className="f08-panel" id="filing-risk" aria-labelledby="f08-title">
  <div className="f08-header"><div><span className="eyebrow">08 / FILING → ECONOMIC IMPACT</span><h3 id="f08-title">공시를 읽고, 위험의 의미를 판단하기</h3><p>발생한 사실과 조건부 부담을 나눠, 내 가격 가정에 어떤 영향을 줄지 봅니다.</p></div><span className="small-badge">원문 0.8.0</span></div>
  {error&&<div className="error-banner" role="alert">{error}</div>}{busy&&<p role="status" className="f08-status"><span className="spinner"/>{busy} 중 · 중복 클릭하지 마세요.</p>}
  {!report&&!error&&<p>저장한 자료 읽는 중 · 새 AI·외부 요청 없음</p>}
  {report&&<>
   <div className="f08-statline"><span>발생 서술 <b>{summary.facts}</b></span><span>조건·노출 <b>{summary.conditional}</b></span><span>통제 평가 <b>{summary.assessments}</b></span><span>이전 주장과 상충 <b>{summary.conflicts}</b></span></div>
   <p className="f08-meta">문서 {report.coverage.documents}개 · 전체 본문 {report.coverage.full_filings}개 · 선택 발췌 {report.coverage.selected_excerpts}개. 문서 내 서술 기준이며 현재 발생·전체 위험 검증이 아닙니다.</p>
   {report.starter_note&&report.coverage.selected_excerpts>0&&<div className="f08-source-note"><b>이번에 함께 제공한 공시 발췌로 먼저 확인할 수 있어요.</b><p>{report.starter_note} 새 종목의 원문은 아래에서 직접 확보하거나 저장 파일을 불러옵니다.</p></div>}
   {summary.conflicts>0&&<div className="f08-correction"><b>이전 ‘약점 발견’ 설명을 그대로 믿으면 안 됩니다.</b><p>인용했던 문서의 통제 평가와 상충하는 문구가 있습니다. 아래에서 기준일과 원문을 함께 확인하세요. 기존 기록은 삭제하지 않습니다.</p></div>}
   <div className="f08-grid">{report.cards.map(c=><RiskCard card={c} ai={comments[c.id]} key={c.id}/>)}</div>
   {!report.cards.length&&<div className="empty">지원하는 위험 문장을 아직 확보하지 못했습니다. 위험이 없다는 뜻이 아닙니다. 아래의 공시 원문 연결을 사용하세요.</div>}
   {ai&&<p className="f08-meta">AI 해석 {seoulTime(ai.generated_at)} KST · {ai.cache_hit?'저장본 · 새 유료 호출 없음':'새 요청 1회'} · {ai.missing_card_ids?.length??0}개 항목의 AI 설명은 미완료 · 원문 카드는 유지</p>}
   <details className="f08-fold"><summary>이전 주장과 대조 · {report.old_claim_checks.length}건</summary><p className="f08-meta">본문과 같은 주제를 찾았다고 이전의 모든 문장을 승인하지 않습니다.</p>{report.old_claim_checks.map((c,i)=><div className="f08-audit" key={c.risk_id??i}><b>{c.title}</b><strong className={c.status==='CONTRARY_DISCLOSURE'?'f08-warning':''}>{claimLabels[c.status]}</strong><p>{c.reason}</p><details><summary>이전 문장 보기 · 사실로 재사용 안 함</summary><p>{c.original_claim}</p></details></div>)}</details>
   <details className="f08-fold"><summary>공시 본문 연결 · SEC 직접 읽기 또는 저장 파일</summary>
    <p>제공 발췌만으로 부족한 범위는 전체 원문을 연결하세요. 이미 읽은 자료는 접근 실패로 지우지 않습니다.</p>
    {!report.registry.length&&<p>이 종목에 연결된 SEC 연차·분기 공시 주소가 없습니다. 기존 재무/조사의 종목·출처부터 확인하세요. 유료 조사는 자동 실행하지 않습니다.</p>}
    {report.registry.map(s=><div className="f08-document" key={s.key}><div><b>{s.form} · {s.period_end}</b><p>{s.title}</p><a href={safeFilingUrl(s.url)??undefined} target="_blank" rel="noopener noreferrer">공시 원문 열기 ↗</a></div><label><span>이 문서의 저장 HTML/PDF 선택</span><input type="file" accept=".htm,.html,.pdf" disabled={locked} onChange={e=>setFiles(prev=>({...prev,[s.key]:e.target.files?.[0]??null}))}/></label></div>)}
    <p className="f08-meta">브라우저에서 원문을 열고 Ctrl+S로 HTML을 저장해 선택하세요. 재무 JSON과는 다른 파일입니다. CIK·문서 종류·기간이 맞지 않으면 저장하지 않습니다. 파일 하나 최대 6 MiB.</p>
    <label className="consent"><input type="checkbox" checked={localConsent} disabled={locked} onChange={e=>setLocalConsent(e.target.checked)}/>선택한 공시 파일을 이 PC의 서버에 저장하고 본문을 추출하는 데 동의합니다. OpenAI·외부 서버로 보내지 않습니다.</label>
    <button className="secondary-button" disabled={locked||!localConsent||!Object.values(files).some(Boolean)} onClick={()=>void importFiles()}>저장 공시 불러오기 · 외부 요청 없음</button>
    <hr/>
    <label className="consent"><input type="checkbox" checked={publicConsent} disabled={locked} onChange={e=>setPublicConsent(e.target.checked)}/>기존 연락 이메일로 SEC의 선택된 공시 최대 두 개를 요청합니다. 자동 우회·AI 호출은 없습니다.</label>
    <button className="secondary-button" disabled={locked||!publicConsent||!report.registry.length} onClick={()=>void readOnline()}>공시 본문 가져오기 · AI 비용 없음</button>
    {report.attempts?.map((a,i)=><p className="f08-meta" key={i}>{labelAttempt(a.status)} · {a.url}</p>)}
   </details>
   <details className="f08-fold"><summary>원문을 이용한 AI 경제적 해석 · 선택 · 유료</summary>
    <p>위의 사실·조건·금액은 유지하고, 확보한 문구와 현재 계산을 연결하는 짧은 설명을 생성합니다. 이전 AI 주장은 입력에서 제외합니다. 새 웹 검색은 하지 않습니다.</p>
    <label className="consent"><input type="checkbox" disabled={locked} checked={paidConsent} onChange={e=>setPaidConsent(e.target.checked)}/>원문과 현재 재무·계산을 OpenAI에 보내는 별도 유료 요청에 동의합니다. 키·SEC 연락 이메일은 보내지 않습니다.</label>
    <button className="primary-button" disabled={locked||!paidConsent||!report.cards.length} onClick={()=>void interpret()}>원문 기반 투자 해석 · 유료 1회</button>
    <p className="f08-meta">같은 입력은 6시간 재사용 · 기존 합산 하루 20회 한도 · 자동 재시도 없음 · 인용 연결 검사는 문장 의미의 완전한 검증이 아닙니다.</p>
   </details>
   <details className="f08-fold"><summary>추가 문구·조사 범위</summary><p>이번 문구에서 찾지 못한 주제: {report.coverage.topics_not_found.join(', ')||'없음'} — 위험이 없다는 판단이 아닙니다.</p>{report.additional_passages.map(c=><div key={c.id} className="f08-audit"><b>{c.title}</b><p>{c.fact_reading}</p>{c.evidence.map(e=><Evidence e={e} key={e.id}/>)}</div>)}</details>
   <div className="f08-actions"><button className="text-button" disabled={locked} onClick={()=>void reload()}>저장 원문 다시 읽기 · 무료</button><button className="secondary-button" disabled={locked} onClick={()=>safeJsonDownload({report,interpretation:ai},`SignalDesk_${symbol}_FilingRisk.json`)}>원문·해석 JSON 저장</button><small>기존 재무 입력·가치 계산·과거 AI 보고서는 변경하지 않습니다.</small></div>
  </>}
 </section>;
}
