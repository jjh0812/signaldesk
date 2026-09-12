"""Synthetic, offline tests only. Test fixtures are NEVER served by the app."""
from __future__ import annotations

import json
import math
import tempfile
import unittest
from dataclasses import asdict, replace
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch
from zoneinfo import ZoneInfo

import pandas as pd
from fastapi.testclient import TestClient

from app.engine import Bar, build_dashboard, observations
from app.provider import ProviderError, YahooProvider, bars_from_frame, normalize_symbol
import app.main as main


def fixture(returns=None, count=110, end=None):
    end = end or datetime.now(ZoneInfo("America/New_York")).date()
    n = len(returns) + 1 if returns is not None else count
    dates=[]; current=end-timedelta(days=1)
    while len(dates)<n:
        if current.weekday()<5:dates.append(current.isoformat())
        current-=timedelta(days=1)
    dates.reverse()
    returns = returns if returns is not None else [(.002 if i%2 else -.0015) for i in range(n-1)]
    price=100.; bars=[Bar(dates[0],price,2_000_000)]
    for d,r in zip(dates[1:],returns):
        price*=1+r;bars.append(Bar(d,price,2_000_000))
    return bars


def sample_meta():
    return {'currency':'USD','provider':'TEST_FIXTURE_ONLY','cache_status':'TEST','warnings':[],
            'fetched_at':datetime.now(timezone.utc).isoformat()}


class EngineTests(unittest.TestCase):
    def test_spike_detected(self):
        bars=fixture();bars[35]=replace(bars[35],close=bars[34].close*1.2)
        row=observations(bars)[35]
        self.assertTrue(row['is_anomaly']);self.assertEqual(row['direction'],'UP')

    def test_crash_detected(self):
        bars=fixture();bars[35]=replace(bars[35],close=bars[34].close*.8)
        row=observations(bars)[35]
        self.assertTrue(row['is_anomaly']);self.assertEqual(row['direction'],'DOWN')

    def test_exact_negative_ten_percent(self):
        bars=fixture([0.0]*30+[-.10])
        row=observations(bars)[-1]
        self.assertTrue(row['is_anomaly']);self.assertIn('LARGE_DAILY_MOVE',row['reasons'])

    def test_baseline_excludes_current_return(self):
        bars=fixture([.01,-.01]*20+[.3]);row=observations(bars)[-1]
        self.assertAlmostEqual(row['mean_20d'],0.0)
        self.assertEqual(row['baseline_count'],20)
        self.assertGreater(row['zscore'],20)

    def test_volume_average_excludes_current_day(self):
        bars=fixture();bars[40]=replace(bars[40],volume=12_000_000)
        self.assertAlmostEqual(observations(bars)[40]['volume_ratio'],6.0)

    def test_future_mutation_does_not_change_prior_observation(self):
        bars=fixture();a=observations(bars)[40]
        altered=[replace(b,close=b.close*10,volume=1) if i>40 else b for i,b in enumerate(bars)]
        self.assertEqual(a,observations(altered)[40])

    def test_insufficient_baseline_does_not_auto_flag(self):
        bars=fixture([.001]*6+[.5]);row=observations(bars)[-1]
        self.assertFalse(row['is_anomaly']);self.assertIn('INSUFFICIENT_BASELINE',row['notes'])

    def test_split_day_is_review_only(self):
        bars=fixture();bars[40]=replace(bars[40],close=bars[39].close*.4,split=2)
        row=observations(bars)[40]
        self.assertFalse(row['is_anomaly']);self.assertIn('SPLIT_DAY_REVIEW',row['notes'])
        self.assertIsNone(row['volume_ratio'])

    def test_split_volume_window_is_suppressed(self):
        bars=fixture();bars[40]=replace(bars[40],split=4)
        rows=observations(bars)
        self.assertIsNone(rows[60]['volume_ratio']);self.assertIsNotNone(rows[61]['volume_ratio'])

    def test_zero_volatility_is_not_infinite(self):
        row=observations(fixture([0.0]*30+[.12]))[-1]
        self.assertIsNone(row['zscore']);self.assertTrue(row['is_anomaly'])

    def test_flat_non_event(self):
        rows=observations(fixture([0.0]*45))
        self.assertFalse(any(row['is_anomaly'] for row in rows))

    def test_market_return_spread_is_arithmetic_not_causal(self):
        a=fixture([.001]*30+[.12]);b=fixture([.001]*30+[.08]);row=observations(a,b)[-1]
        self.assertAlmostEqual(row['benchmark_spread'],.04)
        self.assertNotIn('cause',row)

    def test_missing_benchmark_is_unknown_not_zero(self):
        row=observations(fixture())[-1]
        self.assertIsNone(row['benchmark_return']);self.assertIsNone(row['benchmark_spread'])

    def test_benchmark_previous_date_must_match(self):
        a=fixture();b=[x for i,x in enumerate(a) if i!=40]
        self.assertIsNone(observations(a,b)[41]['benchmark_spread'])

    def test_zero_volume_mean_is_unknown(self):
        bars=[replace(b,volume=0) for b in fixture()]
        self.assertIsNone(observations(bars)[-1]['volume_ratio'])

    def test_invalid_price_rejected(self):
        for val in [0,-1,float('nan'),float('inf')]:
            with self.subTest(val=val),self.assertRaises(ValueError):Bar('2026-01-02',val,1)

    def test_duplicate_dates_rejected(self):
        bars=fixture()
        with self.assertRaises(ValueError):observations([bars[0],bars[0]])

    def test_unsorted_dates_rejected(self):
        with self.assertRaises(ValueError):observations(list(reversed(fixture())))

    def test_short_display_has_warmup(self):
        bars=fixture(count=150);now=datetime.now(ZoneInfo('America/New_York')).date()
        d=build_dashboard(bars,[],symbol='TEST',period='1mo',as_of=now,meta=sample_meta())
        self.assertEqual(d['bars'][0]['baseline_count'],20)
        self.assertLessEqual(len(d['bars']),24)

    def test_current_session_is_excluded(self):
        now=datetime.now(ZoneInfo('America/New_York')).date();bars=fixture()
        bars.append(Bar(now.isoformat(),bars[-1].close*2,999999999))
        d=build_dashboard(bars,[],symbol='TEST',period='1y',as_of=now,meta=sample_meta())
        self.assertLess(d['meta']['data_end'],now.isoformat())

    def test_json_has_no_nan_or_infinity(self):
        now=datetime.now(ZoneInfo('America/New_York')).date()
        d=build_dashboard(fixture([0.0]*60),[],symbol='TEST',period='1y',as_of=now,meta=sample_meta())
        json.dumps(d,allow_nan=False)

    def test_ai_is_explicitly_disabled(self):
        now=datetime.now(ZoneInfo('America/New_York')).date()
        d=build_dashboard(fixture(),[],symbol='TEST',period='1y',as_of=now,meta=sample_meta())
        self.assertFalse(d['meta']['ai_enabled']);self.assertEqual(d['meta']['cause_status'],'NOT_IMPLEMENTED')


class ProviderTests(unittest.TestCase):
    def test_symbols_are_normalized(self):
        self.assertEqual(normalize_symbol(' nvda '),'NVDA');self.assertEqual(normalize_symbol('BRK-B'),'BRK-B')

    def test_invalid_symbols_block_paths_and_non_us_suffix(self):
        for value in ['../a','AAPL?x=1','005930.KS','https://a','AAPL;rm','']:
            with self.subTest(value=value),self.assertRaises(ProviderError):normalize_symbol(value)

    def test_provider_date_is_not_shifted_to_utc(self):
        frame=pd.DataFrame({'Close':[10.,11.],'Volume':[100,200]},index=pd.date_range('2026-01-05',periods=2,tz='America/New_York'))
        bars,_=bars_from_frame(frame);self.assertEqual(bars[0].date,'2026-01-05')

    def test_bad_session_does_not_silently_bridge(self):
        frame=pd.DataFrame({'Close':[10.,float('nan'),11.],'Volume':[100,200,300]},index=pd.date_range('2026-01-05',periods=3))
        with self.assertRaises(ProviderError) as ctx:bars_from_frame(frame)
        self.assertEqual(ctx.exception.code,'INCOMPLETE_PROVIDER_DATA')

    def test_no_fake_fallback_on_network_error(self):
        with tempfile.TemporaryDirectory() as td:
            p=YahooProvider(Path(td))
            with patch.object(p,'_fetch',side_effect=ProviderError('OFFLINE','No network')):
                with self.assertRaises(ProviderError):p.load('AAPL',date(2026,9,9))

    def test_fresh_cache_is_labeled_and_reused(self):
        now=datetime.now(ZoneInfo('America/New_York')).date()
        payload={'version':1,'symbol':'AAPL','as_of':now.isoformat(),'fetched_at':datetime.now(timezone.utc).isoformat(),'currency':'USD','exchange':'TEST','bars':[asdict(b) for b in fixture()]}
        with tempfile.TemporaryDirectory() as td:
            p=YahooProvider(Path(td))
            with patch.object(p,'_fetch',return_value=payload) as f:
                _,m1=p.load('AAPL',now);_,m2=p.load('AAPL',now)
            self.assertEqual(f.call_count,1);self.assertEqual(m1['cache_status'],'FETCHED');self.assertEqual(m2['cache_status'],'CACHE')

    def test_stale_cache_is_never_labeled_fresh(self):
        now=datetime.now(ZoneInfo('America/New_York')).date()
        payload={'version':1,'symbol':'AAPL','as_of':now.isoformat(),'fetched_at':(datetime.now(timezone.utc)-timedelta(days=2)).isoformat(),'currency':'USD','bars':[asdict(b) for b in fixture()]}
        with tempfile.TemporaryDirectory() as td:
            Path(td,'AAPL.json').write_text(json.dumps(payload))
            p=YahooProvider(Path(td))
            with patch.object(p,'_fetch',side_effect=ProviderError('OFFLINE','No network')):
                _,m=p.load('AAPL',now)
            self.assertEqual(m['cache_status'],'STALE_CACHE');self.assertTrue(m['warnings'])

    def test_adapter_explicitly_requests_adjustment_and_no_current_day(self):
        now=date(2026,9,9)
        frame=pd.DataFrame({'Close':[10.,11.],'Volume':[100,200]},index=pd.date_range('2026-09-07',periods=2,tz='America/New_York'))
        from unittest.mock import Mock
        ticker=Mock();ticker.history.return_value=frame;ticker.history_metadata={'currency':'USD','exchangeTimezoneName':'America/New_York','instrumentType':'EQUITY'}
        with tempfile.TemporaryDirectory() as td,patch.dict('sys.modules',{'yfinance':SimpleNamespace(Ticker=lambda symbol:ticker)}):
            p=YahooProvider(Path(td));p._fetch('AAPL',now)
        kwargs=ticker.history.call_args.kwargs
        self.assertTrue(kwargs['auto_adjust']);self.assertEqual(kwargs['end'],'2026-09-09');self.assertFalse(kwargs['repair'])


class APITests(unittest.TestCase):
    def setUp(self):self.client=TestClient(main.app)
    def test_health(self):
        r=self.client.get('/api/health');self.assertEqual(r.status_code,200);self.assertEqual(r.json()['app'],'signaldesk')
    def test_validation(self):
        self.assertEqual(self.client.get('/api/v1/market/AAPL?period=5y').status_code,422)
        self.assertEqual(self.client.get('/api/v1/market/005930.KS').status_code,422)
    def test_network_error_not_http_200(self):
        with patch.object(main.provider,'load',side_effect=ProviderError('OFFLINE','Network unavailable')):
            r=self.client.get('/api/v1/market/AAPL')
        self.assertEqual(r.status_code,502);self.assertEqual(r.json()['error']['code'],'OFFLINE')
    def test_response_contract(self):
        with patch.object(main.provider,'load',return_value=(fixture(),sample_meta())):
            r=self.client.get('/api/v1/market/NVDA')
        self.assertEqual(r.status_code,200);d=r.json()
        self.assertIn('bars',d);self.assertIn('anomalies',d);self.assertFalse(d['meta']['ai_enabled'])
        self.assertEqual(r.headers['cache-control'],'no-store')
    def test_benchmark_failure_preserves_stock_data(self):
        def load(symbol,now):
            if symbol=='SPY':raise ProviderError('OFFLINE','No benchmark')
            return fixture(),sample_meta()
        with patch.object(main.provider,'load',side_effect=load):r=self.client.get('/api/v1/market/AAPL')
        self.assertEqual(r.status_code,200);self.assertTrue(r.json()['meta']['warnings'])
        self.assertIsNone(r.json()['bars'][-1]['benchmark_spread'])
    def test_unknown_api_route_is_json_404(self):
        r=self.client.get('/api/unknown');self.assertEqual(r.status_code,404);self.assertIn('json',r.headers['content-type'])
    def test_untrusted_host_rejected(self):
        r=self.client.get('/api/health',headers={'host':'untrusted.example'})
        self.assertEqual(r.status_code,400)

if __name__=='__main__':unittest.main(verbosity=2)
