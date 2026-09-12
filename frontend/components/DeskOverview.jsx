'use client';
import {useEffect,useRef,useState} from 'react';
import {matchedOutlook,eventView,filingCards,researchCacheIsCurrent} from '../lib/desk.mjs';
import {selectBoardEvents} from '../lib/signals.mjs';
import NewsEventBoard from './NewsEventBoard';

async function json(url,{signal,...options}={}) {
  const res=await fetch(url,{cache:'no-store',...options,signal});
  const body=await res.json();
  if(!res.ok) throw new Error(body?.error?.message || `요청 실패 (${res.status})`);
  return body;
}
function todayNY(){return new Intl.DateTimeFormat('en-CA',{timeZone:'America/New_York',year:'numeric',month:'2-digit',day:'2-digit'}).format(new Date());}
export default function DeskOverview({data,onBusyChange,externalBusy=false}) {
  const [ledger,setLedger]=useState(null),[cache,setCache]=useState(null),[filings,setFilings]=useState(null);
  const [checking,setChecking]=useState(true),[issues,setIssues]=useState([]),[horizon,setHorizon]=useState('all'),[epoch,setEpoch]=useState(0);
  const [busy,setBusy]=useState(false),[serverBusy,setServerBusy]=useState(false),[paidError,setPaidError]=useState(''),[seconds,setSeconds]=useState(0);
  const alive=useRef(true),flight=useRef(false),symbol=data.symbol;
  useEffect(()=>{onBusyChange?.(busy);},[busy,onBusyChange]);
  useEffect(()=>{if(!busy)return;setSeconds(0);const t=setInterval(()=>setSeconds(n=>n+1),1000);return()=>clearInterval(t);},[busy]);
  useEffect(()=>{
    if(!serverBusy||busy)return;
    const ac=new AbortController();
    const t=setInterval(()=>{json('/api/v1/ai/status',{signal:ac.signal}).then(s=>{if(!ac.signal.aborted)setServerBusy(Boolean(s.busy));}).catch(()=>{});},1500);
    return()=>{clearInterval(t);ac.abort();};
  },[serverBusy,busy]);
  useEffect(()=>{
    let live=true;alive.current=true;const ac=new AbortController(),timer=setTimeout(()=>ac.abort(),30000);
    setChecking(true);setIssues([]);
    const requests=[['원문 일정',`/api/v1/evidence/schedule?symbol=${symbol}`],['AI 저장 일정',`/api/v1/ai/outlook/cache?snapshot_id=${encodeURIComponent(data.research_snapshot_id)}`],['저장 공시',`/api/v1/filing-risk/state?symbol=${symbol}`]];
    const errors=[],apply=[setLedger,setCache,setFilings];
    Promise.all(requests.map(async([label,url],i)=>{
      try {const r=await json(url,{signal:ac.signal});if(!live)return;
        if(i===1?!matchedOutlook(r,data):r.symbol!==symbol)throw new Error('종목·기준 불일치');
        apply[i](r);
      } catch(e){if(live){errors.push(`${label}: ${e.name==='AbortError'?'응답 지연':e.message}`);apply[i](null);}}
    })).finally(()=>{clearTimeout(timer);if(live){setIssues(errors);setChecking(false);}});
    return()=>{live=false;alive.current=false;clearTimeout(timer);ac.abort();};
  },[symbol,data.research_snapshot_id,epoch]);
  async function refreshEvents(){
    if(flight.current||externalBusy||checking||serverBusy)return;
    flight.current=true;setPaidError('');
    const ac=new AbortController(),timer=setTimeout(()=>ac.abort(),210000);
    let sent=false;
    try {
      const status=await json('/api/v1/ai/status',{signal:ac.signal});
      if(!alive.current)return;
      if(status.busy){setServerBusy(true);throw new Error('다른 AI 작업이 진행 중입니다. 완료 후 다시 실행하세요.');}
      if(!status.configured)throw new Error('API 키 설정이 필요합니다. 프로젝트의 Configure-AI.ps1을 실행하세요.');
      if(!window.confirm('이벤트 조사 1회를 새로 실행합니다. 티커·날짜·가격 지표가 전송되며 API·웹 검색 비용이 발생할 수 있습니다. 전체 뉴스 검색 기능은 아닙니다. 진행할까요?'))return;
      setBusy(true);sent=true;
      const r=await json('/api/v1/ai/outlook/analyze',{signal:ac.signal,method:'POST',headers:{'Content-Type':'application/json','X-SignalDesk-AI':status.csrf_token},body:JSON.stringify({snapshot_id:data.research_snapshot_id,scope:'catalysts',allow_paid:true,refresh_report:Boolean(cache?.reports?.catalysts)})});
      if(!researchCacheIsCurrent(r,data))throw new Error('종목 또는 가격 기준이 달라 결과를 연결하지 않았습니다.');
      if(alive.current)setCache(old=>({context:r.context,reports:{...(old?.reports||{}),catalysts:r}}));
    } catch(e){if(alive.current)setPaidError(e.name==='AbortError'?'응답 대기가 끝났습니다. 이미 보낸 요청이 처리 중일 수 있습니다. 자동 재시도하지 않습니다.':e.message);}
    finally {clearTimeout(timer);flight.current=false;if(alive.current){setBusy(false);if(sent)json('/api/v1/ai/status').then(s=>{if(alive.current)setServerBusy(Boolean(s.busy));}).catch(()=>{});}}
  }
  const view=eventView(ledger,cache,data,180),today=todayNY();
  const all=selectBoardEvents(view,'all',today),unknown=all.filter(e=>!e.conflict&&!e.eventDate&&!e.windowStart).length;
  const events=selectBoardEvents(view,horizon,today),cards=filingCards(filings,symbol);
  return <div className="ds-overview"><section className="ds-section" id="desk-checks">
    <div className="ds-section-head"><div><span className="eyebrow">02 / NEWS & NEXT EVENTS</span><h2>{symbol} — 지금 알아야 할 것</h2><p>발생한 사실과 아직 결과가 나오지 않은 이벤트를 구분합니다.</p></div><button className="ds-text-button" disabled={checking||busy||externalBusy} onClick={()=>setEpoch(n=>n+1)}>저장본 다시 읽기</button></div>
    <div className="ds-filter-row"><div className="ds-filters" aria-label="이벤트 기간">{['all',30,90,180,'unknown'].map(h=><button key={h} type="button" aria-pressed={h===horizon} className={h===horizon?'active':''} onClick={()=>setHorizon(h)}>{h==='all'?'전체':h==='unknown'?`날짜 미확인 ${unknown}`:`${h}일`}</button>)}</div><button type="button" className="secondary-button ds-update" disabled={busy||checking||externalBusy||serverBusy||!data.research_snapshot_id} onClick={()=>void refreshEvents()}>{busy?`이벤트 조사 중 · ${seconds}초`:serverBusy?'다른 AI 작업 완료 대기…':'이벤트 새로 조사 · 유료 1회'}</button></div>
    <p className="ds-muted ds-date-note">저장 조사일 {view.researchDate||'미확보'} · 기간 필터 기준 {today} (미국 동부). 화면을 여는 것만으로 새 검색을 하지 않습니다.</p>
    {paidError&&<p className="ds-error" role="alert">{paidError} 기존 결과는 유지했습니다.</p>}
    <NewsEventBoard events={events} report={view.report} cards={cards} loading={checking} horizon={horizon}/>
    <details className="ds106-fact ds106-scope"><summary>분석 범위와 자료 상태</summary><p>초록·빨강은 연결된 공시 근거의 요약이며 전체 뉴스 수집 결과가 아닙니다. 미래 이벤트는 저장 AI 보고서 또는 저장 원문 후보입니다. 유형별 판단 기준은 새로운 기업 분석이나 주가 예측이 아닙니다.</p><p>저장 내용의 최신성·완전성·사실성은 독립 검증되지 않았습니다. 날짜 미확인 항목을 확정 일정으로 사용하지 마세요.</p>{issues.map((s,i)=><p key={i}>{s}</p>)}</details>
  </section></div>;
}
