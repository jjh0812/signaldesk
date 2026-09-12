'use client';
import {useEffect,useRef,useState} from 'react';
import {pct,tone} from '../lib/format.mjs';
import {friendlyApiError,reportMatches} from '../lib/research.mjs';
import {makeBrief} from '../lib/brief.mjs';
import ResearchReport from './ResearchReport.jsx';

export default function AIResearch({data,row,compact=false,onBusyChange,externalBusy=false}) {
  const [status,setStatus]=useState(null),[statusError,setStatusError]=useState('');
  const [result,setResult]=useState(null),[error,setError]=useState('');
  const [running,setRunning]=useState(false),[cacheLoading,setCacheLoading]=useState(false);
  const [consent,setConsent]=useState(false),[seconds,setSeconds]=useState(0);
  const paidFlight=useRef(false);
  const sequence=useRef(0),selectedKey=useRef(''),mounted=useRef(true);
  const key=`${data?.research_snapshot_id??''}|${row?.date??''}`;
  const symbol=data?.symbol,day=row?.date;
  selectedKey.current=key;
  useEffect(()=>{onBusyChange?.(running);},[running,onBusyChange]);
  useEffect(()=>{
    if(!status?.busy||running)return;
    const t=setInterval(()=>void loadStatus(),1200);
    return ()=>clearInterval(t);
  },[status?.busy,running]);
  async function loadStatus(signal) {
    try {
      const r=await fetch('/api/v1/ai/status',{cache:'no-store',signal});
      if(!r.ok)throw new Error('AI 상태를 읽지 못했습니다. 서버와 BUILD 04 설치 상태를 확인하세요.');
      const b=await r.json();if(mounted.current){setStatus(b);setStatusError('');}
    }catch(e){if(e.name!=='AbortError'&&mounted.current)setStatusError(e.message);}
  }
  useEffect(()=>{
    mounted.current=true;const ac=new AbortController();void loadStatus(ac.signal);
    return ()=>{mounted.current=false;ac.abort();};
  },[]);
  useEffect(()=>{
    const ac=new AbortController();const seq=++sequence.current;
    setResult(null);setError('');setCacheLoading(false);setConsent(false);
    if(!data?.research_snapshot_id||!row)return ()=>ac.abort();
    setCacheLoading(true);
    fetch(`/api/v1/ai/cache?snapshot_id=${encodeURIComponent(data.research_snapshot_id)}&event_date=${row.date}`,{signal:ac.signal,cache:'no-store'})
      .then(async r=>{const b=await r.json();if(!r.ok)throw new Error(friendlyApiError(b));return b;})
      .then(b=>{if(seq===sequence.current&&reportMatches(b.result,symbol,day))setResult(b.result);})
      .catch(e=>{if(e.name!=='AbortError'&&seq===sequence.current)setError(e.message);})
      .finally(()=>{if(seq===sequence.current)setCacheLoading(false);});
    return ()=>ac.abort();
  },[key]);
  useEffect(()=>{
    if(!running)return;setSeconds(0);const t=setInterval(()=>setSeconds(s=>s+1),1000);return ()=>clearInterval(t);
  },[running]);
  async function analyze(refreshReport=false) {
    if(paidFlight.current||running||externalBusy||status?.busy||!data||!row||!consent||!status?.configured)return;
    if(refreshReport&&!window.confirm('저장본을 읽는 것이 아니라 웹 검색과 AI 분석을 새로 1회 요청합니다. API·웹 검색 비용이 발생할 수 있습니다. 진행할까요?'))return;
    paidFlight.current=true;
    const requestKey=key,seq=++sequence.current;setRunning(true);setError('');
    const ac=new AbortController(),timer=setTimeout(()=>ac.abort(),210000);
    try {
      const response=await fetch('/api/v1/ai/analyze',{
        method:'POST',headers:{'Content-Type':'application/json','X-SignalDesk-AI':status.csrf_token},
        body:JSON.stringify({snapshot_id:data.research_snapshot_id,event_date:day,allow_paid:true,refresh_report:refreshReport}),signal:ac.signal,
      });
      const body=await response.json();
      if(!response.ok){
        if(response.status===409&&body?.error?.code==='AI_BUSY'&&mounted.current)setStatus(s=>s?{...s,busy:true}:s);
        throw new Error(friendlyApiError(body));
      }
      if(mounted.current&&selectedKey.current===requestKey&&seq===sequence.current) {
        if(!reportMatches(body,symbol,day))throw new Error('요청 날짜와 결과 날짜가 달라 결과를 표시하지 않았습니다.');
        setResult(body);
      }
    }catch(e){if(mounted.current&&selectedKey.current===requestKey&&seq===sequence.current)setError(e.name==='AbortError'?'응답 대기 시간이 지났습니다. 자동 재시도하지 않았습니다. 실행 중인 제공처 요청에 비용이 발생할 수 있습니다.':e.message);}
    finally{clearTimeout(timer);paidFlight.current=false;if(mounted.current)setRunning(false);}
  }
  const shown=reportMatches(result,symbol,day)?result:null;
  const improve=Boolean(shown && (makeBrief(shown).mode!=='QUICK'||shown.prompt_version!=='event-research-v0.4.0'));
  const controls=<div className="research-controls">
    <label className="consent-label"><input type="checkbox" checked={consent} onChange={e=>setConsent(e.target.checked)} disabled={running||externalBusy||status?.busy}/><span>티커·날짜·가격 지표를 OpenAI로 전송하며, API와 웹 검색에 별도 비용이 발생함을 확인했습니다.</span></label>
    <div className="research-action"><button type="button" className="primary-button" onClick={()=>void analyze(Boolean(shown))} disabled={!row||!status?.configured||!consent||running||externalBusy||status?.busy||cacheLoading||Boolean(shown&&!improve)}>{status?.busy&&!running?'다른 AI 작업 완료 대기…':running?<><span className="spinner"/>AI 조사 중 · {seconds}초</>:improve?'쉬운 요약으로 다시 분석 · 유료':shown?'요약·상세 함께 저장됨':'이 날짜 AI 분석 · 유료 1회 →'}</button><span>날짜 선택·펼치기만으로는 유료 호출하지 않습니다.<br/>저장 결과 24시간 재사용 · 가격 해석과 합산 하루 최대 20회 시도</span></div>
    {improve&&<p className="brief-caption">다시 분석은 기존 글의 단순 압축이 아니라 새로운 조사입니다. 새 근거에 따라 해석도 달라질 수 있습니다.</p>}
  </div>;
  return <section className="panel research-section" id="ai-research" aria-label="선택한 날짜 AI 원인 후보 분석">
    <div className="research-heading"><div><span className="eyebrow">{compact?'AI QUICK READ':'03 / QUICK BRIEF'}</span><h2>{compact?'AI로 읽는 이날의 이유':'✦ 그날, 왜 움직였을까?'}</h2><p>핵심부터 짧게 읽고, 필요한 근거와 상세 분석만 펼쳐보세요.</p></div><span className="small-badge">회고 분석 · 웹 검색</span></div>
    <div className="research-toolbar"><div className="research-selection"><strong>{symbol??'티커 선택'}</strong><span>{day??'날짜를 먼저 선택하세요'}</span>{row&&<b className={tone(row.return_1d)}>{pct(row.return_1d)}</b>}</div><span className="research-model">{status?.model??'설정 확인 중'}</span></div>
    {!shown&&controls}
    {statusError&&<div className="research-alert" role="alert">{statusError}<button className="text-button" onClick={()=>void loadStatus()}>상태 다시 확인</button></div>}
    {status?.busy&&!running&&<div className="research-progress" role="status">이전 AI 작업이 아직 서버에서 진행 중입니다. 완료 여부를 자동 확인하고 있으며, 끝나면 이 분석 버튼이 다시 활성화됩니다.</div>}
    {status&&!status.configured&&<div className="research-setup"><strong>API 키가 아직 설정되지 않았습니다.</strong><p>설치 중 키 입력을 건너뛰었다면, 별도 PowerShell 터미널에서 아래 명령을 실행하세요. 입력할 키는 채팅에 보내지 마세요.</p><code>powershell.exe -NoProfile -ExecutionPolicy Bypass -File "C:\Projects\signaldesk\Configure-AI.ps1"</code><button className="secondary-button" type="button" onClick={()=>void loadStatus()}>키 설정 후 상태 확인</button></div>}
    {error&&<div className="research-alert" role="alert">{error}</div>}
    {running&&<div className="research-progress" role="status">자료 검색과 해석을 요청했습니다. 처리 시간은 자료·모델 상태에 따라 달라집니다. 다른 날짜를 선택해도 이미 보낸 유료 요청은 취소되지 않습니다.</div>}
    {!shown&&!running&&!error&&<div className="research-empty">{cacheLoading?'이 날짜의 저장된 분석을 확인하고 있습니다.':'위 차트나 목록에서 날짜 선택 → 유료 호출 동의 → AI 분석 버튼. 결과가 없으면 원인 미확인으로 남깁니다.'}</div>}
    {shown&&<>
      <ResearchReport key={`${shown.symbol}|${shown.event_date}|${shown.generated_at}`} result={shown} row={row}/>
      <details className="brief-fold brief-controls" key={`controls|${key}`}><summary><span>AI 호출 설정{improve?' · 쉬운 요약으로 다시 분석':''}</span><small>새 요청은 동의 후 버튼을 눌러야 실행됩니다</small></summary>{controls}</details>
    </>}
    <div className="research-limitations">웹 검색 기반 회고 해석입니다. 요약은 사실 검증이나 매수·매도 신호가 아닙니다. 인용 출처와 공개 시점을 함께 확인하세요.</div>
  </section>;
}
