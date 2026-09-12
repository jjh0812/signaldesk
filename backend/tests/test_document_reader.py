"""Offline reader/integration regressions; synthetic documents, NOT issuer research accuracy."""
import copy, hashlib, json, socket, sqlite3, tempfile, time, unittest
from datetime import datetime, timezone, timedelta
from pathlib import Path
from unittest.mock import patch, Mock
from fastapi.testclient import TestClient
import app.main as main
from app.document_reader import (checked_url, public_addresses, DocumentError, fetch_document,
    parse_isolated, date_tokens, schedule_passages, evidence_bundle, READER_VERSION, MAX_BYTES)
from app.evidence_store import (read_reports, source_candidates, save_bundle, load_bundle,
    prompt_bundle, inspect_sources, report_leads)
from app.outlook_quality import parse_quality_outlook, quality_request_body
from app.research import ResearchService
from test_outlook_quality import quality_doc, quality_raw
from test_outlook import context, raw
from test_price_context import snapshot

URL='https://www.example.com/transcript.pdf'
TEXT='Synthetic text only. Our next earnings call is scheduled for November 17, 2026. This is a fictional company.'

def synthetic_pdf(pages):
    """Minimal native text PDF fixture, no third-party test dependency."""
    objects=[b'<< /Type /Catalog /Pages 2 0 R >>',b'',b'<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>']
    kids=[]
    for text in pages:
        page_id=len(objects)+1; content_id=page_id+1;kids.append(f'{page_id} 0 R')
        content=('BT /F1 12 Tf 40 700 Td ('+text.replace('\\','\\\\').replace('(','\\(').replace(')','\\)')+') Tj ET').encode('ascii')
        objects.append(f'<< /Type /Page /Parent 2 0 R /MediaBox [0 0 800 800] /Resources << /Font << /F1 3 0 R >> >> /Contents {content_id} 0 R >>'.encode())
        objects.append(b'<< /Length '+str(len(content)).encode()+b' >>\nstream\n'+content+b'\nendstream')
    objects[1]=f'<< /Type /Pages /Kids [{" ".join(kids)}] /Count {len(pages)} >>'.encode()
    out=bytearray(b'%PDF-1.4\n');offsets=[0]
    for i,obj in enumerate(objects,1):offsets.append(len(out));out.extend(f'{i} 0 obj\n'.encode()+obj+b'\nendobj\n')
    xref=len(out);out.extend(f'xref\n0 {len(objects)+1}\n0000000000 65535 f \n'.encode())
    for n in offsets[1:]:out.extend(f'{n:010d} 00000 n \n'.encode())
    out.extend(f'trailer\n<< /Size {len(objects)+1} /Root 1 0 R >>\nstartxref\n{xref}\n%%EOF'.encode());return bytes(out)

def bundle(text=TEXT,url=URL):
    return {'version':READER_VERSION,'symbol':'EXM','generated_at':datetime.now(timezone.utc).isoformat(),'api_calls':0,
      'documents':[{'document_id':'d1','status':'TEXT_EXTRACTED','requested_url':url,'url':url,'title':'Synthetic document',
      'sha256':'a'*64,'pages_total':15,'text_truncated':False,'passages':[{'passage_id':'d1.p15.s1','page':15,'text':text}]}]}

def linked_doc():
    d=quality_doc();d['sources'][0]['url']=URL
    d['document_checks'][0]['locator']='d1.p15.s1'
    d['catalysts'][0]['schedule_evidence']['locator']='d1.p15.s1'
    return d

def seed_db(root):
    svc=ResearchService(root)
    report={'symbol':'EXM','scope':'catalysts','generated_at':'2026-09-09T16:42:08Z','sources':[{'id':'s1','url':URL,'role':'ISSUER','title':'Synthetic earnings transcript','published_date':'2026-08-26'}], 'items':[{'title':'Synthetic next results','bucket':'UNKNOWN','category':'EARNINGS','event_date':None}]}
    with svc._db() as db:
        db.execute('INSERT INTO cache(cache_key,expires,payload) VALUES(?,?,?)',('fixture-old',1,json.dumps(report)))
        report['symbol']='OTHER';db.execute('INSERT INTO cache(cache_key,expires,payload) VALUES(?,?,?)',('fixture-other',1,json.dumps(report)))
    return svc

class PublicDocumentSecurityTests(unittest.TestCase):
    def test_private_and_credential_urls_rejected(self):
        for url in ['http://www.example.com/a','https://127.0.0.1/a','https://169.254.169.254/a','https://10.0.0.2/a','https://localhost/a','https://x.local/a','https://u:p@www.example.com/a','https://www.example.com:8000/a','https://www.example.com/a?api_key=secret','https://www.example.com/a?token=secret','https://www.example.com/\\@127.0.0.1']:
            with self.subTest(url=url),self.assertRaises(DocumentError):checked_url(url)
    def test_public_url_preserves_path_and_drops_fragment(self):
        self.assertEqual(checked_url(URL+'#page=15'),URL)
    def test_mixed_private_public_dns_is_rejected(self):
        with patch('socket.getaddrinfo',return_value=[(2,1,6,'',('93.184.216.34',443)),(2,1,6,'',('127.0.0.1',443))]):
            with self.assertRaises(DocumentError):public_addresses('www.example.com')
    def test_dns_failure_is_safe_code(self):
        with patch('socket.getaddrinfo',side_effect=socket.gaierror('secret-details')):
            with self.assertRaises(DocumentError) as e:public_addresses('www.example.com')
            self.assertEqual(str(e.exception),'DNS_FAILED')
    def test_numeric_connection_and_no_auth_headers(self):
        r=Mock(status=200);r.getheader.side_effect=lambda k: {'Content-Type':'text/html'}.get(k);r.read.side_effect=[b'<p>hello</p>',b'']
        con=Mock();con.getresponse.return_value=r
        with patch('app.document_reader.public_addresses',return_value=['93.184.216.34']),patch('app.document_reader.PinnedHTTPS',return_value=con) as cls:
            got=fetch_document('https://www.example.com/page')
        self.assertEqual(cls.call_args.args[1],'93.184.216.34');headers=con.request.call_args.kwargs['headers']
        self.assertFalse(any(k.lower() in ('authorization','cookie') for k in headers));self.assertEqual(got['bytes'],b'<p>hello</p>')
    def test_redirect_to_private_blocked(self):
        r=Mock(status=302);r.getheader.return_value='https://127.0.0.1/private';con=Mock();con.getresponse.return_value=r
        with patch('app.document_reader.public_addresses',return_value=['93.184.216.34']),patch('app.document_reader.PinnedHTTPS',return_value=con):
            with self.assertRaises(DocumentError):fetch_document(URL)
        self.assertEqual(con.request.call_count,1)
    def test_declared_large_document_rejected(self):
        r=Mock(status=200);r.getheader.side_effect=lambda k: str(MAX_BYTES+1) if k=='Content-Length' else None;con=Mock();con.getresponse.return_value=r
        with patch('app.document_reader.public_addresses',return_value=['93.184.216.34']),patch('app.document_reader.PinnedHTTPS',return_value=con):
            with self.assertRaises(DocumentError) as e:fetch_document(URL)
        self.assertEqual(e.exception.code,'DOCUMENT_TOO_LARGE');r.read.assert_not_called()
    def test_http_denial_not_bypassed_or_retried(self):
        r=Mock(status=403);con=Mock();con.getresponse.return_value=r
        with patch('app.document_reader.public_addresses',return_value=['93.184.216.34']),patch('app.document_reader.PinnedHTTPS',return_value=con):
            with self.assertRaises(DocumentError) as e:fetch_document(URL)
        self.assertEqual(e.exception.code,'HTTP_403');self.assertEqual(con.request.call_count,1)

class NativeExtractionTests(unittest.TestCase):
    def test_pdf_last_page_native_text_is_extracted(self):
        b=synthetic_pdf(['Historical discussion without schedule']*14+[TEXT])
        parsed=parse_isolated({'bytes':b,'mime':'application/pdf'})
        self.assertEqual(parsed['pages_total'],15);passages=schedule_passages(parsed['pages']);self.assertEqual(passages[0]['page'],15)
        self.assertIn('November 17',passages[0]['text'])
    def test_html_script_not_executed_or_included(self):
        parsed=parse_isolated({'bytes':b'<script>BAD_SECRET fetch("/keys")</script><p>Next call November 17.</p>','mime':'text/html'})
        self.assertNotIn('BAD_SECRET',parsed['pages'][0]['text']);self.assertIn('November 17',parsed['pages'][0]['text'])
    def test_corrupt_pdf_is_explicit_failure(self):
        with self.assertRaises(DocumentError):parse_isolated({'bytes':b'%PDF-not-real','mime':'application/pdf'})
    def test_empty_text_not_silent_success(self):
        with self.assertRaises(DocumentError):parse_isolated({'bytes':b'<script>nothing</script>','mime':'text/html'})
    def test_fiscal_year_does_not_supply_calendar_year(self):
        t=date_tokens('Q2 FY2027. Our next earnings call will be November 17.');self.assertEqual(t[0]['explicit_year'],None);self.assertIsNone(t[0]['iso_date'])
    def test_invalid_dates_ignored(self):self.assertEqual(date_tokens('February 31, 2026 and 2026-99-10'),[])
    def test_year_present_is_preserved(self):self.assertEqual(date_tokens('November 17, 2026')[0]['iso_date'],'2026-11-17')
    def test_non_schedule_price_date_not_invented_as_event(self):self.assertEqual(schedule_passages([{'page':1,'text':'Closing stock price on November 17 was 5 dollars.'}]),[])
    def test_collection_reports_failure_not_fake_text(self):
        with patch('app.document_reader.fetch_document',side_effect=DocumentError('HTTP_403')):
            b=evidence_bundle([{'url':URL}],'EXM')
        self.assertEqual(b['documents'][0]['status'],'HTTP_403');self.assertEqual(b['api_calls'],0)

class EvidenceCacheTests(unittest.TestCase):
    def setUp(self):self.tmp=tempfile.TemporaryDirectory();self.root=Path(self.tmp.name);self.svc=seed_db(self.root)
    def tearDown(self):self.tmp.cleanup()
    def test_expired_urls_are_reusable_not_other_ticker(self):
        reports=read_reports(self.root,'EXM');self.assertEqual(len(reports),1);self.assertTrue(reports[0]['expired']);self.assertEqual(source_candidates(reports)[0]['url'],URL)
    def test_source_only_hints_exclude_unknown_raw_facts(self):
        self.assertNotIn('fact',report_leads(self.root,'EXM')['items'][0])
    def test_missing_ticker_does_not_start_paid_search(self):
        with patch('app.research.call_openai') as call:
            with self.assertRaises(DocumentError):inspect_sources(self.root,'ZZZZ')
        call.assert_not_called()
    def test_free_read_preserves_database_and_key(self):
        key=self.root/'.env.signaldesk';key.write_text('DO_NOT_READ_SECRET');db=self.root/'.cache/research/research.sqlite3';before=db.read_bytes()
        html=b'<p>Next earnings call scheduled for November 17, 2026. Synthetic only.</p>'
        def fake(url,deadline):return {'requested_url':url,'url':url,'sha256':hashlib.sha256(html).hexdigest(),'bytes':html,'mime':'text/html'}
        with patch('app.research.call_openai') as call,patch('app.research.read_settings',side_effect=AssertionError('credentials read')):
            result=inspect_sources(self.root,'EXM',fetcher=fake)
        self.assertEqual(result['api_calls'],0);call.assert_not_called();self.assertEqual(db.read_bytes(),before);self.assertEqual(key.read_text(),'DO_NOT_READ_SECRET')
        self.assertTrue(load_bundle(self.root,'EXM'))
    def test_stale_bundle_not_paid_input(self):
        b=bundle();b['generated_at']=(datetime.now(timezone.utc)-timedelta(hours=7)).isoformat();save_bundle(self.root,'EXM',b)
        self.assertIsNone(load_bundle(self.root,'EXM'));self.assertTrue(load_bundle(self.root,'EXM',require_fresh=False)['expired']);self.assertIsNone(prompt_bundle(b,'EXM'))
    def test_wrong_ticker_or_version_not_paid_input(self):
        b=bundle();self.assertIsNone(prompt_bundle(b,'OTHER'));b['version']='unknown';self.assertIsNone(prompt_bundle(b,'EXM'))
    def test_no_year_guessed_by_free_saved_bundle(self):
        b=bundle('Next earnings call November 17.');save_bundle(self.root,'EXM',b);self.assertNotIn('2026-11-17',json.dumps(load_bundle(self.root,'EXM')))
    def test_source_priority_transcript_then_latest_earnings(self):
        r=read_reports(self.root,'EXM')[0];r['sources'] += [{'url':'https://www.example.com/earnings','title':'Latest earnings','role':'ISSUER'},{'url':'https://www.example.com/events','title':'events calendar','role':'ISSUER'}]
        self.assertEqual([s['priority'] for s in source_candidates([r])],[0,1,2])
    def test_symlink_cache_rejected(self):
        with tempfile.TemporaryDirectory() as other:
            p=self.root/'.cache/evidence061';p.symlink_to(other,target_is_directory=True)
            with self.assertRaises(DocumentError):save_bundle(self.root,'EXM',bundle())

class ReaderQualityIntegrationTests(unittest.TestCase):
    def test_same_single_search_does_not_erase_candidate_on_withhold(self):
        out=parse_quality_outlook(quality_raw(opened=False),'catalysts',context());c=out['items'][0]
        self.assertEqual(out['usage']['search_calls'],1);self.assertEqual(out['usage']['other_web_actions'],0)
        self.assertIsNone(c['event_date']);self.assertEqual(c['date_candidate']['event_date'],'2026-11-17');self.assertEqual(c['bucket'],'UNKNOWN')
    def test_actual_server_passage_links_date_with_no_fake_open(self):
        d=linked_doc();r=parse_quality_outlook(quality_raw(d,opened=False),'catalysts',context(),bundle())
        self.assertEqual(r['items'][0]['event_date'],'2026-11-17');self.assertEqual(r['items'][0]['schedule_trace'],'LOCAL_TEXT_AND_DATE_LINKED')
        self.assertFalse(r['sources'][0]['open_action_recorded']);self.assertEqual(r['document_checks'][0]['trace_status'],'LOCAL_TEXT_PROVIDED');self.assertEqual(r['usage']['other_web_actions'],0)
    def test_local_url_need_not_appear_in_search_results(self):
        d=linked_doc();r=parse_quality_outlook(raw(d,tool_urls=[]),'catalysts',context(),bundle())
        self.assertEqual(r['items'][0]['event_date'],'2026-11-17');self.assertEqual(r['sources'][0]['validation'],'SERVER_TEXT_URL_MATCH_ONLY')
    def test_different_date_in_actual_text_stays_unknown(self):
        r=parse_quality_outlook(quality_raw(linked_doc(),opened=False),'catalysts',context(),bundle('Next call November 18, 2026.'))
        self.assertIsNone(r['items'][0]['event_date'])
    def test_wrong_passage_id_stays_unknown(self):
        d=linked_doc();d['catalysts'][0]['schedule_evidence']['locator']='d2.p15.s1'
        r=parse_quality_outlook(quality_raw(d,opened=False),'catalysts',context(),bundle());self.assertIsNone(r['items'][0]['event_date'])
    def test_wrong_document_url_stays_unknown(self):
        r=parse_quality_outlook(quality_raw(linked_doc(),opened=False),'catalysts',context(),bundle(url='https://www.example.com/different'))
        self.assertIsNone(r['items'][0]['event_date'])
    def test_old_bundle_does_not_verify_date(self):
        b=bundle();b['generated_at']=(datetime.now(timezone.utc)-timedelta(days=1)).isoformat()
        r=parse_quality_outlook(quality_raw(linked_doc(),opened=False),'catalysts',context(),b);self.assertIsNone(r['items'][0]['event_date'])
    def test_free_text_included_in_same_request_not_second_call(self):
        body=quality_request_body(context(),'catalysts','gpt-5-mini',evidence=bundle());data=json.loads(body['input'])
        self.assertIn('November 17',data['server_extracted_text']['documents'][0]['passages'][0]['text']);self.assertEqual(len(body['tools']),1)
    def test_risk_request_never_receives_catalyst_bundle(self):
        body=quality_request_body(context(),'risks','gpt-5-mini',evidence=bundle());self.assertIsNone(json.loads(body['input'])['server_extracted_text'])
    def test_model_claim_of_local_bundle_cannot_bypass(self):
        d=linked_doc();d['catalysts'][0]['schedule_evidence']['locator']='I read the document'
        r=parse_quality_outlook(quality_raw(d,opened=False),'catalysts',context());self.assertIsNone(r['items'][0]['event_date'])

class EvidenceEndpointTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.root=Path(self.tmp.name);self.svc=seed_db(self.root)
        self.rp=patch.object(main,'ROOT',self.root);self.sp=patch.object(main,'research',self.svc);self.rp.start();self.sp.start();self.client=TestClient(main.app)
        self.headers={'X-SignalDesk-AI':self.svc.csrf_token}
    def tearDown(self):self.rp.stop();self.sp.stop();self.tmp.cleanup()
    def test_helper_page_requires_no_key(self):
        with patch('app.research.read_settings',side_effect=AssertionError('key read')):
            r=self.client.get('/evidence')
        self.assertEqual(r.status_code,200);self.assertIn('OpenAI 호출 0회',r.text);self.assertIn('frame-ancestors',r.headers['content-security-policy'])
    def test_sources_get_neither_ai_nor_external_fetch(self):
        with patch('app.research.call_openai') as ai,patch('app.document_reader.fetch_document') as fetch:
            r=self.client.get('/api/v1/evidence/sources?symbol=EXM')
        self.assertEqual(r.status_code,200);ai.assert_not_called();fetch.assert_not_called();self.assertEqual(r.json()['api_calls'],0)
    def test_consent_and_token_required(self):
        with patch('app.evidence_store.inspect_sources') as read:
            self.assertEqual(self.client.post('/api/v1/evidence/read',json={'symbol':'EXM','allow_public_fetch':True}).status_code,403)
            self.assertEqual(self.client.post('/api/v1/evidence/read',headers=self.headers,json={'symbol':'EXM'}).status_code,400)
        read.assert_not_called()
    def test_external_origin_rejected(self):
        r=self.client.post('/api/v1/evidence/read',headers={**self.headers,'Origin':'https://evil.example'},json={'symbol':'EXM','allow_public_fetch':True});self.assertEqual(r.status_code,403)
    def test_post_cannot_receive_arbitrary_url(self):
        r=self.client.post('/api/v1/evidence/read',headers=self.headers,json={'symbol':'EXM','allow_public_fetch':True,'url':'https://127.0.0.1'});self.assertEqual(r.status_code,422)
    def test_free_post_does_not_reserve_paid_attempt(self):
        with patch('app.evidence_store.inspect_sources',return_value=bundle()) as read,patch.object(self.svc,'_reserve_attempt') as reserve,patch('app.research.call_openai') as call:
            r=self.client.post('/api/v1/evidence/read',headers=self.headers,json={'symbol':'EXM','allow_public_fetch':True})
        self.assertEqual(r.status_code,200);reserve.assert_not_called();call.assert_not_called();self.assertFalse(self.svc._active.locked())
    def test_failed_fetch_unlocks(self):
        with patch('app.evidence_store.inspect_sources',side_effect=DocumentError('NO_CACHED_DOCUMENT_LEADS')):
            r=self.client.post('/api/v1/evidence/read',headers=self.headers,json={'symbol':'EXM','allow_public_fetch':True})
        self.assertEqual(r.status_code,422);self.assertFalse(self.svc._active.locked())
    def test_busy_rejects_reader_without_stopping_other_work(self):
        self.svc._active.acquire()
        try:self.assertEqual(self.client.post('/api/v1/evidence/read',headers=self.headers,json={'symbol':'EXM','allow_public_fetch':True}).status_code,409)
        finally:self.svc._active.release()

class ReaderPaidServiceTests(unittest.TestCase):
    def test_existing_single_paid_call_receives_previously_fetched_text(self):
        with tempfile.TemporaryDirectory() as temp:
            root=Path(temp);svc=seed_db(root)
            (root/'.env.signaldesk').write_text('OPENAI_API_KEY=sk-fixture-'+('x'*40))
            save_bundle(root,'EXM',bundle());token=svc.snapshots.add(snapshot())
            with patch.object(svc,'outlook_context',return_value=context()),patch('app.research.call_openai',return_value=quality_raw(linked_doc(),opened=False)) as call,patch('app.document_reader.fetch_document') as fetch:
                result=svc.analyze_outlook(token,'catalysts',True,True)
            self.assertEqual(call.call_count,1);fetch.assert_not_called()
            self.assertTrue(result['local_evidence_supplied']);self.assertEqual(result['items'][0]['event_date'],'2026-11-17')
            self.assertIn('November 17',call.call_args.args[1]['input'])
            with svc._db() as db:self.assertEqual(db.execute('SELECT SUM(n) FROM attempts').fetchone()[0],1)
    def test_parser_child_gets_no_credential_environment(self):
        import subprocess
        real_run=subprocess.run
        seen=[]
        def wrapped(*args,**kwargs):
            seen.append(kwargs.get('env',{}));return real_run(*args,**kwargs)
        with patch.dict('os.environ',{'OPENAI_API_KEY':'DO_NOT_FORWARD','AWS_SECRET_ACCESS_KEY':'DO_NOT_FORWARD'}),patch('app.document_reader.subprocess.run',side_effect=wrapped):
            parse_isolated({'bytes':b'Next call November 17.','mime':'text/plain'})
        self.assertNotIn('OPENAI_API_KEY',seen[0]);self.assertNotIn('AWS_SECRET_ACCESS_KEY',seen[0])

if __name__=='__main__':unittest.main()
