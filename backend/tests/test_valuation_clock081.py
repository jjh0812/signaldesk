"""Clock-boundary regression: genuine future prices still fail; no external I/O.

All dates are synthetic. Fixed aware clocks emulate Korean early morning,
New York midnight, DST changes, and a year boundary without changing OS time.
"""
from copy import deepcopy
from datetime import datetime, timedelta, timezone
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
from zoneinfo import ZoneInfo

from fastapi import FastAPI
from fastapi.responses import JSONResponse
from fastapi.testclient import TestClient
from app.research import ResearchService, ResearchError
from app.fundamentals import FundamentalsStore
from app.valuation_api import install_routes
from app.valuation import FinancialInput, CalculateRequest, defaults
from valuation_clock_fixture import FIXED_UTC, MARKET_DAY, clock_at


class ValuationClockTests(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.root = Path(tmp.name)
        self.research = ResearchService(self.root)
        self.app = FastAPI()

        @self.app.exception_handler(ResearchError)
        async def error(_, exc):
            return JSONResponse(status_code=exc.status, content={
                'error': {'code': exc.code, 'message': exc.message}})

        install_routes(self.app, self.root, self.research)
        self.client = TestClient(self.app)
        self.addCleanup(self.client.close)
        self.headers = {'X-SignalDesk-AI': self.research.csrf_token}
        for target in ('app.decision.call_openai', 'app.filing_ai.call_openai',
                       'app.fundamentals.yahoo_completed_quote', 'app.filing_store.fetch_sec',
                       'app.fundamentals.FundamentalsStore.get_json'):
            p = patch(target, side_effect=AssertionError('No external request in clock tests.'))
            p.start(); self.addCleanup(p.stop)
        p = patch.object(self.research, '_reserve_attempt', side_effect=AssertionError('No paid attempt.'))
        p.start(); self.addCleanup(p.stop)

    def payload(self, day=MARKET_DAY, **updates):
        f = FinancialInput(symbol='EXM', price=100, price_date=day,
            period_end=day-timedelta(days=60), revenue=10000,
            operating_income=2000, cash=1000, debt=1000, shares=300,
            net_income=1500, sic='3674', share_basis_checked=True,
            claims_checked=True)
        f = f.model_copy(update=updates)
        return CalculateRequest(financials=f, assumptions=defaults(.2)|{'reviewed':True}).model_dump(mode='json')

    def post_at(self, instant, path='/api/v1/decision/calculate', payload=None):
        clock = clock_at(instant)
        with patch('app.valuation_api.datetime', clock), patch('app.filing_api.datetime', clock):
            return self.client.post(path, json=self.payload() if payload is None else payload, headers=self.headers)

    def test_old_local_fixture_mismatch_reproduces_422_not_schema_error(self):
        korean_day = FIXED_UTC.astimezone(ZoneInfo('Asia/Seoul')).date()
        self.assertEqual(korean_day, MARKET_DAY+timedelta(days=1))
        r = self.post_at(FIXED_UTC, payload=self.payload(korean_day))
        self.assertEqual(r.status_code, 422, r.text)
        self.assertEqual(r.json()['error']['code'], 'VALUATION_INPUT')
        self.assertIn('미래 가격', r.json()['error']['message'])

    def test_market_date_is_accepted_during_korean_next_day(self):
        r = self.post_at(FIXED_UTC)
        self.assertEqual(r.status_code, 200, r.text)
        self.assertEqual(r.json()['ai_calls'], 0)
        self.assertEqual(r.json()['financials']['price_date'], MARKET_DAY.isoformat())

    def test_false_sec_claim_still_downgraded_to_user(self):
        r = self.post_at(FIXED_UTC, payload=self.payload(input_kind='SEC'))
        self.assertEqual(r.status_code, 200, r.text)
        self.assertEqual(r.json()['financials']['input_kind'], 'USER')

    def test_save_deduplicates_on_fixed_market_day(self):
        for _ in range(2):
            r = self.post_at(FIXED_UTC, '/api/v1/decision/save', {'calculation':self.payload()})
            self.assertEqual(r.status_code, 200, r.text)
        self.assertEqual(len(r.json()['history']), 1)
        self.assertEqual(r.json()['api_calls'], 0)

    def test_future_save_rejected_without_history_write(self):
        r = self.post_at(FIXED_UTC, '/api/v1/decision/save',
            {'calculation':self.payload(MARKET_DAY+timedelta(days=1))})
        self.assertEqual(r.status_code, 422, r.text)
        self.assertIsNone(FundamentalsStore(self.root).read('history-EXM.json'))

    def test_eight_day_old_price_still_withholds_verdict(self):
        r = self.post_at(FIXED_UTC, payload=self.payload(MARKET_DAY-timedelta(days=8)))
        self.assertEqual(r.status_code, 200, r.text)
        self.assertEqual(r.json()['verdict'], 'STALE_DATA')
        self.assertFalse(r.json()['decision_ready'])

    def test_payload_dates_and_values_are_not_shifted(self):
        body = self.payload(); before = deepcopy(body)
        r = self.post_at(FIXED_UTC, payload=body)
        self.assertEqual(r.status_code, 200, r.text)
        self.assertEqual(body, before)
        for key in ('price_date','period_end','price','revenue','shares'):
            self.assertEqual(r.json()['financials'][key], body['financials'][key])

    def test_new_york_midnight_boundary_in_summer(self):
        tomorrow = MARKET_DAY+timedelta(days=1)
        for moment, code in [('2026-09-11T03:59:59+00:00',422), ('2026-09-11T04:00:00+00:00',200)]:
            with self.subTest(moment=moment):
                r = self.post_at(datetime.fromisoformat(moment), payload=self.payload(tomorrow))
                self.assertEqual(r.status_code, code, r.text)

    def test_new_york_midnight_boundary_in_winter(self):
        for moment, code in [('2026-01-10T04:59:59+00:00',422), ('2026-01-10T05:00:00+00:00',200)]:
            with self.subTest(moment=moment):
                instant = datetime.fromisoformat(moment)
                r = self.post_at(instant, payload=self.payload(datetime(2026,1,10).date()))
                self.assertEqual(r.status_code, code, r.text)

    def test_year_boundary_does_not_roll_future_price_back(self):
        for moment, code in [('2027-01-01T04:59:59+00:00',422), ('2027-01-01T05:00:00+00:00',200)]:
            with self.subTest(moment=moment):
                r = self.post_at(datetime.fromisoformat(moment), payload=self.payload(datetime(2027,1,1).date()))
                self.assertEqual(r.status_code, code, r.text)

    def test_dst_transition_instants_keep_the_market_day(self):
        for value in ['2026-03-08T06:59:59+00:00','2026-03-08T07:00:00+00:00',
                      '2026-11-01T05:59:59+00:00','2026-11-01T06:00:00+00:00']:
            with self.subTest(instant=value):
                instant = datetime.fromisoformat(value)
                market_day = instant.astimezone(ZoneInfo('America/New_York')).date()
                r = self.post_at(instant, payload=self.payload(market_day))
                self.assertEqual(r.status_code, 200, r.text)
                r = self.post_at(instant, payload=self.payload(market_day+timedelta(days=1)))
                self.assertEqual(r.status_code, 422, r.text)

    def test_filing_review_shares_valid_market_date_behavior(self):
        r = self.post_at(FIXED_UTC, '/api/v1/filing-risk/review',
                        {'symbol':'EXM','calculation':self.payload()})
        self.assertEqual(r.status_code, 200, r.text)

    def test_filing_review_keeps_future_date_guard(self):
        r = self.post_at(FIXED_UTC, '/api/v1/filing-risk/review',
            {'symbol':'EXM','calculation':self.payload(MARKET_DAY+timedelta(days=1))})
        self.assertEqual(r.status_code, 422, r.text)
        self.assertEqual(r.json()['error']['code'], 'FILING_CALCULATION')

    def test_invalid_date_schema_is_not_relaxed(self):
        body = self.payload();body['financials']['price_date']='not-a-date'
        r = self.post_at(FIXED_UTC, payload=body)
        self.assertEqual(r.status_code, 422, r.text)

    def test_math_fixture_has_no_implicit_today(self):
        from test_valuation07 import calculate as test_calculate, req
        with patch('app.valuation.date') as local_date:
            local_date.today.side_effect=AssertionError('Tests must supply an explicit date.')
            r = test_calculate(req())
        self.assertEqual(r['financials']['price_date'], MARKET_DAY.isoformat())
        self.assertEqual(r['ai_calls'], 0)

    def test_naive_test_clock_is_rejected(self):
        with self.assertRaises(ValueError):
            clock_at(datetime(2026,9,10))
