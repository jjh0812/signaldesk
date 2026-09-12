import test from 'node:test';
import assert from 'node:assert/strict';
import {PRICE_HEADINGS,makePriceBrief,positionSentence,priceMatches,rangePercent,trendSentence,priceHeading} from './price.mjs';
import {makeBrief} from './brief.mjs';
const metrics={symbol:'TEST',price_date:'2026-09-08',context_id:'a'.repeat(64),year:{from_high:-.25,limited_history:false},horizons:[{observations:63,status:'READY',stock_return:.1,spy_return:.04,spread:.06}]};
const report=()=>({analysis_mode:'CURRENT_PRICE_RESEARCH',symbol:'TEST',price_date:'2026-09-08',context_id:'a'.repeat(64),status:'RESEARCH_READY',unmapped_citation_count:0,
  citations:[{number:1,url:'https://issuer.example/release',title:'SYNTHETIC SOURCE'}],
  segments:[{text:'요약: 가격의 위치\n고점보다 낮지만 싸다는 뜻은 아닙니다.\n\n요약: 기대를 확인할 것\n회사가 새 제품을 발표했습니다.'},{citation:1},{text:' 실제 매출 증가는 아직 미확인입니다.\n\n요약: 위험과 다음 확인\n최신 실적과 자금 조달 자료를 더 확인해야 합니다.\n\n상세 분석\n사업과 실적 근거\n테스트용 원문.'},{citation:1}],
});
test('range position is bounded with unknown preserved',()=>{assert.equal(rangePercent(.25),25);assert.equal(rangePercent(0),0);assert.equal(rangePercent(1),100);for(const x of [null,undefined,NaN,Infinity,'0.5',-1,2])assert.equal(rangePercent(x),null);});
test('current report matches only same mode symbol date and fingerprint',()=>{const r=report();assert.ok(priceMatches(r,metrics));for(const patch of [{analysis_mode:'RETROSPECTIVE_WEB_RESEARCH'},{symbol:'NVDA'},{price_date:'2026-03-31'},{context_id:'b'.repeat(64)}])assert.equal(priceMatches({...r,...patch},metrics),false);});
test('missing identities are not a report match',()=>{assert.equal(priceMatches({},{}),false);assert.equal(priceMatches(null,metrics),false);});
test('price fall is location not bargain claim',()=>{const t=positionSentence(metrics);assert.ok(t.includes('25.00%'));assert.ok(t.includes('판단하지'));});
test('high flat and no-data descriptions do not invent direction',()=>{assert.ok(positionSentence({...metrics,year:{from_high:0}}).includes('판정은 아닙니다'));assert.ok(positionSentence(null).includes('부족'));});
test('limited history not labelled complete one-year history',()=>{assert.ok(!positionSentence({...metrics,year:{...metrics.year,limited_history:true}}).includes('최근 1년'));});
test('trend compares same period but does not attribute cause',()=>{const t=trendSentence(metrics);assert.ok(t.includes('+10.00%'));assert.ok(t.includes('+4.00%'));assert.ok(t.includes('효과가 아닙니다'));});
test('missing benchmark is unknown rather than 0%',()=>{const t=trendSentence({...metrics,horizons:[{...metrics.horizons[0],spy_return:null}]});assert.ok(t.includes('보류'));assert.ok(!t.includes('0.00%'));});
test('insufficient prior observations do not produce period return',()=>{assert.ok(trendSentence({horizons:[]}).includes('부족'));});
test('price headings parsed without colliding with event labels',()=>{assert.equal(priceHeading([{text:'### 사업과 실적 근거'}]),'사업과 실적 근거');assert.equal(priceHeading([{text:'확인한 사건과 원인 후보'}]),null);});
test('price quick brief requires fact-card citation but numeric card can be uncited',()=>{const v=makePriceBrief(report());assert.equal(v.mode,'QUICK');assert.equal(v.cards.length,3);assert.equal(v.cards[0].title,'현재 가격은 어떤 위치인가?');});
test('uncertainty sentence preserved in same card',()=>{const v=makePriceBrief(report());assert.ok(JSON.stringify(v.cards[1].lines).includes('미확인'));});
test('no sources in business card prevents polished quick brief',()=>{const r=report();r.citations=[];assert.equal(makePriceBrief(r).mode,'FORMAT_FALLBACK');});
test('unsafe source cannot validate a brief',()=>{const r=report();r.citations[0].url='javascript:alert(1)';assert.equal(makePriceBrief(r).mode,'FORMAT_FALLBACK');});
test('duplicate short heading is rejected',()=>{const r=report();r.segments.push({text:'\n요약: 가격의 위치\n두 번째 주장'});assert.equal(makePriceBrief(r).mode,'FORMAT_FALLBACK');});
test('long paragraph is never silently truncated',()=>{const r=report();r.segments[0].text='요약: 가격의 위치\n'+'가'.repeat(230)+'\n요약: 기대를 확인할 것\n원문 근거';const v=makePriceBrief(r);assert.equal(v.mode,'FORMAT_FALLBACK');assert.ok(JSON.stringify(v.detailLines).includes('가'.repeat(230)));});
test('unmapped citations cannot validate short brief',()=>{const r=report();r.unmapped_citation_count=1;assert.equal(makePriceBrief(r).mode,'FORMAT_FALLBACK');});
test('research unavailable creates abstention without fabricated valuation',()=>{const r=report();r.status='UNCONFIRMED';const v=makePriceBrief(r);assert.equal(v.mode,'UNCONFIRMED');assert.ok(v.title.includes('보류'));});
test('full report is preserved behind collapsed view',()=>{const r=report();const v=makePriceBrief(r);assert.ok(JSON.stringify(v.detailLines).includes('테스트용 원문'));});
test('event parser is not reused to mislabel price report as daily cause',()=>{assert.notEqual(makeBrief(report()).mode,'QUICK');});
test('zero benchmark return is valid observation',()=>{const t=trendSentence({...metrics,horizons:[{...metrics.horizons[0],spy_return:0}]});assert.ok(t.includes('0.00%'));assert.ok(!t.includes('보류'));});
