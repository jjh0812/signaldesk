"""Offline local import checks, including an extract from the user's actual JSON.
No actual SEC/Yahoo/OpenAI request is performed. Fixture has no market price;
223.67/2026-09-09 below reproduces the user's prior SCREENSHOT, not a live quote.
"""
import copy,json,tempfile,unittest
from datetime import date,datetime,timezone
from pathlib import Path
from unittest.mock import patch
from fastapi import FastAPI
from fastapi.testclient import TestClient
from fastapi.responses import JSONResponse
from app.local_financials import (LocalImportRequest,import_bundle,validated_bundle,strict_json,
    displayed_pack,MAX_REQUEST_BYTES,MAX_BUNDLE_BYTES)
from app.fundamentals import FundamentalsStore,FundamentalsError
from app.valuation import CalculateRequest,defaults,calculate
from app.valuation_api import install_routes
from app.research import ResearchService,ResearchError
from app.decision import DecisionService

DATA=json.loads((Path(__file__).parent/'fixtures/sec_local_nvda072.json').read_text())
TODAY=date(2026,9,10)
QUOTE={'close':223.67,'date':'2026-09-09','currency':'USD','basis':'PROVIDER_CLOSE_NO_DIVIDEND_ADJUSTMENT','splits':[],
       'source':'USER SCREENSHOT REGRESSION INPUT, NOT LIVE PRICE'}

def body(data=None,**kw):
    return {'symbol':'NVDA','bundle_text':json.dumps(DATA if data is None else data),
            'allow_local_import':True,'quote_mode':'SAVED',**kw}

def snapshot(root):
    return {p.relative_to(root).as_posix():p.read_bytes() for p in root.rglob('*') if p.is_file()}

class ImportTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.root=Path(self.tmp.name);self.store=FundamentalsStore(self.root)
        self.store.save('quote-NVDA.json',{'symbol':'NVDA','quote':QUOTE,'generated_at':'2026-09-10T01:00:00+00:00'})
        self.net=patch.object(FundamentalsStore,'get_json',side_effect=AssertionError('NO SEC NETWORK'));self.net.start()
        self.y=patch('app.fundamentals.yahoo_completed_quote',side_effect=AssertionError('NO YAHOO NETWORK'));self.y.start()
        self.ai=patch.object(DecisionService,'analyze',side_effect=AssertionError('NO PAID AI'));self.ai.start()
    def tearDown(self):
        self.ai.stop();self.y.stop();self.net.stop();self.tmp.cleanup()
    def run_import(self,data=None,**kw):
        return import_bundle(self.store,LocalImportRequest(**body(data,**kw)),today=TODAY)
    def test_real_file_identity_and_complete_input(self):
        r=self.run_import();self.assertEqual(r['status'],'READY_FOR_REVIEW');self.assertEqual(r['cik'],'1045810');self.assertEqual(r['input']['input_kind'],'SEC_LOCAL')
    def test_real_revenue_ttm_exact_period_and_operands(self):
        r=self.run_import()['facts']['revenue'];self.assertEqual(r['value'],215938+177837-90805)
        self.assertEqual((r['period_start'],r['period_end']),('2025-07-28','2026-07-26'))
        self.assertEqual([a['sign'] for a in r['facts']],[1,1,-1])
    def test_source_difference_is_disclosed_not_rewritten(self):
        r=self.run_import();c=r['source_consistency']['revenue']
        self.assertEqual(c['selected_ttm'],302970);self.assertEqual(c['four_quarter_sum'],302969)
        self.assertEqual(c['status'],'SOURCE_DIFFERENCE');self.assertEqual(r['input']['revenue'],302970)
        self.assertEqual(r['source_consistency']['operating_income']['status'],'MATCH')
        self.assertTrue(any('차이' in w for w in r['warnings']))
    def test_real_income_ttm(self):
        r=self.run_import()['input'];self.assertEqual(r['operating_income'],130387+117270-50078);self.assertEqual(r['net_income'],120067+118010-45197)
    def test_real_cash_debt_shares_and_dates(self):
        r=self.run_import();self.assertEqual([r['input'][k] for k in ['cash','debt','shares']],[22443,33366,24100]);self.assertEqual(r['facts']['shares']['period_end'],'2026-08-21')
        self.assertEqual([x['tag'] for x in r['facts']['debt']['facts']],['LongTermDebtCurrent','LongTermDebtNoncurrent'])
    def test_capex_missing_not_zero_or_broader_assets_alias(self):
        r=self.run_import();self.assertIsNone(r['input']['capex']);self.assertEqual(r['supplemental_facts']['productive_assets_spend']['value'],7354)
    def test_operating_leases_not_silently_added_to_debt(self):
        r=self.run_import();self.assertEqual(r['supplemental_facts']['operating_lease_liability']['value'],5494);self.assertEqual(r['input']['debt'],33366)
    def test_cash_not_added_to_debt_security_investments(self):
        self.assertEqual(self.run_import()['input']['cash'],22443)
    def test_valuation_review_flags_remain_false(self):
        r=self.run_import();f=r['input'];self.assertFalse(f['share_basis_checked']);self.assertFalse(f['claims_checked'])
        calc=calculate(CalculateRequest(financials=f,assumptions=defaults(f['operating_income']/f['revenue'])),today=TODAY)
        self.assertEqual(calc['verdict'],'ASSUMPTIONS_UNREVIEWED');self.assertFalse(calc['decision_ready'])
    def test_file_import_does_not_rewrite_online_cache_credentials_or_quotes(self):
        self.store.save('NVDA.json',{'old':'remote source'});self.store.save('fetch-diagnostic-NVDA.json',{'result':'FAILED','error_code':'SEC_HTTP_403'})
        self.store.save('sec_contact.json',{'email':'private@example.test'})
        (self.root/'.env.signaldesk').write_text('PRIVATE KEY SENTINEL')
        p=self.root/'.cache/research/research.sqlite3';p.parent.mkdir(parents=True);p.write_bytes(b'STORED RESEARCH AND QUOTA')
        before=snapshot(self.root);r=self.run_import();after=snapshot(self.root)
        self.assertTrue(all(after[k]==v for k,v in before.items()));self.assertEqual(set(after)-set(before),{'.cache/valuation07/local-NVDA.json'})
        result=json.dumps(r);self.assertNotIn('private@example.test',result);self.assertNotIn('PRIVATE KEY',result)
    def test_no_contact_file_required(self):
        with patch.object(FundamentalsStore,'contact',side_effect=AssertionError('Do not read contact for local import')):
            self.assertEqual(self.run_import()['external_requests'],0)
    def test_success_no_network_counters(self):
        r=self.run_import();self.assertEqual(r['retrieval']['sec_request_count'],0);self.assertEqual(r['openai_calls'],0);self.assertFalse(r['source_verified_online'])
    def test_without_consent_no_write(self):
        before=snapshot(self.root)
        with self.assertRaises(FundamentalsError):self.run_import(allow_local_import=False)
        self.assertEqual(snapshot(self.root),before)
    def test_wrong_symbol_and_cik_rejected_without_write(self):
        for mutation in ['symbol','cik','tickers']:
            d=copy.deepcopy(DATA)
            if mutation=='symbol':d['symbol']='OTHER'
            elif mutation=='cik':d['companyfacts']['cik']=123
            else:d['submission']['tickers']=['OTHER']
            with self.subTest(mutation=mutation),self.assertRaises(FundamentalsError):self.run_import(d)
        self.assertIsNone(self.store.read('local-NVDA.json'))
    def test_multiple_share_classes_and_financial_industry_rejected(self):
        for kwargs in [{'tickers':['NVDA','OTHER']},{'sic':'6020'}]:
            d=copy.deepcopy(DATA);d['submission'].update(kwargs)
            with self.subTest(kwargs=kwargs),self.assertRaises(FundamentalsError):self.run_import(d)
    def test_missing_sic_is_not_assumed_nonfinancial(self):
        d=copy.deepcopy(DATA);d['submission'].pop('sic')
        with self.assertRaises(FundamentalsError):self.run_import(d)
    def test_companyfacts_only_not_sufficient_identity(self):
        with self.assertRaises(FundamentalsError):self.run_import(DATA['companyfacts'])
    def test_submissions_only_or_source_read_report_rejected(self):
        for d in [DATA['submission'],{'schema':'document-reader-0.6.1'}]:
            with self.assertRaises(FundamentalsError):self.run_import(d)
    def test_missing_saved_price_requires_manual_no_fallback(self):
        self.store._path('quote-NVDA.json').unlink()
        with self.assertRaises(FundamentalsError) as e:self.run_import()
        self.assertEqual(e.exception.code,'LOCAL_QUOTE_REQUIRED')
    def test_manual_quote_keeps_manual_provenance(self):
        self.store._path('quote-NVDA.json').unlink()
        r=self.run_import(quote_mode='MANUAL',manual_quote={'close':200,'date':'2026-09-09'})
        self.assertEqual(r['quote']['basis'],'USER_ENTERED_UNADJUSTED_CLOSE');self.assertEqual(r['input']['price'],200)
    def test_future_quote_rejected(self):
        with self.assertRaises(FundamentalsError):self.run_import(quote_mode='MANUAL',manual_quote={'close':200,'date':'2026-09-11'})
    def test_adjusted_quote_not_used(self):
        self.store.save('quote-NVDA.json',{'symbol':'NVDA','quote':dict(QUOTE,basis='ADJUSTED_CLOSE')})
        with self.assertRaises(FundamentalsError):self.run_import()
    def test_old_quote_not_labeled_fresh_and_no_network_retry(self):
        r=import_bundle(self.store,LocalImportRequest(**body()),today=date(2026,10,1))
        self.assertEqual(r['quote']['date'],'2026-09-09');self.assertTrue(any('7일' in w for w in r['warnings']))
    def test_disclosures_after_price_cutoff_not_used(self):
        r=self.run_import(quote_mode='MANUAL',manual_quote={'close':200,'date':'2026-08-25'})
        self.assertEqual(r['input']['period_end'],'2026-04-26')
        self.assertTrue(all(row['filed']<='2026-08-25' for m in r['facts'].values() if m for row in m['facts']))
    def test_missing_metric_stays_none(self):
        d=copy.deepcopy(DATA);d['companyfacts']['facts']['us-gaap'].pop('CashAndCashEquivalentsAtCarryingValue')
        r=self.run_import(d);self.assertIsNone(r['input']['cash']);self.assertIn('cash',r['missing'])
    def test_declared_split_after_shares_requires_review(self):
        self.store.save('quote-NVDA.json',{'symbol':'NVDA','quote':dict(QUOTE,splits=[{'date':'2026-09-01','ratio':2}])})
        r=self.run_import();self.assertIn('split_since_share_count',r['missing'])
    def test_invalid_data_shapes_and_values_rejected(self):
        for key,value in [('units',[]),('units',{'USD':'bad'})]:
            d=copy.deepcopy(DATA);d['companyfacts']['facts']['us-gaap']['Revenues'][key]=value
            with self.assertRaises(FundamentalsError):self.run_import(d)
        for v in [None,'100',True,float('nan'),float('inf')]:
            d=copy.deepcopy(DATA);d['companyfacts']['facts']['us-gaap']['Revenues']['units']['USD'][0]['val']=v
            with self.assertRaises(FundamentalsError):self.run_import(d)
    def test_duplicate_json_keys_do_not_silently_overwrite(self):
        with self.assertRaises(FundamentalsError):strict_json('{"cik":1,"cik":2}')
    def test_conflicting_same_disclosure_not_arbitrarily_chosen(self):
        d=copy.deepcopy(DATA);rows=d['companyfacts']['facts']['us-gaap']['Revenues']['units']['USD'];rows.append(dict(rows[-1],val=1))
        with self.assertRaises(FundamentalsError) as e:self.run_import(d)
        self.assertEqual(e.exception.code,'LOCAL_FACT_CONFLICT')
    def test_oversize_bundle_rejected_before_read(self):
        with self.assertRaises(FundamentalsError):validated_bundle(' '* (MAX_BUNDLE_BYTES+1),'NVDA')
    def test_utf8_bom_accepted(self):
        r=import_bundle(self.store,LocalImportRequest(**body(bundle_text='\ufeff'+json.dumps(DATA))),today=TODAY)
        self.assertEqual(r['input']['revenue'],302970)
    def test_no_key_or_path_in_safe_error(self):
        with self.assertRaises(FundamentalsError) as e:validated_bundle('PRIVATE SENTINEL .env.signaldesk','NVDA')
        self.assertNotIn('PRIVATE SENTINEL',e.exception.message)
    def test_latest_display_uses_local_without_changing_remote(self):
        self.store.save('NVDA.json',{'symbol':'NVDA','input':{},'generated_at':'2020-01-01T00:00:00+00:00'})
        self.run_import();self.assertEqual(displayed_pack(self.store,'NVDA')['input']['input_kind'],'SEC_LOCAL')
    def test_failed_import_preserves_prior_valid_local_pack(self):
        before=self.run_import();d=copy.deepcopy(DATA);d['symbol']='OTHER'
        with self.assertRaises(FundamentalsError):self.run_import(d)
        self.assertEqual(self.store.read('local-NVDA.json'),before)

class ImportAPITests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.root=Path(self.tmp.name);self.research=ResearchService(self.root);app=FastAPI()
        @app.exception_handler(ResearchError)
        async def err(request,exc):return JSONResponse(status_code=exc.status,content={'error':{'code':exc.code,'message':exc.message}})
        install_routes(app,self.root,self.research);self.client=TestClient(app);self.headers={'X-SignalDesk-AI':self.research.csrf_token}
        self.store=FundamentalsStore(self.root);self.store.save('quote-NVDA.json',{'symbol':'NVDA','quote':QUOTE})
    def tearDown(self):self.client.close();self.tmp.cleanup()
    def post(self,payload=None,**kwargs):return self.client.post('/api/v1/decision/local-financials',json=body() if payload is None else payload,headers=kwargs.get('headers',self.headers))
    def test_real_input_api_import_then_calculation(self):
        with patch.object(FundamentalsStore,'get_json',side_effect=AssertionError('NO NETWORK')),patch.object(DecisionService,'analyze',side_effect=AssertionError('NO AI')):
            r=self.post();self.assertEqual(r.status_code,200,r.text[:300]);pack=r.json()
            cb={'financials':pack['input'],'assumptions':defaults(pack['input']['operating_income']/pack['input']['revenue'])}
            c=self.client.post('/api/v1/decision/calculate',json=cb,headers=self.headers)
            self.assertEqual(c.status_code,200,c.text[:200]);self.assertFalse(c.json()['decision_ready']);self.assertEqual(c.json()['financials']['input_kind'],'SEC_LOCAL')
    def test_state_reads_import_without_remote_fetch(self):
        self.post()
        with patch.object(FundamentalsStore,'load',side_effect=AssertionError('NO REMOTE')):
            r=self.client.get('/api/v1/decision/state?symbol=NVDA').json();self.assertEqual(r['financial_pack']['input']['input_kind'],'SEC_LOCAL')
    def test_csrf_and_cross_origin_blocked(self):
        self.assertEqual(self.post(headers={}).status_code,403)
        self.assertEqual(self.post(headers={**self.headers,'Origin':'https://evil.example'}).status_code,403)
    def test_missing_consent_400(self):self.assertEqual(self.post(body(allow_local_import=False)).status_code,400)
    def test_content_type_and_length_limit(self):
        r=self.client.post('/api/v1/decision/local-financials',content='{}',headers=self.headers);self.assertEqual(r.status_code,415)
        r=self.client.post('/api/v1/decision/local-financials',content='{}',headers={**self.headers,'Content-Type':'application/json','Content-Length':str(MAX_REQUEST_BYTES+1)});self.assertEqual(r.status_code,413)
    def test_wrong_field_schema_never_echoes_private_input(self):
        b=body();b['unexpected_private_field']='DONT ECHO ME';r=self.post(b);self.assertEqual(r.status_code,422);self.assertNotIn('DONT ECHO ME',r.text);self.assertNotIn('bundle_text',r.text)
    def test_bad_json_releases_busy_lock(self):
        r=self.post(body(bundle_text='not-json'));self.assertEqual(r.status_code,422);self.assertFalse(self.research._active.locked())
    def test_busy_stops_without_overwrite(self):
        self.research._active.acquire()
        try:self.assertEqual(self.post().status_code,409)
        finally:self.research._active.release()
    def test_edited_value_is_labeled_user(self):
        p=self.post().json();f=p['input'];f['revenue']+=1
        r=self.client.post('/api/v1/decision/calculate',json={'financials':f,'assumptions':defaults(.6)},headers=self.headers)
        self.assertEqual(r.status_code,200);self.assertEqual(r.json()['financials']['input_kind'],'USER')
    def test_modified_optional_value_not_misrepresented_local(self):
        p=self.post().json();p['input']['capex']=100
        r=self.client.post('/api/v1/decision/calculate',json={'financials':p['input'],'assumptions':defaults(.6)},headers=self.headers)
        self.assertEqual(r.json()['financials']['input_kind'],'USER')
    def test_unsupported_data_no_persist(self):
        d=copy.deepcopy(DATA);d['submission']['sic']='6020';r=self.post(body(d));self.assertEqual(r.status_code,422);self.assertIsNone(self.store.read('local-NVDA.json'))

if __name__=='__main__':unittest.main(verbosity=2)
