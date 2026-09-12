"""Offline only. All businesses, names and numbers below are synthetic fixtures."""
import copy
import json
import tempfile
import unittest
from pathlib import Path
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo
from unittest.mock import patch, Mock

from fastapi import FastAPI
from fastapi.testclient import TestClient
from fastapi.responses import JSONResponse
from app.research import ResearchService, ResearchError, Settings
from app.provider import ProviderError
from app.thesis_engine import (ThesisService, ThesisDocument, research_request, normalize_request,
                              research_packet, parse_thesis, VERSION, _packet_hash)
from app.dilution_watch import WatchStore, SecClient, stamp
from app.watch_api import install_routes

DAY=datetime.now(ZoneInfo('America/New_York')).date().isoformat()
FIXTURES={
 'DCTX':('데이터시설 예제회사','DEMAND','시험 ALPHA 프로젝트 고객 임대 전환','회사는 ALPHA 프로젝트 임대 조건을 협의 중이며 아직 계약이 없다고 발표했다.',
         '시험 ALPHA의 구속력 있는 고객 계약과 조달 조건이 확인된다.', '시험 ALPHA의 고객 협상 철회 또는 자금확보 지연이 공시된다.'),
 'MEDX':('의약 예제회사','PRODUCT','시험 MX 물질 임상 검증','회사는 MX 후보물질 결과가 아직 나오지 않았다고 발표했다.',
         '시험 MX의 사전 명시된 유효성 지표와 안전성 결과가 발표된다.', '시험 MX의 목표 지표 미달 또는 안전성 문제로 개발이 중단된다.'),
 'SFTX':('소프트웨어 예제회사','ECONOMICS','시험 유료고객 유지와 수익성','회사는 유료고객 이탈이 늘고 계약 갱신이 과제라고 발표했다.',
         '시험 제품의 갱신율 회복과 현금흐름 개선이 보고된다.', '시험 제품의 유료고객 이탈 증가와 매출 수축이 보고된다.'),
 'BNKX':('은행 예제회사','FUNDING','시험 조달 안정과 신용비용','회사는 예금 비용 상승과 대손충당금 확대를 보고했다.',
         '시험 은행의 조달비용 안정과 신용비용 감소가 보고된다.', '시험 은행의 예금 이탈과 충당금 증가가 동시에 나타난다.'),
 'OREX':('광산 예제회사','EXECUTION','시험 채굴 가동률 전환','회사는 시험 광산 가동 목표가 아직 달성되지 않았다고 발표했다.',
         '시험 광산의 실제 생산량과 원가 개선이 공식 보고된다.', '시험 광산 가동 지연과 원가 상승이 공식 보고된다.')}

def web_raw(symbol='DCTX', annotations=True):
 name,axis,title,fact,up,down=FIXTURES[symbol]
 texts=[f'{name}는 미국 거래 티커 {symbol}의 현재 발행사다. [1]',
        f'{name}의 핵심 과제는 {title}다. {fact} 조건: {up} 실패: {down} 사업 성과는 공개된 계약과 운영 지표에서 확인할 수 있다. [2]',
        f'{name}는 운영 현금과 차입 여건을 점검한다고 공시했다. 자금 확보가 지연되면 신주 조달이 필요할 수 있으나 발행은 확인되지 않았다. [3]']
 memo='\n\n'.join(texts);anns=[]
 for i,t in enumerate(texts,1):
  token=f'[{i}]';start=memo.index(token)
  anns.append({'type':'url_citation','start_index':start,'end_index':start+len(token),'url':f'https://example.com/{symbol.lower()}/{i}','title':f'{name} 시험문서 {i}'})
 return {'status':'completed','output':[
  {'type':'web_search_call','status':'completed','action':{'type':'search','sources':[{'url':a['url'],'title':a['title']} for a in anns]}},
  {'type':'message','role':'assistant','phase':'final_answer','content':[{'type':'output_text','text':memo,'annotations':anns if annotations else []}]}]}

def packet(symbol='DCTX'):
 return research_packet(web_raw(symbol),symbol,DAY)

def document(symbol='DCTX'):
 name,axis,title,fact,up,down=FIXTURES[symbol]
 return {'symbol':symbol,'identity':{'company_name':name,'confirmed':True,'evidence_ids':['E1']},
  'business_model':{'text':f'{name}는 공개된 사업 계약과 운영 실적을 통해 수익을 실현한다.','evidence_ids':['E2']},
  'investment_thesis':{'text':f'{title}의 진전이 실제 수익화로 이어지는지 확인하는 조건부 투자 논리다.','evidence_ids':['E2']},
  'bottlenecks':[{'axis':axis,'title':title,'current_fact':fact,'upside_condition':up,'downside_condition':down,
   'why_it_matters':'실제 고객 유지와 수익 실현 가능성이 사업 가치에 영향을 준다.',
   'confirmation':'해당 기업의 후속 계약 공시와 운영 지표 보고서를 확인한다.',
   'milestone_status':'CONDITIONAL','evidence_ids':['E2']}],
  'financing':{'current_state':'회사는 조달 여건을 점검 중이며 현재 신주 발행은 확인되지 않았다.',
   'risk_condition':'차입 여건이 악화되면 신주 발행 의존도가 커질 수 있다.', 'stage':'UNKNOWN','evidence_ids':['E3']},
  'unresolved':['후속 계약 조건과 자금 조달 방식은 아직 미확인이다.']}

def structured(doc=None, text=None):
 return {'status':'completed','output':[{'type':'message','role':'assistant','content':[
  {'type':'output_text','text':text if text is not None else json.dumps(doc if doc is not None else document(),ensure_ascii=False)}]}]}

class PromptTests(unittest.TestCase):
 def test_research_is_prose_and_no_schema(self):
  b=research_request('DCTX',DAY,'gpt-5-mini');self.assertNotIn('text',b);self.assertEqual(b['max_tool_calls'],8);self.assertFalse(b['store'])
 def test_extraction_has_no_web_or_previous_response(self):
  b=normalize_request(packet(),'gpt-5-mini');self.assertNotIn('tools',b);self.assertNotIn('previous_response_id',b);self.assertTrue(b['text']['format']['strict'])
 def test_no_ticker_specific_answer_or_capacity_in_prompt(self):
  s=json.dumps([research_request('TEST',DAY,'gpt-5-mini'),normalize_request({**packet(),'memo':'test','evidence':[],'sources':[]},'gpt-5-mini')])
  for t in ['AIB','KPTI','65MW','selinexor']:self.assertNotIn(t,s)
 def test_schema_strict_all_objects(self):
  def inspect(x):
   if isinstance(x,dict):
    if x.get('type')=='object':
     self.assertIs(x.get('additionalProperties'),False);self.assertEqual(set(x['required']),set(x['properties']))
    for v in x.values():inspect(v)
   elif isinstance(x,list):
    for v in x:inspect(v)
  inspect(ThesisDocument.model_json_schema())
 def test_no_private_fields_in_second_step(self):
  p=packet();p.update(contact='private@example.com',api_key='secret-key',snapshot_id='token',path='C:/Users/private');b=json.dumps(normalize_request(p,'gpt-5-mini'))
  for t in ['private@example','secret-key','C:/Users/private','snapshot_id']:self.assertNotIn(t,b)

class EvidenceTests(unittest.TestCase):
 def test_paragraphs_annotated_and_facts_preserved(self):
  p=packet();self.assertEqual(len(p['evidence']),3);self.assertIn('아직 계약이 없',p['evidence'][1]['text']);self.assertEqual(p['packet_hash'],_packet_hash(p))
 def test_commentary_not_used(self):
  r=web_raw();r['output'].insert(1,{'type':'message','role':'assistant','phase':'commentary','content':[{'type':'output_text','text':'INTERNAL_NOT_FOR_REPORT'}]});self.assertNotIn('INTERNAL',research_packet(r,'DCTX',DAY)['memo'])
 def test_incomplete_raises(self):
  r=web_raw();r['status']='incomplete'
  with self.assertRaises(ResearchError):research_packet(r,'DCTX',DAY)
 def test_refusal_raises(self):
  r=web_raw();r['output'][-1]['content']=[{'type':'refusal','refusal':'refused'}]
  with self.assertRaises(ResearchError):research_packet(r,'DCTX',DAY)
 def test_no_web_cannot_be_called_research(self):
  r=web_raw();r['output']=r['output'][1:]
  with self.assertRaises(ResearchError):research_packet(r,'DCTX',DAY)
 def test_malformed_annotation_is_not_claim_support(self):
  r=web_raw();r['output'][-1]['content'][0]['annotations'][1]['start_index']=-1
  self.assertEqual(len(research_packet(r,'DCTX',DAY)['evidence']),2)
 def test_unlinked_urls_do_not_establish_evidence(self):
  r=web_raw(annotations=False);r['output'][-1]['content'][0]['text']+=' https://not-returned.example/contract';p=research_packet(r,'DCTX',DAY);self.assertEqual(p['evidence'],[])
 def test_returned_explicit_url_can_support_paragraph(self):
  r=web_raw(annotations=False);r['output'][-1]['content'][0]['text']+=' https://example.com/dctx/3';self.assertEqual(len(research_packet(r,'DCTX',DAY)['evidence']),1)
 def test_private_sources_rejected(self):
  r=web_raw();r['output'][-1]['content'][0]['annotations'][0]['url']='http://127.0.0.1/admin';self.assertEqual(len(research_packet(r,'DCTX',DAY)['evidence']),2)
 def test_cited_sources_prioritized_over_search_noise(self):
  r=web_raw();r['output'][0]['action']['sources']=[{'url':f'https://example.com/noise/{n}'} for n in range(90)];p=research_packet(r,'DCTX',DAY);self.assertEqual(len(p['evidence']),3)
 def test_malformed_annotation_container_does_not_crash(self):
  r=web_raw();r['output'][-1]['content'][0]['annotations']=42;self.assertEqual(research_packet(r,'DCTX',DAY)['evidence'],[])
 def test_oversize_not_silently_truncated(self):
  r=web_raw();r['output'][-1]['content'][0]['text']='x'*31000
  with self.assertRaises(ResearchError):research_packet(r,'DCTX',DAY)

class NormalizeTests(unittest.TestCase):
 def test_five_different_sectors_same_engine(self):
  for symbol in FIXTURES:
   with self.subTest(symbol=symbol):
    value=parse_thesis(structured(document(symbol)),packet(symbol));self.assertEqual(value['status'],'READY');self.assertEqual(value['bottlenecks'][0]['title'],FIXTURES[symbol][2]);self.assertIsNone(value['financing']['estimated_dilution_pct'])
 def test_single_bad_item_not_erase_valid_item(self):
  d=document();d['bottlenecks'].append({'title':'bad'});r=parse_thesis(structured(d),packet());self.assertEqual(len(r['bottlenecks']),1);self.assertEqual(r['status'],'PARTIAL')
 def test_unknown_extra_fields_ignored_not_displayed(self):
  d=document();d['target_price']=999;d['bottlenecks'][0]['target_price']=999;r=parse_thesis(structured(d),packet());self.assertNotIn('target_price',json.dumps(r));self.assertEqual(r['status'],'READY')
 def test_markdown_wrapper_tolerated(self):
  self.assertEqual(parse_thesis(structured(text='```json\n'+json.dumps(document())+'\n```'),packet())['status'],'READY')
 def test_duplicate_json_keys_rejected(self):
  s=json.dumps(document());s=s.replace('"symbol": "DCTX"','"symbol":"OTHER","symbol":"DCTX"')
  with self.assertRaises(ResearchError):parse_thesis(structured(text=s),packet())
 def test_incomplete_json_not_guessed(self):
  with self.assertRaises(ResearchError):parse_thesis(structured(text=json.dumps(document())[:-5]),packet())
 def test_lowercase_enum_is_normalized(self):
  d=document();d['bottlenecks'][0]['axis']='demand';d['bottlenecks'][0]['milestone_status']='conditional';self.assertEqual(parse_thesis(structured(d),packet())['status'],'READY')
 def test_completed_not_pending(self):
  d=document();d['bottlenecks'][0]['milestone_status']='COMPLETED';self.assertEqual(parse_thesis(structured(d),packet())['bottlenecks'],[])
 def test_false_identity_blocks_thesis(self):
  d=document();d['identity']['confirmed']=False;r=parse_thesis(structured(d),packet());self.assertIsNone(r['investment_thesis']);self.assertEqual(r['status'],'INSUFFICIENT')
 def test_boolean_string_not_trusted(self):
  d=document();d['identity']['confirmed']='true';self.assertEqual(parse_thesis(structured(d),packet())['status'],'INSUFFICIENT')
 def test_ticker_must_exist_in_identity_evidence(self):
  d=document();d['identity']['evidence_ids']=['E2'];self.assertEqual(parse_thesis(structured(d),packet())['status'],'INSUFFICIENT')
 def test_wrong_company_rejected(self):
  d=document();d['symbol']='OTHER'
  with self.assertRaises(ResearchError):parse_thesis(structured(d),packet())
 def test_unlinked_fact_omitted_not_replaced(self):
  d=document();d['investment_thesis']['evidence_ids']=['E999'];r=parse_thesis(structured(d),packet());self.assertIsNone(r['investment_thesis']);self.assertEqual(len(r['bottlenecks']),1)
 def test_mixed_valid_invalid_refs_no_silent_partial_citation(self):
  d=document();d['bottlenecks'][0]['evidence_ids']=['E2','missing'];self.assertEqual(parse_thesis(structured(d),packet())['bottlenecks'],[])
 def test_one_sided_data_not_forced_pair(self):
  d=document();d['bottlenecks'][0]['upside_condition']=None;r=parse_thesis(structured(d),packet());self.assertIsNone(r['bottlenecks'][0]['upside_condition']);self.assertIsNotNone(r['bottlenecks'][0]['downside_condition'])
 def test_generic_conditions_omitted(self):
  d=document();d['bottlenecks'][0].update(upside_condition='호재가 나오면 주가가 오른다고 생각한다.',downside_condition='악재가 나오면 주가가 떨어질 수 있다.');self.assertEqual(parse_thesis(structured(d),packet())['bottlenecks'],[])
 def test_duplicate_questions_not_counted_twice(self):
  d=document();d['bottlenecks']*=2;self.assertEqual(len(parse_thesis(structured(d),packet())['bottlenecks']),1)
 def test_long_field_omitted_not_truncated(self):
  d=document();d['bottlenecks'][0]['current_fact']='x'*1001;self.assertEqual(parse_thesis(structured(d),packet())['bottlenecks'],[])
 def test_missing_optional_condition_is_unknown_not_full_drop(self):
  d=document();del d['bottlenecks'][0]['upside_condition'];r=parse_thesis(structured(d),packet());self.assertIsNone(r['bottlenecks'][0]['upside_condition']);self.assertEqual(len(r['bottlenecks']),1)
 def test_missing_optional_stage_not_promoted(self):
  d=document();del d['bottlenecks'][0]['milestone_status'];self.assertEqual(parse_thesis(structured(d),packet())['bottlenecks'][0]['milestone_status'],'UNKNOWN')
 def test_nan_is_invalid_json_not_financial_value(self):
  s=json.dumps(document());s=s[:-1]+',"number":NaN}'
  with self.assertRaises(ResearchError):parse_thesis(structured(text=s),packet())
 def test_inputs_immutable(self):
  d=structured();p=packet();a,b=copy.deepcopy(d),copy.deepcopy(p);parse_thesis(d,p);self.assertEqual(d,a);self.assertEqual(p,b)
 def test_absent_financing_not_safe_label(self):
  d=document();d['financing']=None;r=parse_thesis(structured(d),packet());self.assertIsNone(r['financing']);self.assertIn('위험이 없다는 뜻',str(r['unresolved']))
 def test_unexpected_tool_in_normalization_rejected(self):
  r=structured();r['output'].insert(0,{'type':'web_search_call','status':'completed'})
  with self.assertRaises(ResearchError):parse_thesis(r,packet())

class ServiceTests(unittest.TestCase):
 def setUp(self):
  self.tmp=tempfile.TemporaryDirectory();self.root=Path(self.tmp.name);self.research=ResearchService(self.root);self.research.outlook_context=Mock(return_value={'symbol':'DCTX','research_date':DAY});self.svc=ThesisService(self.root,self.research)
  self.settings=patch('app.thesis_engine.read_settings',return_value=Settings('x'*40,'gpt-5-mini'));self.settings.start()
 def tearDown(self):self.settings.stop();self.tmp.cleanup()
 def execute(self,outputs=None,**kw):
  with patch('app.research.call_openai',side_effect=outputs or [web_raw(),structured()]) as call:
   result=self.svc.analyze('test',True,True,max_paid_calls=2,**kw)
   return result,call
 def test_two_steps_and_two_recorded_attempts(self):
  r,c=self.execute();self.assertEqual(r['status'],'READY');self.assertEqual(c.call_count,2);self.assertEqual(r['ai_calls'],2)
  with self.research._db() as db:self.assertEqual(db.execute('SELECT SUM(n) FROM attempts').fetchone()[0],2)
 def test_no_consent_no_call(self):
  with patch('app.research.call_openai',side_effect=AssertionError):
   with self.assertRaises(ResearchError):self.svc.analyze('test',False,True,2)
 def test_old_one_call_consent_cannot_charge_two(self):
  with patch('app.research.call_openai',side_effect=AssertionError):
   with self.assertRaisesRegex(ResearchError,'.*'):self.svc.analyze('test',True,True,1)
 def test_failure_keeps_draft_and_no_automatic_retry(self):
  r,c=self.execute([web_raw(),structured(text='{bad')]);self.assertEqual(c.call_count,2);self.assertEqual(r['status'],'STRUCTURE_FAILED');self.assertTrue(self.svc.draft('DCTX')['can_resume']);self.assertFalse(self.research._active.locked())
 def test_reformat_uses_one_request_and_no_web(self):
  self.execute([web_raw(),structured(text='{bad')])
  with patch('app.research.call_openai',return_value=structured()) as call:
   r=self.svc.analyze('test',True,True,1,True);self.assertEqual(call.call_count,1);self.assertNotIn('tools',call.call_args[0][1]);self.assertTrue(r['research_reused'])
 def test_failed_update_does_not_erase_good_report(self):
  old,_=self.execute();r,_=self.execute([web_raw(),structured(text='{bad')]);self.assertEqual(self.svc.cached('DCTX')['packet_hash'],old['packet_hash']);self.assertIsNotNone(r['previous_report'])
 def test_insufficient_update_keeps_old_report(self):
  old,_=self.execute();d=document();d['identity']['confirmed']=False;r,_=self.execute([web_raw(),structured(d)]);self.assertEqual(r['status'],'INSUFFICIENT_UPDATE');self.assertEqual(self.svc.cached('DCTX')['generated_at'],old['generated_at'])
 def test_expired_draft_never_silent_fresh_research(self):
  p=packet();p['generated_at']=(datetime.now(timezone.utc)-timedelta(hours=7)).isoformat();self.svc.store.save('thesis-draft-DCTX.json',p)
  with patch('app.research.call_openai',side_effect=AssertionError):
   with self.assertRaises(ResearchError):self.svc.analyze('test',True,True,1,True)
 def test_draft_tamper_not_used(self):
  p=packet();p['memo']='changed';self.svc.store.save('thesis-draft-DCTX.json',p);self.assertIsNone(self.svc.draft('DCTX'))
 def test_metadata_only_research_skips_second_paid_call(self):
  r,c=self.execute([web_raw(annotations=False)]);self.assertEqual(c.call_count,1);self.assertEqual(r['status'],'RESEARCH_ONLY')
 def test_research_failure_unlocks_and_logs_safe_error(self):
  with patch('app.research.call_openai',side_effect=ResearchError('AI_TIMEOUT','safe message',504)) as call:
   with self.assertRaises(ResearchError):self.svc.analyze('test',True,True,2)
   self.assertEqual(call.call_count,1);self.assertFalse(self.research._active.locked());self.assertEqual(self.svc.last_attempt('DCTX')['error_code'],'AI_TIMEOUT')
 def test_readonly_cache_does_not_research(self):
  self.execute()
  with patch('app.research.call_openai',side_effect=AssertionError):
   self.assertIsNotNone(self.svc.cached('DCTX'));self.assertIsNotNone(self.svc.draft('DCTX'));self.assertIsNone(self.svc.progress('OTHER'))
 def test_progress_and_lock_clear_after_success(self):
  self.execute();self.assertIsNone(self.svc.progress('DCTX'));self.assertFalse(self.research._active.locked())
 def test_busy_rejected(self):
  self.research._active.acquire()
  try:
   with patch('app.research.call_openai',side_effect=AssertionError):
    with self.assertRaises(ResearchError):self.svc.analyze('test',True,True,2)
  finally:self.research._active.release()
 def test_legacy_driver_files_not_overwritten(self):
  self.svc.store.save('drivers-DCTX.json',{'sentinel':'old'});self.execute();self.assertEqual(self.svc.store.read('drivers-DCTX.json'),{'sentinel':'old'})
 def test_no_sec_request_needed_for_thesis(self):
  self.svc.store.save('cooldown.json',{'until':999999999})
  with patch.object(SecClient,'get',side_effect=AssertionError('SEC')):r,_=self.execute();self.assertEqual(r['status'],'READY')
 def test_second_budget_limit_keeps_research(self):
  with patch.object(self.research,'_reserve_attempt',side_effect=[None,ResearchError('LOCAL_DAILY_LIMIT','limit',429)]):
   r,c=self.execute([web_raw()]);self.assertEqual(c.call_count,1);self.assertEqual(r['status'],'STRUCTURE_FAILED');self.assertEqual(r['ai_calls'],1)

class NewAPITests(unittest.TestCase):
 def setUp(self):
  self.tmp=tempfile.TemporaryDirectory();self.root=Path(self.tmp.name);self.research=ResearchService(self.root);self.research.outlook_context=Mock(return_value={'symbol':'DCTX','research_date':DAY});self.app=FastAPI()
  @self.app.exception_handler(ProviderError)
  async def provider_handle(req,e):return JSONResponse(status_code=e.status,content={'error':{'code':e.code,'message':e.message}})
  @self.app.exception_handler(ResearchError)
  async def handle(req,e):return JSONResponse(status_code=e.status,content={'error':{'code':e.code,'message':e.message}})
  def validate(req):
   if req.headers.get('x-signaldesk-ai')!=self.research.csrf_token:raise ResearchError('CSRF','blocked',403)
  install_routes(self.app,self.root,self.research,validate);self.client=TestClient(self.app);self.headers={'X-SignalDesk-AI':self.research.csrf_token}
 def tearDown(self):self.client.close();self.tmp.cleanup()
 def test_budget_boolean_is_not_two_request_consent(self):
  r=self.client.post('/api/v1/watch/drivers',headers=self.headers,json={'snapshot_id':'a'*24,'allow_paid':True,'refresh':True,'max_paid_calls':True});self.assertEqual(r.status_code,422)
 def test_single_old_request_rejected_before_cost(self):
  with patch('app.research.call_openai',side_effect=AssertionError):
   r=self.client.post('/api/v1/watch/drivers',headers=self.headers,json={'snapshot_id':'a'*24,'allow_paid':True,'refresh':True});self.assertEqual(r.status_code,400)
 def test_state_get_no_network_and_no_email(self):
  self.app.state.dilution_watch.store.set_contact('private@example.com')
  with patch.object(SecClient,'get',side_effect=AssertionError):
   r=self.client.get('/api/v1/watch/state?symbol=DCTX');self.assertEqual(r.status_code,200);self.assertNotIn('private@example',r.text);self.assertIn('sec_cooldown',r.json());self.assertEqual(r.json()['ai_calls'],0)
 def test_cooldown_exposes_only_wait_and_status(self):
  import time
  self.app.state.dilution_watch.store.save('cooldown.json',{'until':time.time()+600,'http_status':403,'secret':'never-show'})
  r=self.client.get('/api/v1/watch/state?symbol=DCTX');self.assertEqual(r.json()['sec_cooldown']['http_status'],403);self.assertNotIn('never-show',r.text)
 def test_unsafe_symbol_rejected(self):self.assertNotEqual(self.client.get('/api/v1/watch/state?symbol=../../.env').status_code,200)

if __name__=='__main__':unittest.main()
