"""Synthetic, offline regression tests. These fixtures are NEVER served in production."""
import copy
import json
import tempfile
import time
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import patch
from zoneinfo import ZoneInfo

from fastapi import FastAPI
from fastapi.testclient import TestClient
from fastapi.responses import JSONResponse

from app.dilution_watch import (DilutionService, WatchStore, SecClient, filing_rows,
    classify_filing, extract_html, metadata_signal, issuer, TICKERS_URL, stamp)
from app.stock_drivers import DriverService, parse_drivers, request_body, VERSION as DRIVER_VERSION
from app.research import ResearchError, ResearchService, Settings
from app.watch_api import install_routes

TODAY = datetime.now(ZoneInfo('America/New_York')).date()
SOURCES = [
 {'id':'s1','title':'TEST issuer identity','url':'https://example.com/test/company','published_date':TODAY.isoformat(),'source_type':'ISSUER'},
 {'id':'s2','title':'TEST issuer project update','url':'https://example.com/test/update','published_date':TODAY.isoformat(),'source_type':'ISSUER'}]

def doc():
 return {'symbol':'TEST','company_name':'Synthetic Company','identity_confirmed':True,'identity_source_ids':['s1'], 'sources':copy.deepcopy(SOURCES),
 'drivers':[{'side':'UPSIDE','title':'시험 프로젝트 임차계약 전환','current_fact':'회사는 시험 프로젝트 임차조건을 협의 중이라고 발표했습니다.',
 'current_stage':'PENDING','trigger':'구속력 있는 임차계약과 상대방·계약 용량이 공시된다.',
 'why_it_matters':'협의 중인 용량의 매출 가시성이 높아질 수 있습니다.',
 'confirmation':'임차인·기간·해지 조건을 명시한 계약 공시를 확인합니다.',
 'timing':'날짜 미확인','source_ids':['s2']}], 'unresolved':['계약 체결 여부는 아직 확인하지 못했습니다.']}

def response(document=None):
 return {'status':'completed','output':[{'type':'web_search_call','status':'completed','action':{'type':'search','sources':[{'url':s['url']} for s in SOURCES]}},
 {'type':'message','role':'assistant','phase':'final_answer','content':[{'type':'output_text','text':json.dumps(document if document is not None else doc(),ensure_ascii=False)}]}]}

def row(form='8-K',items='',number=1):
 acc=f'0000000123-26-{number:06d}'
 return {'accession':acc,'form':form,'filing_date':TODAY.isoformat(),'items':items,
 'url':f'https://www.sec.gov/Archives/edgar/data/123/{acc.replace("-", "")}/filing.htm',
 'index_url':f'https://www.sec.gov/Archives/edgar/data/123/{acc.replace("-", "")}/{acc}-index.html'}

def submission(count=1,form='S-3'):
 rows=[row(form,number=i+1) for i in range(count)]
 return {'cik':123,'name':'Synthetic Company','tickers':['TEST'], 'filings':{'recent':{
 'accessionNumber':[r['accession'] for r in rows], 'filingDate':[r['filing_date'] for r in rows],
 'form':[r['form'] for r in rows], 'primaryDocument':['filing.htm']*count,'items':['']*count}, 'files':[]}}

class DriverParseTests(unittest.TestCase):
 def test_source_linked_specific_card(self):
  value=parse_drivers(response(),'TEST',TODAY.isoformat());self.assertEqual(value['status'],'READY');self.assertEqual(len(value['drivers']),1)
 def test_wrong_symbol_is_rejected(self):
  d=doc();d['symbol']='OTHER'
  with self.assertRaises(ResearchError):parse_drivers(response(d),'TEST',TODAY.isoformat())
 def test_incomplete_is_not_displayed(self):
  raw=response();raw['status']='incomplete'
  with self.assertRaises(ResearchError):parse_drivers(raw,'TEST',TODAY.isoformat())
 def test_invented_source_is_not_trusted(self):
  d=doc();d['sources'][1]['url']='https://example.com/not-returned'
  self.assertEqual(parse_drivers(response(d),'TEST',TODAY.isoformat())['drivers'],[])
 def test_private_link_is_rejected(self):
  d=doc();d['sources'][1]['url']='http://127.0.0.1/private'
  self.assertEqual(parse_drivers(response(d),'TEST',TODAY.isoformat())['drivers'],[])
 def test_one_good_ref_does_not_hide_a_missing_ref(self):
  d=doc();d['drivers'][0]['source_ids']=['s2','missing']
  self.assertEqual(parse_drivers(response(d),'TEST',TODAY.isoformat())['drivers'],[])
 def test_unconfirmed_identity_has_no_cards(self):
  d=doc();d['identity_confirmed']=False
  self.assertEqual(parse_drivers(response(d),'TEST',TODAY.isoformat())['status'],'INSUFFICIENT')
 def test_no_web_search_is_not_web_research(self):
  raw=response();raw['output']=raw['output'][1:]
  self.assertEqual(parse_drivers(raw,'TEST',TODAY.isoformat())['drivers'],[])
 def test_future_publication_date_is_excluded(self):
  d=doc();d['sources'][1]['published_date']=(TODAY+timedelta(days=1)).isoformat()
  self.assertEqual(parse_drivers(response(d),'TEST',TODAY.isoformat())['drivers'],[])
 def test_unknown_publication_date_is_kept_unknown(self):
  d=doc();d['sources'][1]['published_date']=None
  self.assertIsNone(parse_drivers(response(d),'TEST',TODAY.isoformat())['drivers'][0]['sources'][0]['published_date'])
 def test_invalid_day_is_rejected(self):
  d=doc();d['sources'][1]['published_date']='2026-02-30'
  self.assertEqual(parse_drivers(response(d),'TEST',TODAY.isoformat())['drivers'],[])
 def test_duplicate_not_shown_twice(self):
  d=doc();d['drivers']*=2
  self.assertEqual(len(parse_drivers(response(d),'TEST',TODAY.isoformat())['drivers']),1)
 def test_plaintext_commentary_ignored(self):
  raw=response();raw['output'].insert(1,{'type':'message','role':'assistant','phase':'commentary','content':[{'type':'output_text','text':'조사를 시작합니다.'}]})
  self.assertEqual(parse_drivers(raw,'TEST',TODAY.isoformat())['status'],'READY')
 def test_refusal_is_explicit(self):
  raw=response();raw['output'][-1]['content']=[{'type':'refusal','refusal':'refused'}]
  with self.assertRaises(ResearchError):parse_drivers(raw,'TEST',TODAY.isoformat())
 def test_extras_rejected(self):
  d=doc();d['price_target']=999
  with self.assertRaises(ResearchError):parse_drivers(response(d),'TEST',TODAY.isoformat())
 def test_returned_markup_stays_text_data(self):
  d=doc();d['drivers'][0]['title']='<script>alert(1)</script>'
  self.assertIn('<script>',parse_drivers(response(d),'TEST',TODAY.isoformat())['drivers'][0]['title'])
 def test_request_no_secret_no_issuer_hardcode(self):
  b=request_body('TEST',TODAY.isoformat(),'gpt-5-mini');text=json.dumps(b)
  self.assertNotIn('65MW',text);self.assertNotIn('KPTI',text);self.assertNotIn('AIB',text)
  self.assertEqual(b['max_tool_calls'],8);self.assertIs(b['store'],False);self.assertTrue(b['text']['format']['strict'])

class RuleTests(unittest.TestCase):
 def signal(self,text,form='8-K',items=''):
  r=row(form,items);return classify_filing(r,[{'url':r['url'],'text':text}])
 def kinds(self,text,form='8-K'):
  result=self.signal(text,form);return [s['kind'] for s in (result or {}).get('signals',[])]
 def test_s3_does_not_equal_issued(self):
  v=classify_filing(row('S-3'),[]);self.assertEqual(v['signals'][0]['kind'],'REGISTRATION');self.assertEqual(v['issuance_status'],'NOT_INDEPENDENTLY_VERIFIED');self.assertIsNone(v['estimated_dilution_pct'])
 def test_foreign_issuer_forms(self):
  for f in ['F-1','F-1/A','F-3','F-3ASR']:
   self.assertEqual(metadata_signal(row(f))[0],'REGISTRATION')
 def test_secondary_sale_not_new_issuance(self):
  v=self.signal('The prospectus covers resale of common shares by selling shareholders.','F-3')
  self.assertIn('RESALE',[s['kind'] for s in v['signals']]);self.assertIsNone(v['estimated_dilution_pct'])
 def test_effect_is_not_completion(self):self.assertEqual(metadata_signal(row('EFFECT'))[0],'EFFECTIVENESS')
 def test_s8_separate_from_cash_raising(self):self.assertEqual(metadata_signal(row('S-8'))[0],'COMPENSATION_PLAN')
 def test_withdrawal_not_all_programs_closed(self):self.assertEqual(metadata_signal(row('RW'))[0],'WITHDRAWAL')
 def test_8k_item_302_is_candidate(self):self.assertEqual(metadata_signal(row(items='1.01,3.02,9.01'))[0],'UNREGISTERED_SALES_ITEM')
 def test_regular_8k_not_automatically_dilution(self):self.assertIsNone(classify_filing(row(),[]))
 def test_atm_signal(self):self.assertIn('ATM_FACILITY',self.kinds('The company entered into an at-the-market offering program.'))
 def test_convertible_signal(self):self.assertIn('CONVERTIBLE',self.kinds('The company issued convertible senior notes.'))
 def test_warrant_signal(self):self.assertIn('WARRANT',self.kinds('The agreement includes pre-funded warrants.'))
 def test_split_is_separate_not_dilution_pct(self):
  v=self.signal('The company effected a reverse stock split.');self.assertEqual(v['signals'][0]['kind'],'REVERSE_SPLIT');self.assertIsNone(v['estimated_dilution_pct'])
 def test_future_completion_not_closed(self):self.assertNotIn('COMPLETION_LANGUAGE',self.kinds('The company expects to have completed the offering next week.'))
 def test_not_closed_not_complete(self):self.assertNotIn('COMPLETION_LANGUAGE',self.kinds('The company has not completed the offering.'))
 def test_conditional_offering_not_fact(self):self.assertNotIn('OFFERING_TERMS',self.kinds('If we conduct a public offering, ownership may be diluted.'))
 def test_completion_always_has_quote(self):
  v=self.signal('The company completed the private placement on Friday.');sig=next(s for s in v['signals'] if s['kind']=='COMPLETION_LANGUAGE');self.assertIn('completed',sig['quote']);self.assertEqual(sig['basis'],'TEXT_PATTERN_NOT_VERIFIED')
 def test_exact_document_citation_not_search_page(self):
  r=row('6-K');u=r['url'].replace('filing.htm','ex99-1.htm');v=classify_filing(r,[{'url':u,'text':'The company issued and sold common shares.'}]);self.assertEqual(v['signals'][0]['url'],u)
 def test_html_script_removed(self):
  text,links,_=extract_html('<script>completed the offering</script><p>Revenue increased.</p>',row()['url']);self.assertNotIn('offering',text)
 def test_exhibit_same_filing_only(self):
  r=row();html='<a href="ex99-1.htm">Exhibit</a><a href="https://evil.com/ex99.htm">bad</a><a href="../else/ex99.htm">other filing</a>'
  _,links,_=extract_html(html,r['url']);self.assertEqual(links,[r['url'].replace('filing.htm','ex99-1.htm')])
 def test_metadata_column_mismatch(self):
  s=submission();s['filings']['recent']['form']=[]
  with self.assertRaises(ResearchError):filing_rows(s,'0000000123',TODAY)
 def test_future_filing_ignored(self):
  s=submission();s['filings']['recent']['filingDate']=[(TODAY+timedelta(days=1)).isoformat()]
  rows,c=filing_rows(s,'0000000123',TODAY);self.assertEqual(rows,[]);self.assertEqual(c['invalid_rows'],1)
 def test_past_outside_window_ignored(self):
  s=submission();s['filings']['recent']['filingDate']=[(TODAY-timedelta(days=181)).isoformat()]
  self.assertEqual(filing_rows(s,'0000000123',TODAY)[0],[])
 def test_unfetched_history_is_disclosed(self):
  s=submission();s['filings']['files']=[{'name':'older.json'}]
  self.assertFalse(filing_rows(s,'0000000123',TODAY)[1]['window_metadata_complete'])
 def test_malformed_primary_path_never_fetched(self):
  s=submission();s['filings']['recent']['primaryDocument']=['../../secret.htm'];rows,_=filing_rows(s,'0000000123',TODAY);self.assertIsNone(rows[0]['url'])

class FakeSec:
 result = None
 error = None
 def __init__(self,store):self.requests=0;self.urls=[]
 def get(self,url,*,json_result=False):
  self.requests+=1;self.urls.append(url)
  if self.error:raise ResearchError('SEC_HTTP_403','Test blocked',502)
  if url==TICKERS_URL:return {'0':{'ticker':'TEST','cik_str':123}}
  if '/submissions/' in url:return copy.deepcopy(self.result or submission())
  return '<p>The company has entered into an at-the-market offering program.</p>'

class ServiceTests(unittest.TestCase):
 def setUp(self):
  self.tmp=tempfile.TemporaryDirectory();self.root=Path(self.tmp.name);self.service=DilutionService(self.root,FakeSec)
  self.service.store.set_contact('test@example.com');FakeSec.result=None;FakeSec.error=None
 def tearDown(self):self.tmp.cleanup()
 def clear_timer(self):self.service.store.path('attempt-TEST.json').unlink(missing_ok=True)
 def test_no_external_before_consent(self):
  with patch.object(FakeSec,'get',side_effect=AssertionError('network')):
   with self.assertRaises(ResearchError):self.service.scan('TEST',False)
 def test_read_does_not_fetch(self):
  with patch.object(FakeSec,'get',side_effect=AssertionError('network')):self.assertIsNone(self.service.cached('TEST'))
 def test_missing_contact_no_network(self):
  self.service.store.path('contact.json').unlink()
  with patch.object(FakeSec,'get',side_effect=AssertionError('network')):
   with self.assertRaises(ResearchError):self.service.scan('TEST',True)
 def test_first_scan_not_new_historical_alert(self):
  r=self.service.scan('TEST',True);self.assertTrue(r['first_scan']);self.assertEqual(r['new_count'],0);self.assertEqual(r['ai_calls'],0)
 def test_new_accession_dedup(self):
  self.service.scan('TEST',True);self.clear_timer();FakeSec.result=submission(2)
  r=self.service.scan('TEST',True);self.assertEqual(r['new_count'],1)
  self.clear_timer();r=self.service.scan('TEST',True);self.assertEqual(r['new_count'],0)
 def test_unchanged_sec_docs_reused_metadata_still_refreshed(self):
  self.service.scan('TEST',True);self.clear_timer();r=self.service.scan('TEST',True);self.assertEqual(r['network_requests'],1);self.assertEqual(r['coverage']['document_http_requests'],0)
 def test_many_rows_bounded_and_partial(self):
  FakeSec.result=submission(20);r=self.service.scan('TEST',True);self.assertEqual(r['coverage']['primary_documents_checked'],8);self.assertEqual(r['status'],'PARTIAL');self.assertEqual(len(r['alerts']),20)
 def test_cooldown_no_network(self):
  self.service.scan('TEST',True)
  with patch.object(FakeSec,'get',side_effect=AssertionError('network')):
   with self.assertRaises(ResearchError):self.service.scan('TEST',True)
 def test_failed_list_does_not_erase_saved_report(self):
  r=self.service.scan('TEST',True);self.clear_timer();FakeSec.error=True
  with self.assertRaises(ResearchError):self.service.scan('TEST',True)
  self.assertEqual(self.service.cached('TEST')['checked_at'],r['checked_at']);self.assertEqual(self.service.store.read('attempt-TEST.json')['outcome'],'FAILED')
 def test_sec_mismatched_identity(self):
  FakeSec.result=submission();FakeSec.result['tickers']=['OTHER']
  with self.assertRaises(ResearchError):self.service.scan('TEST',True)
 def test_multi_share_classes_do_not_prevent_corporate_filing_scan(self):
  FakeSec.result=submission();FakeSec.result['tickers']=['TEST','TEST-A'];self.assertTrue(self.service.scan('TEST',True)['share_class_warning'])
 def test_email_not_in_result(self):self.assertNotIn('test@example.com',json.dumps(self.service.scan('TEST',True)))
 def test_network_url_allowlist(self):
  c=SecClient(self.service.store)
  with self.assertRaises(ResearchError):c.get('http://127.0.0.1/private')
  self.assertEqual(c.requests,0)
 def test_storage_path_traversal(self):
  with self.assertRaises(ValueError):self.service.store.read('../secret.json')
 def test_stale_keeps_original_time(self):
  r=self.service.scan('TEST',True);r['checked_at']=(datetime.now(timezone.utc)-timedelta(hours=1)).isoformat();self.service.store.save('dilution-TEST.json',r)
  c=self.service.cached('TEST');self.assertTrue(c['stale']);self.assertEqual(c['checked_at'],r['checked_at'])

class DriverServiceTests(unittest.TestCase):
 def setUp(self):
  self.tmp=tempfile.TemporaryDirectory();self.root=Path(self.tmp.name);self.research=ResearchService(self.root);self.service=DriverService(self.root,self.research)
  self.research.outlook_context=lambda _: {'symbol':'TEST','research_date':TODAY.isoformat()}
 def tearDown(self):self.tmp.cleanup()
 def test_without_paid_consent_no_call(self):
  with patch('app.research.call_openai',side_effect=AssertionError('paid')):
   with self.assertRaises(ResearchError):self.service.analyze('test',False,True)
 def test_one_attempt_only_and_global_counter(self):
  with patch('app.stock_drivers.read_settings',return_value=Settings('a'*30)),patch('app.research.call_openai',return_value=response()) as call:
   result=self.service.analyze('test',True,True);self.assertEqual(call.call_count,1);self.assertEqual(result['ai_calls'],1)
  with self.research._db() as db:self.assertEqual(db.execute('select sum(n) from attempts').fetchone()[0],1)
 def test_cache_read_never_paid(self):
  with patch('app.stock_drivers.read_settings',return_value=Settings('a'*30)),patch('app.research.call_openai',return_value=response()):self.service.analyze('test',True,True)
  with patch('app.research.call_openai',side_effect=AssertionError('paid')):
   self.assertTrue(self.service.analyze('test',True,False)['cache_hit'])
 def test_busy_guard_no_paid_call(self):
  self.research._active.acquire()
  try:
   with patch('app.stock_drivers.read_settings',return_value=Settings('a'*30)),patch('app.research.call_openai',side_effect=AssertionError('paid')):
    with self.assertRaises(ResearchError):self.service.analyze('test',True,True)
  finally:self.research._active.release()
 def test_failure_unlocks_and_preserves_previous(self):
  with patch('app.stock_drivers.read_settings',return_value=Settings('a'*30)),patch('app.research.call_openai',return_value=response()):old=self.service.analyze('test',True,True)
  with patch('app.stock_drivers.read_settings',return_value=Settings('a'*30)),patch('app.research.call_openai',side_effect=ResearchError('TEST','test')):
   with self.assertRaises(ResearchError):self.service.analyze('test',True,True)
  self.assertFalse(self.research._active.locked());self.assertEqual(self.service.cached('TEST')['generated_at'],old['generated_at'])
 def test_no_global_env_fallback(self):
  with patch.dict('os.environ',{'OPENAI_API_KEY':'a'*40}),patch('app.research.call_openai',side_effect=AssertionError('paid')):
   with self.assertRaises(ResearchError):self.service.analyze('test',True,True)

class APITests(unittest.TestCase):
 def setUp(self):
  self.tmp=tempfile.TemporaryDirectory();self.root=Path(self.tmp.name);self.research=ResearchService(self.root);self.app=FastAPI()
  @self.app.exception_handler(ResearchError)
  async def errors(req,exc):return JSONResponse(status_code=exc.status,content={'error':{'code':exc.code,'message':exc.message}})
  def validate(req):
   if req.headers.get('x-signaldesk-ai')!=self.research.csrf_token or req.headers.get('origin','http://testserver')!='http://testserver':raise ResearchError('TOKEN','blocked',403)
  install_routes(self.app,self.root,self.research,validate);self.client=TestClient(self.app);self.headers={'X-SignalDesk-AI':self.research.csrf_token}
 def tearDown(self):self.client.close();self.tmp.cleanup()
 def test_state_no_external_no_secrets(self):
  with patch.object(SecClient,'get',side_effect=AssertionError('external')),patch('app.research.call_openai',side_effect=AssertionError('paid')):
   r=self.client.get('/api/v1/watch/state?symbol=TEST');self.assertEqual(r.status_code,200);self.assertEqual(r.json()['network_requests'],0)
 def test_contact_never_echoes_email(self):
  r=self.client.post('/api/v1/watch/contact',headers=self.headers,json={'email':'person@example.com','allow_save':True});self.assertEqual(r.status_code,200);self.assertNotIn('person',r.text)
 def test_contact_consent_required(self):self.assertEqual(self.client.post('/api/v1/watch/contact',headers=self.headers,json={'email':'test@example.com'}).status_code,400)
 def test_foreign_origin_rejected(self):self.assertEqual(self.client.post('/api/v1/watch/contact',headers={**self.headers,'Origin':'https://evil.example'},json={'email':'test@example.com','allow_save':True}).status_code,403)
 def test_missing_token_rejected(self):self.assertEqual(self.client.post('/api/v1/watch/dilution',json={'symbol':'TEST','allow_public_fetch':True}).status_code,403)
 def test_no_arbitrary_prompt_fields(self):self.assertEqual(self.client.post('/api/v1/watch/drivers',headers=self.headers,json={'snapshot_id':'a'*24,'allow_paid':True,'prompt':'anything'}).status_code,422)
 def test_true_string_not_consent(self):self.assertEqual(self.client.post('/api/v1/watch/dilution',headers=self.headers,json={'symbol':'TEST','allow_public_fetch':'true'}).status_code,422)
 def test_failed_sec_scan_releases_global_busy(self):
  r=self.client.post('/api/v1/watch/dilution',headers=self.headers,json={'symbol':'TEST','allow_public_fetch':True});self.assertEqual(r.status_code,400);self.assertFalse(self.research._active.locked())

if __name__=='__main__':unittest.main()
