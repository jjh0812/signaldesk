"""Offline synthetic price-context tests. No financial feed or paid AI requests."""
import copy
import json
import tempfile
import time
import unittest
from datetime import date, datetime, timedelta
from pathlib import Path
from unittest.mock import patch
from zoneinfo import ZoneInfo

from fastapi.testclient import TestClient
import app.main as main
from app.engine import Bar
from app.price_context import (build_price_context, price_ai_context, price_request_body,
                               PRICE_MODE, PRICE_PROMPT_VERSION)
from app.research import ResearchService, ResearchError, PROMPT_VERSION
from test_research import api_response, dashboard

AS_OF=date(2026,9,9)
def series(n=350, growth=1.001, as_of=AS_OF):
    days=[];d=as_of-timedelta(days=1)
    while len(days)<n:
        if d.weekday()<5:days.append(d)
        d-=timedelta(days=1)
    return [Bar(d.isoformat(),100*growth**i,1000+i) for i,d in enumerate(reversed(days))]

def metrics(bars=None, benchmark=None, as_of=AS_OF):
    return build_price_context(bars if bars is not None else series(),
                               benchmark if benchmark is not None else series(growth=1.0005),
                               symbol='NVDA',as_of=as_of)

def snapshot():
    d=dashboard();d['price_context']=metrics();return d

class PriceMathTests(unittest.TestCase):
    def test_last_completed_price_and_no_current_day(self):
        b=series()+[Bar(AS_OF.isoformat(),99999,100)]
        self.assertEqual(metrics(b)['last_close'],series()[-1].close)
    def test_year_high_low_and_position_are_calculated(self):
        m=metrics();self.assertEqual(m['year']['high'],m['last_close'])
        self.assertEqual(m['year']['from_high'],0);self.assertEqual(m['year']['range_position'],1)
    def test_low_is_not_a_buy_signal(self):
        m=metrics(series(growth=.999));self.assertEqual(m['year']['range_position'],0)
        self.assertEqual(m['valuation_status'],'NOT_ESTIMATED');self.assertEqual(m['dilution_status'],'NOT_CALCULATED')
    def test_flat_prices_do_not_fabricate_range_probability(self):
        m=metrics(series(growth=1));self.assertIsNone(m['year']['range_position'])
        self.assertEqual(m['horizons'][0]['stock_return'],0)
    def test_returns_use_n_prior_observations_not_n_rows(self):
        for h in metrics()['horizons']:
            self.assertAlmostEqual(h['stock_return'],1.001**h['observations']-1,7)
    def test_spy_comparison_same_endpoints(self):
        for h in metrics()['horizons']:
            self.assertAlmostEqual(h['spy_return'],1.0005**h['observations']-1,7)
            self.assertAlmostEqual(h['spread'],h['stock_return']-h['spy_return'],7)
    def test_missing_spy_end_is_unknown_not_zero(self):
        for h in metrics(benchmark=series()[:-1])['horizons']:
            self.assertIsNone(h['spy_return']);self.assertIsNone(h['spread'])
    def test_missing_spy_start_does_not_pick_nearest(self):
        b=series();d=b[-22].date
        m=metrics(benchmark=[r for r in b if r.date!=d]);self.assertIsNone(m['horizons'][0]['spy_return'])
        self.assertIsNotNone(m['horizons'][1]['spy_return'])
    def test_internal_spy_gap_does_not_change_endpoint_return(self):
        b=series();m=metrics(benchmark=[r for i,r in enumerate(b) if i!=len(b)-10])
        self.assertAlmostEqual(m['horizons'][0]['spy_return'],1.001**21-1,7)
    def test_short_history_is_explicit_and_period_not_fabricated(self):
        m=metrics(series(n=12));self.assertTrue(m['year']['limited_history'])
        for h in m['horizons']:self.assertEqual(h['status'],'INSUFFICIENT_HISTORY');self.assertIsNone(h['stock_return'])
    def test_average_includes_latest_and_has_expected_denominator(self):
        b=series();m=metrics(b)
        self.assertAlmostEqual(m['averages'][0]['mean_close'],sum(x.close for x in b[-20:])/20,7)
        self.assertTrue(m['averages'][0]['includes_latest'])
    def test_average_requires_entire_window(self):
        m=metrics(series(n=21));self.assertIsNotNone(m['averages'][0]['mean_close']);self.assertIsNone(m['averages'][1]['mean_close'])
    def test_stale_price_is_not_current(self):
        self.assertTrue(metrics(series()[:-10])['stale_price'])
    def test_long_missing_period_labels_limited_history(self):
        b=series();b=b[:-90]+b[-40:];self.assertTrue(metrics(b)['year']['limited_history'])
    def test_unsorted_input_is_rejected(self):
        with self.assertRaises(ValueError):metrics(list(reversed(series())))
    def test_empty_input_rejected(self):
        with self.assertRaises(ValueError):metrics([])
    def test_no_nan_or_infinity(self):
        json.dumps(metrics(series(growth=1)),allow_nan=False)
    def test_fetch_timestamp_and_cache_warning_do_not_change_identity(self):
        b=series();a=build_price_context(b,b,symbol='NVDA',as_of=AS_OF,meta={'cache_status':'FETCHED'})
        c=build_price_context(b,b,symbol='NVDA',as_of=AS_OF,meta={'cache_status':'STALE_CACHE','fetched_at':'different'})
        self.assertEqual(a['context_id'],c['context_id']);self.assertNotEqual(a['warnings'],c['warnings'])
        self.assertEqual(price_ai_context(a),price_ai_context(c))
    def test_revised_price_changes_identity(self):
        b=series();a=metrics(b);b[-1]=Bar(b[-1].date,b[-1].close*1.05,b[-1].volume)
        self.assertNotEqual(a['context_id'],metrics(b)['context_id'])
    def test_new_research_date_changes_identity(self):
        self.assertNotEqual(metrics()['context_id'],metrics(as_of=AS_OF+timedelta(days=1))['context_id'])
    def test_etf_can_be_compared_without_inventing_fundamentals(self):
        m=build_price_context(series(),series(),symbol='SPY',as_of=AS_OF)
        for h in m['horizons']:self.assertEqual(h['spread'],0)
        self.assertEqual(m['fundamentals_status'],'NOT_STRUCTURED_OR_INDEPENDENTLY_VERIFIED')

class PriceResearchTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.root=Path(self.tmp.name)
        (self.root/'.env.signaldesk').write_text('OPENAI_API_KEY=sk-offline-only-'+'x'*30)
        self.service=ResearchService(self.root);self.d=snapshot();self.token=self.service.snapshots.add(self.d)
    def tearDown(self):self.tmp.cleanup()
    def test_metrics_are_copied_not_browser_mutable(self):
        self.d['price_context']['last_close']=99999
        self.assertNotEqual(self.service.snapshots.price_context(self.token)['last_close'],99999)
    def test_returned_context_cannot_mutate_server(self):
        c=self.service.snapshots.price_context(self.token);c['year']['high']=99999
        self.assertNotEqual(self.service.snapshots.price_context(self.token)['year']['high'],99999)
    def test_current_context_not_selected_historical_date(self):
        c=self.service.snapshots.price_context(self.token);self.assertEqual(c['price_date'],'2026-09-08')
        self.assertNotIn('event_date',c)
    def test_invalid_expired_and_old_snapshot_rejected(self):
        for t in ['invalid',self.service.snapshots.add(dashboard())]:
            with self.assertRaises(ResearchError):self.service.snapshots.price_context(t)
        self.service.snapshots._items[self.token]=(0,snapshot())
        with self.assertRaises(ResearchError):self.service.snapshots.price_context(self.token)
    def test_cache_lookup_never_calls_provider(self):
        with patch('app.research.call_openai') as call:
            self.assertIsNone(self.service.cached_price(self.token));call.assert_not_called()
    def test_separate_consent_required(self):
        with patch('app.research.call_openai') as call:
            with self.assertRaises(ResearchError) as err:self.service.analyze_price(self.token,False)
            self.assertEqual(err.exception.code,'PAID_CONSENT_REQUIRED');call.assert_not_called()
    def test_missing_key_never_calls_provider(self):
        (self.root/'.env.signaldesk').unlink()
        with patch('app.research.call_openai') as call:
            with self.assertRaises(ResearchError):self.service.analyze_price(self.token,True)
            call.assert_not_called()
    def test_stale_price_blocks_paid_request(self):
        d=snapshot();d['price_context']=metrics(series()[:-10]);token=self.service.snapshots.add(d)
        with patch('app.research.call_openai') as call:
            with self.assertRaises(ResearchError) as err:self.service.analyze_price(token,True)
            self.assertEqual(err.exception.code,'PRICE_DATA_TOO_OLD');call.assert_not_called()
    def test_new_analysis_one_call_and_cache_read_free(self):
        with patch('app.research.call_openai',return_value=api_response()) as call:
            r=self.service.analyze_price(self.token,True);self.assertEqual(call.call_count,1)
            self.assertEqual(r['analysis_mode'],PRICE_MODE);self.assertNotIn('event_date',r)
            self.assertEqual(r['context_id'],self.d['price_context']['context_id'])
            self.assertTrue(self.service.analyze_price(self.token,False)['cache_hit']);self.assertEqual(call.call_count,1)
    def test_event_and_current_analysis_have_distinct_caches(self):
        with patch('app.research.call_openai',return_value=api_response()):self.service.analyze(self.token,'2026-08-27',True)
        self.assertIsNone(self.service.cached_price(self.token))
        with patch('app.research.call_openai',return_value=api_response()):self.service.analyze_price(self.token,True)
        self.assertEqual(self.service.cached(self.token,'2026-08-27')['analysis_mode'],'RETROSPECTIVE_WEB_RESEARCH')
    def test_shared_attempt_ledger_and_status(self):
        with patch('app.research.call_openai',return_value=api_response()):
            self.service.analyze(self.token,'2026-08-27',True);self.service.analyze_price(self.token,True)
        with self.service._db() as db:self.assertEqual(db.execute('select sum(n) from attempts').fetchone()[0],2)
        self.assertFalse(self.service.status()['busy']);self.assertTrue(self.service.status()['price_context_available'])
    def test_daily_cap_is_shared_not_new_allowance(self):
        today=datetime.now(ZoneInfo('Asia/Seoul')).date().isoformat()
        with self.service._db() as db:db.execute('insert into attempts values (?,20)',(today,))
        with patch('app.research.call_openai') as call:
            with self.assertRaises(ResearchError) as err:self.service.analyze_price(self.token,True)
            self.assertEqual(err.exception.code,'LOCAL_DAILY_LIMIT');call.assert_not_called()
    def test_event_running_prevents_second_paid_request(self):
        self.service._active.acquire()
        try:
            self.assertTrue(self.service.status()['busy'])
            with patch('app.research.call_openai') as call:
                with self.assertRaises(ResearchError) as err:self.service.analyze_price(self.token,True)
                self.assertEqual(err.exception.code,'AI_BUSY');call.assert_not_called()
        finally:self.service._active.release()
    def test_failed_refresh_preserves_cached_result_no_auto_retry(self):
        with patch('app.research.call_openai',return_value=api_response()):r=self.service.analyze_price(self.token,True)
        with patch('app.research.call_openai',side_effect=ResearchError('AI_TIMEOUT','stub')) as call:
            with self.assertRaises(ResearchError):self.service.analyze_price(self.token,True,True)
            self.assertEqual(call.call_count,1)
        self.assertEqual(self.service.cached_price(self.token)['generated_at'],r['generated_at'])
        self.assertFalse(self.service.status()['busy'])
    def test_refresh_requires_fresh_explicit_consent(self):
        with patch('app.research.call_openai',return_value=api_response()):self.service.analyze_price(self.token,True)
        with patch('app.research.call_openai') as call:
            with self.assertRaises(ResearchError):self.service.analyze_price(self.token,False,True)
            call.assert_not_called()
    def test_no_sources_returns_abstention(self):
        raw=api_response();raw['output']=raw['output'][1:]
        with patch('app.research.call_openai',return_value=raw):r=self.service.analyze_price(self.token,True)
        self.assertEqual(r['status'],'UNCONFIRMED');self.assertIn('해석 보류',r['segments'][0]['text'])
    def test_new_snapshot_same_metrics_reuses_result(self):
        with patch('app.research.call_openai',return_value=api_response()) as call:
            self.service.analyze_price(self.token,True);new=self.service.snapshots.add(snapshot())
            self.assertTrue(self.service.analyze_price(new,False)['cache_hit']);self.assertEqual(call.call_count,1)
    def test_price_prompt_covers_financial_and_time_limitations(self):
        b=price_request_body(self.service.snapshots.price_context(self.token),'gpt-5-mini')
        for t in ['Offering size/market cap is NOT dilution','splits are NOT dilution','No target price',
                  'AFTER','GAAP','ETF','주식 수와 자금 조달','native clickable','생태계 확장']:
            self.assertIn(t,b['instructions'])
        self.assertFalse(b['store']);self.assertEqual(b['max_tool_calls'],4);self.assertEqual(b['tool_choice'],'required')
        self.assertNotIn('sk-offline',json.dumps(b))
    def test_step03_report_still_read_without_rebilling(self):
        c=self.service.snapshots.context(self.token,'2026-08-27')
        key=self.service.cache_key(c,'gpt-5-mini','event-research-v0.3.0')
        with self.service._db() as db:db.execute('insert into cache values (?,?,?)',(key,time.time()+3600,json.dumps({'prompt_version':'event-research-v0.3.0'})))
        with patch('app.research.call_openai') as call:
            self.assertEqual(self.service.cached(self.token,'2026-08-27')['prompt_version'],'event-research-v0.3.0');call.assert_not_called()
    def test_api_rejects_missing_csrf_and_cross_origin(self):
        with patch.object(main,'research',self.service),patch('app.research.call_openai') as call:
            client=TestClient(main.app);payload={'snapshot_id':self.token,'allow_paid':True}
            self.assertEqual(client.post('/api/v1/ai/price/analyze',json=payload).status_code,403)
            for headers in [{'Origin':'https://evil.example'},{'Sec-Fetch-Site':'cross-site'}]:
                headers['X-SignalDesk-AI']=self.service.csrf_token
                self.assertEqual(client.post('/api/v1/ai/price/analyze',json=payload,headers=headers).status_code,403)
            call.assert_not_called()
    def test_api_rejects_prompt_price_and_string_booleans(self):
        with patch.object(main,'research',self.service),patch('app.research.call_openai') as call:
            client=TestClient(main.app)
            for extra in [{'prompt':'buy now'},{'price':.1},{'event_date':'2026-03-31'},{'allow_paid':'true'},{'refresh_report':'true'}]:
                payload={'snapshot_id':self.token,'allow_paid':True,**extra}
                self.assertEqual(client.post('/api/v1/ai/price/analyze',json=payload,headers={'X-SignalDesk-AI':self.service.csrf_token}).status_code,422)
            call.assert_not_called()
    def test_api_cache_read_is_free(self):
        with patch.object(main,'research',self.service),patch('app.research.call_openai') as call:
            r=TestClient(main.app).get('/api/v1/ai/price/cache',params={'snapshot_id':self.token})
            self.assertEqual(r.status_code,200);self.assertIsNone(r.json()['result']);call.assert_not_called()
    def test_market_scan_adds_metrics_without_ai_call(self):
        now=datetime.now(ZoneInfo('America/New_York')).date();b=series(as_of=now)
        meta={'warnings':[],'cache_status':'CACHE','fetched_at':'2026-09-09T00:00:00Z','currency':'USD'}
        with patch.object(main,'research',self.service),patch.object(main.provider,'load',return_value=(b,meta)),patch('app.research.call_openai') as call:
            c=TestClient(main.app);a=c.get('/api/v1/market/NVDA?period=1mo');d=c.get('/api/v1/market/NVDA?period=3y')
            self.assertEqual(a.status_code,200);self.assertEqual(d.status_code,200)
            self.assertEqual(a.json()['price_context']['context_id'],d.json()['price_context']['context_id'])
            self.assertIn('research_snapshot_id',a.json());call.assert_not_called()

if __name__=='__main__':unittest.main()
