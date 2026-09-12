import test from 'node:test';
import assert from 'node:assert/strict';
import {financialApiError,cikInputValid,stepName,stepStatus} from './financial-fetch.mjs';

test('SEC 403 remains visible rather than local 502 only',()=>{
 const e=financialApiError({error:{code:'SEC_HTTP_403',message:'Access refused'}},502);
 assert.match(e.message,/SEC_HTTP_403/); assert.equal(e.code,'SEC_HTTP_403');
});
test('stage diagnostic and independent quote preserved on error',()=>{
 const diagnostic={steps:[{stage:'TICKER_DIRECTORY',http_status:403}]};
 const e=financialApiError({error:{code:'SEC_HTTP_403',diagnostic,partial_quote:{close:20,date:'2026-09-08'}}},502);
 assert.equal(e.diagnostic,diagnostic); assert.equal(e.partialQuote.close,20);
});
test('validation location stays readable',()=>assert.match(financialApiError({detail:[{loc:['body','cik'],msg:'invalid'}]},422).message,/cik: invalid/));
test('non-object errors safe and generic',()=>assert.match(financialApiError(null,502).message,/HTTP_502/));
test('valid blank optional and numeric CIK',()=>{for(const v of ['',' ','1','0001045810','9999999999'])assert.equal(cikInputValid(v),true);});
test('invalid CIK is not an API credential or URL',()=>{for(const v of ['0','0000','-1','1e3','sk-key','https://sec.gov','11111111111','1.2'])assert.equal(cikInputValid(v),false);});
test('actual SEC response code displayed beside its step',()=>assert.equal(stepStatus({outcome:'ERROR',http_status:403,error_code:'SEC_HTTP_403'}),'HTTP 403 · SEC_HTTP_403'));
test('cached quote is not labeled newly fetched',()=>assert.match(stepStatus({outcome:'CACHE_NO_REQUEST'}),/저장본/));
test('cooldown is not a new SEC call',()=>assert.match(stepStatus({outcome:'COOLDOWN_NO_REQUEST'}),/새 요청 없음/));
test('stage labels distinguish directory from companyfacts',()=>assert.notEqual(stepName('TICKER_DIRECTORY'),stepName('COMPANYFACTS')));
