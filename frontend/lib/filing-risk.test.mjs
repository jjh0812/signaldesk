import test from 'node:test';import assert from 'node:assert/strict';
import {reportSummary,commentsByCard,readFilingFile,safeFilingUrl,errorText,labelAttempt,claimLabels,directionLabels,importanceLabels}from './filing-risk.mjs';
test('different kinds are not all risk occurrences',()=>assert.deepEqual(reportSummary({cards:[{state:'ASSESSMENT'},{state:'REPORTED_FACT'},{state:'CONDITIONAL'}],old_claim_checks:[{status:'CONTRARY_DISCLOSURE'}]}),{facts:1,conditional:1,assessments:1,conflicts:1}));
test('empty report stays zero',()=>assert.equal(reportSummary(null).facts,0));
test('corpus change drops AI overlay',()=>assert.deepEqual(commentsByCard({cards:[{id:'a'}],corpus_hash:'new'},{corpus_hash:'old',items:[{card_id:'a'}]}),{}));
test('unknown card cannot appear via overlay',()=>assert.deepEqual(commentsByCard({cards:[],corpus_hash:'x'},{corpus_hash:'x',items:[{card_id:'a'}]}),{}));
test('matching overlay stays',()=>assert.equal(commentsByCard({cards:[{id:'a'}],corpus_hash:'x'},{corpus_hash:'x',items:[{card_id:'a',watch:'w'}]}).a.watch,'w'));
test('only SEC archive HTTPS link accepted',()=>assert.equal(safeFilingUrl('https://www.sec.gov/Archives/edgar/data/123/000000012326000001/a.htm'),'https://www.sec.gov/Archives/edgar/data/123/000000012326000001/a.htm'));
test('bad URLs rejected',()=>{for(const u of ['javascript:alert(1)','https://www.sec.gov.evil.com/','https://evil@www.sec.gov/Archives/edgar/data/123/000000012326000001/a.htm','http://www.sec.gov/a',null])assert.equal(safeFilingUrl(u),null)});
test('remote size excess rejected before read',async()=>{await assert.rejects(()=>readFilingFile({size:7*1024*1024,name:'a.htm'},'a'.repeat(24)))});
test('financial JSON is not a filing body',async()=>{await assert.rejects(()=>readFilingFile({size:10,name:'facts.json'},'a'.repeat(24)))});
test('valid small file base64',async()=>{const r=await readFilingFile({size:4,name:'a.htm',arrayBuffer:async()=>new TextEncoder().encode('test').buffer},'a'.repeat(24));assert.equal(r.content_base64,'dGVzdA==')});
test('bad source key rejected',async()=>{await assert.rejects(()=>readFilingFile({size:4,name:'a.htm'},'../'))});
test('no file rejected',async()=>{await assert.rejects(()=>readFilingFile(null,'a'.repeat(24)))});
test('errors do not invent source facts',()=>assert.equal(errorText({error:{message:'denied'}},403),'denied'));
test('failure status not success',()=>assert.ok(labelAttempt('HTTP_403').includes('거절')));
test('unknown importance distinct from low',()=>assert.notEqual(importanceLabels.INSUFFICIENT,importanceLabels.LOW));
test('business direction not buy instruction',()=>assert.equal(directionLabels.MIXED,'혼합'));
test('related topic does not validate whole claim',()=>assert.ok(claimLabels.RELATED_TEXT.includes('전체 주장 검증 아님')));


test('component JSON export uses data first and filename second', async()=>{
 const {readFile}=await import('node:fs/promises');
 const jsx=await readFile(new URL('../components/FilingRiskPanel.jsx',import.meta.url),'utf8');
 assert.ok(jsx.includes('safeJsonDownload({report,interpretation:ai},`SignalDesk_${symbol}_FilingRisk.json`)'));
});
