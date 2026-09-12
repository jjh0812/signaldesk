"""Offline source-pattern and API tests. Synthetic text is not issuer evidence."""
from copy import deepcopy
from datetime import date
import base64,json,hashlib,shutil,tempfile,unittest
from pathlib import Path
from unittest.mock import patch
from fastapi import FastAPI
from fastapi.responses import JSONResponse
from fastapi.testclient import TestClient
from app.filing_risk import classify,render_report,passages_from_pages,old_claim_checks,ident,price_channel
from app.filing_store import FilingStore,prepared_document,sec_url,extract_identity
from app.filing_ai import request_body,parse,FilingAI
from app.document_reader import DocumentError
from app.research import ResearchService,ResearchError
from app.valuation_api import install_routes
from app.valuation import CalculateRequest
from app.decision_evidence import review_result

ROOT=Path(__file__).resolve().parents[2]
SEED=ROOT/'backend/data/filing_excerpt_examples080.json'
FIX=Path(__file__).parent/'fixtures/decision_snapshot073.json'

def data():return json.loads(FIX.read_text('utf-8'))
def seed():return json.loads(SEED.read_text('utf-8'))['documents']
def html(cik='1045810',form='10-K',period='2026-01-25',text=None):
    text=text or '<h2>Item 9A. Controls and Procedures</h2><p>Our management concluded that our internal control over financial reporting was effective as of January 25, 2026.</p><p>Because of inherent limitations, controls may not prevent all errors.</p>'
    return f'''<!doctype html><html><head><title>test filing</title></head><body>
    <ix:nonNumeric name="dei:EntityCentralIndexKey">{cik}</ix:nonNumeric>
    <ix:nonNumeric name="dei:DocumentType">{form}</ix:nonNumeric>
    <ix:nonNumeric name="dei:DocumentPeriodEndDate">{period}</ix:nonNumeric>
    <ix:nonNumeric name="dei:EntityRegistrantName">SYNTHETIC TEST COMPANY</ix:nonNumeric>
    {text}</body></html>'''.encode()
def response(rows):return {'status':'completed','output':[{'type':'message','role':'assistant','phase':'final_answer','content':[{'type':'output_text','text':json.dumps({'items':rows},ensure_ascii=False)}]}]}
def airow(c):return {'card_id':c['id'],'why_it_matters':'현금 흐름에 영향을 줄 수 있는 조건을 점검합니다.',
 'upside_condition':'현금 여력이 충분하면 부담을 줄일 수 있습니다.','downside_condition':'조건이 악화되면 부담이 커질 수 있습니다.',
 'watch':'해당 기간과 후속 공시의 변화 여부를 확인하세요.','price_connection':'계산의 가정을 바꾸려면 추가 근거가 필요합니다.',
 'citations':[{'evidence_id':c['evidence'][0]['id'],'quote':c['evidence'][0]['quote']}]}

class PatternTests(unittest.TestCase):
 def test_effective_is_assessment(self):self.assertEqual(classify('CONTROLS','Our internal control over financial reporting was effective as of this date.')[2],'CONTROL_EFFECTIVE')
 def test_not_effective_is_adverse(self):self.assertEqual(classify('CONTROLS','Our internal control over financial reporting was not effective.')[2],'CONTROL_WEAKNESS_REPORTED')
 def test_if_effective_not_actual(self):self.assertNotEqual(classify('CONTROLS','If our internal control over financial reporting was effective, the errors might have been detected.')[2],'CONTROL_EFFECTIVE')
 def test_found_weakness_is_reported(self):self.assertEqual(classify('CONTROLS','We identified a material weakness in internal control.')[2],'CONTROL_WEAKNESS_REPORTED')
 def test_not_found_not_actual(self):self.assertNotEqual(classify('CONTROLS','We have not identified a material weakness.')[2],'CONTROL_WEAKNESS_REPORTED')
 def test_did_not_identify_not_actual(self):self.assertNotEqual(classify('CONTROLS','We did not identify any material weakness.')[2],'CONTROL_WEAKNESS_REPORTED')
 def test_hypothetical_weakness_not_actual(self):self.assertNotEqual(classify('CONTROLS','If we identified a material weakness, we would remediate it.')[2],'CONTROL_WEAKNESS_REPORTED')
 def test_generic_limitations_not_actual(self):self.assertEqual(classify('CONTROLS','Our internal control has inherent limitations and may not prevent all errors.')[0],'GENERAL')
 def test_issuance_is_mixed(self):self.assertEqual(classify('DEBT','We issued an aggregate of $2 billion of senior unsecured notes.')[:2],('REPORTED_FACT','MIXED'))
 def test_possible_issuance_not_done(self):self.assertNotEqual(classify('DEBT','If we issued $2 billion of senior unsecured notes, leverage could increase.')[0],'REPORTED_FACT')
 def test_negated_issuance_not_done(self):self.assertNotEqual(classify('DEBT','We have not issued senior unsecured notes.')[0],'REPORTED_FACT')
 def test_debt_repayment_failure(self):self.assertEqual(classify('DEBT','We failed to repay our bonds.')[2],'DEBT_DEFAULT_REPORTED')
 def test_debt_hypothetical_default(self):self.assertNotEqual(classify('DEBT','If we defaulted on our bonds, we could incur penalties.')[0],'REPORTED_FACT')
 def test_guarantee_is_conditional(self):self.assertEqual(classify('GUARANTEES','Our payment obligations under the guarantees are triggered upon certain tenant defaults')[0],'CONDITIONAL')
 def test_guarantee_ceiling_is_not_loss(self):self.assertNotEqual(classify('GUARANTEES','We entered into guarantees capped at $50 billion, subject to conditions.')[0],'REPORTED_FACT')
 def test_supply_dependence_not_actual_disruption(self):self.assertEqual(classify('SUPPLY','We depend on third-party manufacturers for supply.')[0],'EXPOSURE')
 def test_export_conditional_not_cost(self):self.assertEqual(classify('EXPORT','Export restrictions may reduce future sales.')[0],'CONDITIONAL')
 def test_export_actual_charge(self):self.assertEqual(classify('EXPORT','We recorded a $1 billion export control charge.')[0],'REPORTED_FACT')
 def test_unknown_text_not_approved(self):self.assertEqual(classify('CONTROLS','the committee held a meeting.')[0],'NEEDS_REVIEW')
 def test_both_controls_assessments_flag_conflict(self):self.assertEqual(classify('CONTROLS','Our internal control over financial reporting was effective. We identified a material weakness.')[0],'CONFLICT')
 def test_multiple_topics_bounded(self):
  pages=[{'page':1,'text':'\n'.join(['We depend on third-party manufacturers for our supply.']*1000)}]
  p=passages_from_pages(pages);self.assertLessEqual(len(p),40)
 def test_end_of_long_document_retained(self):
  pages=[{'page':i,'text':'Generic description of company business and technology.'}for i in range(1,120)]
  pages[-1]['text']='Item 9A Controls\nOur internal control over financial reporting was effective.'
  self.assertTrue(any(p['page']==119 for p in passages_from_pages(pages)))
 def test_seed_quotes_each_document_under_limit(self):
  for d in seed():self.assertLessEqual(sum(len(p['text'].split())for p in d['passages']),25)
 def test_seed_has_no_encoded_conclusions(self):
  for d in seed():self.assertNotIn('direction',d);self.assertNotIn('conclusion',d)
 def test_seed_three_narrow_cards(self):
  r=render_report(seed());self.assertEqual(len(r['cards']),3);self.assertEqual({c['rule']for c in r['cards']},{'CONTROL_EFFECTIVE','DEBT_ISSUED','GUARANTEE_TRIGGER'})
 def test_actual_export_old_material_weakness_gets_contrary_text(self):
  r=render_report(seed(),data()['calculation'],data()['interpretation']);check=next(c for c in r['old_claim_checks'] if c['risk_id']=='risk-4');self.assertEqual(check['status'],'CONTRARY_DISCLOSURE')
 def test_other_old_claims_not_wholesale_approved(self):
  r=render_report(seed(),None,data()['interpretation']);self.assertEqual(sum(c['status']=='RELATED_TEXT' for c in r['old_claim_checks']),2)
 def test_no_same_url_no_claim_correction(self):
  original=data()['interpretation'];original['sources'][6]['url']='https://www.sec.gov/Archives/edgar/data/123/000000012326000001/a.htm'
  r=render_report(seed(),None,original);self.assertEqual(r['old_claim_checks'][-1]['status'],'NO_MATCHED_PASSAGE')
 def test_value_and_report_not_mutated(self):
  original=data();before=deepcopy(original);render_report(seed(),original['calculation'],original['interpretation']);self.assertEqual(before,original)
 def test_cash_ceiling_never_subtracted(self):
  r=render_report(seed(),data()['calculation']);self.assertTrue(all(c['price_connection']['quantified_price_effect'] is None for c in r['cards']))
 def test_actual_scale_is_not_loss_probability(self):
  r=render_report(seed(),data()['calculation']);c=next(c for c in r['cards']if c['rule']=='DEBT_ISSUED');self.assertAlmostEqual(c['price_connection']['scale']['value'],25000/134360)
 def test_no_cfo_no_scale(self):
  c=next(c for c in render_report(seed())['cards']if c['rule']=='DEBT_ISSUED');self.assertIsNone(c['price_connection']['scale'])
 def test_generic_control_text_not_placed_as_occurrence(self):
  d=deepcopy(seed()[0]);d['passages'][0]['text']='Internal control may not prevent all fraud.'
  r=render_report([d]);self.assertFalse(r['cards']);self.assertEqual(len(r['additional_passages']),1)
 def test_truncated_passage_not_promoted(self):
  d=deepcopy(seed()[0]);d['passages'][0]['truncated']=True;self.assertFalse(render_report([d])['cards'])
 def test_same_text_duplicate_single_card(self):
  d=deepcopy(seed()[0]);d['passages']*=2;self.assertEqual(len(render_report([d])['cards']),1)

class StoreTests(unittest.TestCase):
 def setUp(self):
  self.tmp=tempfile.TemporaryDirectory();self.root=Path(self.tmp.name);p=self.root/'backend/data';p.mkdir(parents=True);shutil.copy2(SEED,p/SEED.name);self.store=FilingStore(self.root);self.slots=self.store.registry('NVDA')
 def tearDown(self):self.tmp.cleanup()
 def test_unknown_issuer_ai_link_not_trusted(self):
  self.store.fin.save('impact-AAPL.json',data()['interpretation'])
  self.assertFalse(self.store.registry('AAPL'))
 def test_issuer_conflict_not_merged(self):
  self.store.fin.save('local-NVDA.json',{'cik':'1234'})
  with self.assertRaises(ResearchError):self.store.registry('NVDA')
 def test_get_view_no_files_changed(self):
  before=list(self.root.rglob('*'));self.store.view('NVDA');self.assertEqual(before,list(self.root.rglob('*')))
 def test_other_ticker_no_seed(self):self.assertFalse(self.store.view('AAPL')['cards'])
 def test_seed_not_fresh_full_filing(self):self.assertEqual(self.store.view('NVDA')['coverage']['full_filings'],0)
 def test_local_html_identity_and_extraction(self):
  d=prepared_document(html(),self.slots[0],'USER_SAVED_SEC_FILE');self.assertEqual(d['cik'],'1045810');self.assertTrue(d['passages']);self.assertEqual(d['scope'],'FULL_DOCUMENT')
 def test_wrong_company_rejected(self):
  with self.assertRaises(ResearchError):prepared_document(html(cik='1234'),self.slots[0],'USER_SAVED_SEC_FILE')
 def test_wrong_period_rejected(self):
  with self.assertRaises(ResearchError):prepared_document(html(period='2025-01-25'),self.slots[0],'USER_SAVED_SEC_FILE')
 def test_wrong_form_rejected(self):
  with self.assertRaises(ResearchError):prepared_document(html(form='8-K'),self.slots[0],'USER_SAVED_SEC_FILE')
 def test_no_identity_rejected(self):
  with self.assertRaises(ResearchError):prepared_document(b'<html><p>Our internal control over financial reporting was effective.</p></html>',self.slots[0],'USER_SAVED_SEC_FILE')
 def test_empty_rejected(self):
  with self.assertRaises(ResearchError):prepared_document(b'',self.slots[0],'USER_SAVED_SEC_FILE')
 def test_size_limit(self):
  with self.assertRaises(ResearchError):prepared_document(b'x'*(6*1024*1024+1),self.slots[0],'USER_SAVED_SEC_FILE')
 def test_script_not_extracted(self):
  d=prepared_document(html(text='<script>Our internal control over financial reporting was effective.</script><p>Safe generic text sufficiently long for the parser.</p>'),self.slots[0],'USER_SAVED_SEC_FILE');self.assertFalse(d['passages'])
 def test_import_writes_only_own_cache(self):
  self.store.fin.save('impact-NVDA.json',data()['interpretation']);before=(self.root/'.cache/valuation07/impact-NVDA.json').read_bytes()
  self.store.import_files('NVDA',[{'source_key':self.slots[0]['key'],'content_base64':base64.b64encode(html()).decode()}]);self.assertEqual(before,(self.root/'.cache/valuation07/impact-NVDA.json').read_bytes())
 def test_two_file_batch_is_atomic_on_failure(self):
  items=[{'source_key':self.slots[0]['key'],'content_base64':base64.b64encode(html()).decode()}, {'source_key':self.slots[1]['key'],'content_base64':base64.b64encode(html(cik='2222',form='10-Q',period='2026-07-26')).decode()}]
  with self.assertRaises(ResearchError):self.store.import_files('NVDA',items)
  self.assertFalse(self.store._path('NVDA').exists())
 def test_fetch_denial_keeps_seed_stops_second(self):
  self.store.fin.set_contact('tester@example.org')
  with patch('app.filing_store.fetch_sec',side_effect=DocumentError('HTTP_403'))as fetch:
   r=self.store.fetch('NVDA',[s['key'] for s in self.slots]);self.assertEqual(fetch.call_count,1);self.assertEqual(len(r['cards']),3);self.assertEqual(r['attempts'][-1]['status'],'NOT_REQUESTED_AFTER_DENIAL')
 def test_fetch_needs_contact(self):
  with patch('app.filing_store.fetch_sec')as fetch,self.assertRaises(ResearchError):self.store.fetch('NVDA',[self.slots[0]['key']])
  fetch.assert_not_called()
 def test_url_rejects_private_non_sec(self):
  for u in ('http://www.sec.gov/a','https://127.0.0.1/a','https://evil.example.com/a','https://www.sec.gov@evil.com/','https://www.sec.gov/files/a'):
   with self.subTest(url=u),self.assertRaises((DocumentError,ResearchError)):sec_url(u)
 def test_no_keys_or_email_in_view(self):
  self.store.fin.set_contact('secret-contact@example.org');(self.root/'.env.signaldesk').write_text('VERY_SECRET_KEY')
  text=json.dumps(self.store.view('NVDA'));self.assertNotIn('secret-contact',text);self.assertNotIn('VERY_SECRET',text)
 def test_guarded_previous_report_comparison_kept(self):
  guarded=review_result(data()['interpretation'],data()['calculation']);self.store.fin.save('impact-NVDA.json',guarded)
  self.assertEqual(self.store.view('NVDA')['old_claim_checks'][-1]['status'],'CONTRARY_DISCLOSURE')
 def test_corrupt_cache_rejected_not_emptied(self):
  p=self.store._path('NVDA');p.parent.mkdir(parents=True);p.write_text('BAD');
  with self.assertRaises(ResearchError):self.store.view('NVDA')
  self.assertEqual(p.read_text(),'BAD')
 def test_cache_symlink_rejected(self):
  outside=self.root/'outside';outside.write_text('X');p=self.store._path('NVDA');p.parent.mkdir(parents=True)
  try:p.symlink_to(outside)
  except OSError:self.skipTest('Symlink not permitted')
  with self.assertRaises(DocumentError):self.store.view('NVDA')

class AITests(unittest.TestCase):
 def setUp(self):self.report=render_report(seed(),data()['calculation']);self.report.update(symbol='NVDA',corpus_hash='c'*64)
 def test_no_old_claim_in_prompt(self):
  b=request_body(self.report,data()['calculation'],'gpt-5-mini');self.assertNotIn(data()['interpretation']['risks'][-1]['current_state'],b['input'])
 def test_no_web_tool(self):
  b=request_body(self.report,None,'gpt-5-mini');self.assertNotIn('tools',b);self.assertFalse(b['store']);self.assertTrue(b['text']['format']['strict'])
 def test_correct_quotes_accept(self):self.assertEqual(len(parse(response([airow(c)for c in self.report['cards']]),self.report)['items']),3)
 def test_wrong_quote_reject(self):
  r=airow(self.report['cards'][0]);r['citations'][0]['quote']='A claim that is not in the filing.'
  with self.assertRaises(ResearchError):parse(response([r]),self.report)
 def test_wrong_source_id_reject(self):
  r=airow(self.report['cards'][0]);r['citations'][0]['evidence_id']='E7'
  with self.assertRaises(ResearchError):parse(response([r]),self.report)
 def test_cross_card_quote_reject(self):
  r=airow(self.report['cards'][0]);r['citations']=airow(self.report['cards'][1])['citations']
  with self.assertRaises(ResearchError):parse(response([r]),self.report)
 def test_new_numbers_not_accepted(self):
  r=airow(self.report['cards'][0]);r['price_connection']='주가는 50% 오릅니다.'
  with self.assertRaises(ResearchError):parse(response([r]),self.report)
 def test_control_contradiction_blocked(self):
  c=next(c for c in self.report['cards']if c['rule']=='CONTROL_EFFECTIVE');r=airow(c);r['why_it_matters']='중대한 약점을 발견했다고 해석됩니다.'
  with self.assertRaises(ResearchError):parse(response([r]),self.report)
 def test_guarantee_as_loss_blocked(self):
  c=next(c for c in self.report['cards']if c['rule']=='GUARANTEE_TRIGGER');r=airow(c);r['why_it_matters']='보증 전액이 손실로 발생했습니다.'
  with self.assertRaises(ResearchError):parse(response([r]),self.report)
 def test_incomplete_not_retried(self):
  with self.assertRaises(ResearchError):parse({'status':'incomplete'},self.report)
 def test_missing_card_preserved_in_status(self):
  r=parse(response([airow(self.report['cards'][0])]),self.report);self.assertEqual(len(r['missing_card_ids']),2)
 def test_junk_row_preserves_other(self):
  r=parse(response([{},airow(self.report['cards'][0])]),self.report);self.assertEqual(len(r['withheld']),1)
 def test_duplicate_card_not_double(self):
  r=airow(self.report['cards'][0]);self.assertEqual(len(parse(response([r,r]),self.report)['items']),1)
 def test_ai_cannot_edit_facts(self):
  before=deepcopy(self.report);parse(response([airow(c)for c in self.report['cards']]),self.report);self.assertEqual(before,self.report)

class APITests(unittest.TestCase):
 def setUp(self):
  self.tmp=tempfile.TemporaryDirectory();self.root=Path(self.tmp.name);p=self.root/'backend/data';p.mkdir(parents=True);shutil.copy2(SEED,p/SEED.name)
  self.research=ResearchService(self.root);self.app=FastAPI()
  @self.app.exception_handler(ResearchError)
  async def error(_,exc):return JSONResponse(status_code=exc.status,content={'error':{'code':exc.code,'message':exc.message}})
  install_routes(self.app,self.root,self.research);self.client=TestClient(self.app);self.headers={'X-SignalDesk-AI':self.research.csrf_token};self.store=FilingStore(self.root)
 def tearDown(self):self.client.close();self.tmp.cleanup()
 def test_state_works_without_key(self):
  r=self.client.get('/api/v1/filing-risk/state?symbol=NVDA');self.assertEqual(r.status_code,200);self.assertEqual(len(r.json()['cards']),3)
 def test_review_no_network_or_paid(self):
  with patch('app.filing_store.fetch_sec',side_effect=AssertionError('network')),patch('app.filing_ai.call_openai',side_effect=AssertionError('paid')),patch.object(self.research,'_reserve_attempt',side_effect=AssertionError('quota')):
   r=self.client.post('/api/v1/filing-risk/review',json={'symbol':'NVDA'},headers=self.headers);self.assertEqual(r.status_code,200)
 def test_review_csrf_required(self):self.assertEqual(self.client.post('/api/v1/filing-risk/review',json={'symbol':'NVDA'}).status_code,403)
 def test_review_wrong_origin_rejected(self):
  r=self.client.post('/api/v1/filing-risk/review',json={'symbol':'NVDA'},headers={**self.headers,'Origin':'https://evil.com'});self.assertEqual(r.status_code,403)
 def test_read_consent_required(self):
  r=self.client.post('/api/v1/filing-risk/read',json={'symbol':'NVDA','source_keys':[self.store.registry('NVDA')[0]['key']]},headers=self.headers);self.assertEqual(r.status_code,400)
 def test_paid_consent_required_no_attempt(self):
  report=self.store.view('NVDA')
  with patch.object(self.research,'_reserve_attempt')as reserve:
   r=self.client.post('/api/v1/filing-risk/interpret',json={'symbol':'NVDA','expected_corpus_hash':report['corpus_hash']},headers=self.headers);self.assertEqual(r.status_code,400);reserve.assert_not_called()
 def test_corpus_changed_no_paid(self):
  r=self.client.post('/api/v1/filing-risk/interpret',json={'symbol':'NVDA','expected_corpus_hash':'f'*64,'allow_paid':True},headers=self.headers);self.assertEqual(r.status_code,409)
 def test_local_import_valid(self):
  slot=self.store.registry('NVDA')[0]
  r=self.client.post('/api/v1/filing-risk/import',json={'symbol':'NVDA','allow_local_import':True,'files':[{'source_key':slot['key'],'filename':'test.htm','content_base64':base64.b64encode(html()).decode()}]},headers=self.headers);self.assertEqual(r.status_code,200);self.assertEqual(r.json()['coverage']['full_filings'],1)
 def test_local_import_consent_required(self):
  slot=self.store.registry('NVDA')[0]
  r=self.client.post('/api/v1/filing-risk/import',json={'symbol':'NVDA','files':[{'source_key':slot['key'],'filename':'test.htm','content_base64':'YWJj'}]},headers=self.headers);self.assertEqual(r.status_code,400)
 def test_invalid_json_not_raw_echo(self):
  r=self.client.post('/api/v1/filing-risk/import',content='SECRET_BAD_JSON',headers={**self.headers,'Content-Type':'application/json'});self.assertEqual(r.status_code,422);self.assertNotIn('SECRET_BAD',r.text)
 def test_duplicate_json_fields_not_accepted(self):
  r=self.client.post('/api/v1/filing-risk/import',content='{"symbol":"NVDA","symbol":"AAPL"}',headers={**self.headers,'Content-Type':'application/json'});self.assertEqual(r.status_code,422)
 def test_no_cross_ticker_price(self):
  d=data()['calculation'];body={'financials':{**d['financials'],'symbol':'AAPL'},'assumptions':d['assumptions']}
  r=self.client.post('/api/v1/filing-risk/review',json={'symbol':'NVDA','calculation':body},headers=self.headers);self.assertEqual(r.status_code,422)
 def test_review_actual_calculation_unchanged(self):
  d=data()['calculation'];body={'financials':d['financials'],'assumptions':d['assumptions']}
  r=self.client.post('/api/v1/filing-risk/review',json={'symbol':'NVDA','calculation':body},headers=self.headers);self.assertEqual(r.status_code,200);self.assertFalse(r.json()['valuation_ready']);self.assertTrue(r.json()['valuation_unchanged'])
 def test_paid_service_mock_one_call_and_cache(self):
  from types import SimpleNamespace
  report=self.store.view('NVDA');payload={'symbol':'NVDA','expected_corpus_hash':report['corpus_hash'],'allow_paid':True}
  with patch('app.filing_ai.read_settings',return_value=SimpleNamespace(configured=True,model='test-model')),patch('app.filing_ai.call_openai',return_value=response([airow(c) for c in report['cards']]))as call,patch.object(self.research,'_reserve_attempt')as reserve:
   r=self.client.post('/api/v1/filing-risk/interpret',json=payload,headers=self.headers);self.assertEqual(r.status_code,200);self.assertEqual(r.json()['new_api_calls'],1)
   r2=self.client.post('/api/v1/filing-risk/interpret',json=payload,headers=self.headers);self.assertEqual(r2.status_code,200);self.assertEqual(r2.json()['new_api_calls'],0)
   self.assertEqual(call.call_count,1);self.assertEqual(reserve.call_count,1)
 def test_bad_paid_response_has_no_auto_retry(self):
  from types import SimpleNamespace
  report=self.store.view('NVDA')
  with patch('app.filing_ai.read_settings',return_value=SimpleNamespace(configured=True,model='test-model')),patch('app.filing_ai.call_openai',return_value={'status':'incomplete'})as call,patch.object(self.research,'_reserve_attempt')as reserve:
   r=self.client.post('/api/v1/filing-risk/interpret',json={'symbol':'NVDA','expected_corpus_hash':report['corpus_hash'],'allow_paid':True},headers=self.headers)
   self.assertEqual(r.status_code,502);self.assertEqual(call.call_count,1);self.assertEqual(reserve.call_count,1);self.assertFalse(self.research._active.locked())
 def test_busy_no_read(self):
  self.research._active.acquire()
  try:
   r=self.client.post('/api/v1/filing-risk/read',json={'symbol':'NVDA','allow_public_fetch':True,'source_keys':['a'*24]},headers=self.headers);self.assertEqual(r.status_code,409)
  finally:self.research._active.release()

if __name__=='__main__':unittest.main()
