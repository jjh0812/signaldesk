"""Offline v0.3 compatibility/payment-control tests, not real financial accuracy tests."""
import json
import tempfile
import time
import unittest
from pathlib import Path
from unittest.mock import patch
from fastapi.testclient import TestClient
import app.main as main
from app.research import ResearchService, ResearchError, PROMPT_VERSION, build_prompt
from test_research import api_response, dashboard

class BriefUpgradeTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.root=Path(self.tmp.name)
        (self.root/'.env.signaldesk').write_text('OPENAI_API_KEY=sk-offline-only-'+'x'*30)
        self.service=ResearchService(self.root);self.token=self.service.snapshots.add(dashboard())
        self.ctx=self.service.snapshots.context(self.token,'2026-08-27')
    def tearDown(self):self.tmp.cleanup()
    def seed(self,version='event-research-v0.2.0',expires=None):
        key=self.service.cache_key(self.ctx,'gpt-5-mini',version)
        payload={'symbol':'NVDA','event_date':'2026-08-27','prompt_version':version,'status':'RESEARCH_READY',
                 'segments':[{'text':'OLD SAVED REPORT'}],'citations':[],'cache_hit':False}
        expires=time.time()+3600 if expires is None else expires
        raw=json.dumps(payload)
        with self.service._db() as db:db.execute('INSERT OR REPLACE INTO cache VALUES(?,?,?)',(key,expires,raw))
        return key,expires,raw
    def test_legacy_cache_get_does_not_call_provider(self):
        self.seed()
        with patch('app.research.call_openai') as call:
            result=self.service.cached(self.token,'2026-08-27')
            self.assertTrue(result['cache_hit']);self.assertEqual(result['prompt_version'],'event-research-v0.2.0');call.assert_not_called()
    def test_legacy_get_does_not_rewrite_expiry_or_payload(self):
        key,expiry,raw=self.seed();self.service.cached(self.token,'2026-08-27')
        with self.service._db() as db:
            self.assertEqual(db.execute('SELECT expires,payload FROM cache WHERE cache_key=?',(key,)).fetchone(),(expiry,raw))
            self.assertEqual(db.execute('SELECT count(*) FROM attempts').fetchone()[0],0)
    def test_legacy_analyze_without_refresh_reuses_saved_report(self):
        self.seed()
        with patch('app.research.call_openai') as call:
            self.assertEqual(self.service.analyze(self.token,'2026-08-27',False)['prompt_version'],'event-research-v0.2.0')
            call.assert_not_called()
    def test_new_report_preferred_over_legacy(self):
        self.seed();self.seed(PROMPT_VERSION)
        self.assertEqual(self.service.cached(self.token,'2026-08-27')['prompt_version'],PROMPT_VERSION)
    def test_expired_legacy_not_returned(self):
        self.seed(expires=time.time()-1)
        self.assertIsNone(self.service.cached(self.token,'2026-08-27'))
    def test_refresh_requires_explicit_consent_even_with_cache(self):
        self.seed()
        with patch('app.research.call_openai') as call:
            with self.assertRaises(ResearchError) as error:self.service.analyze(self.token,'2026-08-27',False,True)
            self.assertEqual(error.exception.code,'PAID_CONSENT_REQUIRED');call.assert_not_called()
    def test_refresh_requires_key_even_with_cache(self):
        self.seed();(self.root/'.env.signaldesk').unlink()
        with patch('app.research.call_openai') as call:
            with self.assertRaises(ResearchError):self.service.analyze(self.token,'2026-08-27',True,True)
            call.assert_not_called()
    def test_refresh_one_provider_call_no_hidden_summary_call(self):
        self.seed()
        with patch('app.research.call_openai',return_value=api_response()) as call:
            result=self.service.analyze(self.token,'2026-08-27',True,True)
            self.assertEqual(call.call_count,1);self.assertEqual(result['prompt_version'],PROMPT_VERSION)
            self.assertFalse(result['cache_hit'])
            self.assertTrue(self.service.cached(self.token,'2026-08-27')['cache_hit']);self.assertEqual(call.call_count,1)
        with self.service._db() as db:self.assertEqual(db.execute('SELECT sum(n) FROM attempts').fetchone()[0],1)
    def test_failed_refresh_keeps_original_report(self):
        key,expiry,raw=self.seed()
        with patch('app.research.call_openai',side_effect=ResearchError('AI_TIMEOUT','stub failure')) as call:
            with self.assertRaises(ResearchError):self.service.analyze(self.token,'2026-08-27',True,True)
            self.assertEqual(call.call_count,1)
        self.assertEqual(self.service.cached(self.token,'2026-08-27')['prompt_version'],'event-research-v0.2.0')
        with self.service._db() as db:self.assertEqual(db.execute('SELECT expires,payload FROM cache WHERE cache_key=?',(key,)).fetchone(),(expiry,raw))
    def test_malformed_new_response_does_not_replace_old(self):
        self.seed();raw=api_response();raw['status']='incomplete'
        with patch('app.research.call_openai',return_value=raw):
            with self.assertRaises(ResearchError):self.service.analyze(self.token,'2026-08-27',True,True)
        self.assertEqual(self.service.cached(self.token,'2026-08-27')['prompt_version'],'event-research-v0.2.0')
    def test_refresh_still_obeys_active_request_lock(self):
        self.seed();self.service._active.acquire()
        try:
            with patch('app.research.call_openai') as call:
                with self.assertRaises(ResearchError) as error:self.service.analyze(self.token,'2026-08-27',True,True)
                self.assertEqual(error.exception.code,'AI_BUSY');call.assert_not_called()
        finally:self.service._active.release()
    def test_new_prompt_has_brief_and_detail_contract(self):
        ins,_=build_prompt(self.ctx)
        for h in ['요약: 움직인 이유','요약: 중요한 이유','요약: 주의할 점','상세 분석','한 줄 해석','아직 확인하지 못한 것']:self.assertIn(h,ins)
        self.assertIn('No confidence percentage',ins)
        self.assertIn('not a proven cause',ins)
        self.assertIn('Do NOT offer to fetch block trades',ins)
    def test_refresh_field_is_strict_boolean(self):
        with patch.object(main,'research',self.service):
            client=TestClient(main.app)
            response=client.post('/api/v1/ai/analyze',headers={'X-SignalDesk-AI':self.service.csrf_token},json={
                'snapshot_id':self.token,'event_date':'2026-08-27','allow_paid':True,'refresh_report':'true'})
            self.assertEqual(response.status_code,422)
    def test_free_cache_endpoint_reuses_legacy_and_never_posts(self):
        self.seed()
        with patch.object(main,'research',self.service),patch('app.research.call_openai') as call:
            client=TestClient(main.app)
            r=client.get('/api/v1/ai/cache',params={'snapshot_id':self.token,'event_date':'2026-08-27'})
            self.assertEqual(r.status_code,200);self.assertEqual(r.json()['result']['prompt_version'],'event-research-v0.2.0');call.assert_not_called()
    def test_status_read_is_free(self):
        with patch('app.research.call_openai') as call:
            self.assertTrue(self.service.status()['configured']);call.assert_not_called()

if __name__=='__main__':unittest.main()
