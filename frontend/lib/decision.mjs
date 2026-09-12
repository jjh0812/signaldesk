export const directionNames={POSITIVE:'긍정',NEGATIVE:'부정',MIXED:'혼합',NEUTRAL:'중립',WAITING:'결과 대기 · 양방향',INSUFFICIENT:'근거 부족'};
export const importanceNames={HIGH:'높음',MEDIUM:'중간',LOW:'낮음',INSUFFICIENT:'평가 불충분'};
export const leverNames={REVENUE:'매출 성장',MARGIN:'이익률',REINVESTMENT:'재투자 부담',CASH:'현금',SHARES:'주식 수',DISCOUNT_RATE:'위험·할인율',NONE:'직접 연결 없음',UNKNOWN:'미확인'};
export function initialImpact(category){
 if(category==='EARNINGS')return {direction:'WAITING',importance:'HIGH',reason:'실적과 다음 전망은 투자 가정을 바꿀 수 있습니다. 발표 일정 자체가 호재는 아닙니다.'};
 if(category==='CONFERENCE')return {direction:'NEUTRAL',importance:'LOW',reason:'참석·연설 예정만으로는 새 호재로 보지 않습니다. 계약·제품·전망의 새 내용이 나올 때 다시 평가합니다.'};
 return {direction:'INSUFFICIENT',importance:'INSUFFICIENT',reason:'사업의 무엇이 얼마나 바뀌는지 확인할 근거가 더 필요합니다.'};
}
export function eventImpact(entry,report,symbol){
 const ai=report?.symbol===symbol?report.events?.find(e=>e.event_id===entry.id && (entry.id?.startsWith('local-') || e.event_title===entry.title)):null;
 return ai?{...ai,kind:ai.analysis_origin==='RULE_BASED_SCHEDULE_NOT_NEW_AI'?'원문 일정 · 유형별 기본 점검 (새 AI 해석 아님)':'AI 해석 · 저장 근거 기준'}:{...initialImpact(entry.category),kind:'행사 유형 기준 · 새 AI 분석 아님'};
}
export function finiteNumber(value){if(value===null||value===undefined||typeof value==='boolean'||String(value).trim()==='')return null;const n=Number(value);return Number.isFinite(n)?n:null;}
export function dollars(value){const n=finiteNumber(value);return n===null?'—':new Intl.NumberFormat('en-US',{style:'currency',currency:'USD',maximumFractionDigits:2}).format(n);}
export function percent(value,digits=1){const n=finiteNumber(value);return n===null?'—':`${(n*100).toFixed(digits)}%`;}
export function decimal(value,digits=2){const n=finiteNumber(value);return n===null?'—':n.toLocaleString('en-US',{maximumFractionDigits:digits});}
export const initialAssumptions={years:5,discount_rate:10,terminal_growth:2.5,tax_rate:21,sales_to_capital:3,terminal_roic:15,reviewed:false,
 scenarios:[{name:'보수',growth:5,target_margin:20},{name:'기준',growth:10,target_margin:20},{name:'낙관',growth:20,target_margin:20}]};
export function blankFinancials(symbol=''){
 return {symbol,company_name:'',price:'',price_date:'',period_end:'',revenue:'',operating_income:'',cash:'',debt:'',shares:'',other_claims:0,
 net_income:'',operating_cash_flow:'',capex:'',stock_compensation:'',revenue_growth_yoy:null,sic:'',input_kind:'USER',sources_note:'',share_basis_checked:false,claims_checked:false};
}
export function buildCalculation(f,a,referenceForms=[]){
 const numeric=['price','revenue','operating_income','cash','debt','shares','other_claims','net_income','operating_cash_flow','capex','stock_compensation','revenue_growth_yoy'];
 const financials={...f};numeric.forEach(k=>financials[k]=finiteNumber(f[k]));
 if(['price','revenue','operating_income','cash','debt','shares','other_claims'].some(k=>financials[k]===null))return null;
 if(!/^\d{4}-\d{2}-\d{2}$/.test(f.price_date)||!/^\d{4}-\d{2}-\d{2}$/.test(f.period_end)||!f.symbol)return null;
 const assumptions={...a};
 for(const k of ['years','discount_rate','terminal_growth','tax_rate','sales_to_capital','terminal_roic']){const n=finiteNumber(a[k]);if(n===null)return null;assumptions[k]=['years','sales_to_capital'].includes(k)?n:n/100;}
 assumptions.scenarios=a.scenarios.map(s=>({...s,growth:finiteNumber(s.growth)===null?null:Number(s.growth)/100,target_margin:finiteNumber(s.target_margin)===null?null:Number(s.target_margin)/100}));
 if(assumptions.scenarios.some(s=>s.growth===null||s.target_margin===null))return null;
 const references=referenceForms.filter(r=>String(r.value??'').trim()).map(r=>({...r,value:finiteNumber(r.value),metric:'REVENUE_USD_MILLION'}));
 return {financials,assumptions,references};
}
export function splitPeers(value,target){return [...new Set(String(value??'').split(/[\s,]+/).map(s=>s.toUpperCase()).filter(s=>/^[A-Z][A-Z0-9]{0,9}(?:-[A-Z])?$/.test(s)&&s!==target))].slice(0,3);}
export function valuationAIIsCurrent(report,hash,symbol){return report?.symbol===symbol&&report?.valuation_hash===hash;}
export function referenceLabel(r){return r?.kind==='CONSENSUS'?'시장 컨센서스':'회사 가이던스';}
export function safeJsonDownload(value,name){const blob=new Blob([JSON.stringify(value,null,2)],{type:'application/json'});const url=URL.createObjectURL(blob);const a=document.createElement('a');a.href=url;a.download=name;a.click();setTimeout(()=>URL.revokeObjectURL(url),1000);}
