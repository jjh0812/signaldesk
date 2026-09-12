'use client';
import {percent, decimal} from '../lib/decision.mjs';
import {safeSourceUrl} from '../lib/research.mjs';
import {seoulTime} from '../lib/format.mjs';

function SourceLink({source}) {
 const url=safeSourceUrl(source?.url);
 return url?<a href={url} target="_blank" rel="noopener noreferrer">[{source.id}] 원문 ↗</a>:<span>원문 주소 미확인</span>;
}
export default function DecisionEvidenceReview({report}){
 const audit=report.evidence_review;
 if(!audit)return <div className="v07-warning">이 저장 결과에는 새 근거 점검이 없습니다. 위의 무료 점검 버튼을 사용하세요.</div>;
 const b=report.numerical_brief??{};
 const risks=audit.quarantined_risks??[],events=audit.quarantined_events??[];
 const sources=report.sources??[];
 const present=Number.isFinite(b.historical_revenue_growth_yoy);
 return <div className="v07-ai-result v073-review">
  <div className="v073-heading"><span className="small-badge">근거 점검 0.7.3 · {report.read_only_review?'새 AI 요청 0회':report.cache_hit?'저장 해석 재사용':'AI 해석 요청 1회'}</span><span>{report.read_only_review?'저장본 읽기 전용 점검':'응답에 근거 점검 적용'}</span></div>
  <h4>{report.price_reading}</h4>
  <p className="v073-main">원문 발췌가 있는 출처 <b>{audit.excerpt_count} / {audit.source_count}</b> · 원문 검증이 안 된 위험 주장 <b>{risks.length}건 별도 보존</b></p>
  <p className="v07-muted">이 표시는 출처 본문 보유 여부를 뜻합니다. 본문이 있어도 문장의 의미·진위·최신성을 모두 검증했다는 뜻은 아닙니다.</p>
  {b.symbol&&<section className="v073-numbers" aria-label="저장 숫자와 조건부 성장 요구">
    <h5>이미 있는 숫자로 알 수 있는 것</h5>
    <div className="v07-kpis">
      <div className="v07-kpi"><span>과거 매출 성장 · 입력값</span><strong>{present?percent(b.historical_revenue_growth_yoy,2):'미확보'}</strong><small>최근 12개월 전년 대비 · 미래 성장 아님</small></div>
      <div className="v07-kpi"><span>현재 모형의 성장 요구</span><strong>{Number.isFinite(b.implied_revenue_cagr)?percent(b.implied_revenue_cagr,2)+' / 년':'미계산'}</strong><small>{b.years??'—'}년 · 다른 가정 고정 · 시장 예상 아님</small></div>
      <div className="v07-kpi"><span>입력 재무의 영업이익률</span><strong>{percent(b.historical_operating_margin,2)}</strong><small>과거 영업이익 ÷ 매출 · 지속성은 별도 검토</small></div>
    </div>
    {Number.isFinite(b.required_revenue_multiple)&&<p>같은 조건에서 {b.years}년 뒤 매출이 지금의 <b>약 {decimal(b.required_revenue_multiple)}배</b>가 되는 성장 경로입니다. 과거 성장률이 높다는 이유만으로 이 경로를 달성한다고 결론 내리지 않습니다.</p>}
    {Number.isFinite(b.terminal_value_share)&&<p>기준 시나리오의 기업가치 중 예측기간 이후 가치 비중: <b>{percent(b.terminal_value_share,1)}</b>. 장기 이익률·투자수익률·할인율 가정을 특히 검토해야 합니다.</p>}
    <p className="v07-muted">가격 기준 {b.price_date??'미확보'} · 재무기간 끝 {b.period_end??'미확보'} · {b.consensus_available?'시장 전망 입력 있음 · 범위 검토 필요':'시장 컨센서스 미확보'} · {b.guidance_available?'회사 전망 입력 있음 · 범위 검토 필요':'회사 가이던스 미확보'}</p>
    <p className="v07-muted">{b.sensitivity_present?'할인율 민감도 표는 계산돼 있습니다. 단, 선택한 할인율을 정당화하는 외부 근거와는 다릅니다.':'할인율 민감도 결과가 제공되지 않았습니다.'}</p>
  </section>}
  <div className="v073-hold"><b>위험이 없다는 뜻이 아닙니다.</b><p>위험을 설명하는 공시 본문과 해당 주장과의 일치를 확인하지 못했습니다. 이전 AI의 위험 문장을 새 사실로 재전달하지 않습니다. 촉매·위험 조사 원본은 별도 미검증 자료로 남습니다.</p></div>
  <details className="v073-audit-fold"><summary>검증 대기 중인 이전 위험 주장 · {risks.length}건</summary>
    {risks.map((r,i)=><article className="v073-quarantine" key={r.risk_id??i}><b>이전 AI 주장 · 미검증: {r.title??r.risk_id}</b><p>{r.reason}</p>
      <details><summary>원래 문장·인용 기록 보기 (사실 확인 아님)</summary><blockquote>{r.original_claim?.current_state??'별도 원문 문장이 없습니다.'}</blockquote><div className="v073-links">{(r.original_claim?.evidence_ids??[]).map(id=>{const s=sources.find(s=>s.id===id);return s?<SourceLink key={id} source={s}/>:<span key={id}>[{id}] 근거 연결 미확인</span>;})}</div></details>
    </article>)}
  </details>
  <details className="v073-audit-fold"><summary>본문 연결이 부족한 이전 이벤트 해석 · {events.length}건</summary><p>내용이 거짓으로 판명됐다는 뜻은 아닙니다. 이 해석 요청에 직접 대조할 원문이 없었습니다.</p>{events.map((e,i)=><p key={e.event_id??i}><b>{e.title??e.event_id}</b><br/>{e.reason}</p>)}</details>
  <details className="v073-audit-fold"><summary>출처별 상태·점검 범위</summary><div className="v07-table-wrap"><table><thead><tr><th>출처</th><th>입력 상태</th><th>문서</th></tr></thead><tbody>{(audit.source_coverage??[]).map((s,i)=><tr key={s.id??i}><td>{s.id}</td><td>{s.status==='NO_EXCERPT'?'본문 없음':s.status==='SCHEDULE_EXCERPT_ONLY'?'일정 발췌 있음 · 위험 근거 아님':'본문 출처 확인 필요'}</td><td>{s.title} <SourceLink source={s}/></td></tr>)}</tbody></table></div><p>{audit.note}</p><p className="v07-muted">기존 AI 작성 시각: {report.generated_at?seoulTime(report.generated_at)+' KST':'없음'} · 이 근거 점검 단계 자체에는 추가 AI·외부 요청이 없습니다. 원래 저장본과 계산 가정을 변경하지 않았습니다.</p></details>
 </div>;
}
