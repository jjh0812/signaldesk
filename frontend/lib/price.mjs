// Deterministic display helpers. No fetch, paid requests or trading signals.
import {pct} from './format.mjs';
import {reportLines,safeSourceUrl} from './research.mjs';

export const PRICE_HEADINGS=['요약: 가격의 위치','요약: 기대를 확인할 것','요약: 위험과 다음 확인'];
export const PRICE_DETAILS=['가격의 위치와 한계','사업과 실적 근거','주식 수와 자금 조달','다음 확인과 자료 시점','해석 보류'];
const HEADINGS=new Set([...PRICE_HEADINGS,...PRICE_DETAILS,'상세 분석']);
export function priceHeading(line) {
  const t=line.map(s=>s.text??'').join('').trim().replace(/^#{1,6}\s*/,'').replace(/^\*\*(.*?)\*\*$/,'$1').trim();
  return HEADINGS.has(t)?t:null;
}
export function rangePercent(value) {
  return typeof value==='number'&&Number.isFinite(value)&&value>=0&&value<=1?Math.min(100,Math.max(0,value*100)):null;
}
export function priceMatches(result,metrics) {
  return Boolean(result&&metrics&&result.analysis_mode==='CURRENT_PRICE_RESEARCH'
    &&result.symbol===metrics.symbol&&result.price_date===metrics.price_date
    &&typeof metrics.context_id==='string'&&metrics.context_id.length===64&&result.context_id===metrics.context_id);
}
export function positionSentence(metrics) {
  const gap=metrics?.year?.from_high;
  if(typeof gap!=='number'||!Number.isFinite(gap))return '가격 위치를 계산할 관측값이 부족합니다.';
  const subject=metrics?.year?.limited_history?'확보한 종가 중':'최근 1년 확보 종가 중';
  if(Math.abs(gap)<0.00005)return `${subject} 가장 높은 수준입니다. 비싸다거나 더 오를 것이라는 판정은 아닙니다.`;
  return `${subject} 최고 종가보다 ${pct(Math.abs(gap)).replace(/^\+/,'')} 낮습니다. 내려온 폭만으로 싸다고 판단하지 않습니다.`;
}
export function trendSentence(metrics) {
  const h=metrics?.horizons?.find(x=>x.observations===63);
  if(h?.status!=='READY')return '63거래일 비교에 필요한 과거 관측값이 부족합니다.';
  if(h.spy_return===null||h.spy_return===undefined)return '같은 시작일·종료일의 SPY 가격이 없어 시장 비교는 보류합니다.';
  return `63거래일 관측 구간: 종목 ${pct(h.stock_return)}, SPY ${pct(h.spy_return)}. 차이는 단순 비교이며 뉴스의 효과가 아닙니다.`;
}
const text=line=>line.map(s=>s.text??'').join('').trim();
const note=t=>[[{text:t}]];
export function makePriceBrief(result) {
  const lines=reportLines(Array.isArray(result?.segments)?result.segments:[]);
  const refs=new Set((result?.citations??[]).filter(c=>Number.isInteger(c.number)&&safeSourceUrl(c.url)).map(c=>c.number));
  const sections=new Map();let current=null,detailStart=-1;
  lines.forEach((line,i)=>{
    const h=priceHeading(line);
    if(h){current=h;if(h==='상세 분석'&&detailStart<0)detailStart=i+1;
      if(sections.has(h))sections.get(h).duplicate=true;else sections.set(h,{lines:[],duplicate:false});
    }else if(current)sections.get(current).lines.push(line);
  });
  if(result?.status!=='RESEARCH_READY')return {mode:'UNCONFIRMED',title:'AI 해석 보류',cards:[
    {title:'숫자는 확인 가능',lines:note('위 가격 위치와 비교 수익률은 코드로 계산했습니다. 사업 근거를 충분히 확보하지 못했습니다.')},
    {title:'가치 판단은 보류',lines:note('차트 위치만으로 싸거나 비싸다고 판정하지 않습니다.')},
    {title:'다음 확인',lines:note('최신 실적과 공시의 공개 날짜부터 원문에서 확인하세요.')},
  ],detailLines:lines};
  const short=PRICE_HEADINGS.map(h=>sections.get(h));
  const length=s=>s.lines.reduce((n,l)=>n+text(l).length,0);
  const usable=short.every(s=>s&&!s.duplicate&&length(s)>0&&length(s)<=220)
    &&short.reduce((n,s)=>n+length(s),0)<=660
    &&short[1].lines.some(l=>l.some(seg=>refs.has(seg.citation)))
    &&Number(result?.unmapped_citation_count??0)===0;
  if(usable)return {mode:'QUICK',title:'가격 읽기 · 10초 요약',cards:short.map((s,i)=>({
    title:['현재 가격은 어떤 위치인가?','무엇이 기대를 뒷받침할까?','어떤 위험과 다음 확인이 있나?'][i],
    lines:s.lines.filter(l=>text(l)||l.some(x=>x.citation)),
  })),detailLines:detailStart>=0?lines.slice(detailStart):lines};
  // Never cut a paragraph and drop an uncertainty clause; show all text in details.
  return {mode:'FORMAT_FALLBACK',title:'보고서 저장됨 · 요약 형식 확인 필요',cards:[
    {title:'가격 위치',lines:note('위 숫자는 코드로 계산했습니다. AI 요약의 길이 또는 인용 형식을 확인하지 못했습니다.')},
    {title:'사업 근거',lines:note('내용을 임의로 압축하지 않았습니다. 근거와 상세 분석을 펼쳐 확인하세요.')},
    {title:'추가 호출 없음',lines:note('형식 오류로 유료 재시도하지 않았습니다. 적정주가·희석률을 계산한 결과도 아닙니다.')},
  ],detailLines:lines};
}
