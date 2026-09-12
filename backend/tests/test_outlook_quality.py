"""Synthetic data, offline mocks. NOT financial facts or live LLM accuracy scores."""
import copy
import json
import sqlite3
import tempfile
import time
import unittest
from pathlib import Path
from unittest.mock import patch

from app.outlook import OUTLOOK_VERSION, AREAS, parse_outlook
from app.outlook_quality import (QUALITY_VERSION, MAX_WEB_CALLS, quality_request_body,
                                 parse_quality_outlook, research_plan, seed_from_report)
from app.research import ResearchService, ResearchError
from test_outlook import context, document, raw, source, catalyst
from test_price_context import snapshot


def quality_doc(scope='catalysts'):
    d=document(scope);d['quality_schema']='quality-1'
    d['document_checks']=[{'source_ids':['s1'],'areas':list(AREAS[scope]),'access':'SECTION_READ',
                           'locator':'Closing calendar paragraph (synthetic)', 'note':'실제 공시가 아닌 테스트용 일정 부분입니다.'}]
    if scope=='catalysts':
        d['catalysts'][0]['schedule_evidence']={'source_ids':['s1'],'locator':'Closing paragraph 2 (synthetic)',
             'statement':'가상 발행사의 다음 실적 발표일은 2026년 11월 17일입니다. 테스트 전용.',
             'event_date':'2026-11-17','window_start':None,'window_end':None,'basis':'EXPLICIT_SCHEDULE'}
    else:
        d['sources'].append(source('s2','https://issuer.example/old-report',published='2025-05-28'))
        d['risks'][0].update(historical_observation={'text':'테스트 과거 손실 사례입니다.', 'as_of_date':'2025-05-01','source_ids':['s2']},
                            latest_observation={'text':'테스트 최신 분기에는 해당 노출이 계속된다고 적었습니다.','as_of_date':'2026-07-26','source_ids':['s1']},
                            change_summary='서로 다른 시점의 자료를 비교하는 테스트입니다.')
    return d


def quality_raw(d=None,scope='catalysts',opened=True):
    d=copy.deepcopy(d or quality_doc(scope));r=raw(d,scope)
    if opened:
        r['output'].insert(1,{'type':'web_search_call','status':'completed','action':{'type':'open_page','url':d['sources'][0]['url']}})
    return r


class QualityPlanTests(unittest.TestCase):
    def test_plan_prioritizes_latest_and_transcript_before_calendar(self):
        p=research_plan(context(),'catalysts');self.assertEqual([x['area'] for x in p[:3]],['LATEST_EARNINGS','CALL_FORWARD_SCHEDULE','IR_CALENDAR'])
        self.assertIn('closing',p[1]['query']);self.assertIn('next earnings',p[1]['query'])
    def test_no_ticker_story_hardcoded(self):
        for scope in ['catalysts','risks']:
            b=quality_request_body(context(),scope,'gpt-5-mini');txt=json.dumps(b,ensure_ascii=False)
            for word in ['NVIDIA','Marvell','H20','H200','Berlin','105 billion']:
                self.assertNotIn(word,txt)
            self.assertIn('EXM',b['input'])
    def test_risk_plan_quarterly_before_annual(self):
        self.assertEqual(research_plan(context(),'risks')[0]['area'],'QUARTERLY_MDA')
    def test_model_and_key_not_taken_from_seed(self):
        previous={'symbol':'EXM','scope':'catalysts','api_key':'DO_NOT_SEND','model':'bogus'}
        b=quality_request_body(context(),'catalysts','gpt-5-mini',previous)
        self.assertNotIn('DO_NOT_SEND',json.dumps(b));self.assertEqual(b['model'],'gpt-5-mini')
    def test_unknown_items_are_follow_up_queries_not_asserted_dates(self):
        prev={'symbol':'EXM','scope':'catalysts','items':[{'title':'테스트 제품 출시','bucket':'UNKNOWN','category':'PRODUCT'}],'sources':[]}
        b=quality_request_body(context(),'catalysts','gpt-5-mini',prev);data=json.loads(b['input'])
        self.assertEqual(data['research_plan'][-1]['area'],'FOLLOW_UP');self.assertIn('테스트 제품',data['research_plan'][-1]['query'])
        self.assertNotIn('event_date',data['previous_report_leads']['unknown_items'][0])
    def test_other_symbol_seed_discarded(self):
        self.assertFalse(seed_from_report({'symbol':'OTHER','scope':'catalysts','sources':[source()]},context(),'catalysts')['source_leads'])
    def test_private_source_lead_not_forwarded(self):
        prev={'symbol':'EXM','scope':'catalysts','sources':[source(url='http://127.0.0.1/secret')]}
        self.assertFalse(seed_from_report(prev,context(),'catalysts')['source_leads'])
    def test_schema_nullable_fields_required(self):
        def check(x):
            if isinstance(x,dict):
                if x.get('type')=='object':
                    self.assertFalse(x['additionalProperties']);self.assertEqual(set(x['properties']),set(x['required']))
                for v in x.values():check(v)
            elif isinstance(x,list):
                for v in x:check(v)
        for scope in ['catalysts','risks']:
            b=quality_request_body(context(),scope,'gpt-5-mini');check(b['text']['format']['schema'])
            self.assertEqual(b['max_tool_calls'],MAX_WEB_CALLS);self.assertFalse(b['store']);self.assertEqual(len(b['tools']),1)
    def test_legacy_request_contract_is_not_rewritten(self):
        from app.outlook import outlook_request_body
        self.assertEqual(outlook_request_body(context(),'catalysts','gpt-5-mini')['max_tool_calls'],6)


class QualityScheduleTests(unittest.TestCase):
    def parse(self,d=None,opened=True):return parse_quality_outlook(quality_raw(d,opened=opened),'catalysts',context())
    def test_future_date_from_past_publication_survives(self):
        r=self.parse();self.assertEqual(r['items'][0]['event_date'],'2026-11-17');self.assertEqual(r['items'][0]['bucket'],'D90')
        self.assertEqual(r['next_earnings_check'],'DATED');self.assertEqual(r['quality_version'],QUALITY_VERSION)
        self.assertEqual(r['sources'][0]['publication_relation'],'BEFORE_PRICE_DATE')
    def test_no_open_record_is_not_full_review(self):
        r=self.parse(opened=False);self.assertEqual(r['coverage'][0]['status'],'UNAVAILABLE')
        self.assertEqual(r['items'][0]['bucket'],'UNKNOWN');self.assertEqual(r['next_earnings_check'],'UNDATED')
    def test_search_snippet_not_upgraded_by_open_metadata_alone(self):
        d=quality_doc();d['document_checks'][0]['access']='SEARCH_ONLY'
        self.assertEqual(self.parse(d)['items'][0]['timing'],'UNCONFIRMED')
    def test_unavailable_source_cannot_authenticate_schedule(self):
        d=quality_doc();d['document_checks'][0]['access']='UNAVAILABLE'
        self.assertEqual(self.parse(d)['items'][0]['bucket'],'UNKNOWN')
    def test_different_evidence_date_withheld(self):
        d=quality_doc();d['catalysts'][0]['schedule_evidence']['event_date']='2026-11-18'
        self.assertEqual(self.parse(d)['items'][0]['bucket'],'UNKNOWN')
    def test_missing_schedule_evidence_withheld(self):
        d=quality_doc();d['catalysts'][0]['schedule_evidence']=None
        self.assertIsNone(self.parse(d)['items'][0]['event_date'])
    def test_wrong_source_evidence_withheld(self):
        d=quality_doc();d['catalysts'][0]['schedule_evidence']['source_ids']=['MISSING']
        self.assertIsNone(self.parse(d)['items'][0]['event_date'])
    def test_open_of_other_url_does_not_confirm_source(self):
        r=quality_raw();r['output'][1]['action']['url']='https://issuer.example/unrelated'
        out=parse_quality_outlook(r,'catalysts',context());self.assertEqual(out['items'][0]['bucket'],'UNKNOWN')
    def test_mixed_check_does_not_authenticate_unopened_second_source(self):
        d=quality_doc();d['sources'].append(source('s2','https://issuer.example/another'))
        d['document_checks'][0]['source_ids'].append('s2')
        d['catalysts'][0]['date_source_ids']=['s2'];d['catalysts'][0]['schedule_evidence']['source_ids']=['s2']
        self.assertEqual(self.parse(d)['items'][0]['bucket'],'UNKNOWN')
    def test_estimated_remains_estimated(self):
        d=quality_doc();d['sources'][0]['role']='REPORTING';d['catalysts'][0]['timing']='ESTIMATED';d['catalysts'][0]['schedule_evidence']['basis']='EXPLICIT_ESTIMATE'
        self.assertEqual(self.parse(d)['items'][0]['timing'],'ESTIMATED')
    def test_company_confirmed_not_built_from_reporting_source(self):
        d=quality_doc();d['sources'][0]['role']='REPORTING'
        self.assertEqual(self.parse(d)['items'][0]['timing'],'UNCONFIRMED')
    def test_conference_only_has_next_earnings_warning(self):
        d=quality_doc();d['catalysts'][0]['category']='CONFERENCE'
        r=self.parse(d);self.assertEqual(r['next_earnings_check'],'NOT_FOUND');self.assertTrue(r['quality_warnings'])
    def test_etf_not_given_corporate_earnings_missing_alarm(self):
        d=quality_doc();d['identity']['security_type']='ETF';d['catalysts']=[]
        self.assertEqual(self.parse(d)['next_earnings_check'],'NOT_APPLICABLE')
    def test_same_title_different_dates_keep_separate_evidence(self):
        d=quality_doc();second=copy.deepcopy(d['catalysts'][0]);second['event_date']='2026-10-21'
        second['schedule_evidence']['event_date']='2026-10-21';second['schedule_evidence']['locator']='Second different date'
        d['catalysts'].append(second);r=self.parse(d)
        self.assertEqual({i['event_date'] for i in r['items']},{'2026-10-21','2026-11-17'})
        self.assertEqual(r['items'][0]['schedule_evidence']['locator'],'Second different date')
    def test_original_url_and_locator_kept(self):
        r=self.parse();self.assertEqual(r['sources'][0]['url'],'https://issuer.example/events')
        self.assertIn('Closing',r['items'][0]['schedule_evidence']['locator'])
    def test_long_ids_rekey_new_nested_references_too(self):
        d=quality_doc();old='s1';new='a-very-long-web-document-source-id-'*5
        def rename(x):
            if isinstance(x,dict):
                for k,v in x.items():
                    if k=='id' and v==old:x[k]=new
                    elif k in ['source_ids','date_source_ids']:x[k]=[new if r==old else r for r in v]
                    else:rename(v)
            elif isinstance(x,list):
                for i in x:rename(i)
        rename(d);r=self.parse(d);sid=r['sources'][0]['id'];self.assertLessEqual(len(sid),30)
        self.assertEqual(r['document_checks'][0]['source_ids'],[sid]);self.assertEqual(r['items'][0]['schedule_evidence']['source_ids'],[sid])
        self.assertEqual(r['items'][0]['bucket'],'D90')
    def test_bad_new_metadata_preserves_core_but_withholds_dates(self):
        d=quality_doc();d['document_checks'][0]['locator']=123
        r=self.parse(d);self.assertEqual(r['quality_version'],'QUALITY_DETAILS_INCOMPLETE');self.assertEqual(r['items'][0]['bucket'],'UNKNOWN')
        self.assertEqual(r['sources'][0]['url'],'https://issuer.example/events')
    def test_bad_core_not_silently_allowed(self):
        d=quality_doc();d['catalysts'][0]['importance']='ABSOLUTE';d['document_checks']=[]
        with self.assertRaises(ResearchError):self.parse(d)
    def test_legacy_provider_output_is_labeled_not_claimed_new(self):
        r=parse_quality_outlook(raw(),'catalysts',context());self.assertEqual(r['quality_version'],'LEGACY_OUTPUT');self.assertEqual(r['status'],'PARTIAL')
    def test_no_claim_of_semantic_verification(self):
        r=self.parse();self.assertEqual(r['sources'][0]['validation'],'WEB_TOOL_URL_MATCH_ONLY')
        self.assertIn('독립 검증한 것은 아닙니다',r['quality_limitations'][0])


class QualityRiskTests(unittest.TestCase):
    def parse(self,d=None,opened=True):return parse_quality_outlook(quality_raw(d,scope='risks',opened=opened),'risks',context())
    def test_distinct_historical_and_latest_dates(self):
        item=self.parse()['items'][0];self.assertEqual(item['historical_observation']['as_of_date'],'2025-05-01')
        self.assertEqual(item['latest_observation']['as_of_date'],'2026-07-26');self.assertEqual(item['temporal_status'],'RECENT_SOURCE_LINKED')
        self.assertIn('확정 손실',item['mandatory_amount_notice'])
    def test_latest_absent_does_not_mean_risk_resolved(self):
        d=quality_doc('risks');d['risks'][0]['latest_observation']=None;r=self.parse(d)['items'][0]
        self.assertEqual(r['temporal_status'],'CURRENT_UNCONFIRMED');self.assertIsNone(r['change_summary']);self.assertTrue(r['temporal_notes'])
    def test_old_observation_in_new_release_is_old_observation(self):
        d=quality_doc('risks');d['risks'][0]['latest_observation']['as_of_date']='2025-06-01'
        self.assertEqual(self.parse(d)['items'][0]['temporal_status'],'OLDER_OBSERVATION')
    def test_identical_past_and_latest_text_is_not_new(self):
        d=quality_doc('risks');d['risks'][0]['latest_observation']['text']=d['risks'][0]['historical_observation']['text']
        self.assertIsNone(self.parse(d)['items'][0]['latest_observation'])
    def test_latest_older_than_history_withheld(self):
        d=quality_doc('risks');d['risks'][0]['latest_observation']['as_of_date']='2024-01-01'
        self.assertIsNone(self.parse(d)['items'][0]['latest_observation'])
    def test_observation_after_publication_not_claimed_as_fact(self):
        d=quality_doc('risks');d['risks'][0]['latest_observation']['as_of_date']='2026-09-01'
        self.assertIsNone(self.parse(d)['items'][0]['latest_observation'])
    def test_future_observation_withheld(self):
        d=quality_doc('risks');d['risks'][0]['latest_observation']['as_of_date']='2027-01-01'
        self.assertIsNone(self.parse(d)['items'][0]['latest_observation'])
    def test_invalid_observation_date_withheld_not_whole_result(self):
        d=quality_doc('risks');d['risks'][0]['latest_observation']['as_of_date']='2026-02-30'
        self.assertIsNone(self.parse(d)['items'][0]['latest_observation']);self.assertEqual(len(self.parse(d)['items']),1)
    def test_latest_unlinked_reference_withheld(self):
        d=quality_doc('risks');d['risks'][0]['latest_observation']['source_ids']=['missing']
        self.assertIsNone(self.parse(d)['items'][0]['latest_observation'])
    def test_primary_source_not_opened_never_claimed_recent_review(self):
        self.assertEqual(self.parse(opened=False)['items'][0]['temporal_status'],'CURRENT_UNCONFIRMED')
    def test_fiscal_period_kept_separate(self):
        d=quality_doc('risks');d['sources'][0]['fiscal_period']='FY2027 Q2 synthetic'
        r=self.parse(d);self.assertEqual(r['sources'][0]['fiscal_period'],'FY2027 Q2 synthetic');self.assertEqual(r['sources'][0]['published_date'],'2026-08-26')
    def test_newer_reviewed_quarter_not_linked_to_risk_is_flagged(self):
        d=quality_doc('risks');d['sources'].append(source('s3','https://issuer.example/newer',published='2026-09-01'))
        d['document_checks'].append({'source_ids':['s3'],'areas':['QUARTERLY_MDA'],'access':'SECTION_READ','locator':'Note 4 synthetic','note':'테스트 최신 자료'})
        r=quality_raw(d,scope='risks');r['output'].insert(1,{'type':'web_search_call','status':'completed','action':{'type':'open_page','url':d['sources'][2]['url']}})
        out=parse_quality_outlook(r,'risks',context());self.assertIn('더 최근 분기자료',' '.join(out['items'][0]['temporal_notes']))
    def test_recent_source_not_guaranteed_latest(self):
        r=self.parse();self.assertTrue(r['items'][0]['timeline_is_ai_extracted']);self.assertIn('최신성',r['quality_limitations'][0])


class QualityCacheTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.root=Path(self.temp.name)
        (self.root/'.env.signaldesk').write_text('OPENAI_API_KEY=sk-fixture-'+('x'*40))
        self.svc=ResearchService(self.root);self.token=self.svc.snapshots.add(snapshot())
        self.ctx=patch.object(self.svc,'outlook_context',return_value=context());self.ctx.start()
    def tearDown(self):self.ctx.stop();self.temp.cleanup()
    def seed_old(self):
        result=parse_outlook(raw(),'catalysts',context());result.update(symbol='EXM',scope='catalysts',context_id=context()['context_id'])
        key=self.svc.cache_key(context(),'gpt-5-mini',OUTLOOK_VERSION+':catalysts')
        with self.svc._db() as db:db.execute('INSERT INTO cache VALUES(?,?,?)',(key,time.time()+3600,json.dumps(result)))
    def test_old_cache_loaded_without_billing_or_expiry_change(self):
        self.seed_old()
        with self.svc._db() as db:before=db.execute('SELECT expires FROM cache').fetchone()[0]
        with patch('app.research.call_openai') as call:
            r=self.svc.cached_outlook(self.token);self.assertTrue(r['reports']['catalysts']['quality_update_available']);call.assert_not_called()
        with self.svc._db() as db:self.assertEqual(db.execute('SELECT expires FROM cache').fetchone()[0],before)
    def test_upgrade_does_not_charge_without_refresh(self):
        self.seed_old()
        with patch('app.research.call_openai') as call:
            r=self.svc.analyze_outlook(self.token,'catalysts',False);self.assertTrue(r['cache_hit']);call.assert_not_called()
    def test_explicit_followup_one_call_with_old_source_leads(self):
        self.seed_old()
        with patch('app.research.call_openai',return_value=quality_raw()) as call:
            r=self.svc.analyze_outlook(self.token,'catalysts',True,True);self.assertEqual(call.call_count,1)
            inp=json.loads(call.call_args.args[1]['input']);self.assertTrue(inp['previous_report_leads']['source_leads'])
            self.assertEqual(r['quality_version'],QUALITY_VERSION)
        with self.svc._db() as db:self.assertEqual(db.execute('SELECT COUNT(*) FROM cache').fetchone()[0],2)
    def test_quality_cache_preferred_and_free(self):
        self.seed_old()
        with patch('app.research.call_openai',return_value=quality_raw()) as call:
            self.svc.analyze_outlook(self.token,'catalysts',True,True)
            r=self.svc.cached_outlook(self.token)['reports']['catalysts'];self.assertFalse(r['quality_update_available']);self.assertEqual(call.call_count,1)
    def test_failure_preserves_old_result_and_attempt_ledger(self):
        self.seed_old()
        with patch('app.research.call_openai',side_effect=ResearchError('TEST','fixture failure')) as call:
            with self.assertRaises(ResearchError):self.svc.analyze_outlook(self.token,'catalysts',True,True)
            self.assertEqual(call.call_count,1)
        self.assertIsNotNone(self.svc.cached_outlook(self.token)['reports']['catalysts'])
        with self.svc._db() as db:self.assertEqual(db.execute('SELECT SUM(n) FROM attempts').fetchone()[0],1)
    def test_status_exposes_budget_not_secret(self):
        s=self.svc.status();self.assertEqual(s['outlook_max_web_calls'],10);self.assertNotIn('sk-fixture',json.dumps(s))


if __name__=='__main__':unittest.main()
