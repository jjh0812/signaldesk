"""Offline endpoint regressions. All research operations are dependency-injected."""
import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock, patch
from fastapi import FastAPI
from fastapi.testclient import TestClient
from fastapi.responses import JSONResponse
from app.catalyst_api import install_routes as catalysts
from app.watch_api import install_routes as thesis
from app.research import ResearchError, ResearchService

class ForwardAPITests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.root=Path(self.temp.name)
        self.research=ResearchService(self.root)
        self.research.cached_outlook=Mock(return_value={'context':{'symbol':'TEST'},'reports':{'catalysts':None,'risks':{'private':'not needed'}}})
        self.research.analyze_outlook=Mock(return_value={'symbol':'TEST','scope':'catalysts'})
        self.app=FastAPI()
        @self.app.exception_handler(ResearchError)
        async def err(req,e):return JSONResponse(status_code=e.status,content={'error':{'code':e.code}})
        def validate(req):
            if req.headers.get('x-signaldesk-ai')!='test-token':raise ResearchError('CSRF','blocked',403)
            if req.headers.get('origin') not in (None,'http://testserver'):raise ResearchError('ORIGIN','blocked',403)
        catalysts(self.app,self.root,self.research,validate);thesis(self.app,self.root,self.research,validate)
        self.client=TestClient(self.app);self.headers={'X-SignalDesk-AI':'test-token'}
        self.body={'snapshot_id':'a'*24,'allow_paid':True,'refresh_report':True}
    def tearDown(self):self.client.close();self.temp.cleanup()
    def test_state_is_cache_only(self):
        r=self.client.get('/api/v1/catalysts/state?snapshot_id='+'a'*24)
        self.assertEqual(r.status_code,200);self.assertEqual(r.json()['ai_calls'],0)
        self.research.analyze_outlook.assert_not_called();self.assertNotIn('risks',r.json()['reports'])
    def test_consented_post_uses_existing_forward_engine(self):
        r=self.client.post('/api/v1/catalysts/analyze',headers=self.headers,json=self.body)
        self.assertEqual(r.status_code,200);self.research.analyze_outlook.assert_called_once_with('a'*24,'catalysts',True,True)
    def test_no_consent_no_call(self):
        r=self.client.post('/api/v1/catalysts/analyze',headers=self.headers,json={**self.body,'allow_paid':False})
        self.assertEqual(r.status_code,400);self.research.analyze_outlook.assert_not_called()
    def test_token_required(self):
        r=self.client.post('/api/v1/catalysts/analyze',json=self.body)
        self.assertEqual(r.status_code,403);self.research.analyze_outlook.assert_not_called()
    def test_cross_origin_rejected(self):
        r=self.client.post('/api/v1/catalysts/analyze',headers={**self.headers,'Origin':'https://other.example'},json=self.body)
        self.assertEqual(r.status_code,403);self.research.analyze_outlook.assert_not_called()
    def test_strict_boolean_consent(self):
        for v in (1,'true',None):
            r=self.client.post('/api/v1/catalysts/analyze',headers=self.headers,json={**self.body,'allow_paid':v})
            self.assertEqual(r.status_code,422)
        self.research.analyze_outlook.assert_not_called()
    def test_extra_fields_rejected(self):
        r=self.client.post('/api/v1/catalysts/analyze',headers=self.headers,json={**self.body,'scope':'risks'})
        self.assertEqual(r.status_code,422);self.research.analyze_outlook.assert_not_called()
    def test_invalid_snapshot_rejected(self):
        self.assertEqual(self.client.get('/api/v1/catalysts/state?snapshot_id=bad').status_code,422)
    def test_removed_sec_routes(self):
        for route in ('dilution','contact'):
            self.assertEqual(self.client.post('/api/v1/watch/'+route,json={}).status_code,404)
        self.assertFalse(hasattr(self.app.state,'dilution_watch'))
    def test_no_sec_fields_in_thesis_cache(self):
        r=self.client.get('/api/v1/watch/state?symbol=TEST')
        for key in ('dilution','sec_cooldown','contact_configured','sec_busy','last_sec_attempt'):self.assertNotIn(key,r.json())
    def test_source_has_no_direct_sec_network_client(self):
        import app.watch_store as s
        self.assertFalse(hasattr(s,'SecClient'));self.assertFalse(hasattr(s.WatchStore,'contact'))
    def test_main_registers_new_routes(self):
        from app.main import app
        routes={r.path for r in app.routes}
        self.assertIn('/api/v1/catalysts/analyze',routes);self.assertNotIn('/api/v1/watch/dilution',routes)
if __name__=='__main__':unittest.main()
