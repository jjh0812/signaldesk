import test from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs';
import {buildCatalystView,visibleCatalysts,dateStatus,eventDateText,eventCountdown,nextEarningsSummary,dayNumber,normalizedSourceUrl} from './unified-catalysts.mjs';

const SOURCE='https://issuer.example.com/q3.pdf';
const candidate={id:'local-a',category:'EARNINGS',title:'실적 발표 콘퍼런스콜',sentence:'Our earnings call to discuss the results of our third quarter of fiscal 2031 is scheduled for November 17.',
  event_date_candidate:'2030-11-17',year_basis:'CONTEXT_YEAR_CANDIDATE',month_day_text:'November 17',basis:'LOCAL_TEXT_RULE_CANDIDATE',
  source_url:SOURCE,downloaded_url:'https://cdn.example.com/q3.pdf',source_document_date:'2030-08-26',page:15};
const ledger=(c=[candidate])=>({version:'source-schedule-0.6.2',symbol:'EXM',research_date:'2030-09-10',source_is_expired:false,candidates:structuredClone(c)});
const item={category:'EARNINGS',title:'다음 분기 실적 발표 콘퍼런스콜',timing:'ANNOUNCED_DATE',event_date:'2030-11-17',bucket:'D90',source_ids:['s1'],date_source_ids:['s1'],
  fact:'Synthetic report fact',watch:'실적과 전망의 변화를 확인하세요.',why_it_matters:'Synthetic interpretation'};
const report=(items=[item])=>({symbol:'EXM',scope:'catalysts',analysis_mode:'FORWARD_CATALYST_RISK',context:{research_date:'2030-09-10'},sources:[{id:'s1',number:1,url:SOURCE}],items:structuredClone(items)});
const build=(l=ledger(),r=report(),extra={})=>buildCatalystView({ledger:l,report:r,symbol:'EXM',researchDate:'2030-09-10',...extra});
const conference=(id,name,day='2030-10-21')=>({...candidate,id,category:'CONFERENCE',title:name,sentence:`He will speak at ${name} on October 21.`,event_date_candidate:day});
const conferenceItem=(name,day='2030-10-21')=>({...item,category:'CONFERENCE',title:name,event_date:day});

test('same event/date is one view card; raw report and ledger are immutable',()=>{
 const l=ledger(),r=report(),before=JSON.stringify([l,r]),v=build(l,r);
 assert.equal(v.entries.length,1);assert.equal(v.linkedCount,1);assert.equal(v.entries[0].mode,'MERGED');assert.equal(JSON.stringify([l,r]),before);
});
test('inferred date does not become announced or independently verified after a join',()=>{
 const e=build().entries[0];assert.equal(e.candidate,true);assert.equal(e.inferred,true);assert.equal(dateStatus(e),'연도 문맥 기준');assert.equal(eventCountdown(e,'2030-09-10'),null);
});
test('undated next-earnings report joins source, with stale AI text in original record only',()=>{
 const v=build(ledger(),report([{...item,timing:'UNCONFIRMED',event_date:null,bucket:'UNKNOWN',fact:'Company has no date',watch:'Find the date'}]));
 assert.equal(v.entries.length,1);assert.equal(v.unknownCount,0);assert.equal(v.entries[0].eventDate,'2030-11-17');assert.equal(v.entries[0].ai.fact,'Company has no date');
 assert.equal(v.entries[0].matchNotice,'REPORT_UNDATED');assert.equal(v.entries[0].usesAIQuestion,false);assert.notEqual(v.entries[0].question,'Find the date');
 assert.equal(nextEarningsSummary(v).kind,'source');
});
test('different dates remain visible as a conflict, not silently replaced',()=>{
 const v=build(ledger(),report([{...item,event_date:'2030-11-20'}]));
 assert.equal(v.entries.length,1);assert.equal(v.conflictCount,1);assert.equal(v.entries[0].eventDate,null);
 assert.equal(v.entries[0].sourceDate,'2030-11-17');assert.equal(v.entries[0].aiDate,'2030-11-20');assert.equal(visibleCatalysts(v,90).length,1);assert.equal(visibleCatalysts(v,'review').length,1);
 assert.equal(eventDateText(v.entries[0]),'날짜 불일치 · 확인 필요');
});
test('different fiscal quarters are NOT merged',()=>{
 const v=build(ledger(),report([{...item,title:'Q4 FY2031 Earnings Call'}]));assert.equal(v.entries.length,2);assert.equal(v.linkedCount,0);
});
test('equal earnings dates alone do not establish same event without a shared document',()=>{
 const r=report();r.sources[0].url='https://example.com/other.pdf';assert.equal(build(ledger(),r).entries.length,2);
});
test('earnings release is not assumed to be the earnings call',()=>{
 assert.equal(build(ledger(),report([{...item,title:'Q3 FY2031 earnings release'}])).entries.length,2);
});
test('one known earnings quarter and one different release do not absorb each other',()=>{
 const l=ledger([{...candidate,sentence:'Our earnings call Q3 FY2031 is scheduled for November 17.'}]);
 assert.equal(build(l,report([{...item,title:'Q4 FY2031 next earnings call'}])).entries.length,2);
});
test('two undated plausible next-earnings records remain separate instead of a greedy merge',()=>{
 const r=report([{...item,event_date:null,timing:'UNCONFIRMED',bucket:'UNKNOWN'},{...item,event_date:null,timing:'UNCONFIRMED',bucket:'UNKNOWN'}]);
 assert.equal(build(ledger(),r).linkedCount,0);
});
test('event-specific names match despite punctuation and a descriptive suffix',()=>{
 const c=conference('conf','Goldman Sachs Communacopia & Technology Conference in San Francisco · 대담');
 const i=conferenceItem('Goldman Sachs Communacopia + Technology Conference 참석 — 경영진 IR 발표');
 assert.equal(build(ledger([c]),report([i])).linkedCount,1);
});
test('generic conference/technology words do not cause a false join',()=>{
 assert.equal(build(ledger([conference('a','Alpha Technology Conference')]),report([conferenceItem('Beta Technology Conference')])).linkedCount,0);
});
test('two conferences with different distinctive names stay separate even on the same day',()=>{
 const l=ledger([conference('a','Alpha Lake Forum'),conference('b','Beta Ridge Forum')]);
 assert.equal(build(l,report([conferenceItem('Alpha Lake Forum')])).entries.length,2);
});
test('conflicting named-conference dates require review with same source',()=>{
 const v=build(ledger([conference('a','GTC Berlin keynote')]),report([conferenceItem('GTC Berlin keynote','2030-10-25')]));assert.equal(v.conflictCount,1);
});
test('ambiguous two-to-one conference links do not hide either record',()=>{
 const l=ledger([conference('a','Alpha Lake Forum'),conference('b','Alpha Lake Forum','2030-10-22')]);
 assert.equal(build(l,report([conferenceItem('Alpha Lake Forum')])).linkedCount,0);
});
test('two passages with same source schedule do not duplicate a card',()=>{
 const c=structuredClone(candidate);c.id='copy';assert.equal(build(ledger([candidate,c]),null).entries.length,1);
});
test('stale source remains visible with unchanged timestamp and stale marker',()=>{
 const l=ledger();l.source_is_expired=true;l.source_collected_at='2020-01-01T00:00:00Z';const v=build(l,null);
 assert.equal(visibleCatalysts(v,90).length,1);assert.equal(v.ledger.source_is_expired,true);assert.equal(v.ledger.source_collected_at,l.source_collected_at);
});
test('source-only card has labelled basic checklist, never a fake AI interpretation',()=>{
 const e=build(ledger(),null).entries[0];assert.equal(e.mode,'SOURCE_ONLY');assert.equal(e.ai,null);assert.equal(e.questionLabel,'이번에 볼 질문 · 기본 점검');
});
test('withheld AI date stays in unknown bucket without source evidence',()=>{
 const v=build(null,report([{...item,timing:'UNCONFIRMED',bucket:'UNKNOWN',date_candidate:{event_date:'2030-11-17'}}]));
 assert.equal(v.unknownCount,1);assert.equal(visibleCatalysts(v,90).length,0);assert.equal(visibleCatalysts(v,'unknown').length,1);
});
test('unknown source year stays unknown, not replaced by a guessed current year',()=>{
 const v=build(ledger([{...candidate,event_date_candidate:null,year_basis:'UNRESOLVED'}]),null);
 assert.equal(v.unknownCount,1);assert.equal(visibleCatalysts(v,'unknown').length,1);assert.match(eventDateText(v.entries[0]),/연도 미확인/);
});
test('stale bucket day counts recomputed against the chosen research date',()=>{
 const v=build(ledger([{...candidate,event_date_candidate:'2030-09-09'}]),null);assert.equal(visibleCatalysts(v,180).length,0);
});
test('30/90/180 filters count source candidates and AI cards consistently',()=>{
 const v=build(ledger(),report([{...item,category:'CORPORATE_ACTION',title:'Dividend',event_date:'2030-10-01'}]));
 assert.equal(visibleCatalysts(v,30).length,1);assert.equal(visibleCatalysts(v,90).length,2);assert.equal(visibleCatalysts(v,180).length,2);
});
test('date window overlaps research date without being collapsed into an exact day',()=>{
 const v=build(null,report([{...item,timing:'ANNOUNCED_WINDOW',event_date:null,window_start:'2030-09-01',window_end:'2030-10-01'}]));
 assert.equal(visibleCatalysts(v,30).length,1);assert.match(eventDateText(v.entries[0]),/~ /);
});
test('source outside AI date window is visibly conflicting',()=>{
 const v=build(ledger(),report([{...item,timing:'ANNOUNCED_WINDOW',event_date:null,window_start:'2030-10-01',window_end:'2030-10-20'}]));assert.equal(v.conflictCount,1);
});
test('report with different ticker cannot leak into current view',()=>{
 const r=report();r.symbol='OTHER';const v=build(ledger(),r);assert.equal(v.inputMismatch,true);assert.equal(v.linkedCount,0);assert.equal(v.report,null);
});
test('source ledger with different ticker is rejected',()=>{
 const l=ledger();l.symbol='OTHER';assert.equal(build(l,null).entries.length,0);
});
test('risk scope is not treated as a catalyst report',()=>{
 const r=report();r.scope='risks';assert.equal(build(null,r).entries.length,0);
});
test('older report research date is not silently merged with a newer context',()=>{
 const r=report();r.context.research_date='2030-09-09';assert.equal(build(ledger(),r).linkedCount,0);
});
test('tracking and page fragments ignored, content query parameters preserved',()=>{
 assert.equal(normalizedSourceUrl(SOURCE+'?utm_source=x#page=15'),SOURCE);
 assert.notEqual(normalizedSourceUrl(SOURCE+'?event=1'),normalizedSourceUrl(SOURCE+'?event=2'));
 assert.equal(normalizedSourceUrl('javascript:alert(1)'),null);
});
test('impossible and malformed dates rejected, leap year accepted',()=>{
 assert.equal(dayNumber('2030-02-30'),null);assert.equal(dayNumber('2030-2-1'),null);assert.equal(dayNumber('2030-02-29'),null);assert.notEqual(dayNumber('2032-02-29'),null);
});
test('context year candidate does not generate a definitive D-day count',()=>{
 assert.equal(eventCountdown(build().entries[0],'2030-09-10'),null);
 const c={...candidate,year_basis:'EXPLICIT_IN_SENTENCE',event_date_candidate:'2030-09-10'};
 assert.match(eventCountdown(build(ledger([c]),null).entries[0],'2030-09-10'),/오늘/);
});
test('missing evidence and missing reports do not create placeholder events',()=>{
 const v=build(null,null);assert.equal(v.entries.length,0);assert.equal(nextEarningsSummary(v).kind,'missing');
});
test('pure formatting/filtering never invokes fetch',()=>{
 const old=globalThis.fetch;globalThis.fetch=()=>{throw new Error('unexpected network')};
 try{for(const h of [30,90,180,'unknown','review'])visibleCatalysts(build(),h);}finally{globalThis.fetch=old;}
});
test('uploaded source text replay plus dividend-only simulated AI yields three source events and dividend, no duplicated earnings',()=>{
 const l=JSON.parse(fs.readFileSync(new URL('./fixtures/source-ledger063.json',import.meta.url),'utf8'));
 const r=report([{...item,category:'CORPORATE_ACTION',title:'Dividend fixture',event_date:'2026-10-01'}]);r.symbol='NVDA';r.context.research_date='2026-09-10';
 const v=buildCatalystView({ledger:l,report:r,symbol:'NVDA',researchDate:'2026-09-10'});
 assert.equal(v.sourceCount,3);assert.equal(visibleCatalysts(v,90).length,4);assert.equal(v.entries.filter(e=>e.category==='EARNINGS').length,1);
 assert.equal(v.entries[0].eventDate,'2026-11-17');assert.equal(v.entries[0].inferred,true);assert.equal(v.entries[0].candidates[0].page,15);
});

test('year-unresolved source is not assigned the year from a dated AI card',()=>{
 const v=build(ledger([{...candidate,event_date_candidate:null,year_basis:'UNRESOLVED'}]));
 assert.equal(v.linkedCount,0);assert.equal(v.unknownCount,1);assert.equal(v.entries.find(e=>e.mode==='SOURCE_ONLY').eventDate,null);
});
test('malformed source date is not accepted or hidden as a dated candidate',()=>{
 const v=build(ledger([{...candidate,event_date_candidate:'2030-02-30'}]),null);
 assert.equal(v.unknownCount,1);assert.equal(visibleCatalysts(v,180).length,0);
});
