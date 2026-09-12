'use client';
import {money,pct,pp,tone,seoulTime} from '../lib/format.mjs';
import {safeSourceUrl} from '../lib/research.mjs';
import {displayProse,headingOf,makeBrief} from '../lib/brief.mjs';
import {makePriceBrief,priceHeading} from '../lib/price.mjs';

function Inline({line,refs}) {
  return line.map((seg,i)=>{
    if(typeof seg.text==='string')return <span key={i}>{displayProse(seg.text)}</span>;
    const c=refs.get(seg.citation),url=safeSourceUrl(c?.url);
    return url?<a key={i} href={url} title={c.title} target="_blank" rel="noopener noreferrer" className="inline-citation">[{c.number}]</a>:null;
  });
}
export function ReportLines({lines,citations=[]}) {
  const refs=new Map(citations.map(c=>[c.number,c]));
  return <div className="research-prose">{lines.map((line,i)=>{
    const h=headingOf(line)??priceHeading(line);
    if(h)return <h3 key={i}>{h}</h3>;
    if(!line.length)return <div className="research-spacer" key={i}/>;
    return <p key={i}><Inline line={line} refs={refs}/></p>;
  })}</div>;
}

export default function ResearchReport({result,row}) {
  const current=result?.analysis_mode==='CURRENT_PRICE_RESEARCH';
  const view=current?makePriceBrief(result):makeBrief(result),citations=Array.isArray(result.citations)?result.citations:[];
  const refs=new Map(citations.map(c=>[c.number,c]));
  const obs=result.observation??row??{};
  const consulted=Array.isArray(result.consulted_sources)?result.consulted_sources:[];
  const usage=result.usage??{};
  return <div className="brief-report" data-testid="brief-report">
    <div className="brief-heading">
      <div><span className="eyebrow">{view.mode==='QUICK'?'THE QUICK READ':'SAVED RESEARCH'}</span><h3>{view.title}</h3></div>
      <span className="small-badge brief-status">{view.mode==='UNCONFIRMED'?(current?'해석 보류':'원인 미확인'):(current?'AI 설명 · 가치평가 아님':'AI 설명 · 원인 확정 아님')}</span>
    </div>
    {!current&&<div className="brief-metrics" aria-label="코드로 계산한 가격 비교">
      <div><span>{result.symbol} 당일</span><strong className={tone(obs.return_1d)}>{pct(obs.return_1d)}</strong><small>수정종가 {money(obs.close)}</small></div>
      <div><span>시장 전체 · SPY</span><strong className={tone(obs.benchmark_return)}>{pct(obs.benchmark_return)}</strong><small>같은 관측 기간</small></div>
      <div><span>시장과의 차이</span><strong className={tone(obs.benchmark_spread)}>{pp(obs.benchmark_spread)}</strong><small>단순 차이 · 원인 기여도 아님</small></div>
    </div>}
    {view.mode==='LEGACY_EXCERPT'&&<div className="brief-legacy-note">기존 저장본에서 문단을 발췌했습니다. 새 AI 요약은 아니며, 추가 호출은 없습니다. 아래 <b>AI 호출 설정</b>에서 동의 후 쉬운 요약으로 다시 분석할 수 있습니다.</div>}
    {view.mode==='FORMAT_FALLBACK'&&<div className="brief-legacy-note">짧은 요약의 길이·형식 또는 인용 연결을 확인하지 못해 상세 보고서를 보존했습니다. 내용을 억지로 자르거나 유료 재시도하지 않았습니다.</div>}
    <div className="brief-cards">
      {view.cards.map((card,i)=><article className={`brief-card brief-card-${i}`} key={card.title}><div className="brief-card-top"><span className="brief-number">0{i+1}</span><h4>{card.title}</h4></div><div>{card.lines.map((line,j)=><p key={j}><Inline line={line} refs={refs}/></p>)}</div></article>)}
    </div>
    <div className="brief-bottom"><span>{current?'가격 기준일·자료 공개일 확인 필요 · 적정주가 산정 아님':'회고 분석 · 공개 시점과 실제 영향은 원문 확인 필요'}</span><span>{seoulTime(result.generated_at)} KST {result.cache_hit?'· 저장본':'· '+result.elapsed_seconds+'초'}</span></div>
    <details className="brief-fold" data-testid="evidence-fold">
      <summary><span>근거 보기 <b>{citations.length}</b></span><small>인용 출처 · 누르면 펼쳐집니다</small></summary>
      <div className="brief-fold-content"><p className="brief-caption">인용 링크가 있다는 뜻이며, 그 내용의 정확성이나 주가 변동 원인을 독립 검증했다는 뜻은 아닙니다.</p><div className="brief-source-grid">{citations.map(c=>{const url=safeSourceUrl(c.url);return url?<a key={c.number} href={url} target="_blank" rel="noopener noreferrer" className="research-source"><span>[{c.number}] {c.domain} ↗</span><strong>{c.title}</strong></a>:null;})}</div>{result.unmapped_citation_count>0&&<p className="inline-warning">일부 인용 위치를 연결하지 못했습니다. 요약 문장과 원문을 직접 대조하세요.</p>}
      {consulted.length>0&&<details className="research-consulted"><summary>검색 중 참고한 URL ({consulted.length}) · 전부 원인 근거는 아닙니다</summary>{consulted.map((c,i)=>{const url=safeSourceUrl(c.url);return url?<a key={i} href={url} target="_blank" rel="noopener noreferrer">{c.title} ↗</a>:null;})}</details>}</div>
    </details>
    <details className="brief-fold" data-testid="detail-fold"><summary><span>상세 분석 펼치기</span><small>{current?'가격 위치 · 사업 근거 · 자금 조달 · 다음 확인':'사건 · 발표 시점 · 가격 해석 · 미확인 사항'}</small></summary><div className="brief-fold-content"><ReportLines lines={view.detailLines} citations={citations}/></div></details>
    <details className="brief-fold brief-meta"><summary><span>사용량과 분석 한계</span><small>저장된 내용 표시 · 추가 AI 호출 없음</small></summary><div className="brief-fold-content"><p>이 결과 생성 시 검색 {usage.search_calls??'미확인'}회 · 입력 {usage.input_tokens??'미확인'} / 출력 {usage.output_tokens??'미확인'} 토큰. 실제 청구액은 API 사용 내역에서 확인하세요.</p>{(result.limitations??[]).map((l,i)=><p key={i}>{l}</p>)}</div></details>
  </div>;
}
