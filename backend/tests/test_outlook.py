"""Synthetic unit/API fixtures only; NOT real issuer facts or measured AI accuracy."""
from __future__ import annotations
import copy
import json
import tempfile
import time
import unittest
from datetime import date, timedelta
from pathlib import Path
from unittest.mock import patch

from fastapi.testclient import TestClient
import app.main as main
from app.outlook import (AREAS, OUTLOOK_VERSION, OUTLOOK_CACHE_SECONDS, make_context,
                         outlook_request_body, parse_outlook, publication_relation, valid_day)
from app.research import ResearchService, ResearchError
from test_price_context import snapshot

TODAY = date(2026, 9, 9)

def context():
    return make_context({'symbol':'EXM','price_date':'2026-09-08','context_id':'test-price-id','stale_price':False}, TODAY)

def source(sid='s1', url='https://issuer.example/events', role='ISSUER', published='2026-08-26'):
    return {'id':sid,'url':url,'title':'SYNTHETIC EXAMPLE ONLY','role':role,
            'document_type':'IR calendar / synthetic fixture','published_date':published,'fiscal_period':None}

def catalyst(**changes):
    c={'title':'가상 기업 분기 실적 발표','category':'EARNINGS','timing':'ANNOUNCED_DATE',
       'event_date':'2026-11-17','window_start':None,'window_end':None,'window_label':None,
       'date_basis':'테스트용 회사 자료가 제시한 실적 발표 일정입니다.','date_source_ids':['s1'],
       'fact':'가상 기업이 분기 실적을 발표할 예정입니다. 실제 종목 정보가 아닙니다.',
       'why_it_matters':'매출이 늘고 있는지 확인할 수 있습니다.','positive_condition':'판매와 이익이 함께 늘어나는 경우입니다.',
       'negative_condition':'판매가 늘어도 비용이 더 빠르게 증가하는 경우입니다.','watch':'매출 성장과 이익률을 함께 확인합니다.',
       'importance':'HIGH','importance_reason':'사업 성과를 직접 확인하는 일정입니다.','source_ids':['s1']}
    c.update(changes);return c

def risk(**changes):
    r={'title':'조건부 보증 부담 · 테스트','category':'DEBT','fact':'가상 기업은 특정 계약 의무를 보증한다고 공시했습니다.',
       'mechanism':'상대방이 지급하지 못하면 현금 부담이 생길 수 있습니다.','trigger':'계약상 채무불이행 등 조건이 충족되는 경우입니다.',
       'monitor':'보증 조건과 실제 청구 여부를 확인합니다.','mitigating_factor':None,'state':'CONDITIONAL',
       'amount_basis':'LIMIT','amount_caution':'한도는 확정 손실이 아닙니다.','importance':'HIGH',
       'importance_reason':'예상하지 못한 현금 부담이 생길 수 있습니다.','source_ids':['s1']}
    r.update(changes);return r

def document(scope='catalysts'):
    return {'schema_version':'outlook-1','symbol':'EXM','identity':{'name':'Example Company (Synthetic)','security_type':'COMPANY','source_ids':['s1']},
            'sources':[source()], 'coverage':[{'area':a,'status':'FOUND','source_ids':['s1'],'note':'테스트에서 연결한 합성 자료입니다.'} for a in AREAS[scope]],
            'unresolved':['실제 발행사 자료가 아닌 테스트 전용입니다.'],scope:[catalyst() if scope=='catalysts' else risk()]}

def raw(document=None,scope='catalysts',tool_urls=None):
    d=copy.deepcopy(document if document is not None else globals()['document'](scope))
    urls=tool_urls if tool_urls is not None else [s['url'] for s in d['sources']]
    return {'status':'completed','output':[
        {'type':'web_search_call','status':'completed','action':{'type':'search','queries':['SYNTHETIC issuer upcoming events'], 'sources':[{'url':u} for u in urls]}},
        {'type':'message','role':'assistant','content':[{'type':'output_text','text':json.dumps(d,ensure_ascii=False),'annotations':[]}]}],
        'usage':{'input_tokens':200,'output_tokens':400,'total_tokens':600}}

class OutlookDateTests(unittest.TestCase):
    def test_old_publication_announces_future_event(self):
        r=parse_outlook(raw(),'catalysts',context());self.assertEqual(r['items'][0]['event_date'],'2026-11-17')
        self.assertEqual(r['sources'][0]['publication_relation'],'BEFORE_PRICE_DATE')
    def test_prior_source_never_classified_as_after_price(self):
        self.assertEqual(publication_relation('2026-09-02','2026-09-08'),'BEFORE_PRICE_DATE')
    def test_after_price_before_research_is_marked_after(self):
        d=document();d['sources'][0]['published_date']='2026-09-09'
        self.assertEqual(parse_outlook(raw(d),'catalysts',context())['sources'][0]['publication_relation'],'AFTER_PRICE_DATE')
    def test_same_day_time_is_unknown(self):self.assertEqual(publication_relation('2026-09-08','2026-09-08'),'SAME_DATE_TIME_UNKNOWN')
    def test_undated_calendar_is_not_given_today(self):
        d=document();d['sources'][0]['published_date']=None;r=parse_outlook(raw(d),'catalysts',context())
        self.assertIsNone(r['sources'][0]['published_date']);self.assertEqual(r['items'][0]['timing'],'ANNOUNCED_DATE')
    def test_future_publication_blocks_identity(self):
        d=document();d['sources'][0]['published_date']='2026-09-10'
        with self.assertRaises(ResearchError):parse_outlook(raw(d),'catalysts',context())
    def test_past_event_is_not_a_future_catalyst(self):
        d=document();d['catalysts'][0]['event_date']='2026-08-26';r=parse_outlook(raw(d),'catalysts',context())
        self.assertEqual(r['items'],[]);self.assertEqual(r['excluded_item_count'],1)
    def test_180_day_boundaries(self):
        for offset,expected in [(0,'D30'),(30,'D30'),(31,'D90'),(90,'D90'),(91,'D180'),(180,'D180')]:
            with self.subTest(offset=offset):
                d=document();d['catalysts'][0]['event_date']=(TODAY+timedelta(days=offset)).isoformat()
                self.assertEqual(parse_outlook(raw(d),'catalysts',context())['items'][0]['bucket'],expected)
    def test_181_days_is_not_in_180_horizon(self):
        d=document();d['catalysts'][0]['event_date']=(TODAY+timedelta(days=181)).isoformat()
        self.assertEqual(parse_outlook(raw(d),'catalysts',context())['items'],[])
    def test_impossible_date_removed_not_nearest(self):
        d=document();d['catalysts'][0]['event_date']='2027-02-30'
        self.assertEqual(parse_outlook(raw(d),'catalysts',context())['items'],[])
    def test_unconfirmed_never_acquires_horizon_or_day(self):
        d=document();d['catalysts'][0]['timing']='UNCONFIRMED'
        r=parse_outlook(raw(d),'catalysts',context())['items'][0]
        self.assertIsNone(r['event_date']);self.assertIsNone(r['days_to_start']);self.assertEqual(r['bucket'],'UNKNOWN')
    def test_no_date_source_downgrades_without_inventing_estimate(self):
        d=document();d['catalysts'][0]['date_source_ids']=[];r=parse_outlook(raw(d),'catalysts',context())['items'][0]
        self.assertEqual(r['timing'],'UNCONFIRMED');self.assertIsNone(r['event_date'])
    def test_reporting_date_is_not_official_announcement(self):
        d=document();d['sources'][0]['role']='REPORTING'
        self.assertEqual(parse_outlook(raw(d),'catalysts',context())['items'][0]['timing'],'UNCONFIRMED')
    def test_explicit_reporting_estimate_stays_estimated(self):
        d=document();d['sources'][0]['role']='REPORTING';d['catalysts'][0]['timing']='ESTIMATED'
        self.assertEqual(parse_outlook(raw(d),'catalysts',context())['items'][0]['timing'],'ESTIMATED')
    def test_announced_window_keeps_full_interval(self):
        d=document();d['catalysts'][0].update(timing='ANNOUNCED_WINDOW',event_date=None,window_start='2026-09-01',window_end='2026-09-30',window_label='2026년 9월')
        r=parse_outlook(raw(d),'catalysts',context())['items'][0]
        self.assertTrue(r['window_overlaps_today']);self.assertEqual(r['window_start'],'2026-09-01')
    def test_reversed_window_is_not_displayed_precisely(self):
        d=document();d['catalysts'][0].update(timing='ANNOUNCED_WINDOW',event_date=None,window_start='2026-12-01',window_end='2026-10-01')
        r=parse_outlook(raw(d),'catalysts',context())['items'][0];self.assertEqual(r['bucket'],'UNKNOWN')
    def test_exact_and_window_conflict_is_unknown(self):
        d=document();d['catalysts'][0].update(window_start='2026-11-01',window_end='2026-11-30')
        self.assertIsNone(parse_outlook(raw(d),'catalysts',context())['items'][0]['event_date'])
    def test_invalid_calendar_input_raises(self):
        for day in ['2026-9-09','tomorrow','2026-02-29',None]:
            if day is None:self.assertIsNone(valid_day(day))
            else:
                with self.subTest(day=day),self.assertRaises(ValueError):valid_day(day)

class OutlookParserTests(unittest.TestCase):
    def test_duplicate_source_ids_rejected_even_when_first_link_was_removed(self):
        d=document();d['sources'].insert(0,source(url='https://unlinked.example/item'))
        with self.assertRaises(ResearchError) as e:
            parse_outlook(raw(d,tool_urls=['https://issuer.example/events']),'catalysts',context())
        self.assertEqual(e.exception.code,'OUTLOOK_SOURCE_IDS')
    def test_downgraded_schedule_does_not_repeat_asserted_date_basis(self):
        d=document();d['catalysts'][0]['date_source_ids']=[]
        item=parse_outlook(raw(d),'catalysts',context())['items'][0]
        self.assertEqual(item['timing'],'UNCONFIRMED')
        self.assertIn('다시 확인',item['date_basis'])
        self.assertIsNone(item['event_date'])
    def test_real_search_metadata_required(self):
        r=raw();r['output'][0]['status']='failed'
        with self.assertRaises(ResearchError) as e:parse_outlook(r,'catalysts',context())
        self.assertEqual(e.exception.code,'OUTLOOK_NO_SEARCH')
    def test_fabricated_link_is_not_a_source(self):
        d=document();d['sources'][0]['url']='https://unlinked.example/story'
        with self.assertRaises(ResearchError):parse_outlook(raw(d,tool_urls=['https://issuer.example/events']),'catalysts',context())
    def test_tracking_removed_only_for_matching(self):
        d=document();d['sources'][0]['url']+='?utm_source=openai'
        r=parse_outlook(raw(d,tool_urls=['https://issuer.example/events']),'catalysts',context())
        self.assertEqual(len(r['items']),1)
    def test_different_semantic_query_is_not_same_source(self):
        d=document();d['sources'][0]['url']+='?document=2'
        with self.assertRaises(ResearchError):parse_outlook(raw(d,tool_urls=['https://issuer.example/events?document=1']),'catalysts',context())
    def test_private_and_script_urls_blocked(self):
        for url in ['http://127.0.0.1/a','javascript:alert(1)','file:///etc/passwd','http://localhost/a']:
            d=document();d['sources'][0]['url']=url
            with self.subTest(url=url),self.assertRaises(ResearchError):parse_outlook(raw(d),'catalysts',context())
    def test_wrong_ticker_is_rejected(self):
        d=document();d['symbol']='OTHER'
        with self.assertRaises(ResearchError) as e:parse_outlook(raw(d),'catalysts',context())
        self.assertEqual(e.exception.code,'OUTLOOK_SYMBOL')
    def test_unknown_identity_not_filled(self):
        d=document();d['identity']['security_type']='UNKNOWN'
        with self.assertRaises(ResearchError):parse_outlook(raw(d),'catalysts',context())
    def test_incomplete_response_never_rendered(self):
        r=raw();r['status']='incomplete'
        with self.assertRaises(ResearchError):parse_outlook(r,'catalysts',context())
    def test_refusal_not_overridden(self):
        r=raw();r['output'][1]['content']=[{'type':'refusal','refusal':'no'}]
        with self.assertRaises(ResearchError):parse_outlook(r,'catalysts',context())
    def test_invalid_json_no_automatic_repair(self):
        r=raw();r['output'][1]['content'][0]['text']='```json invalid```'
        with self.assertRaises(ResearchError):parse_outlook(r,'catalysts',context())
    def test_duplicate_json_keys_rejected(self):
        r=raw();r['output'][1]['content'][0]['text']='{"symbol":"EXM", "symbol":"OTHER"}'
        with self.assertRaises(ResearchError):parse_outlook(r,'catalysts',context())
    def test_extra_fields_rejected(self):
        d=document();d['target_price']=9999
        with self.assertRaises(ResearchError):parse_outlook(raw(d),'catalysts',context())
    def test_length_limit_not_lossy_truncation(self):
        d=document();d['catalysts'][0]['fact']='A'*400
        with self.assertRaises(ResearchError):parse_outlook(raw(d),'catalysts',context())
    def test_unlinked_item_is_removed_with_visible_count(self):
        d=document();d['catalysts'][0]['source_ids']=['s99'];r=parse_outlook(raw(d),'catalysts',context())
        self.assertEqual(r['items'],[]);self.assertEqual(r['excluded_item_count'],1);self.assertTrue(r['validation_notes'])
    def test_empty_items_are_allowed_not_auto_filled(self):
        d=document();d['catalysts']=[];r=parse_outlook(raw(d),'catalysts',context())
        self.assertEqual(r['items'],[]);self.assertEqual(r['status'],'PARTIAL')
    def test_missing_coverage_marked_unavailable(self):
        d=document();d['coverage']=[];r=parse_outlook(raw(d),'catalysts',context())
        self.assertEqual(len(r['coverage']),4);self.assertTrue(all(c['status']=='UNAVAILABLE' for c in r['coverage']))
    def test_found_without_source_downgrades_coverage(self):
        d=document();d['coverage'][0]['source_ids']=[];r=parse_outlook(raw(d),'catalysts',context())
        self.assertEqual(r['coverage'][0]['status'],'UNAVAILABLE')
    def test_duplicate_card_removed(self):
        d=document();d['catalysts'].append(copy.deepcopy(d['catalysts'][0]))
        self.assertEqual(len(parse_outlook(raw(d),'catalysts',context())['items']),1)
    def test_guarantee_limit_caution_is_code_enforced(self):
        d=document('risks');d['risks'][0]['amount_caution']=None
        item=parse_outlook(raw(d),'risks',context())['items'][0]
        self.assertIn('확정 손실과 다릅니다',item['mandatory_amount_notice'])
    def test_ordinary_risk_no_limit_caution(self):
        d=document('risks');d['risks'][0]['amount_basis']='NONE'
        self.assertNotIn('mandatory_amount_notice',parse_outlook(raw(d),'risks',context())['items'][0])
    def test_fiscal_period_not_derived_from_calendar(self):
        d=document();d['sources'][0]['fiscal_period']='FY2027 Q2 (fixture)'
        self.assertEqual(parse_outlook(raw(d),'catalysts',context())['sources'][0]['fiscal_period'],'FY2027 Q2 (fixture)')
    def test_sources_have_no_fact_verification_claim(self):
        s=parse_outlook(raw(),'catalysts',context())['sources'][0]
        self.assertEqual(s['validation'],'WEB_TOOL_URL_MATCH_ONLY');self.assertTrue(s['metadata_is_ai_extracted'])
    def test_scope_specific_schema_and_queries(self):
        a=outlook_request_body(context(),'catalysts','gpt-5-mini');b=outlook_request_body(context(),'risks','gpt-5-mini')
        self.assertTrue(a['text']['format']['strict']);self.assertIn('CALL_FORWARD_SCHEDULE',a['instructions'])
        self.assertIn('FINANCIAL_NOTES',b['instructions']);self.assertNotEqual(a['text']['format']['schema'],b['text']['format']['schema'])
        self.assertFalse(a['store']);self.assertEqual(a['max_tool_calls'],6);self.assertNotIn('api_key',json.dumps(a))
    def test_no_ticker_specific_story_in_instructions(self):
        ins=outlook_request_body(context(),'risks','gpt-5-mini')['instructions']
        self.assertNotIn('NVIDIA',ins);self.assertNotIn('Marvell',ins);self.assertNotIn('105',ins)
    def test_context_changes_on_new_research_day(self):
        a=context();b=make_context({'symbol':'EXM','price_date':a['price_date'],'context_id':'test-price-id'},TODAY+timedelta(days=1))
        self.assertNotEqual(a['context_id'],b['context_id'])
    def test_context_has_no_historical_clicked_event(self):self.assertNotIn('event_date',context())
    def test_schema_all_properties_required(self):
        def inspect(x):
            if isinstance(x,dict):
                if x.get('type')=='object':
                    self.assertFalse(x['additionalProperties']);self.assertEqual(set(x['required']),set(x['properties']))
                for v in x.values():inspect(v)
            elif isinstance(x,list):
                for v in x:inspect(v)
        for scope in ['catalysts','risks']:inspect(outlook_request_body(context(),scope,'gpt-5-mini')['text']['format']['schema'])

class OutlookServiceTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.root=Path(self.tmp.name)
        (self.root/'.env.signaldesk').write_text('OPENAI_API_KEY=sk-offline-fixture-'+'x'*30)
        self.service=ResearchService(self.root);d=snapshot();d['symbol']='EXM';d['price_context']['symbol']='EXM'
        self.token=self.service.snapshots.add(d)
        self.ctx=patch.object(self.service,'outlook_context',return_value=context());self.ctx.start()
    def tearDown(self):self.ctx.stop();self.tmp.cleanup()
    def invoke(self,scope='catalysts',consent=True,refresh=False):return self.service.analyze_outlook(self.token,scope,consent,refresh)
    def test_cache_inspection_never_calls_provider(self):
        with patch('app.research.call_openai') as call:
            self.assertIsNone(self.service.cached_outlook(self.token)['reports']['risks']);call.assert_not_called()
    def test_separate_consent_required(self):
        with patch('app.research.call_openai') as call:
            with self.assertRaises(ResearchError):self.invoke(consent=False)
            call.assert_not_called()
    def test_missing_key_no_call(self):
        (self.root/'.env.signaldesk').unlink()
        with patch('app.research.call_openai') as call:
            with self.assertRaises(ResearchError):self.invoke()
            call.assert_not_called()
    def test_one_paid_call_per_scope_and_no_auto_summary_call(self):
        with patch('app.research.call_openai',return_value=raw()) as call:self.invoke();self.assertEqual(call.call_count,1)
    def test_same_report_cache_free_without_consent(self):
        with patch('app.research.call_openai',return_value=raw()) as call:
            self.invoke();r=self.invoke(consent=False);self.assertTrue(r['cache_hit']);self.assertEqual(call.call_count,1)
    def test_purposes_have_independent_caches(self):
        with patch('app.research.call_openai',side_effect=[raw(),raw(scope='risks')]) as call:
            self.invoke();self.invoke('risks');self.assertEqual(call.call_count,2)
            r=self.service.cached_outlook(self.token);self.assertEqual(r['reports']['catalysts']['scope'],'catalysts');self.assertEqual(r['reports']['risks']['scope'],'risks')
    def test_first_result_survives_second_failure(self):
        with patch('app.research.call_openai',side_effect=[raw(),ResearchError('TEST','fixture failure')]):
            self.invoke()
            with self.assertRaises(ResearchError):self.invoke('risks')
        reports=self.service.cached_outlook(self.token)['reports'];self.assertIsNotNone(reports['catalysts']);self.assertIsNone(reports['risks'])
    def test_daily_quota_counts_both_requests(self):
        with patch('app.research.call_openai',side_effect=[raw(),raw(scope='risks')]):self.invoke();self.invoke('risks')
        with self.service._db() as db:self.assertEqual(db.execute('SELECT SUM(n) FROM attempts').fetchone()[0],2)
    def test_failure_not_automatically_retried(self):
        with patch('app.research.call_openai',side_effect=ResearchError('TEST','fixture')) as call:
            with self.assertRaises(ResearchError):self.invoke()
            self.assertEqual(call.call_count,1)
        self.assertFalse(self.service._active.locked())
    def test_old_saved_result_survives_failed_refresh(self):
        with patch('app.research.call_openai',return_value=raw()):self.invoke()
        with patch('app.research.call_openai',side_effect=ResearchError('TEST','fixture')):
            with self.assertRaises(ResearchError):self.invoke(refresh=True)
        self.assertIsNotNone(self.service.cached_outlook(self.token)['reports']['catalysts'])
    def test_cached_expiry_six_hours(self):
        with patch('app.research.call_openai',return_value=raw()):self.invoke()
        with self.service._db() as db:expires=db.execute('SELECT expires FROM cache').fetchone()[0]
        self.assertLessEqual(expires-time.time(),21600);self.assertGreater(expires-time.time(),21550)
    def test_busy_lock_shared_with_other_ai_features(self):
        self.service._active.acquire()
        try:
            with patch('app.research.call_openai') as call:
                with self.assertRaises(ResearchError) as err:self.invoke()
                self.assertEqual(err.exception.code,'AI_BUSY');call.assert_not_called()
        finally:self.service._active.release()
    def test_bad_format_costs_one_attempt_not_retry(self):
        response=raw();response['status']='incomplete'
        with patch('app.research.call_openai',return_value=response) as call:
            with self.assertRaises(ResearchError):self.invoke()
            self.assertEqual(call.call_count,1)
    def test_existing_credentials_bytes_unchanged(self):
        before=(self.root/'.env.signaldesk').read_bytes()
        with patch('app.research.call_openai',return_value=raw()):self.invoke()
        self.assertEqual(before,(self.root/'.env.signaldesk').read_bytes())
    def test_result_has_no_credentials(self):
        with patch('app.research.call_openai',return_value=raw()):r=self.invoke()
        self.assertNotIn('sk-offline-fixture',json.dumps(r));self.assertEqual(r['analysis_mode'],'FORWARD_CATALYST_RISK')

class OutlookAPITests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.svc=ResearchService(Path(self.tmp.name));self.token=self.svc.snapshots.add(snapshot())
        self.p=patch.object(main,'research',self.svc);self.p.start();self.client=TestClient(main.app)
        self.body={'snapshot_id':self.token,'scope':'catalysts','allow_paid':True,'refresh_report':False}
        self.headers={'X-SignalDesk-AI':self.svc.csrf_token}
    def tearDown(self):self.client.close();self.p.stop();self.tmp.cleanup()
    def test_get_does_not_invoke_paid_api(self):
        with patch('app.research.call_openai') as call:
            r=self.client.get('/api/v1/ai/outlook/cache',params={'snapshot_id':self.token});self.assertEqual(r.status_code,200);call.assert_not_called()
    def test_missing_local_token_rejected(self):self.assertEqual(self.client.post('/api/v1/ai/outlook/analyze',json=self.body).status_code,403)
    def test_cross_origin_rejected(self):
        r=self.client.post('/api/v1/ai/outlook/analyze',json=self.body,headers={**self.headers,'Origin':'https://other.example'});self.assertEqual(r.status_code,403)
    def test_arbitrary_prompt_or_ticker_rejected(self):
        for key in ['ticker','prompt','api_key','model','research_date','horizon']:
            with self.subTest(key=key):self.assertEqual(self.client.post('/api/v1/ai/outlook/analyze',json={**self.body,key:'injected'},headers=self.headers).status_code,422)
    def test_string_true_is_not_paid_consent(self):
        self.assertEqual(self.client.post('/api/v1/ai/outlook/analyze',json={**self.body,'allow_paid':'true'},headers=self.headers).status_code,422)
    def test_scope_enum_checked(self):self.assertEqual(self.client.post('/api/v1/ai/outlook/analyze',json={**self.body,'scope':'all'},headers=self.headers).status_code,422)
    def test_expired_snapshot_no_provider_call(self):
        self.svc.snapshots._items[self.token]=(0,snapshot())
        with patch('app.research.call_openai') as call:
            self.assertEqual(self.client.get('/api/v1/ai/outlook/cache',params={'snapshot_id':self.token}).status_code,409);call.assert_not_called()
    def test_status_exposes_feature_not_key(self):
        d=self.client.get('/api/v1/ai/status').json();self.assertTrue(d['outlook_available']);self.assertEqual(d['outlook_cache_hours'],6);self.assertNotIn('api_key',d)

if __name__=='__main__':unittest.main()
