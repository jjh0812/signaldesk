/** Presentation only. No provider requests, verification upgrades or stored-data mutations. */
import {buildCalculation,initialAssumptions,blankFinancials,finiteNumber} from './decision.mjs';
import {buildCatalystView,visibleCatalysts} from './unified-catalysts.mjs';

export function defaultCalculation(pack,symbol){
  if(pack?.input?.symbol!==symbol)return null;
  const f={...blankFinancials(symbol),...pack.input,share_basis_checked:false,claims_checked:false};
  const margin=f.revenue>0&&f.operating_income>0?Math.min(75,Math.max(1,f.operating_income/f.revenue*100)):null;
  if(margin===null)return null;
  const a={...initialAssumptions,reviewed:false,scenarios:initialAssumptions.scenarios.map(s=>({...s,target_margin:Number(margin.toFixed(2))}))};
  return buildCalculation(f,a,[]);
}
export function matchedOutlook(value,data){
  if(!value||value.context?.symbol!==data?.symbol||!data?.price_context?.context_id||value.context?.price_context_id!==data.price_context.context_id)return null;
  return value;
}
export function eventView(ledger,cache,data,horizon=90){
  const good=matchedOutlook(cache,data);
  const view=buildCatalystView({ledger,report:good?.reports?.catalysts,symbol:data?.symbol,researchDate:good?.context?.research_date??ledger?.research_date});
  return {...view,visible:visibleCatalysts(view,horizon)};
}
export function filingCards(report,symbol){
  if(report?.symbol!==symbol)return [];
  // Never show URL-only old AI risk claims here. A displayed rule card needs a SEC quotation.
  return (Array.isArray(report.cards)?report.cards:[]).filter(c=>c&&Array.isArray(c.evidence)&&c.evidence.some(e=>typeof e.quote==='string'&&e.quote.trim().length>0&&/^https:\/\/www\.sec\.gov\/Archives\/edgar\/data\//.test(e.url??'')));
}
export function valuationDigest(value,symbol){
  if(value?.symbol!==symbol||value?.financials?.symbol!==symbol||!value?.base)return null;
  const growth=finiteNumber(value.reverse?.growth);
  const years=finiteNumber(value.reverse?.years);
  const multiple=growth!==null&&years!==null?Math.pow(1+growth,years):null;
  return {price:finiteNumber(value.financials.price),priceDate:value.financials.price_date,
    growth,years,multiple:Number.isFinite(multiple)?multiple:null,
    terminalWeight:finiteNumber(value.base.terminal_weight),verdict:value.verdict,
    reviewed:Boolean(value.assumptions?.reviewed),ready:value.decision_ready===true,
    stale:value.verdict==='STALE_DATA',periodEnd:value.financials.period_end};
}
export function humanFailure(message){
  if(/기간|period|FILING/i.test(message??''))return '공시 자료를 연결하지 못했습니다. 가격 조회와 저장된 분석은 계속 사용할 수 있습니다.';
  return '일부 저장 자료를 불러오지 못했습니다. 사용 가능한 결과는 그대로 표시합니다.';
}
export function researchCacheIsCurrent(report,data){
  return report?.symbol===data?.symbol&&report?.scope==='catalysts'&&report?.context?.price_context_id===data?.price_context?.context_id;
}
