import test from 'node:test';
import assert from 'node:assert/strict';
import {QUALITY_VERSION,hasQualityReview,qualityMessages,riskDisplay,earningsCheckLabel,filterCatalysts,temporalLabel,scheduleText} from './outlook.mjs';
const report={quality_version:QUALITY_VERSION,quality_warnings:[]};
test('old cache is labeled unreviewed, not silently current',()=>{
 assert.equal(hasQualityReview({prompt_version:'outlook-v0.5.0'}),false);
 assert.match(qualityMessages({prompt_version:'outlook-v0.5.0'})[0],/이전 형식/);
});
test('new review requires exact quality version',()=>{assert.equal(hasQualityReview(report),true);assert.equal(hasQualityReview({quality_version:'LEGACY_OUTPUT'}),false);});
test('no report has no invented warnings',()=>{assert.deepEqual(qualityMessages(null),[]);});
test('partial quality output uses actual warning',()=>{assert.deepEqual(qualityMessages({quality_version:'QUALITY_DETAILS_INCOMPLETE',quality_warnings:['보강 불완전']}),['보강 불완전']);});
test('missing next earnings is prominent',()=>{assert.match(earningsCheckLabel('NOT_FOUND'),/미확보/);assert.match(earningsCheckLabel('UNDATED'),/미확인/);});
test('ETF is not given a company earnings date',()=>{assert.match(earningsCheckLabel('NOT_APPLICABLE'),/대상 아님/);});
test('missing latest risk does not recycle history as current',()=>{
 const d=riskDisplay({fact:'OLD CHARGE',historical_observation:{text:'OLD CHARGE'}},report);
 assert.equal(d.kind,'UNCONFIRMED');assert.equal(d.text.includes('OLD CHARGE'),false);assert.deepEqual(d.source_ids,[]);
});
test('current risk text comes from its own linked observation',()=>{
 const d=riskDisplay({fact:'OLD CHARGE',source_ids:['old'],latest_observation:{text:'RECENT OBSERVATION',source_ids:['new']}},report);
 assert.equal(d.text,'RECENT OBSERVATION');assert.deepEqual(d.source_ids,['new']);assert.match(d.label,/AI 설명/);
});
test('legacy content is not falsely represented as refreshed',()=>{const d=riskDisplay({fact:'OLD',source_ids:['s1']},{});assert.equal(d.kind,'LEGACY');assert.match(d.label,/시점 분리 전/);});
test('old observations have explicit warning label',()=>{assert.match(temporalLabel.OLDER_OBSERVATION,/오래된 관찰/);assert.match(temporalLabel.CURRENT_UNCONFIRMED,/미확인/);});
test('dates without source review stay out of day bands',()=>{
 const items=[{bucket:'UNKNOWN',event_date:null},{bucket:'D90',event_date:'2026-11-17'}];
 assert.equal(filterCatalysts(items,90).length,1);assert.equal(filterCatalysts(items,'unknown').length,1);
});
test('warning extraction is read only',()=>{const r={...report,quality_warnings:['미확보']},before=JSON.stringify(r);qualityMessages(r);assert.equal(JSON.stringify(r),before);});
import {readTraceLabel,candidateDateLabel} from './outlook.mjs';
test('reader061 quality compatible with old display helpers',()=>{assert.equal(hasQualityReview({quality_version:'outlook-quality-v0.6.1'}),true)});
test('locally read text is not falsely called provider open action',()=>{assert.match(readTraceLabel('LOCAL_TEXT_PROVIDED'),/서버 추출/);assert.doesNotMatch(readTraceLabel('LOCAL_TEXT_PROVIDED'),/웹 열람 동작/)});
test('withheld candidate remains outside normal horizon',()=>{const item={bucket:'UNKNOWN',timing:'UNCONFIRMED',event_date:null,date_candidate:{event_date:'2026-11-17'}};assert.equal(filterCatalysts([item],90).length,0);assert.match(candidateDateLabel(item),/확정 일정 아님/);assert.match(scheduleText(item),/아직 확인하지 못/)});
