/** Presentation only. Source links are provenance, not independent fact verification. */
import {eventInsight} from './signals.mjs';
const text=v=>typeof v==='string'?v.trim():'';
function condition(v){const s=text(v);return s.length>=12&&s.length<=500&&!/목표주가|상승\s*확률|하락\s*확률|\d+\s*%\s*(상승|하락)|무조건|확실히\s*오르/.test(s)?s:null;}
export function forwardInsight(entry,report){
 const base=eventInsight(entry,report),ai=entry?.ai;
 const linked=base.links.length>0&&!entry?.conflict;
 const positive=linked?condition(ai?.positive_condition):null,negative=linked?condition(ai?.negative_condition):null;
 const specific=positive&&negative&&positive!==negative;
 return {...base,...(specific?{positive,negative,why:text(ai?.why_it_matters)||base.why,
   basis:'기업별 공개자료 기반 AI 시나리오 · 원문 대조 필요'}:{}),
   watch:linked?text(ai?.watch):'',importance:linked&&['HIGH','MEDIUM','LOW'].includes(ai?.importance)?ai.importance:null,
   importanceReason:linked?text(ai?.importance_reason):'',timing:entry?.ai?.timing??null};
}
