'use client';
import {useEffect,useState} from 'react';
import {seoulTime} from '../lib/format.mjs';
import {safeSourceUrl} from '../lib/research.mjs';
import {matchingSourceLedger,visibleSourceCandidates,sourceDateLabel,reportLinkState} from '../lib/source-schedule.mjs';

export function SourceScheduleView({ledger,report,horizon=90,onReload,loading=false,error=''}){
  const items=visibleSourceCandidates(ledger,horizon);
  const retained=ledger?.candidates?.length??0;
  return <section className="sl-panel" aria-label="원문 일정 후보">
    <div className="sl-header"><div><span className="eyebrow">SOURCE FIRST / NO AI CALL</span><h3>원문에서 찾은 일정</h3></div><span className="sl-tag">확정 일정과 구분 · 원문 후보 {retained}개</span></div>
    <p className="sl-explain">AI가 빠뜨려도 읽어 둔 일정 문구는 사라지지 않습니다. 아래 날짜는 <b>원문 기반 후보</b>이며, 연도 추론·일정 변경·회사 공식성은 별도 확인해야 합니다.</p>
    <div className="sl-meta"><span>원문 수집 {ledger?.source_collected_at?`${seoulTime(ledger.source_collected_at)} KST`:'기록 없음'}</span><span>조회 기준 {ledger?.research_date??'확인 중'}</span><span>추가 AI·외부 검색 0회</span></div>
    {ledger?.source_is_expired&&<p className="sl-note">6시간이 지난 보관 원문입니다. 다시 수집한 최신 자료처럼 표시하지 않습니다. 과거에 읽은 문구만 보존합니다.</p>}
    {report&&<p className="sl-note">표시 중인 AI 보고서에 원문 첨부 기록: {report.local_evidence_supplied===true?'있음 (AI가 모두 반영했다는 뜻은 아님)':report.local_evidence_supplied===false?'없음':'이전 형식 · 확인 불가'}. 아래 원문 후보와 AI 보고서는 서로 다른 결과입니다.</p>}
    {loading&&<p role="status">저장된 원문 읽는 중 · 유료 요청 없음</p>}
    {error&&<p role="alert" className="sl-note">{error} 유료 조사 버튼을 누를 필요는 없습니다.</p>}
    {!loading&&!error&&(!items.length?<div className="sl-empty"><b>{retained?'선택 기간의 원문 후보 없음':'저장 원문에서 지원되는 일정 문장을 확보하지 못했습니다.'}</b><p>기간·날짜 미정 탭을 확인하세요. 이는 미래 이벤트가 없다는 뜻이 아닙니다.</p><a href="/evidence" target="_blank" rel="noopener noreferrer">저장 원문 확인 →</a></div>:<div className="sl-cards">{items.map(c=>{
      const raw=safeSourceUrl(c.source_url);const url=raw&&Number.isInteger(c.page)?`${raw.split('#')[0]}#page=${c.page}`:raw;
      return <article key={c.id} className={`sl-card ${c.category==='EARNINGS'?'sl-earnings':''}`}>
        <div className="sl-card-top"><span>{c.category==='EARNINGS'?'실적 발표 · 우선 확인':'경영진 행사'}</span><b>{sourceDateLabel(c)}</b></div>
        <h4>{c.title}</h4><p className="sl-link-state">{reportLinkState(c,report)}</p>
        <p>{c.year_explanation}</p>
        <details><summary>원문 문장 · 연도 근거 보기</summary><div className="sl-proof"><blockquote>{c.sentence}</blockquote><p>문서 기준일 {c.source_document_date??'미확인'} · {c.page??'?'}페이지 · {c.passage_id}</p><p>{c.document_title}</p><p className="sl-header-text">머리글: {c.header_text}</p>{url&&<a href={url} target="_blank" rel="noopener noreferrer">원문 {c.page??''}페이지 열기 ↗</a>}<p>취소·변경 여부를 새로 확인하지 않았습니다. 문장 연결은 제한된 규칙 처리이며 잘못 연결될 수 있습니다.</p></div></details>
      </article>;
    })}</div>)}
    <div className="sl-footer"><button type="button" className="text-button" disabled={loading} onClick={onReload}>저장 원문 다시 표시 · 무료</button><a href="/evidence" target="_blank" rel="noopener noreferrer">원문 확보 점검</a></div>
    <details className="sl-coverage"><summary>무엇을 처리했고, 무엇을 처리하지 못했나?</summary>{ledger?.document_checks?.map((d,i)=><p key={i}><b>{d.title}</b><br/>{d.status} · 후보 {d.candidates_found}개 · {d.reason}</p>)}{ledger?.limitations?.map((n,i)=><p key={i}>{n}</p>)}</details>
  </section>;
}
export default function SourceSchedule({symbol,report,horizon}){
  const [ledger,setLedger]=useState(null),[loading,setLoading]=useState(true),[error,setError]=useState(''),[reload,setReload]=useState(0);
  useEffect(()=>{
    let live=true;const ac=new AbortController();setLoading(true);setError('');setLedger(null);
    async function read(){try{
      const response=await fetch(`/api/v1/evidence/schedule?symbol=${encodeURIComponent(symbol)}`,{cache:'no-store',signal:ac.signal});const data=await response.json();
      if(!response.ok)throw new Error(data?.error?.message??'저장 원문 읽기 실패');
      const matched=matchingSourceLedger(data,symbol);if(!matched)throw new Error('원문 종목·형식이 맞지 않아 표시하지 않았습니다.');
      if(live)setLedger(matched);
    }catch(e){if(live&&e.name!=='AbortError')setError(e.message);}finally{if(live)setLoading(false);}}
    void read();return()=>{live=false;ac.abort();};
  },[symbol,reload]);
  return <SourceScheduleView ledger={ledger} report={report} horizon={horizon} onReload={()=>setReload(n=>n+1)} loading={loading} error={error}/>;
}
