"""Offline/stubbed research tests. NOT measurements of real AI factual accuracy."""
from __future__ import annotations
import copy
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

import httpx
from fastapi.testclient import TestClient
import app.main as main
from app.research import (ResearchError, ResearchService, Settings, Snapshots, build_prompt,
                          call_openai, parse_response, public_url, read_settings, request_body)


def dashboard():
    return {"symbol":"NVDA", "bars":[
        {"date":"2026-08-26","close":100.0,"return_1d":0.01,"volume_ratio":1.0,"volume":100},
        {"date":"2026-08-27","close":108.74,"return_1d":0.0874,"volume_ratio":2.56,"volume":256,
         "benchmark_return":0.0066,"benchmark_spread":0.0808,"notes":[]}],"meta":{}}


def api_response(text="한 줄 해석\n테스트 전용 문장.[ref]\n아직 확인하지 못한 것\n독립 검증 필요."):
    start=text.find('[ref]')
    return {"status":"completed","output":[
        {"type":"web_search_call","status":"completed","action":{"type":"search","sources":[
            {"url":"https://issuer.example/release","title":"SYNTHETIC TEST SOURCE"}]}},
        {"type":"message","role":"assistant","content":[{"type":"output_text","text":text,
         "annotations":[{"type":"url_citation","start_index":start,"end_index":start+5,
         "url":"https://issuer.example/release","title":"SYNTHETIC TEST SOURCE"}]}]}],
        "usage":{"input_tokens":100,"output_tokens":50,"total_tokens":150}}


class ResearchSettingsTests(unittest.TestCase):
    def test_missing_key_is_disabled(self):
        with tempfile.TemporaryDirectory() as d:self.assertFalse(read_settings(Path(d)).configured)
    def test_generic_environment_key_is_not_used(self):
        with tempfile.TemporaryDirectory() as d,patch.dict('os.environ',{'OPENAI_API_KEY':'sk-other-project-'+'x'*25}):
            self.assertFalse(read_settings(Path(d)).configured)
    def test_project_key_read_without_exposing_in_repr(self):
        with tempfile.TemporaryDirectory() as d:
            root=Path(d);secret='sk-test-local-only-'+'x'*30
            (root/'.env.signaldesk').write_text('OPENAI_API_KEY='+secret+'\nSIGNALDESK_AI_MODEL=gpt-5-mini\n')
            settings=read_settings(root)
            self.assertTrue(settings.configured);self.assertNotIn(secret,repr(settings))
    def test_invalid_model_cannot_change_endpoint(self):
        with tempfile.TemporaryDirectory() as d:
            (Path(d)/'.env.signaldesk').write_text('SIGNALDESK_AI_MODEL=https://evil.example\n')
            self.assertEqual(read_settings(Path(d)).model,'gpt-5-mini')
    def test_malformed_key_rejected(self):
        with tempfile.TemporaryDirectory() as d:
            (Path(d)/'.env.signaldesk').write_text('OPENAI_API_KEY=$(do-not-execute)\n')
            self.assertFalse(read_settings(Path(d)).configured)
    def test_private_or_script_links_rejected(self):
        for url in ['javascript:alert(1)','file:///c:/secret','https://localhost/a','http://127.0.0.1/a',
                    'http://10.0.0.1','http://[::1]/','https://u:p@issuer.example','https://x.local',
                    'https://x.example:9999/a','http://2130706433/','https://x.example\\@localhost']:
            with self.subTest(url=url):self.assertIsNone(public_url(url))
    def test_public_url_preserved(self):
        url='https://www.sec.gov/Archives/example?a=1#section';self.assertEqual(public_url(url),url)


class SnapshotTests(unittest.TestCase):
    def test_snapshot_is_server_copied(self):
        s=Snapshots();d=dashboard();token=s.add(d);d['bars'][1]['close']=999
        self.assertEqual(s.context(token,'2026-08-27')['observation']['close'],108.74)
    def test_context_contains_previous_date(self):
        s=Snapshots();self.assertEqual(s.context(s.add(dashboard()),'2026-08-27')['previous_observation_date'],'2026-08-26')
    def test_no_nearest_date_substitution(self):
        s=Snapshots()
        with self.assertRaises(ResearchError):s.context(s.add(dashboard()),'2026-08-29')
    def test_invalid_calendar_date_rejected(self):
        s=Snapshots()
        with self.assertRaises(ResearchError):s.context(s.add(dashboard()),'2026-02-30')
    def test_snapshot_expires(self):
        s=Snapshots();token=s.add(dashboard());s._items[token]=(0,dashboard())
        with self.assertRaises(ResearchError):s.context(token,'2026-08-27')
    def test_missing_return_blocks_request(self):
        s=Snapshots();d=dashboard();d['bars'][1]['return_1d']=None
        with self.assertRaises(ResearchError):s.context(s.add(d),'2026-08-27')
    def test_snapshot_limit(self):
        s=Snapshots();first=s.add(dashboard())
        for _ in range(35):s.add(dashboard())
        self.assertLessEqual(len(s._items),32)
        with self.assertRaises(ResearchError):s.context(first,'2026-08-27')
    def test_prompt_has_date_basis_and_no_causal_certainty(self):
        s=Snapshots();ctx=s.context(s.add(dashboard()),'2026-08-27');ins,body=build_prompt(ctx)
        self.assertIn('2026-08-27',body);self.assertIn('ADJUSTED',ins)
        self.assertIn('after the target session',ins);self.assertIn('원인 미확인',ins)
    def test_one_fixed_endpoint_no_store_bounded_tools(self):
        s=Snapshots();body=request_body(s.context(s.add(dashboard()),'2026-08-27'),'gpt-5-mini')
        self.assertFalse(body['store']);self.assertEqual(body['max_tool_calls'],4)
        self.assertEqual(body['tools'][0]['type'],'web_search');self.assertNotIn('api_key',json.dumps(body))


class ProvenanceTests(unittest.TestCase):
    def test_real_annotations_become_clickable_segments(self):
        r=parse_response(api_response());self.assertEqual(r['status'],'RESEARCH_READY')
        self.assertIn({'citation':1},r['segments']);self.assertEqual(r['citations'][0]['number'],1)
        self.assertNotIn('[ref]',''.join(p.get('text','') for p in r['segments']))
    def test_no_search_means_unconfirmed(self):
        raw=api_response();raw['output']=raw['output'][1:]
        r=parse_response(raw);self.assertEqual(r['status'],'UNCONFIRMED');self.assertEqual(r['citations'],[])
    def test_no_citation_means_no_fluent_fake_explanation(self):
        raw=api_response();raw['output'][1]['content'][0]['annotations']=[]
        r=parse_response(raw);self.assertEqual(r['status'],'UNCONFIRMED')
        self.assertNotIn('테스트 전용',''.join(s.get('text','') for s in r['segments']))
    def test_incomplete_response_not_displayed(self):
        raw=api_response();raw['status']='incomplete'
        with self.assertRaises(ResearchError):parse_response(raw)
    def test_refusal_not_displayed_as_research(self):
        raw=api_response();raw['output'][1]['content']=[{'type':'refusal','refusal':'No'}]
        with self.assertRaises(ResearchError):parse_response(raw)
    def test_invalid_link_not_clickable(self):
        raw=api_response();raw['output'][1]['content'][0]['annotations'][0]['url']='javascript:alert(1)'
        self.assertEqual(parse_response(raw)['status'],'UNCONFIRMED')
    def test_bad_offsets_flagged_not_sliced(self):
        raw=api_response();raw['output'][1]['content'][0]['annotations'][0]['end_index']=999999
        r=parse_response(raw);self.assertEqual(r['unmapped_citation_count'],1);self.assertEqual(len(r['citations']),1)
    def test_duplicate_citation_url_deduplicated(self):
        raw=api_response();part=copy.deepcopy(raw['output'][1]['content'][0]);raw['output'][1]['content'].append(part)
        r=parse_response(raw);self.assertEqual(len(r['citations']),1)
        self.assertEqual(sum(s.get('citation')==1 for s in r['segments']),2)
    def test_usage_is_not_confidence(self):
        r=parse_response(api_response());self.assertEqual(r['usage']['total_tokens'],150)
        self.assertNotIn('confidence',r);self.assertNotIn('probability',r)
    def test_negative_usage_not_accepted(self):
        raw=api_response();raw['usage']['total_tokens']=-1
        self.assertIsNone(parse_response(raw)['usage']['total_tokens'])


class ServiceTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.root=Path(self.temp.name)
        (self.root/'.env.signaldesk').write_text('OPENAI_API_KEY=sk-offline-test-'+'x'*35+'\n')
        self.service=ResearchService(self.root);self.token=self.service.snapshots.add(dashboard())
    def tearDown(self):self.temp.cleanup()
    def test_status_never_exposes_credentials(self):
        status=json.dumps(self.service.status());self.assertNotIn('sk-offline',status);self.assertNotIn('api_key',status)
    def test_missing_key_no_provider_call(self):
        (self.root/'.env.signaldesk').unlink()
        with patch('app.research.call_openai') as call:
            with self.assertRaises(ResearchError):self.service.analyze(self.token,'2026-08-27',True)
            call.assert_not_called()
    def test_no_consent_no_provider_call(self):
        with patch('app.research.call_openai') as call:
            with self.assertRaises(ResearchError):self.service.analyze(self.token,'2026-08-27',False)
            call.assert_not_called()
    def test_cache_get_is_free(self):
        with patch('app.research.call_openai') as call:
            self.assertIsNone(self.service.cached(self.token,'2026-08-27'));call.assert_not_called()
    def test_result_cached_without_second_call(self):
        with patch('app.research.call_openai',return_value=api_response()) as call:
            first=self.service.analyze(self.token,'2026-08-27',True)
            second=self.service.analyze(self.token,'2026-08-27',True)
            self.assertFalse(first['cache_hit']);self.assertTrue(second['cache_hit']);self.assertEqual(call.call_count,1)
    def test_cache_key_changes_when_price_changes(self):
        ctx=self.service.snapshots.context(self.token,'2026-08-27');a=self.service.cache_key(ctx,'gpt-5-mini')
        ctx['observation']['close']=99;self.assertNotEqual(a,self.service.cache_key(ctx,'gpt-5-mini'))
    def test_busy_no_duplicate_paid_call(self):
        self.service._active.acquire()
        try:
            with patch('app.research.call_openai') as call:
                with self.assertRaises(ResearchError):self.service.analyze(self.token,'2026-08-27',True)
                call.assert_not_called()
        finally:self.service._active.release()
    def test_daily_attempt_limit_persists_and_counts_failed_calls(self):
        with patch('app.research.DAILY_ATTEMPT_LIMIT',1),patch('app.research.call_openai',side_effect=ResearchError('FAIL','fixture')) as call:
            with self.assertRaises(ResearchError):self.service.analyze(self.token,'2026-08-27',True)
            with self.assertRaises(ResearchError) as error:self.service.analyze(self.token,'2026-08-26',True)
            self.assertEqual(error.exception.code,'LOCAL_DAILY_LIMIT');self.assertEqual(call.call_count,1)
    def test_http_auth_error_is_sanitized_no_key_in_message(self):
        client=Mock();client.post.return_value=httpx.Response(401,json={'error':{'message':'SENSITIVE-ECHO'}})
        with patch('app.research.httpx.Client') as cls:
            cls.return_value.__enter__.return_value=client
            with self.assertRaises(ResearchError) as error:call_openai(Settings('secret-not-in-errors'),{})
        self.assertNotIn('SENSITIVE',str(error.exception));self.assertNotIn('secret',str(error.exception))
        self.assertEqual(client.post.call_count,1)
    def test_no_transparent_http_retry(self):
        client=Mock();client.post.side_effect=httpx.ReadTimeout('sensitive request')
        with patch('app.research.httpx.Client') as cls:
            cls.return_value.__enter__.return_value=client
            with self.assertRaises(ResearchError):call_openai(Settings('secret'),{})
        self.assertEqual(client.post.call_count,1)


class ResearchAPITests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.service=ResearchService(Path(self.temp.name))
        self.patch=patch.object(main,'research',self.service);self.patch.start();self.client=TestClient(main.app)
        self.token=self.service.snapshots.add(dashboard())
        self.body={'snapshot_id':self.token,'event_date':'2026-08-27','allow_paid':True}
        self.headers={'X-SignalDesk-AI':self.service.csrf_token}
    def tearDown(self):self.patch.stop();self.temp.cleanup()
    def test_ai_status_available_no_key(self):
        r=self.client.get('/api/v1/ai/status');self.assertEqual(r.status_code,200)
        self.assertFalse(r.json()['configured']);self.assertNotIn('api_key',r.text)
    def test_custom_header_required(self):
        self.assertEqual(self.client.post('/api/v1/ai/analyze',json=self.body).status_code,403)
    def test_cross_origin_blocked(self):
        r=self.client.post('/api/v1/ai/analyze',json=self.body,headers={**self.headers,'Origin':'https://evil.example'})
        self.assertEqual(r.status_code,403)
    def test_cannot_send_custom_price_or_key(self):
        r=self.client.post('/api/v1/ai/analyze',json={**self.body,'price':1,'api_key':'bad'},headers=self.headers)
        self.assertEqual(r.status_code,422)
    def test_config_missing_explicit_error(self):
        r=self.client.post('/api/v1/ai/analyze',json=self.body,headers=self.headers)
        self.assertEqual(r.status_code,503);self.assertEqual(r.json()['error']['code'],'AI_NOT_CONFIGURED')
    def test_cached_route_never_invokes_provider(self):
        with patch('app.research.call_openai') as call:
            r=self.client.get('/api/v1/ai/cache',params={'snapshot_id':self.token,'event_date':'2026-08-27'})
        self.assertEqual(r.status_code,200);self.assertIsNone(r.json()['result']);call.assert_not_called()
    def test_unknown_day_explicit_error(self):
        r=self.client.get('/api/v1/ai/cache',params={'snapshot_id':self.token,'event_date':'2026-08-29'})
        self.assertEqual(r.status_code,422)
    def test_consented_success_then_free_cache_same_exact_event(self):
        (Path(self.temp.name)/'.env.signaldesk').write_text('OPENAI_API_KEY=sk-fixture-'+'x'*35+'\n')
        with patch('app.research.call_openai',return_value=api_response()) as call:
            r=self.client.post('/api/v1/ai/analyze',json=self.body,headers=self.headers)
            self.assertEqual(r.status_code,200)
            self.assertEqual(r.json()['symbol'],'NVDA');self.assertEqual(r.json()['event_date'],'2026-08-27')
            self.assertEqual(r.json()['observation']['close'],108.74)
            self.assertEqual(r.json()['status'],'RESEARCH_READY');self.assertEqual(len(r.json()['citations']),1)
            c=self.client.get('/api/v1/ai/cache',params={'snapshot_id':self.token,'event_date':'2026-08-27'})
            self.assertTrue(c.json()['result']['cache_hit']);self.assertEqual(call.call_count,1)
            self.assertEqual(call.call_args.args[1]['tool_choice'],'required')
    def test_api_error_no_store(self):
        r=self.client.post('/api/v1/ai/analyze',json=self.body,headers=self.headers)
        self.assertEqual(r.headers['cache-control'],'no-store')

if __name__=='__main__':unittest.main()
