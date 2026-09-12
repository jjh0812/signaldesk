import test from 'node:test';
import assert from 'node:assert/strict';
import {safeSourceUrl,reportLines,reportMatches,friendlyApiError,REPORT_HEADINGS} from './research.mjs';
test('script and local links are not rendered as citations',()=>{
  for(const url of ['javascript:alert(1)','file:///C:/key','http://127.0.0.1/a','http://2130706433/','http://localhost','https://x.local','https://u:p@x.example','http://[::1]/'])assert.equal(safeSourceUrl(url),null);
});
test('public HTTPS citations are preserved',()=>assert.equal(safeSourceUrl('https://www.sec.gov/example'),'https://www.sec.gov/example'));
test('citation stays beside associated text',()=>assert.deepEqual(reportLines([{text:'요약\n내용'},{citation:1},{text:'\n끝'}]),[[{text:'요약'}],[{text:'내용'},{citation:1}],[{text:'끝'}]]));
test('a different date cannot display an old answer',()=>assert.equal(reportMatches({symbol:'NVDA',event_date:'2026-08-27'},'NVDA','2026-08-26'),false));
test('a different ticker cannot display an old answer',()=>assert.equal(reportMatches({symbol:'AAPL',event_date:'2026-08-27'},'NVDA','2026-08-27'),false));
test('matching event is accepted',()=>assert.equal(reportMatches({symbol:'NVDA',event_date:'2026-08-27'},'NVDA','2026-08-27'),true));
test('plain HTML-looking text remains data, not executable markup',()=>assert.deepEqual(reportLines([{text:'<img src=x onerror=alert(1)>'}]),[[{text:'<img src=x onerror=alert(1)>'}]]));
test('only known headings receive heading treatment',()=>{assert.ok(REPORT_HEADINGS.has('공개 시점 점검'));assert.ok(!REPORT_HEADINGS.has('<script>'));});
test('provider error message absent falls back safely',()=>assert.equal(friendlyApiError({detail:[{}]},'오류'),'오류'));
test('malformed citations do not create link placeholders',()=>assert.deepEqual(reportLines([{citation:'1'},{citation:-1}]),[[]]));
