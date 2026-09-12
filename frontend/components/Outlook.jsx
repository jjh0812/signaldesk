'use client';
import {useEffect,useRef,useState} from 'react';
import UnifiedCatalysts from './UnifiedCatalysts.jsx';
import {buildCatalystView} from '../lib/unified-catalysts.mjs';
import {matchingSourceLedger} from '../lib/source-schedule.mjs';
import {seoulTime} from '../lib/format.mjs';
import {safeSourceUrl,friendlyApiError} from '../lib/research.mjs';
import {areaLabel,coverageLabel,publicationLabel,timingLabel,stateLabel,scopeLabel,outlookMatches,filterCatalysts,scheduleText,countdownText,missingScopes,temporalLabel,hasQualityReview,qualityMessages,earningsCheckLabel,riskDisplay,readTraceLabel,candidateDateLabel} from '../lib/outlook.mjs';

function SourceLinks({ids=[],sources=[]}){
  return <span className="ol-inline-sources">{ids.map(id=>{const s=sources.find(x=>x.id===id),url=safeSourceUrl(s?.url);return s&&url?<a key={id} className="inline-citation" href={url} target="_blank" rel="noopener noreferrer" title={`${s.title} · 원문 대조 필요`}>[{s.number}]</a>:null;})}</span>;
}
function CardDetail({label,text}){return text?<div className="ol-detail-line"><b>{label}</b><p>{text}</p></div>:null;}
function CatalystCard({item,report}){
  const countdown=countdownText(item);
  return <article className="ol-card ol-catalyst">
    <div className="ol-card-top"><span className={`ol-badge ${item.timing==='ESTIMATED'?'ol-amber':''}`}>{timingLabel[item.timing]}</span>{countdown&&<span className="ol-countdown">{countdown}</span>}</div>
    <div className="ol-date">{scheduleText(item)}<SourceLinks ids={item.date_source_ids} sources={report.sources}/></div>
    {item.validation_notes?.length>0&&<p className="ol-small ol-date-warning">일정 근거가 부족해 날짜를 보류했습니다. 본문에 적힌 시점도 원문 대조가 필요합니다.</p>}
    <h4>{item.title}</h4><p className="ol-fact">{item.fact}<SourceLinks ids={item.source_ids} sources={report.sources}/></p>
    <div className="ol-watch"><span>이번에 볼 질문 · AI 제안</span><p>{item.watch}</p></div>
    <details className="ol-card-fold"><summary>왜 중요하고, 무엇이 달라질까?</summary><div>
      {candidateDateLabel(item)&&<p className="oq-check-label">{candidateDateLabel(item)}</p>}
      {item.schedule_evidence&&<div className="oq-evidence-location"><b>일정 문구 위치 · AI가 추출한 내용</b><p>{item.schedule_evidence.locator}</p><p>{item.schedule_evidence.statement}<SourceLinks ids={item.schedule_evidence.source_ids} sources={report.sources}/></p><small>날짜 필드·출처·열람 동작을 대조한 상태이며 원문 사실을 독립 검증한 것은 아닙니다.</small></div>}
      <CardDetail label="왜 중요한가 · 해석" text={item.why_it_matters}/>
      <CardDetail label="기대를 지지할 조건" text={item.positive_condition}/>
      <CardDetail label="기대를 약화할 조건" text={item.negative_condition}/>
      <CardDetail label="선정 이유 · AI 판단" text={item.importance_reason}/>
      <div className="ol-detail-line"><b>일정 근거 · AI 추출</b><p>{item.date_basis}<SourceLinks ids={item.date_source_ids} sources={report.sources}/></p></div>
      {item.window_label&&<p className="ol-small">자료가 제시한 기간: {item.window_label}</p>}
      {item.window_extends_horizon&&<p className="ol-small">이 기간은 180일 조회 범위와 일부만 겹칩니다.</p>}
      {item.validation_notes?.map((n,i)=><p key={i} className="ol-small">{n}</p>)}
      <p className="ol-small">위 조건은 확인할 시나리오이며 주가 방향 예측이 아닙니다. 발표 일정도 변경될 수 있습니다.</p>
    </div></details>
  </article>;
}
function RiskCard({item,report}){
  const display=riskDisplay(item,report),quality=hasQualityReview(report);
  return <article className="ol-card ol-risk">
    <div className="ol-card-top"><span className="ol-badge ol-amber">{stateLabel[item.state]}</span><span className="ol-small">AI 분류 · 새 악재라는 뜻 아님</span></div>
    <h4>{item.title}</h4>
    {quality&&<div className={`oq-freshness ${item.temporal_status==='RECENT_SOURCE_LINKED'?'':'oq-caution'}`}><b>{temporalLabel[item.temporal_status]??'현재 상황 미확인'}</b><span>자료 공개일 {item.latest_observation?.source_published_date??'미확인'}{Number.isInteger(item.latest_source_age_days)?` · 조사일 ${item.latest_source_age_days}일 전`:''}</span></div>}
    <div className="oq-latest"><span>{display.label}</span><p className="ol-fact">{display.text}<SourceLinks ids={display.source_ids} sources={report.sources}/></p>{item.latest_observation?.as_of_date&&<small>관찰 기준 {item.latest_observation.as_of_date} · 자료 공개일과 별개</small>}</div>
    {item.mandatory_amount_notice&&<p className="ol-amount-warning">{item.mandatory_amount_notice}</p>}
    {quality&&item.temporal_notes?.map((note,i)=><p className="oq-warning-line" key={i}>{note}</p>)}
    <div className="ol-watch ol-risk-watch"><span>위험이 커지는 조건 · 확인할 가정</span><p>{item.trigger}</p></div>
    <details className="ol-card-fold"><summary>과거 사례 · 변화 · 다음 확인</summary><div>
      {quality&&<div className="oq-history"><b>과거 사례 · 이번에 생긴 손실이라는 뜻 아님</b>{item.historical_observation?<><p>{item.historical_observation.text}<SourceLinks ids={item.historical_observation.source_ids} sources={report.sources}/></p><small>관찰일 {item.historical_observation.as_of_date??'미확인'} · 자료 공개일 {item.historical_observation.source_published_date??'미확인'}</small></>:<p>별도의 과거 사례를 확인하지 못했습니다.</p>}</div>}
      {quality&&<CardDetail label="과거와 비교한 변화 · AI 해석" text={item.change_summary??'비교할 근거가 부족해 개선·악화를 단정하지 않습니다.'}/>}
      <div className="ol-detail-line"><b>기본 위험 근거 · 기존 노출을 포함</b><p>{item.fact}<SourceLinks ids={item.source_ids} sources={report.sources}/></p></div>
      <CardDetail label="사업에 미칠 영향 · 해석" text={item.mechanism}/>
      <CardDetail label="다음 확인" text={item.monitor}/>
      <CardDetail label="위험을 줄일 수 있는 근거" text={item.mitigating_factor??'이번 조사에서 완화 요인을 확인하지 못했습니다.'}/>
      <CardDetail label="금액 해석 시 주의" text={item.amount_caution}/>
      <CardDetail label="선정 이유 · AI 판단" text={item.importance_reason}/>
      <p className="ol-small">최근 120일은 자료의 나이를 안내하는 기준이지 위험이 새롭거나 해소됐다는 판정이 아닙니다. 위험의 존재는 매도 신호가 아닙니다.</p>
    </div></details>
  </article>;
}
function Evidence({report}){
  return <details className="brief-fold ol-evidence"><summary><span>근거·검색 범위·미확인 사항 <b>{report.sources.length}</b></span></summary><div className="brief-fold-content">
    <p className="ol-small">아래는 AI가 확인했다고 보고한 자료입니다. URL 연결은 검사하지만 문서 전체 열람·내용·공개일을 독립 검증한 것은 아닙니다.</p>
    <div className="ol-coverage">{report.coverage.map(c=><div key={c.area}><span>{areaLabel[c.area]??c.area}</span><b className={c.status==='FOUND'?'positive':'ol-amber-text'}>{coverageLabel[c.status]}</b><p>{c.note}<SourceLinks ids={c.source_ids} sources={report.sources}/></p></div>)}</div>
    {report.document_checks?.length>0&&<div className="oq-doc-checks"><h5>자료의 어느 부분을 확인했나?</h5>{report.document_checks.map((c,i)=><div key={i}><b>{c.areas.map(a=>areaLabel[a]??a).join(' · ')}</b><small>{readTraceLabel(c.trace_status)}</small><p>{c.locator}<SourceLinks ids={c.source_ids} sources={report.sources}/></p><p>{c.note}</p></div>)}</div>}
    <div className="ol-sources">{report.sources.map(s=>{const url=safeSourceUrl(s.url);return <div key={s.id} className="ol-source">{url?<a href={url} target="_blank" rel="noopener noreferrer"><b>[{s.number}] {s.title}</b><span>{s.domain}</span></a>:<b>안전한 원문 주소 없음</b>}<small>공개일 {s.published_date??'미확인'} · {publicationLabel[s.publication_relation]}</small>{s.fiscal_period&&<small>회계기간 · {s.fiscal_period} (AI 추출)</small>}<small>자료 유형 · {s.document_type} / {s.role} (AI 분류)</small></div>;})}</div>
    {report.unresolved.length>0&&<div className="ol-unresolved"><h5>아직 확인하지 못한 것</h5>{report.unresolved.map((s,i)=><p key={i}>{s}</p>)}</div>}
    {report.validation_notes.length>0&&<div className="ol-unresolved"><h5>날짜·근거 연결 검사</h5>{report.validation_notes.map((s,i)=><p key={i}>{s}</p>)}<p>제외한 항목: {report.excluded_item_count}개 · 의미의 정확성을 보증하지 않습니다.</p></div>}
    {report.limitations?.length>0&&<details className="ol-query-fold"><summary>이 조사로 확인할 수 없는 것</summary>{report.limitations.map((note,i)=><p key={i}>{note}</p>)}</details>}
    {report.research_plan?.length>0&&<details className="ol-query-fold"><summary>서버가 지정한 조사 계획 · 실행 보장 아님</summary>{report.research_plan.map((p,i)=><div key={i}><b>{p.goal}</b><p>{p.query}</p></div>)}</details>}
    {report.quality_limitations?.map((note,i)=><p key={i} className="ol-small">{note}</p>)}
    {report.queries?.length>0&&<details className="ol-query-fold"><summary>웹 도구에 기록된 검색어</summary>{report.queries.map((q,i)=><p key={i}>{q}</p>)}</details>}
    <p className="ol-small">모델 {report.model} · {report.elapsed_seconds}초 · 검색 {report.usage.search_calls}회 · 기타 웹 동작 {report.usage.other_web_actions}회</p>
  </div></details>;
}
function ScopeResult({report,scope,horizon,busy}){
  const [expanded,setExpanded]=useState(false);
  useEffect(()=>setExpanded(false),[report?.generated_at,horizon]);
  const isCatalyst=scope==='catalysts';
  const items=report?(isCatalyst?filterCatalysts(report.items,horizon):report.items):[];
  const shown=expanded?items:items.slice(0,3);
  return <section className={`ol-column ${isCatalyst?'':'ol-risk-column'}`} aria-label={scopeLabel[scope]}>
    <div className="ol-column-heading"><div><span className="eyebrow">{isCatalyst?'CATALYSTS / WHAT COULD CHANGE?':'RISKS / WHAT COULD GO WRONG?'}</span><h3>{isCatalyst?'AI 해석 · 주요 이벤트':'놓치면 안 되는 위험'}</h3></div><span className="small-badge">{report?`${items.length}건`:'미조사'}</span></div>
    {!report?<div className="ol-empty">{busy?<><span className="spinner"/><b>{scopeLabel[scope]} 조사 중</b><p>검색과 근거 연결을 기다리고 있습니다.</p></>:<><b>아직 조사하지 않았습니다.</b><p>조회만으로 AI 비용을 발생시키지 않습니다.<br/>위쪽 동의 후 조사 버튼을 눌러 주세요.</p></>}</div>:<>
      <div className="ol-report-meta"><span>{report.status==='PARTIAL'?'자료 일부 미확보 · 범위 확인 필요':'AI 조사 결과 · 원문 대조 필요'}</span><small>{seoulTime(report.generated_at)} KST {report.cache_hit?'· 저장본':''}</small></div>
      {qualityMessages(report).length>0&&<div className="oq-quality-banner" role="status">{isCatalyst&&<b>AI 보고서만의 점검 결과 · 위 원문 후보와 별도</b>}{qualityMessages(report).map((m,i)=><p key={i}>{m}</p>)}</div>}
      {isCatalyst&&hasQualityReview(report)&&<p className="oq-check-label">{earningsCheckLabel(report.next_earnings_check)} · 날짜 미정은 확정 일정과 별도</p>}
      {report.limitations?.filter(x=>x.startsWith('저장 실패')).map((note,i)=><p key={i} className="warning-banner">{note}</p>)}
      {shown.length?shown.map((item,i)=>isCatalyst?<CatalystCard key={`${item.title}|${i}`} item={item} report={report}/>:<RiskCard key={`${item.title}|${i}`} item={item} report={report}/>):<div className="ol-empty"><b>{isCatalyst?'선택 범위에 표시할 일정을 확보하지 못했습니다.':'근거를 연결한 위험 항목을 확보하지 못했습니다.'}</b><p>{isCatalyst?'180일 또는 날짜 미정 탭과 아래 검색 범위를 확인하세요.':'위험이 없다는 뜻이 아닙니다. 아래 미확보 자료를 확인하세요.'}</p></div>}
      {items.length>3&&<button type="button" className="ol-more" onClick={()=>setExpanded(!expanded)}>{expanded?'핵심 3개만 보기':`나머지 ${items.length-3}개 펼치기 · 무료`}</button>}
      <Evidence report={report}/>
    </>}
  </section>;
}

function OutlookContent({data,impact=null}){
  const [status,setStatus]=useState(null),[context,setContext]=useState(null),[reports,setReports]=useState({});
  const [checking,setChecking]=useState(true),[error,setError]=useState(''),[consent,setConsent]=useState(false);
  const [active,setActive]=useState(''),[seconds,setSeconds]=useState(0),[horizon,setHorizon]=useState(90);
  const [sourceLedger,setSourceLedger]=useState(null),[sourceLoading,setSourceLoading]=useState(true),[sourceError,setSourceError]=useState(''),[sourceReload,setSourceReload]=useState(0);
  useEffect(()=>{
    let live=true;const ac=new AbortController();setSourceLoading(true);setSourceError('');setSourceLedger(null);
    async function readSource(){try{
      const response=await fetch(`/api/v1/evidence/schedule?symbol=${encodeURIComponent(data.symbol)}`,{cache:'no-store',signal:ac.signal});
      const body=await response.json();if(!response.ok)throw new Error(body?.error?.message??'저장 원문 읽기 실패');
      const ledger=matchingSourceLedger(body,data.symbol);if(!ledger)throw new Error('원문 종목·형식이 달라 연결하지 않았습니다.');
      if(live)setSourceLedger(ledger);
    }catch(e){if(live&&e.name!=='AbortError')setSourceError(e.message);}finally{if(live)setSourceLoading(false);}}
    void readSource();return()=>{live=false;ac.abort();};
  },[data.symbol,sourceReload]);
  const mounted=useRef(true),inFlight=useRef(false),requestSeq=useRef(0);
  async function load(signal){
    setChecking(true);setError('');
    try{
      const [s,c]=await Promise.all([fetch('/api/v1/ai/status',{signal,cache:'no-store'}),fetch(`/api/v1/ai/outlook/cache?snapshot_id=${encodeURIComponent(data.research_snapshot_id)}`,{signal,cache:'no-store'})]);
      const sb=await s.json(),cb=await c.json();if(!s.ok)throw new Error(friendlyApiError(sb));if(!c.ok)throw new Error(friendlyApiError(cb));
      if(cb.context?.symbol!==data.symbol||cb.context?.price_context_id!==data.price_context.context_id)throw new Error('조회 종목과 조사 기준이 달라 표시하지 않았습니다. SCAN을 다시 눌러 주세요.');
      if(mounted.current){setStatus(sb);setContext(cb.context);setReports(cb.reports??{});}
    }catch(e){if(mounted.current&&e.name!=='AbortError')setError(e.message);}
    finally{if(mounted.current)setChecking(false);}
  }
  useEffect(()=>{mounted.current=true;const ac=new AbortController();void load(ac.signal);return()=>{mounted.current=false;requestSeq.current++;ac.abort();};},[]);
  useEffect(()=>{if(!active)return;setSeconds(0);const timer=setInterval(()=>setSeconds(n=>n+1),1000);return()=>clearInterval(timer);},[active]);
  async function run(scopes,refresh=false){
    if(inFlight.current||!consent||!status?.configured||!context||!scopes.length)return;
    if(refresh&&!window.confirm(`저장본을 다시 조사합니다. 최대 ${scopes.length}개 API 요청과 각 요청의 웹 검색 비용이 발생할 수 있습니다. 보강 조사는 웹 도구를 최대 10회 사용해 이전 버전보다 비용·시간이 늘 수 있습니다. 진행할까요?`))return;
    inFlight.current=true;const seq=++requestSeq.current;setError('');
    try{
      // Separate endpoints/caches: partial success survives a failed second job.
      for(const scope of scopes){
        if(!mounted.current||seq!==requestSeq.current)break;
        setActive(scope);
        const ac=new AbortController(),timer=setTimeout(()=>ac.abort(),210000);
        try{
          const response=await fetch('/api/v1/ai/outlook/analyze',{method:'POST',headers:{'Content-Type':'application/json','X-SignalDesk-AI':status.csrf_token},body:JSON.stringify({snapshot_id:data.research_snapshot_id,scope,allow_paid:true,refresh_report:refresh}),signal:ac.signal});
          const body=await response.json();if(!response.ok)throw new Error(friendlyApiError(body));
          if(mounted.current&&seq===requestSeq.current){
            if(!outlookMatches(body,context,scope))throw new Error('조사 기준이 바뀌었습니다. SCAN으로 갱신한 뒤 저장본을 확인하세요.');
            setReports(old=>({...old,[scope]:body}));
          }
        }catch(e){throw new Error(`${scopeLabel[scope]}: ${e.name==='AbortError'?'대기 시간이 지났습니다. 이미 보낸 요청에는 비용이 들 수 있습니다.':e.message} 성공한 결과는 유지하며, 남은 요청을 자동 실행하지 않았습니다.`);}
        finally{clearTimeout(timer);}
      }
    }catch(e){if(mounted.current)setError(e.message);}
    finally{inFlight.current=false;if(mounted.current)setActive('');}
  }
  const matched={catalysts:outlookMatches(reports.catalysts,context,'catalysts')?reports.catalysts:null,risks:outlookMatches(reports.risks,context,'risks')?reports.risks:null};
  const missing=missingScopes(matched,context),anyReport=Boolean(matched.catalysts||matched.risks);
  const catalystView=buildCatalystView({ledger:sourceLedger,report:matched.catalysts,symbol:data.symbol,researchDate:context?.research_date});
  const unknown=catalystView.unknownCount;
  const ready=Boolean(context&&status?.configured&&!checking&&!active);
  const controls=<div className="ol-controls">
    <label className="consent-label"><input type="checkbox" checked={consent} onChange={e=>setConsent(e.target.checked)} disabled={Boolean(active)}/><span>티커·기준일을 OpenAI에 전송하고 API·웹 검색 비용이 발생할 수 있음에 동의합니다. 이벤트와 위험은 <b>별도 조사 2개</b>이며, 함께 실행하면 최대 2개 API 요청을 순서대로 보냅니다. <b>각 요청은 웹 도구를 최대 10회 사용</b>할 수 있어 이전 버전보다 비용과 시간이 늘 수 있습니다.</span></label>
    <div className="ol-control-buttons"><button type="button" className="primary-button" disabled={!ready||!consent} onClick={()=>void run(missing.length?missing:['catalysts','risks'],!missing.length)}>{active?<><span className="spinner"/>{scopeLabel[active]} · {seconds}초</>:missing.length===2?'촉매 + 위험 조사 · 최대 2회':missing.length===1?'남은 조사 실행 · 최대 1회':'두 조사 새로 실행 · 유료'}</button>
      <button type="button" className="secondary-button" disabled={!ready||!consent} onClick={()=>void run(['catalysts'],Boolean(matched.catalysts))}>{matched.catalysts?'일정 누락 보강 조사':'이벤트만 조사'} · 유료</button>
      <button type="button" className="secondary-button" disabled={!ready||!consent} onClick={()=>void run(['risks'],Boolean(matched.risks))}>{matched.risks?'위험 최신성 보강 조사':'위험만 조사'} · 유료</button>
    </div>
    <p className="ol-small">동일 종목·조사일·가격 기준 저장본은 6시간 재사용합니다. 모든 AI 기능 합산 하루 20회 요청 시도 한도입니다. 기간 변경·근거 펼치기·저장본 확인은 새 AI 요청을 보내지 않습니다.</p>
  </div>;
  return <>
    <div className="ol-reference"><div><strong>{data.symbol}</strong><span>조사 기준 {context?.research_date??'확인 중'} · 미국 동부 날짜</span><span>가격 기준 {data.price_context.price_date} · 최신 확보 일봉</span></div><p>미래 일정은 조사일 기준입니다. 차트의 과거 날짜를 눌러도 바뀌지 않습니다.</p></div>
    {context?.price_is_stale&&<div className="warning-banner">가격 데이터는 오래된 저장본입니다. 이번 조사는 현재 공개자료 기준이며 오래된 종가의 의미를 판단하지 않습니다.</div>}
    {error&&<div className="research-alert ol-alert" role="alert">{error}<button type="button" className="text-button" disabled={Boolean(active)} onClick={()=>void load()}>상태·저장본 확인 · 무료</button></div>}
    {status&&!status.configured&&<div className="research-setup"><strong>API 키 설정이 필요합니다.</strong><p>기존 Configure-AI.ps1로 설정하세요. 키를 채팅에 보내지 마세요.</p><button type="button" className="secondary-button" onClick={()=>void load()}>설정 후 상태 확인</button></div>}
    {checking&&<p className="ol-small" role="status">설정·저장본 확인 중 · 유료 요청 없음</p>}
    <p className="uc-version-line"><span>화면 0.7.0 · 일정·방향·중요도</span><a href="/evidence" target="_blank" rel="noopener noreferrer">원문 확보 점검 ↗</a></p>
    {(anyReport||catalystView.sourceCount>0)?<details className="brief-fold ol-controls-fold" open={Boolean(active)||undefined}><summary><span>AI 조사 설정 · 선택 실행</span><small>각 조사 요청에 별도 비용</small></summary>{controls}</details>:controls}
    {active&&<p className="ol-progress" role="status">{scopeLabel[active]} 조사 중 · {seconds}초. 화면을 떠나도 이미 보낸 API 요청은 계속될 수 있습니다. 자동 재시도하지 않습니다.</p>}
    <div className="ol-tabs-row"><div className="ol-tabs" aria-label="이벤트 조회 범위">{[30,90,180,'unknown',...(catalystView.conflictCount?['review']:[])].map(h=><button type="button" key={h} aria-pressed={horizon===h} className={horizon===h?'active':''} onClick={()=>setHorizon(h)}>{h==='review'?`날짜 불일치 ${catalystView.conflictCount}`:h==='unknown'?`날짜 미정 ${unknown}`:`${h}일`}</button>)}</div><span>기간 탭은 이벤트만 필터링 · 핵심 위험은 유지</span></div>
    <div className="ol-grid"><UnifiedCatalysts view={catalystView} horizon={horizon} impact={impact} loading={sourceLoading} error={sourceError} onReload={()=>setSourceReload(n=>n+1)} busy={active==='catalysts'} reportEvidence={matched.catalysts?<Evidence report={matched.catalysts}/>:null}/><ScopeResult report={matched.risks} scope="risks" horizon={horizon} busy={active==='risks'}/></div>
    <div className="ol-footer-note">회사·기관 일정, 자료 공개일, 회계기간은 AI 추출 정보입니다. 코드는 날짜 관계·근거 URL 연결을 검사하지만 사실성까지 보증하지 않습니다. 예상일 ≠ 확정일 · 미확보 ≠ 이벤트/위험 없음 · 시나리오 ≠ 주가 예측.</div>
  </>;
}
export default function Outlook({data,impact=null}){
  return <section className="panel outlook-section" id="outlook" aria-label="다가오는 촉매와 핵심 위험">
    <div className="ol-heading"><div><span className="eyebrow">06 / CATALYSTS & RISKS</span><h2>앞으로 바뀔 것, 놓치면 안 될 것.</h2><p>일정과 그 근거, 다음에 확인할 질문을 함께 봅니다.</p></div><span className="ol-label">일정 근거 + 투자 확인 질문</span></div>
    {data?.price_context?<OutlookContent key={data.research_snapshot_id} data={data} impact={impact}/>:<div className="ol-start"><b>티커를 조회하면 시작할 수 있습니다.</b><p>실제 자료 조사 전에는 예시 이벤트나 가짜 위험을 표시하지 않습니다. 위의 SCAN은 시세만 조회하고, AI는 동의 후 별도로 실행합니다.</p></div>}
  </section>;
}
