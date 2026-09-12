"""Synthetic network responses; no SEC/Yahoo/OpenAI network requests."""
import contextlib
import copy
import io
import json
import ssl
import tempfile
import time
import unittest
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import patch
import httpx
from fastapi import FastAPI
from fastapi.testclient import TestClient
from fastapi.responses import JSONResponse
from app.fundamentals import FundamentalsStore, FundamentalsError, canonical_cik, endpoint_info, validate_issuer, TICKER_URL
from app.valuation_api import install_routes
from app.research import ResearchService, ResearchError
from test_valuation07 import sec_fixture

RealClient = httpx.Client
SUB = 'https://data.sec.gov/submissions/CIK0000000001.json'
FACTS = 'https://data.sec.gov/api/xbrl/companyfacts/CIK0000000001.json'
QUOTE = {'close': 20.0, 'date': '2026-09-08', 'currency': 'USD', 'basis': 'PROVIDER_CLOSE_NO_DIVIDEND_ADJUSTMENT',
         'source': 'SYNTHETIC QUOTE', 'splits': [], 'url': 'https://finance.yahoo.com/quote/EXM/history/'}
SUBMISSION = {'cik': '0000000001', 'name': 'SYNTHETIC COMPANY', 'tickers': ['EXM'], 'sic': '3674'}


class FetchTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.s = FundamentalsStore(self.root)
        self.s.set_contact('test-contact@example.test')
        self.http_calls = []
        self.defaults = {TICKER_URL: {'0': {'cik_str': 1, 'ticker': 'EXM'}}, SUB: SUBMISSION, FACTS: sec_fixture()}
        self.output = io.StringIO()
        self.capture = contextlib.redirect_stdout(self.output)
        self.capture.__enter__()
        self.sleep = patch('app.fundamentals.time.sleep')
        self.sleep.start()

    def tearDown(self):
        self.sleep.stop()
        self.capture.__exit__(None, None, None)
        self.tmp.cleanup()

    def transport(self, responses=None, error=None):
        results = self.defaults if responses is None else responses
        def handler(request):
            self.http_calls.append(str(request.url))
            if error is not None:
                raise error
            val = results[str(request.url)]
            if isinstance(val, httpx.Response):
                return val
            return httpx.Response(200, json=val)
        return patch('app.fundamentals.httpx.Client', side_effect=lambda **kw: RealClient(transport=httpx.MockTransport(handler), **kw))

    def load(self, **kw):
        return self.s.load('EXM', quote_loader=lambda symbol: copy.deepcopy(QUOTE), **kw)

    def test_normal_directory_mode_makes_three_sec_requests(self):
        with self.transport():
            r = self.load()
        self.assertEqual(self.http_calls, [TICKER_URL, SUB, FACTS])
        self.assertEqual(r['input']['revenue'], 115)
        self.assertEqual(r['retrieval']['sec_request_count'], 3)

    def test_explicit_cik_mode_uses_two_official_endpoints_only(self):
        with self.transport({SUB: SUBMISSION, FACTS: sec_fixture()}):
            r = self.load(cik_hint='1')
        self.assertEqual(self.http_calls, [SUB, FACTS])
        self.assertEqual(r['retrieval']['identity_mode'], 'USER_CIK_VERIFY_WITH_SEC')
        self.assertEqual(r['input']['operating_income'], 23)

    def test_directory_403_reports_stage_and_preserves_quote(self):
        with self.transport({TICKER_URL: httpx.Response(403, text='PRIVATE RESPONSE')}):
            with self.assertRaises(FundamentalsError) as e:
                self.load()
        self.assertEqual(e.exception.code, 'SEC_HTTP_403')
        self.assertEqual(e.exception.partial_quote['close'], 20)
        self.assertEqual(e.exception.diagnostic['steps'][-1]['stage'], 'TICKER_DIRECTORY')
        self.assertEqual(e.exception.diagnostic['steps'][-1]['http_status'], 403)
        self.assertEqual(self.s.read('quote-EXM.json')['quote']['close'], 20)
        self.assertIsNone(self.s.read('EXM.json'))
        self.assertEqual(self.http_calls, [TICKER_URL])
        self.assertNotIn('PRIVATE RESPONSE', self.output.getvalue())

    def test_submissions_403_does_not_try_companyfacts_or_other_hosts(self):
        with self.transport({SUB: httpx.Response(403)}):
            with self.assertRaises(FundamentalsError) as e:
                self.load(cik_hint='1')
        self.assertEqual(e.exception.diagnostic['steps'][-1]['stage'], 'SUBMISSIONS')
        self.assertEqual(self.http_calls, [SUB])

    def test_companyfacts_403_does_not_erase_verified_identity_or_quote(self):
        with self.transport({SUB: SUBMISSION, FACTS: httpx.Response(403)}):
            with self.assertRaises(FundamentalsError) as e:
                self.load(cik_hint='1')
        self.assertEqual(e.exception.diagnostic['steps'][-1]['stage'], 'COMPANYFACTS')
        self.assertEqual(self.s.read('issuer-EXM.json')['cik'], '0000000001')
        self.assertEqual(self.http_calls, [SUB, FACTS])

    def test_403_404_429_500_are_not_all_hidden_behind_502(self):
        for status in [403, 404, 429, 500]:
            self.s._path('sec-cooldown.json').unlink(missing_ok=True)
            with self.subTest(status=status), self.transport({SUB: httpx.Response(status)}):
                with self.assertRaises(FundamentalsError) as e:
                    self.s.get_json(SUB)
            self.assertEqual(e.exception.code, f'SEC_HTTP_{status}')
            self.assertIn(f'HTTP {status}', e.exception.message)

    def test_redirect_not_followed(self):
        with self.transport({SUB: httpx.Response(302, headers={'Location': 'https://other.example/path'})}):
            with self.assertRaises(FundamentalsError) as e:
                self.s.get_json(SUB)
        self.assertEqual(e.exception.code, 'SEC_HTTP_302')
        self.assertEqual(self.http_calls, [SUB])

    def test_json_html_failure_classified_separately(self):
        with self.transport({SUB: httpx.Response(200, text='<html>No JSON</html>')}):
            with self.assertRaises(FundamentalsError) as e:
                self.s.get_json(SUB)
        self.assertEqual(e.exception.code, 'SEC_JSON_INVALID')

    def test_json_array_not_accepted_as_company_object(self):
        with self.transport({SUB: [1, 2, 3]}):
            with self.assertRaises(FundamentalsError) as e:
                self.s.get_json(SUB)
        self.assertEqual(e.exception.code, 'SEC_JSON_INVALID')

    def test_timeout_classified(self):
        with self.transport(error=httpx.ReadTimeout('raw-secret-do-not-log')):
            with self.assertRaises(FundamentalsError) as e:
                self.load(cik_hint='1')
        self.assertEqual(e.exception.code, 'SEC_TIMEOUT')
        self.assertNotIn('raw-secret-do-not-log', self.output.getvalue())

    def test_connect_failure_classified(self):
        with self.transport(error=httpx.ConnectError('PRIVATE IP AND HEADERS')):
            with self.assertRaises(FundamentalsError) as e:
                self.load(cik_hint='1')
        self.assertEqual(e.exception.code, 'SEC_CONNECT_FAILED')
        self.assertNotIn('PRIVATE IP', self.output.getvalue())

    def test_certificate_classified_without_disabling_tls(self):
        problem = httpx.ConnectError('CERTIFICATE_VERIFY_FAILED')
        problem.__cause__ = ssl.SSLCertVerificationError(1, 'private-path-and-name')
        with self.transport(error=problem):
            with self.assertRaises(FundamentalsError) as e:
                self.load(cik_hint='1')
        self.assertEqual(e.exception.code, 'SEC_TLS_CERTIFICATE')
        self.assertNotIn('private-path', self.output.getvalue())

    def test_transport_error_separate(self):
        with self.transport(error=httpx.RemoteProtocolError('PRIVATE')):
            with self.assertRaises(FundamentalsError) as e:
                self.load(cik_hint='1')
        self.assertEqual(e.exception.code, 'SEC_TRANSPORT_ERROR')

    def test_rate_limit_waits_without_further_request(self):
        with self.transport({SUB: httpx.Response(429, headers={'Retry-After': '120'})}):
            with self.assertRaises(FundamentalsError):
                self.s.get_json(SUB)
            with self.assertRaises(FundamentalsError) as e:
                self.s.get_json(FACTS)
        self.assertEqual(e.exception.code, 'SEC_COOLDOWN')
        self.assertEqual(self.http_calls, [SUB])

    def test_contact_email_sent_only_as_declared_header_not_diagnostics(self):
        def handler(req):
            self.assertIn('SignalDesk Research/0.7.1', req.headers['user-agent'])
            self.assertIn('test-contact@example.test', req.headers['user-agent'])
            return httpx.Response(403)
        with patch('app.fundamentals.httpx.Client', side_effect=lambda **kw: RealClient(transport=httpx.MockTransport(handler), **kw)):
            with self.assertRaises(FundamentalsError):
                self.load(cik_hint='1')
        d = json.dumps(self.s.read('fetch-diagnostic-EXM.json'))
        for forbidden in ['test-contact@example.test', 'User-Agent', str(self.root), 'OPENAI_API_KEY']:
            self.assertNotIn(forbidden, d)
            self.assertNotIn(forbidden, self.output.getvalue())

    def test_wrong_cik_ticker_cannot_use_unrelated_financials(self):
        wrong = dict(SUBMISSION, tickers=['OTHER'])
        with self.transport({SUB: wrong}):
            with self.assertRaises(FundamentalsError) as e:
                self.load(cik_hint='1')
        self.assertEqual(e.exception.code, 'SEC_SYMBOL_MISMATCH')
        self.assertEqual(self.http_calls, [SUB])
        self.assertIsNone(self.s.read('EXM.json'))

    def test_wrong_submission_cik_rejected(self):
        with self.transport({SUB: dict(SUBMISSION, cik=2)}):
            with self.assertRaises(FundamentalsError) as e:
                self.load(cik_hint='1')
        self.assertEqual(e.exception.code, 'SEC_CIK_MISMATCH')

    def test_companyfacts_identity_mismatch_rejected(self):
        f = sec_fixture(); f['cik'] = 2
        with self.transport({SUB: SUBMISSION, FACTS: f}):
            with self.assertRaises(FundamentalsError) as e:
                self.load(cik_hint='1')
        self.assertEqual(e.exception.code, 'SEC_CIK_MISMATCH')
        self.assertIsNone(self.s.read('EXM.json'))

    def test_saved_identity_reverified_no_directory_dependency(self):
        self.s.save('issuer-EXM.json', {'symbol': 'EXM', 'cik': '1', 'verified_by': 'SEC_SUBMISSIONS'})
        with self.transport({SUB: SUBMISSION, FACTS: sec_fixture()}):
            self.load()
        self.assertEqual(self.http_calls, [SUB, FACTS])

    def test_stale_identity_cannot_bypass_ticker_verification(self):
        self.s.save('issuer-EXM.json', {'symbol': 'EXM', 'cik': '1', 'verified_by': 'SEC_SUBMISSIONS'})
        with self.transport({SUB: dict(SUBMISSION, tickers=['OTHER'])}):
            with self.assertRaises(FundamentalsError) as e:
                self.load()
        self.assertEqual(e.exception.code, 'SEC_SYMBOL_MISMATCH')

    def test_failed_refresh_preserves_last_successful_financials(self):
        with self.transport():
            self.load()
        before = self.s._path('EXM.json').read_bytes()
        with self.transport({SUB: httpx.Response(403)}):
            with self.assertRaises(FundamentalsError):
                self.load(refresh=True)
        self.assertEqual(self.s._path('EXM.json').read_bytes(), before)

    def test_recent_partial_quote_reused_without_yahoo_retry(self):
        with self.transport({TICKER_URL: httpx.Response(403)}):
            with self.assertRaises(FundamentalsError): self.load()
        with self.transport({SUB: SUBMISSION, FACTS: sec_fixture()}), patch('app.fundamentals.yahoo_completed_quote', side_effect=AssertionError('NO YAHOO')):
            result = self.s.load('EXM', cik_hint='1')
        self.assertEqual(result['retrieval']['yahoo_loader_calls'], 0)

    def test_missing_ttm_is_not_filled_with_zero(self):
        f = sec_fixture(); f['facts']['us-gaap'].pop('RevenueFromContractWithCustomerExcludingAssessedTax')
        with self.transport({SUB: SUBMISSION, FACTS: f}):
            with self.assertRaises(FundamentalsError) as e:
                self.load(cik_hint='1')
        self.assertEqual(e.exception.code, 'REVENUE_TTM_MISSING')
        self.assertIsNone(self.s.read('EXM.json'))

    def test_partial_missing_debt_does_not_become_zero(self):
        f = sec_fixture(); f['facts']['us-gaap'] = {k:v for k,v in f['facts']['us-gaap'].items() if 'Debt' not in k and 'Borrow' not in k}
        with self.transport({SUB: SUBMISSION, FACTS: f}):
            r = self.load(cik_hint='1')
        self.assertEqual(r['status'], 'PARTIAL')
        self.assertIsNone(r['input']['debt'])

    def test_cik_formats_reject_urls_zero_keys_boolean_and_negative(self):
        for invalid in [True, -1, '0', '0000000000', '1e3', 'https://sec.gov', 'sk-test', '../1', '11111111111', None]:
            with self.subTest(invalid=invalid), self.assertRaises(FundamentalsError): canonical_cik(invalid)
        self.assertEqual(canonical_cik(' 1 '), '0000000001')
        self.assertEqual(canonical_cik(1), '0000000001')

    def test_invalid_cik_no_network_no_quote(self):
        with patch.object(self.s, 'get_json') as get, patch('app.fundamentals.yahoo_completed_quote') as q:
            with self.assertRaises(FundamentalsError): self.s.load('EXM', cik_hint='../1')
            get.assert_not_called(); q.assert_not_called()

    def test_contact_missing_no_network(self):
        self.s._path('sec_contact.json').unlink()
        with patch.object(self.s, 'get_json') as get, patch('app.fundamentals.yahoo_completed_quote') as q:
            with self.assertRaises(FundamentalsError) as e: self.s.load('EXM', cik_hint='1')
            self.assertEqual(e.exception.code, 'SEC_CONTACT_REQUIRED')
            get.assert_not_called(); q.assert_not_called()

    def test_automatic_retry_count_zero_even_on_failure(self):
        with self.transport({SUB: httpx.Response(500)}):
            with self.assertRaises(FundamentalsError) as e: self.load(cik_hint='1')
        self.assertEqual(e.exception.diagnostic['automatic_retries'], 0)
        self.assertEqual(e.exception.diagnostic['openai_calls'], 0)
        self.assertEqual(e.exception.diagnostic['sec_request_count'], 1)

    def test_diagnostics_preserve_credentials_and_research_database(self):
        (self.root / '.env.signaldesk').write_bytes(b'PRIVATE KEY FIXTURE')
        (self.root / '.cache/research').mkdir(parents=True)
        db = self.root / '.cache/research/research.sqlite3'; db.write_bytes(b'QUOTA AND REPORT FIXTURE')
        with self.transport({SUB: httpx.Response(403)}):
            with self.assertRaises(FundamentalsError): self.load(cik_hint='1')
        self.assertEqual(db.read_bytes(), b'QUOTA AND REPORT FIXTURE')
        self.assertEqual((self.root / '.env.signaldesk').read_bytes(), b'PRIVATE KEY FIXTURE')
        self.assertNotIn('PRIVATE KEY FIXTURE', self.output.getvalue())

    def test_completed_cache_no_sec_yahoo_or_ai_request(self):
        with self.transport(): self.load()
        with patch.object(self.s, 'get_json', side_effect=AssertionError('NO SEC')), patch('app.fundamentals.yahoo_completed_quote', side_effect=AssertionError('NO YAHOO')):
            self.assertTrue(self.s.load('EXM')['cache_hit'])

    def test_quote_failure_does_not_replace_with_chart_adjusted_price(self):
        with patch('app.fundamentals.yahoo_completed_quote', side_effect=FundamentalsError('VALUATION_QUOTE_FAILED', 'Quote failed', 502)), patch.object(self.s, 'get_json') as get:
            with self.assertRaises(FundamentalsError) as e: self.s.load('EXM', cik_hint='1')
        self.assertIsNone(e.exception.partial_quote)
        get.assert_not_called()


class FetchAPITests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(); self.root = Path(self.tmp.name)
        self.research = ResearchService(self.root); app = FastAPI()
        @app.exception_handler(ResearchError)
        async def err(request, exc):
            return JSONResponse(status_code=exc.status, content={'error': {'code': exc.code, 'message': exc.message}})
        install_routes(app, self.root, self.research)
        self.client = TestClient(app)
        self.headers = {'X-SignalDesk-AI': self.research.csrf_token}

    def tearDown(self):
        self.client.close(); self.tmp.cleanup()

    def test_error_response_preserves_code_trace_and_quote(self):
        e = FundamentalsError('SEC_HTTP_403', 'SEC HTTP 403', 502)
        e.partial_quote = QUOTE; e.diagnostic = {'symbol': 'EXM', 'steps': [{'stage': 'TICKER_DIRECTORY', 'http_status': 403}], 'openai_calls': 0}
        with patch('app.valuation_api.FundamentalsStore.load', side_effect=e):
            r = self.client.post('/api/v1/decision/financials', json={'symbol': 'EXM', 'allow_public_fetch': True}, headers=self.headers)
        self.assertEqual(r.status_code, 502)
        self.assertEqual(r.json()['error']['code'], 'SEC_HTTP_403')
        self.assertEqual(r.json()['error']['partial_quote']['close'], 20)
        self.assertEqual(r.json()['error']['diagnostic']['steps'][0]['http_status'], 403)

    def test_cik_passed_only_to_data_loader(self):
        with patch('app.valuation_api.FundamentalsStore.load', return_value={'ok': True}) as load:
            r = self.client.post('/api/v1/decision/financials', json={'symbol': 'EXM', 'cik': '1', 'allow_public_fetch': True}, headers=self.headers)
        self.assertEqual(r.status_code, 200)
        self.assertEqual(load.call_args.kwargs['cik_hint'], '1')

    def test_public_consent_still_required_for_cik_mode(self):
        with patch('app.valuation_api.FundamentalsStore.load') as load:
            r = self.client.post('/api/v1/decision/financials', json={'symbol': 'EXM', 'cik': '1'}, headers=self.headers)
        self.assertEqual(r.status_code, 400); load.assert_not_called()

    def test_invalid_cik_api_rejected_before_load(self):
        with patch('app.valuation_api.FundamentalsStore.load') as load:
            r = self.client.post('/api/v1/decision/financials', json={'symbol': 'EXM', 'cik': 'https://bad.example', 'allow_public_fetch': True}, headers=self.headers)
        self.assertEqual(r.status_code, 422); load.assert_not_called()

    def test_get_state_diagnostic_read_only_no_fetch_or_email(self):
        store = FundamentalsStore(self.root); store.set_contact('private@example.test')
        store.save('fetch-diagnostic-EXM.json', {'diagnostic_version':'0.7.1','symbol':'EXM','result':'FAILED','steps':[]})
        store.save('quote-EXM.json', {'symbol':'EXM','quote':QUOTE})
        with patch('app.valuation_api.FundamentalsStore.load', side_effect=AssertionError('NO LOAD')), patch('app.decision.call_openai', side_effect=AssertionError('NO AI')):
            r = self.client.get('/api/v1/decision/state?symbol=EXM')
        self.assertEqual(r.status_code, 200)
        self.assertEqual(r.json()['financial_diagnostic']['result'], 'FAILED')
        self.assertEqual(r.json()['quote_pack']['quote']['close'], 20)
        self.assertNotIn('private@example.test', r.text)

    def test_error_releases_job_lock(self):
        with patch('app.valuation_api.FundamentalsStore.load', side_effect=FundamentalsError('SEC_HTTP_403', 'Failed', 502)):
            self.client.post('/api/v1/decision/financials', json={'symbol':'EXM','allow_public_fetch':True}, headers=self.headers)
        self.assertTrue(self.research._active.acquire(blocking=False)); self.research._active.release()


if __name__ == '__main__': unittest.main(verbosity=2)
