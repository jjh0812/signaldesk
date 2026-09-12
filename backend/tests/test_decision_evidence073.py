"""Offline replay of an uploaded output; fixture assertions are NOT real-world facts."""
from copy import deepcopy
from datetime import date
import hashlib
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
from fastapi import FastAPI
from fastapi.responses import JSONResponse
from fastapi.testclient import TestClient
from app.decision_evidence import (admitted_context, review_result, source_status,
                                  numerical_brief, POLICY_VERSION)
from app.decision import request_body, parse, digest, DecisionService
from app.research import ResearchService, ResearchError
from app.fundamentals import FundamentalsStore
from app.valuation import CalculateRequest, calculate
from app.valuation_api import install_routes

FIX=Path(__file__).parent/'fixtures/decision_snapshot073.json'

def recorded():return json.loads(FIX.read_text(encoding='utf-8'))
def request_fixture():
 d=recorded()['calculation'];return {'financials':d['financials'],'assumptions':d['assumptions'],'references':[]}
def context_fixture():
 r=recorded()['interpretation']
 events=[]
 for e in r['events']:
  events.append(dict(event_id=e['event_id'],title=e['event_title'],
    category='EARNINGS' if '실적' in e['event_title'] else 'CONFERENCE',
    source_ids=e['evidence_ids'],calendar_only=True,archived=True,
    date_status='CONTEXT_YEAR_CANDIDATE',event_date=None,fact='UNTRUSTED_SAVED_FACT'))
 risks=[dict(risk_id=r['risk_id'],title=r['risk_title'],fact=r['current_state'],source_ids=r['evidence_ids']) for r in r['risks']]
 ctx=dict(symbol='NVDA',research_date='2026-09-10',events=events,risks=risks,sources=deepcopy(r['sources']))
 return dict(ctx,context_hash=digest(ctx))

def raw_response():
 r=recorded()['interpretation'];payload={k:r[k] for k in ('price_reading','market_expectation_limit','next_check','events','risks','assumption_review')}
 return {'status':'completed','output':[{'type':'message','role':'assistant','phase':'final_answer','content':[{'type':'output_text','text':json.dumps(payload,ensure_ascii=False)}]}]}

class EvidenceReplayTests(unittest.TestCase):
 def test_actual_ten_sources_seven_empty(self):
  d=recorded();r=review_result(d['interpretation'],d['calculation'])
  self.assertEqual((r['evidence_review']['source_count'],r['evidence_review']['excerpt_count'],r['evidence_review']['no_excerpt_count']),(10,3,7))
 def test_actual_five_risks_are_quarantined_not_confirmed_false(self):
  d=recorded();r=review_result(d['interpretation'],d['calculation'])
  self.assertEqual(r['risks'],[]);self.assertEqual(len(r['evidence_review']['quarantined_risks']),5)
  self.assertTrue(all(x['status']=='UNVERIFIED_NOT_FALSE' for x in r['evidence_review']['quarantined_risks']))
 def test_material_weakness_assertion_not_in_current_narrative(self):
  d=recorded();r=review_result(d['interpretation'],d['calculation'])
  active={k:r[k] for k in ('price_reading','next_check','market_expectation_limit','events','risks','assumption_review')}
  self.assertNotIn('중대한 약점',json.dumps(active,ensure_ascii=False))
  self.assertIn('중대한 약점',json.dumps(r['evidence_review']['quarantined_risks'],ensure_ascii=False))
 def test_three_schedule_excerpts_retained_five_other_events_held(self):
  d=recorded();r=review_result(d['interpretation'],d['calculation'])
  self.assertEqual((len(r['events']),len(r['evidence_review']['quarantined_events'])),(3,5))
 def test_guard_does_not_modify_uploaded_report_or_calculation(self):
  d=recorded();before=json.dumps(d,sort_keys=True);review_result(d['interpretation'],d['calculation'])
  self.assertEqual(before,json.dumps(d,sort_keys=True))
 def test_same_url_cannot_launder_empty_duplicate_source(self):
  d=recorded();r=review_result(d['interpretation'],d['calculation']);held={x['event_id'] for x in r['evidence_review']['quarantined_events']}
  self.assertIn('ai-1',held);self.assertEqual(d['interpretation']['sources'][0]['url'],d['interpretation']['sources'][4]['url'])
 def test_nonempty_saved_ai_text_not_admitted_as_raw(self):
  s=dict(id='x',text='We found a material weakness in internal control.',basis='SAVED_AI_EXTRACTION_NOT_INDEPENDENTLY_VERIFIED')
  self.assertEqual(source_status(s),'PROVENANCE_NOT_ADMITTED')
 def test_blank_and_invalid_source_text(self):
  for text in [None,'','  ',[],{}]:self.assertEqual(source_status({'text':text,'basis':'LOCAL_TEXT_DATE_CANDIDATE'}),'NO_EXCERPT')
 def test_prompt_drops_unsupported_risk_claims_and_titles(self):
  ctx=context_fixture();body=request_body(ctx,recorded()['calculation'],'gpt-5-mini',{})
  supplied=json.loads(body['input'])['context'];self.assertEqual(supplied['risks'],[])
  self.assertNotIn('중대한 약점',body['input']);self.assertNotIn('UNTRUSTED_SAVED_FACT',body['input'])
  self.assertEqual(len(supplied['events']),3);self.assertEqual(len(supplied['sources']),3)
 def test_prompt_retains_historical_and_sensitivity_data(self):
  body=request_body(context_fixture(),recorded()['calculation'],'gpt-5-mini',{})
  supplied=json.loads(body['input'])['valuation'];self.assertTrue(supplied['numerical_observations']['sensitivity_present']);self.assertEqual(len(supplied['sensitivity']['values']),5)
 def test_prompt_uses_literal_schedule_not_old_fact(self):
  c=context_fixture();safe=admitted_context(c);self.assertIn('Our earnings call',safe['events'][0]['fact'])
 def test_context_filter_is_pure(self):
  c=context_fixture();before=deepcopy(c);admitted_context(c);self.assertEqual(before,c)
 def test_prompt_has_no_web_tools(self):
  b=request_body(context_fixture(),recorded()['calculation'],'gpt-5-mini',{});self.assertNotIn('tools',b);self.assertFalse(b['store']);self.assertTrue(b['text']['format']['strict'])
 def test_old_response_with_removed_source_ids_is_not_reaccepted_as_new(self):
  with self.assertRaises(ResearchError):parse(raw_response(),context_fixture(),{})
 def test_new_response_cannot_reintroduce_omitted_risks(self):
  raw=raw_response();d=json.loads(raw['output'][0]['content'][0]['text'])
  d['events']=d['events'][:3]
  for event in d['events']:event['evidence_ids']=[e for e in event['evidence_ids'] if e in ['E1','E2','E3']]
  raw['output'][0]['content'][0]['text']=json.dumps(d)
  r=parse(raw,context_fixture(),{});self.assertEqual(r['risks'],[]);self.assertEqual(len(r['events']),3)
 def test_read_side_guard_idempotent(self):
  d=recorded();r=review_result(d['interpretation'],d['calculation']);again=review_result(r,d['calculation'])
  self.assertEqual(r,again)
 def test_unverified_free_text_summary_is_replaced(self):
  d=recorded();d['interpretation'].update(price_reading='중대한 약점 발생',next_check='공식 확정 2099-01-01',market_expectation_limit='선반영 100%')
  r=review_result(d['interpretation'],d['calculation']);self.assertNotIn('2099',r['next_check']);self.assertNotIn('100%',r['market_expectation_limit']);self.assertNotIn('중대한 약점',r['price_reading'])
 def test_date_certainty_not_upgraded(self):
  d=recorded();r=review_result(d['interpretation'],d['calculation'])
  self.assertIn('연도 추정',r['next_check']);self.assertNotIn('회사 공시된',r['next_check'])
 def test_actual_numeric_brief(self):
  b=numerical_brief(recorded()['calculation'])
  self.assertAlmostEqual(b['historical_revenue_growth_yoy'],.8337590335193501)
  self.assertAlmostEqual(b['historical_operating_margin'],197579/302970)
  self.assertAlmostEqual(b['implied_revenue_cagr'],.30960389433647084)
  self.assertAlmostEqual(b['terminal_value_share'],.7076085674774037)
  self.assertTrue(b['sensitivity_present']);self.assertFalse(b['consensus_available']);self.assertFalse(b['guidance_available'])
 def test_empty_calculation_no_made_up_metrics(self):
  b=numerical_brief(None);self.assertIsNone(b['implied_revenue_cagr']);self.assertIsNone(b['required_revenue_multiple'])
 def test_no_single_reverse_solution_no_growth(self):
  d=recorded()['calculation'];d['reverse']['status']='MULTIPLE_SOLUTIONS';self.assertIsNone(numerical_brief(d)['implied_revenue_cagr'])
 def test_no_investment_approval_toggle(self):
  d=recorded();r=review_result(d['interpretation'],d['calculation']);self.assertFalse(r['numerical_brief']['decision_ready']);self.assertFalse(d['calculation']['assumptions']['reviewed'])
 def test_context_leads_are_retained_only_in_quarantine(self):
  c=context_fixture();r=review_result({'sources':c['sources'],'events':[],'risks':[]},source_context=c)
  self.assertEqual(len(r['evidence_review']['quarantined_risks']),5);self.assertEqual(len(r['evidence_review']['quarantined_events']),5)
 def test_direct_risk_assertions_always_require_missing_claim_validator(self):
  d=recorded();d['interpretation']['risks'][4]['evidence_ids']=['E1'];r=review_result(d['interpretation'],d['calculation'])
  self.assertEqual(r['risks'],[])
 def test_original_api_attempt_retained_new_review_zero(self):
  d=recorded();r=review_result(d['interpretation'],d['calculation']);self.assertEqual(r['api_attempts'],1);self.assertEqual(r['evidence_review']['new_api_calls'],0)
 def test_scenario_values_unchanged_by_review(self):
  d=recorded();result=calculate(CalculateRequest.model_validate(request_fixture()),today=date(2026,9,10));review_result(d['interpretation'],result)
  self.assertEqual([round(s['fair_value'],2) for s in result['scenarios']],[85.35,103.78,151.30])

class ReviewAPITests(unittest.TestCase):
 def setUp(self):
  self.tmp=tempfile.TemporaryDirectory();self.root=Path(self.tmp.name);self.research=ResearchService(self.root)
  app=FastAPI()
  @app.exception_handler(ResearchError)
  async def handle(request,exc):return JSONResponse(status_code=exc.status,content={'error':{'code':exc.code,'message':exc.message}})
  install_routes(app,self.root,self.research);self.client=TestClient(app);self.headers={'X-SignalDesk-AI':self.research.csrf_token}
  self.store=FundamentalsStore(self.root);d=recorded();self.store.save('impact-NVDA.json',d['interpretation']);self.store.save('local-NVDA.json',{'input':d['calculation']['financials'],'missing':[]})
  self.ctx_patch=patch('app.valuation_api.context',return_value=context_fixture());self.ctx_patch.start()
 def tearDown(self):self.ctx_patch.stop();self.client.close();self.tmp.cleanup()
 def payload(self):return {'symbol':'NVDA','calculation':request_fixture()}
 def test_review_api_reads_actual_saved_report_no_external_calls(self):
  with patch('app.decision.call_openai',side_effect=AssertionError('NO OPENAI')),patch('app.fundamentals.FundamentalsStore.get_json',side_effect=AssertionError('NO SEC')),patch.object(self.research,'_reserve_attempt',side_effect=AssertionError('NO RESERVATION')):
   r=self.client.post('/api/v1/decision/review',json=self.payload(),headers=self.headers)
  self.assertEqual(r.status_code,200);d=r.json();self.assertTrue(d['read_only_review']);self.assertEqual(d['new_api_calls'],0);self.assertEqual(d['evidence_review']['risk_claims_quarantined'],5)
 def test_review_does_not_mutate_any_project_file(self):
  def snapshot():return {str(p.relative_to(self.root)):hashlib.sha256(p.read_bytes()).hexdigest() for p in self.root.rglob('*') if p.is_file()}
  before=snapshot();r=self.client.post('/api/v1/decision/review',json=self.payload(),headers=self.headers);self.assertEqual(r.status_code,200);self.assertEqual(snapshot(),before)
 def test_token_required(self):
  self.assertEqual(self.client.post('/api/v1/decision/review',json=self.payload()).status_code,403)
 def test_cross_origin_denied(self):
  self.assertEqual(self.client.post('/api/v1/decision/review',json=self.payload(),headers=self.headers|{'Origin':'https://invalid.example'}).status_code,403)
 def test_symbol_mismatch_rejected(self):
  b=self.payload();b['symbol']='MSFT';self.assertEqual(self.client.post('/api/v1/decision/review',json=b,headers=self.headers).status_code,422)
 def test_no_paid_consent_parameter_needed(self):
  r=self.client.post('/api/v1/decision/review',json={'symbol':'NVDA'},headers=self.headers);self.assertEqual(r.status_code,200)
 def test_guarded_state_cannot_leak_unsafe_active_risks(self):
  x=recorded()['interpretation'];x['context_hash']=context_fixture()['context_hash'];self.store.save('impact-NVDA.json',x)
  r=self.client.get('/api/v1/decision/state?symbol=NVDA').json();self.assertEqual(r['latest_interpretation']['risks'],[])
 def test_context_version_change_does_not_trigger_paid_regeneration(self):
  x=recorded()['interpretation'];x['context_hash']='OLD';self.store.save('impact-NVDA.json',x)
  with patch('app.decision.call_openai',side_effect=AssertionError('NO API')):
   r=self.client.post('/api/v1/decision/review',json=self.payload(),headers=self.headers)
  self.assertEqual(r.status_code,200);self.assertTrue(r.json()['saved_report_present'])
 def test_no_saved_report_clearly_labeled(self):
  # Use a different symbol with no saved result; no artificial output marked AI.
  ctx=dict(context_fixture(),symbol='EXM')
  with patch('app.valuation_api.context',return_value=ctx):
   r=self.client.post('/api/v1/decision/review',json={'symbol':'EXM'},headers=self.headers)
  self.assertEqual(r.status_code,200);self.assertFalse(r.json()['saved_report_present']);self.assertIsNone(r.json().get('generated_at'))

if __name__=='__main__':unittest.main()
