'use client';
import {useEffect,useRef,useState} from 'react';
import PriceChart from '../components/PriceChart';
import AIResearch from '../components/AIResearch';
import DeskOverview from '../components/DeskOverview';
import StockWatch from '../components/StockWatch';
import {RELEASE_VERSION, UI_BUILD_ID} from '../lib/release.mjs';
import {findExactDate,money,pct,pp,ratio,seoulTime,tone} from '../lib/format.mjs';
const PERIODS=[['1mo','1M'],['3mo','3M'],['6mo','6M'],['1y','1Y'],['3y','3Y']];
export default function Home(){
 const [ticker,setTicker]=useState('NVDA'),[period,setPeriod]=useState('1y'),[data,setData]=useState(null),[selected,setSelected]=useState(null);
 const [dateInput,setDateInput]=useState(''),[dateError,setDateError]=useState(''),[error,setError]=useState(''),[loading,setLoading]=useState(false);
 const [eventBusy,setEventBusy]=useState(false),[outlookBusy,setOutlookBusy]=useState(false),[watchBusy,setWatchBusy]=useState(false),[online,setOnline]=useState(false),[buildWarning,setBuildWarning]=useState('');
 const seq=useRef(0),controller=useRef(null),lookupFlight=useRef(false);const busy=eventBusy||outlookBusy||watchBusy;
 useEffect(()=>{const ac=new AbortController();fetch('/api/health',{signal:ac.signal}).then(r=>r.json()).then(h=>{setOnline(h.app==='signaldesk');if(h.ui_build_id!==UI_BUILD_ID||h.frontend_build_id!==UI_BUILD_ID)setBuildWarning('서버와 화면 버전이 다릅니다. 기존 서버를 Ctrl+C로 종료한 뒤 이 프로젝트에서 다시 실행하세요.');}).catch(()=>{});
  const s=new URLSearchParams(window.location.search).get('symbol');if(s&&/^[A-Z][A-Z0-9]{0,9}(?:-[A-Z])?$/.test(s))setTicker(s);
  return()=>{ac.abort();controller.current?.abort();};},[]);
 useEffect(()=>{if(!busy)return;const before=e=>{e.preventDefault();e.returnValue='';};window.addEventListener('beforeunload',before);return()=>window.removeEventListener('beforeunload',before);},[busy]);
 function select(row){if(busy)return;setSelected(row);setDateInput(row.date);setDateError('');}
 async function scan(symbol=ticker,nextPeriod=period){
  if(busy||lookupFlight.current)return;
  const clean=symbol.trim().toUpperCase();if(!/^[A-Z][A-Z0-9]{0,9}(?:-[A-Z])?$/.test(clean)){setError('미국 주식 티커를 입력하세요. 예: NVDA, AAPL, BRK-B');return;}
  lookupFlight.current=true;controller.current?.abort();const ac=new AbortController();controller.current=ac;const current=++seq.current;const timer=setTimeout(()=>ac.abort(),65000);
  setLoading(true);setError('');setDateError('');setData(null);setSelected(null);setDateInput('');
  try{const res=await fetch(`/api/v1/market/${encodeURIComponent(clean)}?period=${nextPeriod}`,{signal:ac.signal,cache:'no-store'});const body=await res.json();
   if(!res.ok)throw new Error(body.error?.message??'시세를 불러오지 못했습니다.');if(current!==seq.current)return;
   if(body.symbol!==clean||!Array.isArray(body.bars)||!body.summary)throw new Error('시세 응답을 확인하지 못했습니다.');
   setData(body);setPeriod(nextPeriod);setTicker(clean);const initial=body.anomalies?.[0]??body.bars.at(-1);if(initial){setSelected(initial);setDateInput(initial.date);}
  }catch(e){if(current===seq.current)setError(e.name==='AbortError'?'시세 제공처 응답이 늦어 조회를 멈췄습니다. 잠시 후 다시 조회하세요.':e.message);}
  finally{clearTimeout(timer);lookupFlight.current=false;if(current===seq.current)setLoading(false);}
 }
 function changePeriod(p){if(busy||loading)return;setPeriod(p);if(data)void scan(data.symbol,p);}
 function inspect(e){e.preventDefault();if(!data||busy)return;const row=findExactDate(data.bars,dateInput);if(row)select(row);else{setSelected(null);setDateError('이 날짜의 일봉이 없습니다. 휴장일 또는 조회 기간을 확인하세요.');}}
 const s=data?.summary;
 return <div className="ds-app">
  <header className="ds-header"><a className="ds-brand" href="/" aria-label="SignalDesk 홈">S<span>SignalDesk</span></a><div className="ds-header-right"><span className="ds-release" data-testid="release-label"><i className={online?'ds-dot online':'ds-dot'}/>v{RELEASE_VERSION} · 간단 분석</span></div></header>
  <main className="ds-main">
   {buildWarning&&<p className="ds-error" role="alert">{buildWarning}</p>}
   <section className="ds-hero"><span className="eyebrow">YOUR STOCK RESEARCH, IN ONE PLACE</span><h1>복잡한 종목 분석,<br className="ds-mobile-break"/> 핵심부터.</h1><p>가격이 움직인 이유와 앞으로의 촉매, 투자 논리가 강해지거나 틀어지는 조건을 확인하세요.</p></section>
   <section className="ds-search" aria-label="종목 조회"><form onSubmit={e=>{e.preventDefault();void scan();}}><label htmlFor="ticker">미국 주식</label><input id="ticker" aria-label="미국 주식 티커" autoComplete="off" spellCheck={false} maxLength={12} placeholder="예: NVDA" value={ticker} disabled={loading||busy} onChange={e=>setTicker(e.target.value.toUpperCase())}/><button type="submit" className="primary-button" disabled={loading||busy}>{loading?'조회 중…':'조회 →'}</button></form><div className="ds-filters" aria-label="가격 조회 기간">{PERIODS.map(([v,l])=><button type="button" aria-pressed={period===v} disabled={loading||busy} key={v} className={period===v?'active':''} onClick={()=>changePeriod(v)}>{l}</button>)}</div></section>
   <p className="ds-search-note">조회는 일봉 시세만 가져옵니다. AI 분석은 유료 표시 버튼에서 동의 후 실행됩니다.</p>
   {error&&<p className="ds-error" role="alert">{error}</p>}
   {busy&&<p className="ds-caution" role="status">요청을 처리하고 있습니다. 중복 요청을 막기 위해 완료될 때까지 종목·날짜 변경을 잠시 멈췄습니다.</p>}
   {!data?<section className="ds-welcome"><div className="ds-welcome-mark">⌁</div><h2>{loading?'일봉 데이터를 가져오고 있어요.':'티커를 입력하고 조회해 보세요.'}</h2><p>가격·급등락 원인 → 앞으로의 촉매 → 투자 논리</p><small>실제 조회 전에는 샘플 주가나 임의의 분석을 표시하지 않습니다.</small></section>:<>
    <div className="ds-market-strip"><div><span>{data.symbol} · 수정종가</span><strong>{money(s.last_close)} <small className={tone(s.last_return)}>{pct(s.last_return)}</small></strong><small>{data.meta.data_end} · 실시간 가격 아님</small></div><div><span>선택 기간 수익률</span><strong className={tone(s.range_return)}>{pct(s.range_return)}</strong><small>구간 첫 종가 대비</small></div><div><span>최근 1년 최고 종가 대비</span><strong>{pct(s.from_year_high)}</strong><small>확보된 수정종가 기준</small></div><div><span>이상 변동 탐지</span><strong>{s.anomaly_count}건</strong><small>수치 기반 탐지 · 원인 판단 아님</small></div></div>
    {data.meta.warnings?.length>0&&<div className="ds-caution" role="status">{data.meta.warnings.map((w,i)=><p key={i}>{w}</p>)}</div>}
    <nav className="ds-nav" aria-label="분석 이동"><a href="#desk-move">가격과 이유</a><a href="#desk-catalysts">앞으로의 촉매</a><a href="#desk-drivers">투자 논리</a></nav>
    <section className="ds-section" id="desk-move"><div className="ds-section-head"><div><span className="eyebrow">01 / PRICE & WHY</span><h2>언제, 왜 움직였을까?</h2></div><span className="ds-muted">차트나 아래 날짜를 선택하세요.</span></div>
     <PriceChart rows={data.bars} selectedDate={selected?.date} onSelect={select}/>
     <div className="ds-anomalies" aria-label="이상 변동 날짜">{data.anomalies?.slice(0,8).map(a=><button type="button" key={a.date} disabled={busy} aria-pressed={selected?.date===a.date} className={selected?.date===a.date?'active':''} onClick={()=>select(a)}>{a.date}<strong className={tone(a.return_1d)}>{pct(a.return_1d)}</strong></button>)}{!data.anomalies?.length&&<p className="ds-muted">선택 기간에서 기본 기준에 해당하는 이상 변동은 없습니다. 날짜를 직접 선택할 수도 있습니다.</p>}</div>
     {data.anomalies?.length>8&&<details className="ds-fold"><summary>이상 변동 {data.anomalies.length}개 전체 보기</summary><div className="ds-anomalies">{data.anomalies.slice(8).map(a=><button type="button" disabled={busy} key={a.date} onClick={()=>select(a)}>{a.date}<strong className={tone(a.return_1d)}>{pct(a.return_1d)}</strong></button>)}</div></details>}
     <form className="ds-date-form" onSubmit={inspect}><label htmlFor="day">날짜 직접 선택</label><input id="day" type="date" value={dateInput} min={data.meta.data_start} max={data.meta.data_end} disabled={busy} onChange={e=>setDateInput(e.target.value)}/><button type="submit" className="secondary-button" disabled={busy}>확인</button>{selected&&<span>거래량 {ratio(selected.volume_ratio)} · SPY 대비 {pp(selected.benchmark_spread)} <small>(단순 차이)</small></span>}</form>
     {dateError&&<p className="ds-caution" role="status">{dateError}</p>}
     <div className="ds-ai"><AIResearch data={data} row={selected} compact onBusyChange={setEventBusy} externalBusy={outlookBusy||watchBusy}/></div>
    </section>
    <DeskOverview key={data.research_snapshot_id} data={data} onBusyChange={setOutlookBusy} externalBusy={eventBusy||watchBusy}/>
    <StockWatch key={"watch-"+data.research_snapshot_id} data={data} onBusyChange={setWatchBusy} externalBusy={eventBusy||outlookBusy}/>
   </>}
   <footer className="ds-footer"><div><strong>SignalDesk</strong><span>v{RELEASE_VERSION} · <code>{UI_BUILD_ID}</code> · 로컬 리서치 · 주문·자동매매 없음</span></div><details><summary>데이터 기준과 한계</summary><p>가격은 수정 일봉이며 실시간 주가가 아닙니다. AI 원인 후보, 저장 공시 근거, 미래 이벤트와 유형별 시나리오는 서로 다릅니다. 자료 미확보는 호재·악재·이벤트가 없다는 의미가 아닙니다. 자료의 최신성과 실제 결과는 원문에서 확인하세요.</p>{data&&<p>시세 출처 Yahoo Finance via yfinance · 수집 {seoulTime(data.meta.fetched_at)} KST</p>}</details></footer>
  </main>
 </div>;
}
