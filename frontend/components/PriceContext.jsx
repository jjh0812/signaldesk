'use client';
import {useEffect,useRef,useState} from 'react';
import {money,pct,pp,tone} from '../lib/format.mjs';
import {friendlyApiError} from '../lib/research.mjs';
import {positionSentence,priceMatches,rangePercent,trendSentence} from '../lib/price.mjs';
import ResearchReport from './ResearchReport.jsx';

function CurrentResearch({data,metrics}) {
  const [status,setStatus]=useState(null),[statusError,setStatusError]=useState('');
  const [result,setResult]=useState(null),[error,setError]=useState('');
  const [running,setRunning]=useState(false),[checking,setChecking]=useState(false);
  const [consent,setConsent]=useState(false),[seconds,setSeconds]=useState(0);
  const sequence=useRef(0),selected=useRef(''),mounted=useRef(true);
  const key=`${data.research_snapshot_id}|${metrics.context_id}`;
  selected.current=key;
  async function loadStatus(signal) {
    try {
      const r=await fetch('/api/v1/ai/status',{signal,cache:'no-store'});
      if(!r.ok)throw new Error('AI 상태를 확인하지 못했습니다. 서버가 실행 중인지 확인하세요.');
      const b=await r.json();if(mounted.current){setStatus(b);setStatusError('');}
    }catch(e){if(e.name!=='AbortError'&&mounted.current)setStatusError(e.message);}
  }
  useEffect(()=>{mounted.current=true;const ac=new AbortController();void loadStatus(ac.signal);return ()=>{mounted.current=false;ac.abort();};},[]);
  useEffect(()=>{
    const ac=new AbortController(),seq=++sequence.current;
    setResult(null);setError('');setConsent(false);setChecking(true);
    fetch(`/api/v1/ai/price/cache?snapshot_id=${encodeURIComponent(data.research_snapshot_id)}`,{signal:ac.signal,cache:'no-store'})
      .then(async r=>{const b=await r.json();if(!r.ok)throw new Error(friendlyApiError(b));return b;})
      .then(b=>{if(seq===sequence.current&&priceMatches(b.result,metrics))setResult(b.result);})
      .catch(e=>{if(e.name!=='AbortError'&&seq===sequence.current)setError(e.message);})
      .finally(()=>{if(seq===sequence.current)setChecking(false);});
    return ()=>ac.abort();
  },[key]);
  useEffect(()=>{if(!running)return;setSeconds(0);const t=setInterval(()=>setSeconds(s=>s+1),1000);return ()=>clearInterval(t);},[running]);
  async function analyze(refresh=false) {
    if(running||!consent||!status?.configured||metrics.stale_price)return;
    if(refresh&&!window.confirm('저장본이 아닌 새 웹 검색·AI 해석을 요청합니다. 추가 API 비용이 발생할 수 있습니다. 진행할까요?'))return;
    const requestKey=key,seq=++sequence.current;
    setRunning(true);setError('');
    const ac=new AbortController(),timer=setTimeout(()=>ac.abort(),210000);
    try {
      const r=await fetch('/api/v1/ai/price/analyze',{
        method:'POST',headers:{'Content-Type':'application/json','X-SignalDesk-AI':status.csrf_token},
        body:JSON.stringify({snapshot_id:data.research_snapshot_id,allow_paid:true,refresh_report:refresh}),signal:ac.signal,
      });
      const b=await r.json();if(!r.ok)throw new Error(friendlyApiError(b));
      if(mounted.current&&selected.current===requestKey&&seq===sequence.current){
        if(!priceMatches(b,metrics))throw new Error('요청한 가격 기준과 결과가 달라 표시하지 않았습니다. SCAN을 다시 눌러 주세요.');
        setResult(b);
      }
    }catch(e){if(mounted.current&&selected.current===requestKey&&seq===sequence.current)setError(e.name==='AbortError'?'대기 시간이 지났습니다. 자동 재시도하지 않았습니다. 이미 보낸 API 요청에 비용이 발생할 수 있습니다.':e.message);}
    finally{clearTimeout(timer);if(mounted.current)setRunning(false);}
  }
  const shown=priceMatches(result,metrics)?result:null;
  const controls=<div className="research-controls pc-controls">
    <label className="consent-label"><input type="checkbox" checked={consent} onChange={e=>setConsent(e.target.checked)} disabled={running}/><span>현재 가격 해석을 위해 티커·기준일·계산 지표를 OpenAI에 보내며, API·웹 검색 비용이 발생할 수 있음에 동의합니다. 날짜별 분석과는 별도 요청입니다.</span></label>
    <div className="research-action"><button type="button" className="primary-button" onClick={()=>void analyze(Boolean(shown))} disabled={!consent||!status?.configured||running||checking||metrics.stale_price}>{running?<><span className="spinner"/>가격 조사 중 · {seconds}초</>:shown?'가격 해석 다시 조사 · 유료':'현재 가격 AI 해석 · 유료 →'}</button><span>SCAN·날짜 선택·상세 펼치기는 AI를 호출하지 않습니다.<br/>동일 기준 저장본 24시간 재사용 · 모든 AI 조사 합산 하루 20회 시도</span></div>
  </div>;
  return <div className="pc-research">
    <div className="pc-ai-heading"><div><span className="eyebrow">OPTIONAL / AI + EVIDENCE</span><h3>✦ 숫자에 사업 근거를 연결하기</h3></div><span className="research-model">{status?.model??'설정 확인 중'}</span></div>
    <p className="pc-intro">최근 실적·사업 소식·자금 조달을 조사해 기대와 위험을 설명합니다. 적정주가·실제 희석률을 자동 계산하는 기능은 아직 아닙니다.</p>
    {metrics.stale_price&&<div className="research-alert">가격 기준일이 오래되어 새 AI 해석을 보류합니다. 시세부터 갱신하세요.</div>}
    {statusError&&<div className="research-alert" role="alert">{statusError}<button className="text-button" onClick={()=>void loadStatus()}>상태 다시 확인</button></div>}
    {status&&!status.configured&&<div className="research-setup"><strong>API 키 설정이 필요합니다.</strong><p>기존 Configure-AI.ps1에서 로컬 키를 설정한 다음 상태를 다시 확인하세요. 키를 채팅에 보내지 마세요.</p><button className="secondary-button" onClick={()=>void loadStatus()}>키 설정 후 상태 확인</button></div>}
    {!shown&&controls}
    {error&&<div className="research-alert" role="alert">{error}</div>}
    {running&&<div className="research-progress" role="status">현재 가격 기준의 사업 근거를 조사 중입니다. 날짜를 눌러도 기준일은 변하지 않습니다. 화면을 떠나도 이미 보낸 요청이 취소되지는 않습니다.</div>}
    {checking&&!shown&&<p className="brief-caption">현재 가격 기준의 저장본 확인 중 · 유료 요청 없음</p>}
    {shown&&<><ResearchReport key={`${shown.context_id}|${shown.generated_at}`} result={shown}/><details className="brief-fold"><summary><span>가격 AI 호출 설정 · 다시 조사</span><small>새 요청은 추가 비용이 들 수 있습니다</small></summary>{controls}</details></>}
  </div>;
}

export default function PriceContext({data}) {
  const m=data?.price_context;
  const point=rangePercent(m?.year?.range_position);
  return <section className="panel price-context-section" id="price-context" aria-label="최신 확보 일봉의 가격 위치와 해석">
    <div className="research-heading"><div><span className="eyebrow">04 / PRICE CONTEXT</span><h2>지금 가격, 어떻게 볼까?</h2><p>예전 가격과 비교한 위치를 확인하고, 기대와 위험은 근거로 따져봅니다.</p></div><span className="small-badge">최신 확보 일봉 · 실시간 아님</span></div>
    {!m?<div className="research-empty">티커를 SCAN하면 가격 위치부터 표시합니다. 이 단계에서는 AI 비용이 발생하지 않습니다.</div>:<>
      <div className="pc-anchor"><div><strong>{m.symbol}</strong><span>가격 기준일 {m.price_date} · 미국시장</span></div><p>차트에서 과거 날짜를 선택해도 이 패널은 최신 확보 일봉 기준입니다.</p></div>
      {m.warnings?.map((w,i)=><div className="warning-banner" key={i}>{w}</div>)}
      <div className="pc-main-grid">
        <div className="pc-range-box"><span className="eyebrow">PRICE LOCATION / NOT VALUATION</span><div className="pc-price">{money(m.last_close)}<span>수정종가</span></div><p className="pc-position">{positionSentence(m)}</p>
          <div className="pc-range" aria-label="확보한 1년 종가의 최저·최고 사이 위치"><div className="pc-range-track">{point!==null&&<span className="pc-range-marker" style={{left:`${point}%`}}/>}</div><div className="pc-range-ends"><span>최저 종가 <b>{money(m.year.low)}</b><small>{m.year.low_date}</small></span><span>최고 종가 <b>{money(m.year.high)}</b><small>{m.year.high_date}</small></span></div></div>
          <p className="brief-caption">{point===null?'종가 범위가 같아 위치 비율을 계산하지 않았습니다.':'막대는 최저~최고 사이의 위치입니다. 저평가 점수·상승 확률이 아닙니다.'}</p>
          <span className="pc-observations">{m.year.observed_start} ~ {m.year.observed_end} · {m.year.observations}개 관측 {m.year.limited_history?'· 제한된 이력':''}</span>
        </div>
        <div className="pc-reading-box"><span className="eyebrow">NUMBERS FIRST / NO AI CALL</span><h3>숫자만으로 알 수 있는 것</h3><div className="pc-reading-item"><b>시장은 함께 움직였나?</b><p>{trendSentence(m)}</p></div><div className="pc-reading-item"><b>이 가격이 싼지는?</b><p>아직 판단하지 않습니다. 이익·현금·부채·주식 수를 함께 확인해야 합니다.</p></div><div className="pc-reading-item"><b>새 주식 발행으로 지분이 줄었나?</b><p>실제 희석률은 아직 계산하지 않았습니다. 주가가 내렸다는 사실만으로 추정하지 않습니다.</p></div></div>
      </div>
      <details className="brief-fold pc-metrics-fold"><summary><span>기간별 시장 비교 · 평균 가격 보기</span><small>코드 계산 · 추가 AI 호출 없음</small></summary><div className="brief-fold-content"><div className="table-wrap"><table className="pc-horizons"><thead><tr><th>관측 구간</th><th>시작 → 종료</th><th>{m.symbol}</th><th>SPY</th><th>단순 차이</th></tr></thead><tbody>{m.horizons.map(h=><tr key={h.observations}><td>{h.observations}거래일</td><td className="mono">{h.start_date?`${h.start_date} → ${h.end_date}`:'이력 부족'}</td><td className={`mono ${tone(h.stock_return)}`}>{pct(h.stock_return)}</td><td className={`mono ${tone(h.spy_return)}`}>{pct(h.spy_return)}</td><td className="mono">{pp(h.spread)}</td></tr>)}</tbody></table></div><p className="brief-caption">일봉 관측 수 기준이며 정확한 달력 월수는 아닙니다. 같은 시작일·종료일의 SPY가 없으면 비교값을 표시하지 않습니다. 베타·섹터 조정이나 원인 기여도는 아닙니다.</p><div className="pc-averages">{m.averages.map(a=><div key={a.observations}><span>최근 {a.observations}개 종가 평균</span><b>{money(a.mean_close)}</b><small>최신 종가와 차이 {pct(a.distance)}</small></div>)}</div><p className="brief-caption">평균은 최신 일봉을 포함합니다. 이동평균 위·아래에 있다는 것만으로 매수·매도 신호를 만들지 않습니다.</p></div></details>
      <details className="brief-fold legacy-price-fold"><summary><span>기존 가격 AI 보고서 · 보조 해석</span><small>일정·위험은 상단 전용 패널 사용</small></summary><p className="brief-caption">이전 저장본은 그대로 유지합니다. 기존 자유서술 보고서의 일정·자료 시점·회계기간은 원문과 대조하세요. 새로운 촉매·위험 조사는 위 전용 패널에서 실행합니다.</p><CurrentResearch data={data} metrics={m}/></details>
      <div className="research-limitations">현재 수정된 과거 종가 데이터입니다. 장중 고가·저가, 당시 정보만 재현한 분석, 자동 적정주가 산정은 포함하지 않습니다.</div>
    </>}
  </section>;
}
