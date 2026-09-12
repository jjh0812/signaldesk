'use client';
import {useEffect,useRef,useState} from 'react';
import {safeSourceUrl} from '../lib/research.mjs';
import {seoulTime} from '../lib/format.mjs';
import {matchingWatchState,scanHeadline,canAutoScan,thesisItems,hasThesisBlock,thesisAxes,thesisPhase,cooldownSeconds,formatCooldown,canResumeDraft} from '../lib/stock-watch.mjs';

async function json(url,options={}){
 const response=await fetch(url,{cache:'no-store',...options});
 const result=await response.json();
 if(!response.ok){const error=new Error(result?.error?.message??`요청 실패 (${response.status}). 자동 재시도하지 않습니다.`);error.code=result?.error?.code;throw error;}
 return result;
}
function Link({url,children}){const safe=safeSourceUrl(url);return safe?<a href={safe} target="_blank" rel="noopener noreferrer">{children??'원문 ↗'}</a>:null;}
function Evidence({value}){
 return <details className="th-evidence"><summary>근거 · 원문 보기</summary>
  {(value?.sources??[]).map(s=><div className="sw-sources" key={s.id}><Link url={s.url}>{s.title} ↗</Link></div>)}
  {(value?.evidence??[]).map(e=><blockquote key={e.id}>{e.text}</blockquote>)}
  <small>발췌된 문단은 원문이 아니라 웹 조사 AI의 요약입니다. 사실·단계·날짜는 링크 원문과 대조하세요.</small>
 </details>;
}
function ThesisCard({item,index}){
 return <article className="th-question" data-testid="thesis-bottleneck">
  <div className="th-card-heading"><span>{String(index+1).padStart(2,'0')} · {thesisAxes[item.axis]??'핵심 변수'}</span><small>{item.milestone_status==='UNKNOWN'?'단계 미확인':'아직 충족 여부를 봐야 할 조건'}</small></div>
  <h4>{item.title}</h4>
  <p className="th-fact"><b>지금은</b>{item.current_fact}</p>
  <div className="th-outcomes"><div className="th-up"><b>● 상승 논리가 강해지려면</b><p>{item.upside_condition??'근거 있는 상승 조건을 충분히 연결하지 못했습니다.'}</p></div><div className="th-down"><b>● 투자 논리가 틀어지는 경우</b><p>{item.downside_condition??'근거 있는 실패 조건을 충분히 연결하지 못했습니다.'}</p></div></div>
  <p className="th-why"><b>왜 중요한가</b>{item.why_it_matters}</p>
  <p className="th-confirm"><b>다음에 확인할 것</b>{item.confirmation}</p>
  <Evidence value={item}/>
 </article>;
}
function FilingCard({item}){
 return <article className="sw-filing">
  <div className="sw-card-top"><strong>{item.form} · {item.filing_date}</strong>{item.new_since_previous&&<span className="sw-new">직전 확인 후 새 신호</span>}</div>
  {item.signals.map(signal=><div className="sw-signal" key={signal.kind}>
   <h4>{signal.label}<small>{signal.basis==='FILING_METADATA'?'서류 분류':'문구 탐지 · 사실 확정 아님'}</small></h4>
   <p>{signal.meaning}</p>
   {signal.quote&&<details><summary>탐지 문구 확인</summary><blockquote>{signal.quote}</blockquote></details>}
   <Link url={signal.url}>SEC 원문 ↗</Link>
  </div>)}
  <small className="sw-limit">예상 희석률: 미산정 · 발행량·발행 전 주식 수·주식종류 검증 필요</small>
 </article>;
}
export default function StockWatch({data,onBusyChange,externalBusy=false}){
 const symbol=data.symbol;
 const [state,setState]=useState(null),[checking,setChecking]=useState(true),[driverError,setDriverError]=useState(''),[secError,setSecError]=useState(''),[working,setWorking]=useState('');
 const [seconds,setSeconds]=useState(0),[serverBusy,setServerBusy]=useState(false),[auto,setAuto]=useState(false),[email,setEmail]=useState(''),[clock,setClock]=useState(Date.now());
 const alive=useRef(true),flight=useRef(false),latest=useRef(null);
 useEffect(()=>{onBusyChange?.(Boolean(working));},[working,onBusyChange]);
 useEffect(()=>{if(!working)return;setSeconds(0);const timer=setInterval(()=>setSeconds(n=>n+1),1000);return()=>clearInterval(timer);},[working]);
 async function load(signal){
  setChecking(true);
  try{
   const [body,status]=await Promise.all([json(`/api/v1/watch/state?symbol=${encodeURIComponent(symbol)}`,{signal}),json('/api/v1/ai/status',{signal})]);
   const matched=matchingWatchState(body,symbol);if(!matched)throw new Error('종목이 달라 저장 결과를 연결하지 않았습니다.');
   if(alive.current){setState(matched);setServerBusy(Boolean(status.busy));setDriverError('');setSecError('');}
  }catch(e){if(alive.current&&e.name!=='AbortError')setDriverError(e.message);}
  finally{if(alive.current)setChecking(false);}
 }
 useEffect(()=>{alive.current=true;const ac=new AbortController();void load(ac.signal);return()=>{alive.current=false;ac.abort();};},[symbol]);
 useEffect(()=>{
  const timer=setInterval(()=>{if(document.visibilityState!=='visible')return;json('/api/v1/ai/status').then(s=>{if(alive.current)setServerBusy(Boolean(s.busy));}).catch(()=>{});},6000);
  return()=>clearInterval(timer);
 },[]);
 // Read-only progress. It does not start or retry either paid step.
 useEffect(()=>{
  if(!['drivers','resume'].includes(working))return;
  const ac=new AbortController();let reading=false;
  const timer=setInterval(async()=>{if(reading)return;reading=true;try{const s=await json(`/api/v1/watch/state?symbol=${encodeURIComponent(symbol)}`,{signal:ac.signal});if(alive.current&&s.symbol===symbol)setState(old=>({...old,thesis_progress:s.thesis_progress}));}catch{}finally{reading=false;}},3000);
  return()=>{clearInterval(timer);ac.abort();};
 },[working,symbol]);
 useEffect(()=>{if(!state?.sec_cooldown?.active)return;setClock(Date.now());const t=setInterval(()=>{setClock(Date.now());if(cooldownSeconds(state.sec_cooldown)===0)clearInterval(t);},1000);return()=>clearInterval(t);},[state?.sec_cooldown?.retry_at_epoch]);
 async function readSecState(){
  try{const body=await json(`/api/v1/watch/state?symbol=${encodeURIComponent(symbol)}`);if(alive.current&&body.symbol===symbol)setState(old=>({...old,sec_cooldown:body.sec_cooldown,last_sec_attempt:body.last_sec_attempt,...(body.dilution?{dilution:body.dilution}:{})}));}catch{}
 }
 async function run(kind,automatic=false){
  if(flight.current||externalBusy||checking||serverBusy)return;
  const isAI=kind==='drivers'||kind==='resume';
  if(kind==='sec'&&cooldownSeconds(state?.sec_cooldown)>0)return;
  if(kind==='drivers'&&!window.confirm('투자 논리를 자동 조사합니다. 1단계: 웹 조사 1회(웹 도구 최대 8회). 2단계: 조사문 정리 1회(웹 검색 없음). 티커와 공개자료를 OpenAI에 전송하며 총 최대 2회 API 비용이 발생할 수 있습니다. 자동 유료 재시도는 없습니다. 진행할까요?'))return;
  if(kind==='resume'&&!window.confirm('저장된 웹 조사 초안만 다시 정리합니다. 새 웹 검색 없이 최대 1회 API 비용이 발생합니다. 이전 정리 결과는 유지합니다. 진행할까요?'))return;
  if(kind==='sec'&&!automatic&&!window.confirm('SEC 공개자료를 확인합니다. 식별용 이메일이 SEC 요청 헤더에 포함되며, 유료 AI는 호출하지 않습니다. 진행할까요?'))return;
  flight.current=true;setWorking(kind);if(isAI)setDriverError('');else setSecError('');
  const ac=new AbortController(),timer=setTimeout(()=>ac.abort(),isAI?395000:125000);
  try{
   const status=await json('/api/v1/ai/status',{signal:ac.signal});
   if(status.busy){setServerBusy(true);throw new Error('다른 작업이 진행 중입니다. 완료 후 확인하세요.');}
   const body=isAI?{snapshot_id:data.research_snapshot_id,allow_paid:true,refresh:true,max_paid_calls:kind==='resume'?1:2,reuse_research:kind==='resume'}:{symbol,allow_public_fetch:true};
   const result=await json(`/api/v1/watch/${isAI?'drivers':'dilution'}`,{method:'POST',headers:{'Content-Type':'application/json','X-SignalDesk-AI':status.csrf_token},body:JSON.stringify(body),signal:ac.signal});
   if(result.symbol!==symbol)throw new Error('응답 종목이 달라 연결하지 않았습니다.');
   if(alive.current){
    if(isAI){
     const partial=['STRUCTURE_FAILED','RESEARCH_ONLY','INSUFFICIENT_UPDATE'].includes(result.status);
     setState(old=>({...old,symbol,drivers:partial?(result.previous_report??old?.drivers??null):result,
      research_draft:result.research_draft??old?.research_draft,
      last_thesis_attempt:{outcome:result.status,error_code:result.error_code,ai_calls:result.ai_calls},thesis_progress:null}));
     if(partial)setDriverError(`${result.notice??'정리가 끝나지 않았습니다.'} 이번 요청 ${result.ai_calls}회 · 자동 유료 재시도 없음`);
    }else{
     setState(old=>({...old,symbol,dilution:result,last_sec_attempt:{outcome:'OK'}}));
     if(result.coverage?.errors?.length)setAuto(false);
     await readSecState();
    }
   }
  }catch(e){if(alive.current){
   const message=e.name==='AbortError'?'응답 대기가 끝났습니다. 서버 요청은 진행 중일 수 있습니다. 기존 결과를 유지하며 자동 재시도하지 않습니다.':e.message;
   if(isAI){setDriverError(message);setState(old=>({...old,last_thesis_attempt:{outcome:'FAILED',error_code:e.code}}));}
   else{setSecError(message);setAuto(false);await readSecState();}
  }}
  finally{clearTimeout(timer);flight.current=false;if(alive.current){setWorking('');json('/api/v1/ai/status').then(s=>{if(alive.current)setServerBusy(Boolean(s.busy));}).catch(()=>{});}}
 }
 async function saveContact(e){
  e.preventDefault();if(flight.current)return;
  flight.current=true;setWorking('contact');setSecError('');
  try{
   const status=await json('/api/v1/ai/status');
   await json('/api/v1/watch/contact',{method:'POST',headers:{'Content-Type':'application/json','X-SignalDesk-AI':status.csrf_token},body:JSON.stringify({email:email.trim(),allow_save:true})});
   if(alive.current){setState(old=>({...old,contact_configured:true}));setEmail('');}
  }catch(e){if(alive.current)setSecError(e.message);}
  finally{flight.current=false;if(alive.current)setWorking('');}
 }
 const cooldown=cooldownSeconds(state?.sec_cooldown,clock);
 latest.current={enabled:auto,working,externalBusy,serverBusy,contactConfigured:state?.contact_configured,cooldown,run};
 useEffect(()=>{
  if(!auto)return;
  const timer=setInterval(()=>{const current=latest.current;if(canAutoScan({...current,visible:document.visibilityState==='visible'}))void current.run('sec',true);},300000);
  return()=>clearInterval(timer);
 },[auto]);
 const report=state?.drivers,scan=state?.dilution,headline=scanHeadline(scan),items=thesisItems(report,symbol),draft=state?.research_draft;
 const disabled=checking||Boolean(working)||externalBusy||serverBusy;
 const secFailed=state?.last_sec_attempt?.outcome==='FAILED';
 const thesisFailed=['FAILED','STRUCTURE_FAILED','RESEARCH_ONLY','INSUFFICIENT','INSUFFICIENT_UPDATE'].includes(state?.last_thesis_attempt?.outcome);
 const resume=thesisFailed&&canResumeDraft(draft,symbol,draft?.research_date);
 return <section className="ds-section sw-section" id="desk-drivers" aria-label="기업별 투자 논리와 발행 감시">
  <div className="ds-section-head"><div><span className="eyebrow">03 / INVESTMENT THESIS & DILUTION WATCH</span><h2>{symbol} — 이 회사의 투자 논리는?</h2><p>사업 구조와 핵심 변수를 조사해, 무엇이 확인되면 투자 논리가 강해지거나 틀어지는지 정리합니다.</p></div><button type="button" className="ds-text-button" disabled={disabled} onClick={()=>void load()}>저장본 읽기</button></div>
  {driverError&&<p className="ds-error" role="alert">{driverError}</p>}
  {!driverError&&thesisFailed&&<p className="ds-caution">지난 분석이 끝까지 완료되지 않았거나 근거가 부족했습니다. 트리거가 없다는 뜻이 아닙니다. {state?.last_thesis_attempt?.error_code??''}</p>}
  <div className="sw-action"><button id="sd-stock-drivers-action" type="button" className="primary-button" disabled={disabled} onClick={()=>void run('drivers')}>{['drivers','resume'].includes(working)?`${thesisPhase[state?.thesis_progress?.phase]??'투자 논리 분석'} · ${seconds}초`:serverBusy?'다른 작업 완료 대기…':'투자 논리 자동 분석 · 최대 2회'}</button><span>웹 조사 → 근거 연결·정리. 화면을 열거나 저장본을 읽는 것만으로 유료 호출하지 않습니다.</span></div>
  {resume&&<button id="sd-thesis-resume-action" type="button" className="secondary-button" disabled={disabled} onClick={()=>void run('resume')}>저장 조사로 정리만 다시 · 유료 1회</button>}
  {report&&<p className="sw-meta">{report.company_name} · 조사일 {report.research_date} · 생성 {seoulTime(report.generated_at)} KST{report.stale?' · 오래된 저장본 · 새 조사 필요':''} · {report.status==='READY'?'근거 연결 완료 · AI 해석':'일부 근거만 연결 · AI 해석'} · 웹 도구 {report.web_calls??'미확인'}회{report.research_reused?' · 이전 웹 조사 재사용':''}</p>}
  <div id="sd-thesis-summary" className="th-summary">
   {hasThesisBlock(report?.business_model)&&<div className="th-business"><span>어떻게 돈을 버는가</span><p>{report.business_model.text}</p><Evidence value={report.business_model}/></div>}
   <div className="th-main"><span>핵심 투자 논리 · AI 해석</span><p>{hasThesisBlock(report?.investment_thesis)?report.investment_thesis.text:checking?'저장 결과 확인 중…':thesisFailed?'분석이 완료되지 않았습니다. 아래 조사 초안이나 오류를 확인하세요.':report?'투자 논리를 요약할 근거가 부족합니다. 연결된 조건과 미확인 사항을 확인하세요.':'위 버튼으로 공개자료를 조사하면, 이 회사에서 무엇이 달라져야 하는지 한 문장으로 정리합니다.'}</p>{hasThesisBlock(report?.investment_thesis)&&<Evidence value={report.investment_thesis}/>}</div>
  </div>
  <div id="sd-thesis-bottlenecks" className="th-questions">{items.map((item,i)=><ThesisCard key={item.id} item={item} index={i}/>)}</div>
  {report?.financing&&<div id="sd-thesis-funding" className="th-funding"><h3>자금조달에서 봐야 할 것</h3><p>{report.financing.current_state}</p><p><b>위험이 커지는 조건</b> {report.financing.risk_condition??'조건을 충분히 연결하지 못했습니다.'}</p><small>등록·발행 완료 여부와 희석률을 확정한 결과가 아닙니다. 아래 SEC 감시는 별도입니다.</small><Evidence value={report.financing}/></div>}
  {report&&<details className="ds-fold"><summary>확인하지 못한 것 · 해석의 한계</summary>{report.unresolved?.map((s,i)=><p key={i}>{s}</p>)}{report.limits?.map((s,i)=><p key={i}>{s}</p>)}</details>}
  {draft&&<details className="ds-fold th-draft"><summary>웹 조사 초안 · 원문 목록 {draft.stale?'· 오래된 저장본':''}</summary><p>조사일 {draft.research_date}. 아래는 AI 웹 조사 초안이며 검증된 투자 사실이 아닙니다. 구조화에 실패해도 확보한 조사 내용을 확인할 수 있습니다.</p><div className="th-memo">{draft.memo}</div>{draft.sources?.map(s=><div className="sw-sources" key={s.id}><Link url={s.url}>{s.title} ↗</Link></div>)}</details>}
  <div className="sw-sec">
   <div className="ds-section-head"><div><span className="eyebrow">DILUTION WATCH · 유료 AI 호출 없음</span><h3>새 주식 발행 위험, 공시에서 먼저 확인</h3><p>투자 논리 분석과 별도입니다. 등록 → 발행 조건 → 완료 관련 문구를 구분하며 미공개 증자를 예언하지 않습니다.</p></div><button id="sd-dilution-scan-action" type="button" className="secondary-button" disabled={disabled||!state?.contact_configured||cooldown>0} onClick={()=>void run('sec')}>{working==='sec'?`SEC 확인 중 · ${seconds}초`:cooldown>0?`SEC 대기 · ${formatCooldown(cooldown)}`:'SEC 지금 확인 · AI 비용 없음'}</button></div>
   {secError&&<p className="ds-error" role="alert">{secError}</p>}
   {cooldown>0&&<p className="ds-caution">SEC 접근 제한 {state?.sec_cooldown?.http_status?`(HTTP ${state.sec_cooldown.http_status})`:''} · {formatCooldown(cooldown)} 후 다시 확인할 수 있습니다. 이 제한은 위 투자 논리 조사와 별개이며, 자동 재요청하지 않습니다.</p>}
   {!checking&&!state?.contact_configured&&<form className="sw-contact" onSubmit={saveContact}><label htmlFor="watch-sec-email">SEC 요청 식별용 이메일 · 최초 1회</label><div><input id="watch-sec-email" type="email" value={email} maxLength={254} required autoComplete="off" placeholder="본인 연락 이메일" disabled={Boolean(working)} onChange={e=>setEmail(e.target.value)}/><button type="submit" className="secondary-button" disabled={Boolean(working)||!email.trim()}>저장</button></div><small>이 PC에 저장하고 SEC 요청에만 사용합니다. OpenAI로 전송하지 않습니다. CIK·JSON 파일은 입력할 필요 없습니다.</small></form>}
   <div className={`sw-sec-status ${headline.tone}`}><strong>{headline.title}</strong>{scan&&<span>마지막 확인 {seoulTime(scan.checked_at)} KST · {scan.first_scan?'첫 확인 · 과거 신호 포함':`직전 확인 후 새 신호 ${scan.new_count}개`}</span>}</div>
   {secFailed&&<p className="ds-caution">마지막 SEC 요청은 실패했습니다. {scan?'아래는 이전 저장 결과입니다.':'성공적으로 확인한 SEC 결과가 아직 없습니다.'} 코드: {state.last_sec_attempt.error_code}</p>}
   {scan&&<>
    <p className="sw-meta">대상 {scan.coverage?.from_date} ~ {scan.coverage?.through_date} · 관련 서류 {scan.coverage?.relevant_filings}개 · 본문 확인 {scan.coverage?.primary_documents_checked}개 · 미검토 {scan.coverage?.pending_documents}개</p>
    {scan.status==='PARTIAL'&&<p className="sw-meta">부분 확인입니다. SEC 접근 제한·본문 누락·확인 한도 때문에 일부 신호를 놓칠 수 있습니다.</p>}
    {scan.alerts?.slice(0,3).map(a=><FilingCard key={a.id} item={a}/>)}
    {scan.alerts?.length>3&&<details className="ds-fold"><summary>관련 공시 나머지 {scan.alerts.length-3}개</summary>{scan.alerts.slice(3).map(a=><FilingCard key={a.id} item={a}/>)}</details>}
    {!scan.alerts?.length&&<p className="sw-empty">확인한 자료에서 해당 신호를 찾지 못했습니다. 희석 위험이 없다는 뜻은 아닙니다.</p>}
    <details className="ds-fold"><summary>확인 범위와 한계</summary>{scan.limits?.map((s,i)=><p key={i}>{s}</p>)}{scan.coverage?.errors?.map((e,i)=><p key={i}>{e.accession}: {e.code}</p>)}</details>
   </>}
   <label className="sw-auto"><input type="checkbox" checked={auto} disabled={!state?.contact_configured||!scan||Boolean(working)||externalBusy||cooldown>0} onChange={e=>setAuto(e.target.checked)}/><span>이 탭이 보이는 동안 5분마다 SEC만 재확인 <small>유료 AI 자동 실행 없음 · 탭을 닫으면 중단 · 실패하면 자동 확인 해제</small></span></label>
  </div>
 </section>;
}
