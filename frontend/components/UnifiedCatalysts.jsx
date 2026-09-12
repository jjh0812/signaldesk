'use client';
import ImpactSignal from './ImpactSignal.jsx';
import {eventImpact} from '../lib/decision.mjs';
import {seoulTime} from '../lib/format.mjs';
import {safeSourceUrl} from '../lib/research.mjs';
import {categoryName,visibleCatalysts,eventDateText,dateStatus,eventCountdown,nextEarningsSummary} from '../lib/unified-catalysts.mjs';

function ReportLinks({item,report}) {
  const ids=new Set([...(item?.source_ids??[]),...(item?.date_source_ids??[])]);
  return <span className="uc-report-links">{(report?.sources??[]).filter(s=>ids.has(s.id)).map(s=>{
    const url=safeSourceUrl(s.url);
    return url?<a href={url} key={s.id} target="_blank" rel="noopener noreferrer" title={s.title}>AI 근거 [{s.number}] ↗</a>:null;
  })}</span>;
}
function SourceProof({candidate}) {
  const safe=safeSourceUrl(candidate.source_url);
  const url=safe&&Number.isInteger(candidate.page)?`${safe.split('#')[0]}#page=${candidate.page}`:safe;
  return <div className="uc-source-proof">
    <b>{candidate.document_title}</b>
    <p>문서 기준일 {candidate.source_document_date??'미확인'} · {candidate.page??'?'}페이지</p>
    <blockquote>{candidate.sentence}</blockquote>
    <p>{candidate.year_explanation}</p>
    {url&&<a href={url} target="_blank" rel="noopener noreferrer">원문 {candidate.page??''}페이지 열기 ↗</a>}
    <p className="uc-muted">문장 연결은 규칙 기반 추출입니다. 문서의 회사 공식성·행사 변경·진행 여부를 새로 확인하지 않았습니다.</p>
  </div>;
}
function Insight({label,value}) {
  return value?<div className="uc-insight"><b>{label}</b><p>{value}</p></div>:null;
}
export function UnifiedCatalystCard({entry,view,impact=null}) {
  const source=entry.candidates[0],ai=entry.ai,countdown=eventCountdown(entry,view.researchDate);
  const evaluation=eventImpact(entry,impact,view.ledger?.symbol??view.report?.symbol);
  const hasDecision=evaluation.kind==='AI 해석 · 저장 근거 기준';
  return <article className={`uc-card ${entry.category==='EARNINGS'?'uc-earnings':''} ${entry.conflict?'uc-conflict':''}`} data-event-id={entry.id}>
    <div className="uc-card-meta"><span className="uc-category">{categoryName[entry.category]??'기타 일정'}</span><span className="uc-date-basis">{dateStatus(entry)}</span></div>
    <div className="uc-date-row"><strong>{eventDateText(entry)}</strong>{countdown&&<span>{countdown}</span>}</div>
    <h4>{entry.title}</h4>
    <ImpactSignal entry={entry} report={impact} symbol={view.ledger?.symbol??view.report?.symbol}/>
    {entry.conflict&&<div className="uc-conflict-box" role="status"><b>어느 날짜가 맞는지 확인하지 못했습니다.</b><p>원문 후보: {entry.sourceDate??'미확인'}<br/>AI 기록: {entry.aiDate??(ai?.window_start?`${ai.window_start} ~ ${ai.window_end}`:'미확인')}</p><small>변경 공지인지 추출 오류인지 원문 대조가 필요합니다. 한 날짜로 합치지 않았습니다.</small></div>}
    <p className="uc-basis-line">{source?`근거: ${source.source_document_date??'날짜 미확인'} 문서 · ${source.page??'?'}페이지`:'근거: 저장된 AI 조사 · 원문 대조 필요'}</p>
    <p className="uc-caveat">{source?'원문 일정 후보 · 최신 변경 미확인':'최신 변경·실제 진행 여부 미확인'}</p>
    {!hasDecision&&<div className="uc-question"><span>{entry.questionLabel}</span><p>{entry.question}</p></div>}
    <details className="uc-details"><summary>근거와 해석 보기</summary><div className="uc-proof-body">
      {entry.candidates.map(c=><SourceProof key={c.id} candidate={c}/>)}
      {ai?<>
        <h5>AI 해석 · 회사가 예고한 발표 내용과 구분</h5>
        {entry.matchNotice==='REPORT_UNDATED'&&<p className="uc-note">AI 저장본은 날짜를 미확인으로 남겼지만 원문에는 날짜 후보가 있습니다. 화면의 날짜는 원문 후보에서 가져왔으며 저장본은 변경하지 않았습니다.</p>}
        <Insight label="왜 중요한가 · AI 해석" value={ai.why_it_matters}/>
        <Insight label="기대를 뒷받침할 조건 · AI 제안" value={ai.positive_condition}/>
        <Insight label="기대를 약화할 조건 · AI 제안" value={ai.negative_condition}/>
        <ReportLinks item={ai} report={view.report}/>
        <details className="uc-original"><summary>기존 AI 기록 그대로 보기</summary><h5>{ai.title}</h5><p>{ai.fact}</p><Insight label="AI가 제시한 일정 근거" value={ai.date_basis}/><Insight label="AI가 제안한 확인 질문" value={ai.watch}/>{ai.schedule_evidence&&<Insight label="AI가 인용한 일정 문구" value={ai.schedule_evidence.statement}/>}</details>
      </>:<p className="uc-no-ai">{hasDecision?'위 방향·중요도는 새 연결 해석입니다. 가격 가정이 바뀌면 해당 해석은 초기화되며, 원문 일정은 그대로 유지됩니다.':'이 일정에 연결할 AI 해석은 아직 없습니다. 위 질문은 기본 점검 항목이며 새 AI 분석 결과가 아닙니다.'}</p>}
      <p className="uc-muted">일정이나 시나리오는 주가 방향·수익률을 예측하지 않습니다. 같은 자료의 원문과 AI 해석이 일치해도 독립적인 교차 검증은 아닙니다.</p>
    </div></details>
  </article>;
}

export default function UnifiedCatalysts({view,horizon=90,loading=false,error='',onReload,busy=false,reportEvidence=null,impact=null}) {
  const items=visibleCatalysts(view,horizon),summary=nextEarningsSummary(view);
  const any=Boolean(view.ledger||view.report);
  return <section className="ol-column uc-column" aria-label="다가오는 주요 이벤트">
    <div className="ol-column-heading"><div><span className="eyebrow">CATALYSTS / EVIDENCE + INTERPRETATION</span><h3>다가오는 주요 이벤트</h3></div><span className="small-badge">{items.length}건</span></div>
    <p className="uc-section-caption">일정 근거와 확인할 질문을 한 카드에서 봅니다.</p>
    <p className="uc-section-limits">저장 자료 기준 · 전체 일정·최신 변경 미검증</p>
    {view.ledger?.source_is_expired&&<p className="uc-note">6시간이 지난 보관 원문이 포함돼 있습니다. 최신 자료로 다시 확인한 결과는 아닙니다.</p>}
    {view.inputMismatch&&<p className="uc-note" role="alert">종목 또는 조사일이 다른 AI 보고서는 연결하지 않았습니다.</p>}
    {error&&<p className="uc-note" role="alert">{error} 유료 재조사를 누르지 말고 아래 저장 원문 상태를 확인하세요.</p>}
    {loading&&<p className="uc-muted" role="status">저장 원문 연결 중 · AI 호출 없음</p>}
    {busy&&<p className="uc-muted" role="status">새 AI 조사 진행 중 · 기존 결과는 아래에 유지합니다.</p>}
    {!loading&&any&&<p className={`uc-summary uc-summary-${summary.kind}`}>{summary.text}</p>}
    {view.conflictCount>0&&<p className="uc-conflict-notice" role="status">날짜가 서로 다른 일정 {view.conflictCount}건 · ‘날짜 불일치’ 탭에서 전체를 확인하세요.</p>}
    <div className="uc-cards">{items.slice(0,3).map(entry=><UnifiedCatalystCard key={entry.id} entry={entry} view={view} impact={impact}/>)}</div>
    {items.length>3&&<details className="uc-more" key={String(horizon)}><summary>나머지 {items.length-3}개 일정 보기 · 추가 AI 호출 없음</summary><div className="uc-cards">{items.slice(3).map(entry=><UnifiedCatalystCard key={entry.id} entry={entry} view={view} impact={impact}/>)}</div></details>}
    {!items.length&&!loading&&<div className="ol-empty"><b>{any?'이 범위에 표시할 일정을 확보하지 못했습니다.':'아직 표시할 저장 일정이 없습니다.'}</b><p>‘날짜 미정’과 다른 기간을 확인하세요. 이벤트가 없다는 뜻은 아닙니다.</p></div>}
    <details className="brief-fold uc-audit"><summary><span>자료 시점·조사 기록</span></summary><div className="brief-fold-content">
      <p>원문 수집: {view.ledger?.source_collected_at?`${seoulTime(view.ledger.source_collected_at)} KST`:'없음'}</p>
      <p>AI 조사: {view.report?.generated_at?`${seoulTime(view.report.generated_at)} KST`:'없음'}</p>
      <p>연결한 일정 {view.linkedCount}건 · 원문 포함 {view.sourceCount}건. 같은 행사임을 충분히 연결하지 못한 항목은 따로 남깁니다.</p>
      <p>기존 AI 경고와 ‘날짜 미확인’ 기록은 아래에 보존했습니다. 원문에 날짜가 없다는 뜻으로 해석하지 마세요.</p>
      {view.report?.quality_warnings?.map((w,i)=><p className="uc-muted" key={i}>기존 AI 점검: {w}</p>)}
      {view.ledger?.document_checks?.map((d,i)=><p className="uc-muted" key={i}>{d.title} · {d.status} · {d.reason}</p>)}
      {view.ledger?.limitations?.map((n,i)=><p className="uc-muted" key={i}>{n}</p>)}
      <div className="uc-audit-actions"><button type="button" className="secondary-button" disabled={loading} onClick={onReload}>저장 원문 다시 표시 · 무료</button><a href="/evidence" target="_blank" rel="noopener noreferrer">원문 확보 점검 ↗</a></div>
      {reportEvidence}
    </div></details>
  </section>;
}
