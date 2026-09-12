'use client';
import {safeSourceUrl} from '../lib/research.mjs';
import {eventImpact,directionNames,importanceNames,leverNames} from '../lib/decision.mjs';
export default function ImpactSignal({entry,report,symbol}){
 const x=eventImpact(entry,report,symbol);
 return <div className="impact07" aria-label="사건 방향과 중요도">
   <div className="impact07-chips"><span className={`impact07-${x.direction.toLowerCase()}`}>사업 방향 · {directionNames[x.direction]}</span><span className={`impact07-importance-${x.importance.toLowerCase()}`}>관찰 중요도 · {importanceNames[x.importance]}</span></div>
   <p className="impact07-reason">{x.reason}</p><small>{x.kind} · 중요도는 예상 상승폭이 아닙니다.</small>
   {x.watch&&<p className="impact07-watch"><b>판단을 바꿀 확인</b> {x.watch}</p>}
   {x.economic_channel&&<details><summary>긍정·부정 조건과 가격 연결</summary><p><b>긍정 조건</b> {x.positive_condition}</p><p><b>부정 조건</b> {x.negative_condition}</p><p><b>모형의 어느 부분인가</b> {leverNames[x.economic_channel]??'미확인'}</p><p>현재 모형 포함: {x.model_inclusion==='INCLUDED_BY_USER'?'사용자가 포함으로 지정':x.model_inclusion==='NOT_INCLUDED_BY_USER'?'사용자가 미포함으로 지정':'미확인'}. 시장 선반영 여부와는 다릅니다.</p><p>새 정보 여부: {({NEW:'새 정보',UPDATED:'기존 전망 변경',REPEAT:'반복',UNKNOWN:'확인 못함'})[x.novelty]??'확인 못함'} · {x.novelty_reason}</p><p>금액·비중 평가: {x.quantification==='SUPPORTED_IN_INPUT'?'입력 근거에 따른 AI 해석 · 원문 대조 필요':'정량 영향 미확인'}</p><p>{x.uncertainty}</p><div>{(x.evidence_ids??[]).map(id=>{const s=report?.sources?.find(s=>s.id===id);const u=safeSourceUrl(s?.url);return u?<a key={id} href={u} target="_blank" rel="noopener noreferrer">[{id}] 원문 </a>:null;})}</div></details>}
 </div>;
}
