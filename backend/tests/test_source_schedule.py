"""No network/API: replay uploaded extracted text + synthetic edge cases.
The source fixture is a regression input, NOT live data shipped into the app.
"""
import copy,json,tempfile,unittest
from datetime import date,datetime,timezone,timedelta
from pathlib import Path
from unittest.mock import patch
from fastapi.testclient import TestClient
import app.main as main
from app.source_schedule import build_source_schedule,calendar_anchor,candidate_audit
from app.evidence_store import save_bundle
from app.outlook_quality import quality_request_body
from app.research import ResearchService

FIXTURE=Path(__file__).with_name('fixtures')/'source_read_user_061.json'
def fixture():return json.loads(FIXTURE.read_text(encoding='utf-8'))
def synthetic(text='Our next earnings call is scheduled for October 14.',header='07-Sep-2030 EXAMPLE Corp. (EXM) Q2 2031 Earnings Call'):
    b=fixture();b['symbol']='EXM';b['generated_at']=datetime.now(timezone.utc).isoformat();b['documents']=b['documents'][:1]
    d=b['documents'][0];d.update(header_text=header,title='EXAMPLE transcript',published_date_claim='2030-09-07',requested_url='https://www.example.com/report.pdf',url='https://www.example.com/report.pdf')
    d['passages']=[{'page':9,'passage_id':'d1.p9.s1','text':text}]
    return b
class SourceScheduleTests(unittest.TestCase):
    def test_exact_uploaded_file_produces_three_unique_candidates(self):
        r=build_source_schedule(fixture(),'NVDA',date(2026,9,10))
        self.assertEqual(len(r['candidates']),3)
        self.assertEqual({x['event_date_candidate'] for x in r['candidates']},{'2026-09-10','2026-10-21','2026-11-17'})
        self.assertEqual(r['candidates'][0]['category'],'EARNINGS')
    def test_actual_fixture_never_calls_fy2027_the_calendar_year(self):
        r=build_source_schedule(fixture(),'NVDA',date(2026,9,10))
        self.assertTrue(all(x['year_basis']=='CONTEXT_YEAR_CANDIDATE' for x in r['candidates']))
        self.assertTrue(all('2027-' not in x['event_date_candidate'] for x in r['candidates']))
    def test_actual_source_retains_page_and_sentence_not_just_date(self):
        c=build_source_schedule(fixture(),'NVDA',date(2026,9,10))['candidates'][0]
        self.assertEqual(c['page'],15);self.assertIn('November 17',c['sentence']);self.assertIn('fiscal 2027',c['sentence'])
        self.assertTrue(c['source_url'].startswith('https://investor.nvidia.com/'))
        self.assertFalse(c['latest_change_checked']);self.assertFalse(c['issuer_authenticity_verified'])
    def test_http_403_and_old_reporting_dates_not_promoted(self):
        r=build_source_schedule(fixture(),'NVDA',date(2026,9,10))
        self.assertEqual(r['document_checks'][1]['candidates_found'],0)
        self.assertEqual(r['document_checks'][2]['candidates_found'],0)
    def test_duplicate_passages_do_not_duplicate_earnings(self):
        b=fixture();b['documents'][0]['passages']*=3
        r=build_source_schedule(b,'NVDA',date(2026,9,10));self.assertEqual(len(r['candidates']),3)
    def test_two_conferences_same_day_keep_distinct_titles(self):
        b=synthetic("He will be giving a keynote at Alpha Conference on October 14. He will be giving a keynote at Beta Conference on October 14.")
        self.assertEqual(len(build_source_schedule(b,'EXM',date(2030,9,10))['candidates']),2)
    def test_symbols_and_dates_are_not_hardcoded(self):
        r=build_source_schedule(synthetic(),'EXM',date(2030,9,10));self.assertEqual(r['candidates'][0]['event_date_candidate'],'2030-10-14')
    def test_source_input_is_not_mutated(self):
        b=fixture();before=copy.deepcopy(b);build_source_schedule(b,'NVDA',date(2026,9,10));self.assertEqual(b,before)
    def test_mismatched_symbol_discarded(self):self.assertFalse(build_source_schedule(fixture(),'MSFT',date(2026,9,10))['candidates'])
    def test_header_must_match_ticker(self):
        b=synthetic();b['documents'][0]['header_text']='07-Sep-2030 Different (NOPE) Earnings Call'
        self.assertFalse(build_source_schedule(b,'EXM',date(2030,9,10))['candidates'])
    def test_no_header_calendar_date_keeps_month_day_undated(self):
        b=synthetic(header='EXAMPLE (EXM) Q2 2031 Earnings Call')
        c=build_source_schedule(b,'EXM',date(2030,9,10))['candidates'][0]
        self.assertIsNone(c['event_date_candidate']);self.assertEqual(c['month_day_text'],'October 14')
    def test_multiple_header_calendar_dates_are_ambiguous(self):
        self.assertIsNone(calendar_anchor('07-Sep-2030 updated 2030-09-10')[0])
    def test_header_formats(self):
        for header in ['07-Sep -2030','2030-09-07','September 7, 2030']:
            with self.subTest(header=header):self.assertEqual(calendar_anchor(header)[0],date(2030,9,7))
    def test_explicit_sentence_year_separate_from_inference(self):
        c=build_source_schedule(synthetic('Our next earnings call is scheduled for October 14, 2030.'),'EXM',date(2030,9,10))['candidates'][0]
        self.assertEqual(c['year_basis'],'EXPLICIT_IN_SENTENCE')
    def test_new_year_is_anchored_to_document_not_query_today(self):
        b=synthetic('Our next earnings call is scheduled for January 12.',header='20-Dec-2030 EXM Earnings Call');b['documents'][0]['published_date_claim']='2030-12-20'
        c=build_source_schedule(b,'EXM',date(2031,1,3))['candidates'][0]
        self.assertEqual(c['event_date_candidate'],'2031-01-12')
    def test_past_occurrence_not_rolled_to_next_year(self):
        c=build_source_schedule(synthetic(),'EXM',date(2030,11,1))['candidates'][0]
        self.assertEqual(c['event_date_candidate'],'2030-10-14');self.assertEqual(c['horizon_state'],'PAST')
    def test_cancelled_conditional_tentative_sentences_skipped(self):
        for text in ['Our earnings call is not scheduled for October 14.','Our earnings call was cancelled, previously scheduled for October 14.', 'If approved, our earnings call is scheduled for October 14.', 'Our earnings call is tentatively scheduled for October 14.']:
            with self.subTest(text=text):self.assertFalse(build_source_schedule(synthetic(text),'EXM',date(2030,9,10))['candidates'])
    def test_multiple_dates_in_single_sentence_not_guessed(self):
        self.assertFalse(build_source_schedule(synthetic('Our earnings call is scheduled for October 14 or October 15.'),'EXM',date(2030,9,10))['candidates'])
    def test_past_text_near_future_word_does_not_become_schedule(self):
        self.assertFalse(build_source_schedule(synthetic('Our next products will launch soon. From March 31 through June 30 institutions bought shares.'),'EXM',date(2030,9,10))['candidates'])
    def test_changed_or_private_url_rejected(self):
        b=synthetic();b['documents'][0]['requested_url']='https://127.0.0.1/key'
        self.assertFalse(build_source_schedule(b,'EXM',date(2030,9,10))['candidates'])
    def test_expired_source_not_discarded_or_refreshed(self):
        b=fixture();b['expired']=True;r=build_source_schedule(b,'NVDA',date(2026,9,10))
        self.assertEqual(len(r['candidates']),3);self.assertTrue(r['source_is_expired']);self.assertEqual(r['source_collected_at'],b['generated_at'])
    def test_old_report_omission_is_visible_without_rewriting_it(self):
        report={'items':[{'category':'CORPORATE_ACTION','event_date':'2026-10-01','title':'Dividend'}]};before=copy.deepcopy(report)
        a=candidate_audit(build_source_schedule(fixture(),'NVDA',date(2026,9,10)),report)
        self.assertEqual(a['findings'][0]['status'],'REPORT_NOT_LINKED');self.assertEqual(report,before)
    def test_different_earnings_date_flagged_not_silently_replaced(self):
        a=candidate_audit(build_source_schedule(fixture(),'NVDA',date(2026,9,10)),{'items':[{'category':'EARNINGS','event_date':'2026-11-20'}]})
        self.assertEqual(a['findings'][0]['status'],'DIFFERENT_DATE_REVIEW')
    def test_fresh_source_candidates_in_single_future_request(self):
        b=fixture();b['generated_at']=datetime.now(timezone.utc).isoformat()
        ctx={'symbol':'NVDA','research_date':'2026-09-10','price_date':'2026-09-08','through_date':'2027-03-09'}
        body=quality_request_body(ctx,'catalysts','gpt-5-mini',evidence=b);inp=json.loads(body['input'])
        self.assertEqual(len(inp['server_schedule_candidates']),3);self.assertTrue(inp['server_extracted_text'])
        self.assertIn('Local URLs supplied',body['instructions']);self.assertNotIn('NVDA',body['instructions'])
    def test_expired_source_not_silently_sent_as_fresh_ai_input(self):
        b=fixture();b['generated_at']=(datetime.now(timezone.utc)-timedelta(days=2)).isoformat()
        body=quality_request_body({'symbol':'NVDA','research_date':'2026-09-10','price_date':'2026-09-08','through_date':'2027-03-09'},'catalysts','gpt-5-mini',evidence=b)
        self.assertIsNone(json.loads(body['input'])['server_extracted_text']);self.assertFalse(json.loads(body['input'])['server_schedule_candidates'])

class ScheduleEndpointTests(unittest.TestCase):
    def test_real_source_fixture_free_endpoint_no_keys_network_or_db_writes(self):
        with tempfile.TemporaryDirectory() as t:
            root=Path(t);save_bundle(root,'NVDA',fixture());db=root/'.cache/research/research.sqlite3';db.parent.mkdir(parents=True);db.write_bytes(b'UNCHANGED RESEARCH AND QUOTA')
            (root/'.env.signaldesk').write_text('SENTINEL_CREDENTIAL_NOT_FOR_READING')
            before={str(f.relative_to(root)):f.read_bytes() for f in root.rglob('*') if f.is_file()}
            with patch.object(main,'ROOT',root), patch('app.research.read_settings',side_effect=AssertionError('key read')),patch('app.research.call_openai',side_effect=AssertionError('paid request')),patch('app.document_reader.fetch_document',side_effect=AssertionError('network fetch')):
                res=TestClient(main.app).get('/api/v1/evidence/schedule?symbol=NVDA')
            self.assertEqual(res.status_code,200);self.assertEqual(len(res.json()['candidates']),3)
            for k in ['api_calls','external_requests','database_writes']:self.assertEqual(res.json()[k],0)
            self.assertNotIn('SENTINEL_CREDENTIAL',res.text)
            self.assertEqual(before,{str(f.relative_to(root)):f.read_bytes() for f in root.rglob('*') if f.is_file()})
    def test_missing_evidence_does_not_trigger_search(self):
        with tempfile.TemporaryDirectory() as t,patch.object(main,'ROOT',Path(t)),patch('app.research.call_openai',side_effect=AssertionError('paid request')):
            r=TestClient(main.app).get('/api/v1/evidence/schedule?symbol=NVDA');self.assertEqual(r.status_code,200);self.assertEqual(r.json()['status'],'NO_LOCAL_TEXT')
    def test_private_symbol_rejected(self):
        r=TestClient(main.app).get('/api/v1/evidence/schedule?symbol=..%2Fkey');self.assertEqual(r.status_code,422)

if __name__=='__main__':unittest.main(verbosity=2)
