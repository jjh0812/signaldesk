import test from 'node:test';
import assert from 'node:assert/strict';
import {makeBrief,splitReport,headingOf,displayProse,lineText} from './brief.mjs';
const citation={number:1,url:'https://issuer.example/release',title:'SYNTHETIC TEST SOURCE'};
const base={status:'RESEARCH_READY',prompt_version:'event-research-v0.3.0',citations:[citation],unmapped_citation_count:0};
const summary=[{text:'요약: 움직인 이유\n테스트용 협력 소식이 나왔지만 원인은 확정되지 않았습니다.'},{citation:1},
 {text:'\n요약: 중요한 이유\n새 사업 기대를 줄 수 있지만 실제 매출은 아닙니다.'},{citation:1},
 {text:'\n요약: 주의할 점\n공개 시각은 미확인이며 시장도 같이 움직였습니다.\n상세 분석\n한 줄 해석\n상세 문장.'},{citation:1}];
const fresh=()=>({...base,segments:structuredClone(summary)});
const legacy=()=>({...base,prompt_version:'event-research-v0.2.0',segments:[
 {text:'한 줄 해석\n발표가 있었습니다. 다만 상승 원인이라고 확정하지 않습니다.'},{citation:1},
 {text:'\n\n확인한 사건과 원인 후보\n긴 상세 원문\n가격을 해석할 때 주의할 점\n시장도 함께 움직였습니다.\n\n아직 확인하지 못한 것\n정확한 공개 시각을 확인하지 못했습니다.'}]});
test('new three-card output accepted with its original citations',()=>{const v=makeBrief(fresh());assert.equal(v.mode,'QUICK');assert.equal(v.cards.length,3);assert.ok(v.cards[0].lines.flat().some(x=>x.citation===1));});
test('detail view starts after short brief',()=>{const v=makeBrief(fresh());assert.ok(!v.detailLines.map(lineText).join('').includes('요약:'));assert.ok(v.detailLines.map(lineText).join('').includes('상세 문장'));});
test('legacy never pretends to be a freshly generated AI summary',()=>{const v=makeBrief(legacy());assert.equal(v.mode,'LEGACY_EXCERPT');assert.match(v.title,/발췌/);});
test('legacy keeps complete paragraph including the uncertainty sentence',()=>assert.equal(makeBrief(legacy()).cards[0].lines.map(lineText).join(''),'발표가 있었습니다. 다만 상승 원인이라고 확정하지 않습니다.'));
test('legacy source refs stay attached',()=>assert.ok(makeBrief(legacy()).cards[0].lines.flat().some(s=>s.citation===1)));
test('rendering does not mutate a saved result',()=>{const r=legacy(),before=JSON.stringify(r);makeBrief(r);assert.equal(JSON.stringify(r),before);});
test('missing caution blocks short-brief treatment',()=>{const r=fresh();r.segments[4].text='\n상세 분석\n한 줄 해석\n상세 문장';assert.equal(makeBrief(r).mode,'FORMAT_FALLBACK');});
test('absent factual citations blocks short-brief treatment',()=>{const r=fresh();r.citations=[];assert.equal(makeBrief(r).mode,'FORMAT_FALLBACK');});
test('invalid URLs cannot qualify brief as sourced',()=>{const r=fresh();r.citations=[{...citation,url:'javascript:alert(1)'}];assert.equal(makeBrief(r).mode,'FORMAT_FALLBACK');});
test('oversized model summary is not blindly truncated',()=>{const r=fresh();r.segments[0].text='요약: 움직인 이유\n'+'긴문장'.repeat(100);assert.equal(makeBrief(r).mode,'FORMAT_FALLBACK');});
test('duplicate summary heading is treated as malformed',()=>{const r=fresh();r.segments.push({text:'\n요약: 주의할 점\n다른 말'});assert.equal(makeBrief(r).mode,'FORMAT_FALLBACK');});
test('bad annotation offsets block quick treatment',()=>{const r=fresh();r.unmapped_citation_count=1;assert.equal(makeBrief(r).mode,'FORMAT_FALLBACK');});
test('unknown cause does not receive an invented event',()=>{const r={...fresh(),status:'UNCONFIRMED'};const v=makeBrief(r);assert.equal(v.mode,'UNCONFIRMED');assert.ok(!v.cards.map(c=>c.lines.map(lineText)).flat().join('').includes('협력'));});
test('markdown heading wrappers are supported',()=>{assert.equal(headingOf([{text:'### **요약: 움직인 이유**'}]),'요약: 움직인 이유');});
test('unknown headings do not get silently matched',()=>assert.equal(headingOf([{text:'결론: 매수'}]),null));
test('currency formatting rounds only displayed dollar amounts',()=>assert.equal(displayProse('$174.1969757 / 2026-03-31 / +5.59% / 20억 달러'),'$174.20 / 2026-03-31 / +5.59% / 20억 달러'));
test('plain HTML-looking content stays plain text',()=>assert.equal(displayProse('<img src=x onerror=alert(1)>'),'<img src=x onerror=alert(1)>'));
test('empty and malformed report inputs do not crash',()=>{for(const r of [null,{}, {segments:null},{segments:'oops'}, {status:'RESEARCH_READY'}])assert.ok(makeBrief(r).cards.length>0);});
test('long legacy paragraph gets safe fallback not partial misleading quotation',()=>{const r=legacy();r.segments[0].text='한 줄 해석\n'+'호재입니다. '.repeat(100)+'그러나 이 결론은 검증되지 않았습니다.';assert.match(makeBrief(r).cards[0].lines.map(lineText).join(''),/상세 분석/);});
test('missing legacy sections do not fabricate importance',()=>{const r=legacy();r.segments=[{text:'unknown format'}];const v=makeBrief(r);assert.ok(v.cards.every(c=>c.lines.length));assert.ok(!v.cards.some(c=>c.title==='왜 중요한가?'));});
