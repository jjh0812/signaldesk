import {forwardInsight} from '../lib/forward-catalysts.mjs';
import {eventInsight, sourcesForEvent, splitNewsCards} from '../lib/signals.mjs';
import {safeSourceUrl} from '../lib/research.mjs';

function SourceLinks({links}) {
  return links.length ? <div className="ds106-sources">{links.slice(0,3).map((s,i)=><a key={s.url} href={s.url} target="_blank" rel="noopener noreferrer">{i?'추가 근거':'원문'} ↗</a>)}</div> : <small className="ds-muted">원문 미연결</small>;
}
export function SignalEventCard({entry,report,forward=false}) {
  const item=forward?forwardInsight(entry,report):eventInsight(entry,report);
  return <article className="ds106-event" data-testid="signal-event" data-direction={item.tone}>
    <div className="ds106-event-top"><span className={`ds106-verdict ${item.tone}`}>{item.label}</span><span className="ds106-date">{item.dateText}</span></div>
    {forward&&<p className="ds-muted">일정 구분: {({ANNOUNCED_DATE:'발표된 날짜',ANNOUNCED_WINDOW:'발표된 기간',ESTIMATED:'추정 · 확정 아님',UNCONFIRMED:'미확인'})[item.timing]??'원문 일정 후보'}{item.importance?` · 중요도 ${({HIGH:'높음',MEDIUM:'중간',LOW:'낮음'})[item.importance]} · AI 판단`:''}</p>}
    <h3>{item.title}</h3>
    <p className="ds106-meaning">{item.why}</p>
    {item.positive || item.negative ? <div className="ds106-outcomes">
      <div className="good" data-ui-feature="sd-event-upside-condition"><b><i aria-hidden="true"/>호재가 되는 조건</b><p>{item.positive || '판단 기준 미확보'}</p></div>
      <div className="bad" data-ui-feature="sd-event-downside-condition"><b><i aria-hidden="true"/>악재가 되는 조건</b><p>{item.negative || '판단 기준 미확보'}</p></div>
    </div> : <p className="ds106-no-basis">근거를 확보하기 전에는 긍정·부정을 임의로 채우지 않습니다.</p>}
    {forward&&item.watch&&<p className="th-confirm" data-ui-feature="sd-catalyst-watch"><b>발표 후 확인할 것</b> {item.watch}</p>}
    {forward&&item.importanceReason&&<p className="ds-muted">중요도 판단 근거: {item.importanceReason}</p>}
    <div className="ds106-event-bottom"><small>{item.basis}</small><SourceLinks links={item.links}/></div>
    <details className="ds106-fact"><summary>저장 내용 · 날짜 근거</summary>
      {item.originalTitle!==item.title&&<p>원래 기록: {item.originalTitle}</p>}
      <p>{item.dateLabel} · {item.unknownDate?'확정 일정이 아닙니다.':''}</p>
      {item.fact ? <p><b>저장 AI 내용:</b> {item.fact}</p> : <p>이 항목의 사실 내용을 원문과 직접 대조하지 않았습니다.</p>}
      {entry.conflict&&<p>원문 날짜 {entry.sourceDate || '미확인'} / AI 날짜 {entry.aiDate || '미확인'}</p>}
      {entry.candidates?.map(c=><p key={c.id}>{c.sentence}</p>)}
      <p>{item.note}</p>
    </details>
  </article>;
}
function NewsCard({card}) {
  const evidence=Array.isArray(card.evidence)?card.evidence:[];
  const links=evidence.flatMap(e=>{const url=safeSourceUrl(e.url);return url?[{url,title:e.title}]:[];});
  const stamp=evidence.find(e=>e.filing_date)?.filing_date;
  const tag=card.direction==='MIXED'?'상반된 영향':card.state==='REPORTED_FACT'?'공시 내용':card.state==='CONDITIONAL'?'조건부 위험':'공시상 위험';
  return <article className="ds106-news-item"><div className="ds106-news-meta"><span>{tag}</span><span>{stamp?`공시 ${stamp}`:'공시일 미확보'}</span></div><h4>{card.title}</h4><p>{card.why_it_matters}</p><SourceLinks links={links}/><details className="ds106-fact"><summary>공시 근거</summary>{evidence.map((e,i)=><div key={e.id||i}><blockquote>{e.quote}</blockquote><small>재무기간 {e.period_end||'미확인'} · 공시일 {e.filing_date||'미확인'}</small></div>)}<p>{card.limit}</p></details></article>;
}
function NewsColumn({type,title,cards,loading}) {
  return <section className={`ds106-news ${type}`}><header><h3><i aria-hidden="true"/>{title}</h3><small>연결된 근거 {cards.length}개</small></header>
    {cards.length ? <>{cards.slice(0,2).map(c=><NewsCard key={c.id} card={c}/>)}{cards.length>2&&<details className="ds106-fact"><summary>나머지 {cards.length-2}개</summary>{cards.slice(2).map(c=><NewsCard key={c.id} card={c}/>)}</details>}</> : <div className="ds106-news-empty">{loading?'저장 근거 확인 중…':'이 칸에 연결된 공시 근거가 없습니다.'}<small>전체 뉴스를 검색해 {type==='positive'?'호재':'악재'}가 없다고 확인한 결과가 아닙니다.</small></div>}
  </section>;
}
export default function NewsEventBoard({events=[],report=null,cards=[],loading=false,horizon='all',forward=false,showNews=true}) {
  const news=splitNewsCards(cards);
  return <div data-testid="news-event-board" data-ui-feature="direction-conditions-v106">
    {showNews&&<div className="ds106-news-grid"><NewsColumn type="positive" title="긍정 뉴스·근거" cards={news.positive} loading={loading}/><NewsColumn type="negative" title="부정 뉴스·리스크" cards={news.negative} loading={loading}/></div>}
    <section className="ds106-upcoming"><header className="ds106-upcoming-head"><div><h3><i aria-hidden="true"/>{horizon==='unknown'?'날짜 미확인 이벤트':'다가오는 이벤트·확인할 항목'}</h3><p>먼저 현재 판단을 읽고, 아래 두 줄에서 호재·악재가 되는 조건을 확인하세요.</p></div><b>{events.length}</b></header>
      {events.length?<>{events.slice(0,3).map(e=><SignalEventCard key={e.id} entry={e} report={report} forward={forward}/>)}{events.length>3&&<details className="ds106-fact ds106-more"><summary>나머지 이벤트 {events.length-3}개</summary>{events.slice(3).map(e=><SignalEventCard key={e.id} entry={e} report={report} forward={forward}/>)}</details>}</>:<p className="ds106-news-empty">{loading?'저장 이벤트 확인 중…':'선택한 범위에 표시할 근거를 확보하지 못했습니다. 확정된 일정이 없다는 의미는 아닙니다.'}</p>}
    </section>
    {news.other.length>0&&<details className="ds106-fact"><summary>방향을 확정하지 않은 공시 근거 {news.other.length}개</summary>{news.other.map(c=><NewsCard key={c.id} card={c}/>)}</details>}
  </div>;
}
