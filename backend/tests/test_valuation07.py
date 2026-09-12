"""Synthetic, offline tests. No real company price/forecast is asserted here."""
import copy,json,math,tempfile,unittest
from pathlib import Path
from datetime import date,datetime,timedelta,timezone
from unittest.mock import patch
from pydantic import ValidationError
from fastapi import FastAPI
from fastapi.testclient import TestClient
from fastapi.responses import JSONResponse
from app.valuation import FinancialInput,Assumptions,Scenario,CalculateRequest,defaults,calculate as production_calculate,project,reverse_growth,multiples,compare_peers
from app.fundamentals import observations,ttm,instant,debt_at,assemble,FundamentalsError,FundamentalsStore
from app.decision import parse,request_body,context,DecisionService,initial_impact
from app.valuation_api import install_routes
from app.research import ResearchService,ResearchError

from valuation_clock_fixture import MARKET_DAY, FixedDateTime

# Offline tests share a fixed market date; their success must not depend on
# whether the installer runs after midnight in Korea but before midnight in NY.
TODAY=MARKET_DAY

def calculate(request, *, today=TODAY):
    return production_calculate(request, today=today)
def fin(**kw):
    x=dict(symbol='EXM',price=100,price_date=TODAY,period_end=TODAY-timedelta(days=60),revenue=10000,operating_income=2000,cash=1000,debt=1000,shares=300,net_income=1500,sic='3674',share_basis_checked=True,claims_checked=True)
    return FinancialInput(**(x|kw))
def ass(**kw):return Assumptions(**(defaults(.2)|{'reviewed':True}|kw))
def req(**kw):return CalculateRequest(financials=fin(**kw),assumptions=ass())
class ValuationMathTests(unittest.TestCase):
    def test_manual_fcff_identity(self):
        r=project(fin(),ass(),Scenario(name='기준',growth=.10,target_margin=.2));row=r['rows'][0]
        self.assertAlmostEqual(row['revenue'],11000);self.assertAlmostEqual(row['nopat'],1738);self.assertAlmostEqual(row['reinvestment'],1000/3);self.assertAlmostEqual(row['fcff'],1738-1000/3)
    def test_enterprise_equity_bridge(self):
        r=project(fin(cash=2000,debt=500,other_claims=300),ass(),ass().scenarios[1]);self.assertAlmostEqual(r['equity_value_before_floor'],r['enterprise_value']+1200)
    def test_terminal_reinvestment_not_free_growth(self):
        a=ass();r=project(fin(),a,a.scenarios[1]);self.assertGreater(r['terminal_reinvestment'],0);self.assertAlmostEqual(r['terminal_reinvestment']/r['terminal_fcff'],(a.terminal_growth/a.terminal_roic)/(1-a.terminal_growth/a.terminal_roic))
    def test_value_independent_of_observed_price(self):
        self.assertAlmostEqual(calculate(req(price=40))['base']['fair_value'],calculate(req(price=90))['base']['fair_value'])
    def test_price_changes_reverse_not_intrinsic(self):self.assertNotEqual(calculate(req(price=40))['reverse']['growth'],calculate(req(price=90))['reverse']['growth'])
    def test_reverse_round_trip(self):
        a=ass();p=project(fin(),a,Scenario(name='기준',growth=.234,target_margin=.2))['fair_value'];self.assertAlmostEqual(reverse_growth(fin(price=p),a)['growth'],.234,places=6)
    def test_reverse_unreachable_is_unknown(self):
        r=reverse_growth(fin(price=1e7),ass());self.assertEqual(r['status'],'OUTSIDE_SEARCH_RANGE');self.assertIsNone(r['growth'])
    def test_double_shares_halves_per_share_value(self):self.assertAlmostEqual(calculate(req(shares=600))['base']['fair_value']*2,calculate(req())['base']['fair_value'])
    def test_higher_discount_lowers_value(self):self.assertLess(project(fin(),ass(discount_rate=.15),ass().scenarios[1])['fair_value'],project(fin(),ass(),ass().scenarios[1])['fair_value'])
    def test_reinvestment_efficiency_matters(self):self.assertGreater(project(fin(),ass(sales_to_capital=6),ass().scenarios[1])['fair_value'],project(fin(),ass(sales_to_capital=2),ass().scenarios[1])['fair_value'])
    def test_shrinkage_does_not_monetize_assets(self):self.assertTrue(all(r['reinvestment']==0 for r in project(fin(),ass(),Scenario(name='보수',growth=-.1,target_margin=.2))['rows']))
    def test_equity_floor_preserves_negative_bridge(self):
        r=calculate(req(debt=1e9))['base'];self.assertEqual(r['fair_value'],0);self.assertLess(r['equity_value_before_floor'],0)
    def test_unreviewed_no_verdict(self):self.assertFalse(calculate(CalculateRequest(financials=fin(),assumptions=ass(reviewed=False)))['decision_ready'])
    def test_share_review_required(self):self.assertEqual(calculate(req(share_basis_checked=False))['verdict'],'ASSUMPTIONS_UNREVIEWED')
    def test_claims_review_required(self):self.assertEqual(calculate(req(claims_checked=False))['verdict'],'ASSUMPTIONS_UNREVIEWED')
    def test_stale_price_no_verdict(self):self.assertEqual(calculate(req(price_date=TODAY-timedelta(days=10)))['verdict'],'STALE_DATA')
    def test_stale_financial_no_verdict(self):self.assertEqual(calculate(req(period_end=TODAY-timedelta(days=250)))['verdict'],'STALE_DATA')
    def test_future_price_rejected(self):
        with self.assertRaises(ValueError):calculate(req(price_date=TODAY+timedelta(days=1)))
    def test_near_base_ui_rule(self):
        p=calculate(req())['base']['fair_value'];self.assertEqual(calculate(req(price=p))['verdict'],'NEAR_BASE_VALUE')
    def test_references_missing_not_zero(self):self.assertEqual([x['status'] for x in calculate(req())['references']],['NOT_AVAILABLE']*2)
    def test_after_price_reference_not_priced_in(self):
        ref=dict(kind='CONSENSUS',value=12000,period_start=TODAY.isoformat(),period_end=(TODAY+timedelta(days=365)).isoformat(),published_date=(TODAY+timedelta(days=1)).isoformat(),source_url='https://example.com/estimate')
        r=calculate(CalculateRequest(financials=fin(),assumptions=ass(),references=[ref]));self.assertEqual(r['references'][0]['status'],'AFTER_PRICE_DATE')
    def test_grid_dimensions(self):
        r=calculate(req())['sensitivity'];self.assertEqual(len(r['values']),len(r['discount_rates']));self.assertTrue(all(len(row)==len(r['growths']) for row in r['values']))
    def test_no_ai_math_calls_and_no_nan(self):
        r=calculate(req());self.assertEqual(r['ai_calls'],0);json.dumps(r,allow_nan=False)
    def test_cfo_capex_not_fcff(self):
        r=multiples(fin(operating_cash_flow=500,capex=900));self.assertEqual(r['cfo_minus_capex'],-400);self.assertIn('FCFF',r['fcf_note'])
    def test_negative_earnings_per_unknown(self):self.assertIsNone(multiples(fin(net_income=-5))['pe'])
    def test_bad_model_inputs_rejected(self):
        for change in [dict(shares=0),dict(price=0),dict(revenue=-1),dict(operating_income=0),dict(cash=-1),dict(price=float('nan')),dict(sic='6020')]:
            with self.subTest(change=change),self.assertRaises(ValidationError):fin(**change)
    def test_terminal_invalid_rejected(self):
        for change in [dict(discount_rate=.04,terminal_growth=.04),dict(terminal_roic=.03,terminal_growth=.03),dict(years=2)]:
            with self.subTest(change=change),self.assertRaises(ValidationError):ass(**change)
    def test_extra_input_rejected(self):
        with self.assertRaises(ValidationError):fin(secret_key='forbidden')
    def test_peer_minimum_two(self):self.assertIsNone(compare_peers(fin(),[fin(symbol='ONE')])['comparison']['pe']['median'])
    def test_peer_industry_date_gate(self):
        r=compare_peers(fin(),[fin(symbol='ONE',sic='2834'),fin(symbol='TWO',price_date=TODAY-timedelta(days=2)),fin(symbol='THR')]);self.assertEqual(sum(x['eligible'] for x in r['rows']),1)
    def test_peer_median_no_self_duplicate(self):
        r=compare_peers(fin(),[fin(symbol='ONE',price=50),fin(symbol='TWO',price=150),fin(symbol='EXM')]);self.assertEqual(r['comparison']['pe']['sample_count'],2);self.assertAlmostEqual(r['comparison']['pe']['premium'],0)

def factrow(value,start,end,filed,form='10-Q',**kw):return dict(val=value*1e6,start=start,end=end,filed=filed,form=form,accn='0000000001-26-000001',**kw)
def sec_fixture():
    facts={'cik':1,'entityName':'SYNTHETIC EXAMPLE ONLY','facts':{'us-gaap':{},'dei':{}}}
    def settag(tag,values):facts['facts']['us-gaap'][tag]={'units':{'USD':values}}
    for tag,m in [('RevenueFromContractWithCustomerExcludingAssessedTax',1),('OperatingIncomeLoss',.2),('NetIncomeLoss',.15),('NetCashProvidedByUsedInOperatingActivities',.25),('PaymentsToAcquirePropertyPlantAndEquipment',.05)]:
        settag(tag,[factrow(100*m,'2025-01-01','2025-12-31','2026-02-01','10-K'),factrow(45*m,'2025-01-01','2025-06-30','2025-08-01'),factrow(60*m,'2026-01-01','2026-06-30','2026-08-01')])
    for tag,v in [('CashAndCashEquivalentsAtCarryingValue',20),('LongTermDebtCurrentAndNoncurrent',30),('LongTermDebtCurrent',5),('LongTermDebtNoncurrent',25),('ShortTermBorrowings',2)]:
        settag(tag,[dict(val=v*1e6,end='2026-06-30',filed='2026-08-01',form='10-Q',accn='0000000001-26-000001')])
    facts['facts']['dei']['EntityCommonStockSharesOutstanding']={'units':{'shares':[dict(val=2e6,end='2026-07-25',filed='2026-08-01',form='10-Q')]}}
    return facts
CUTOFF=date(2026,9,8)
class FundamentalsTests(unittest.TestCase):
    def test_ttm_fy_plus_ytd_minus_prior(self):
        r=ttm(sec_fixture(),['RevenueFromContractWithCustomerExcludingAssessedTax'],CUTOFF,1);self.assertEqual(r['value'],115);self.assertEqual(r['method'],'FY_PLUS_YTD_MINUS_PRIOR_YTD');self.assertEqual([x['sign'] for x in r['facts']],[1,1,-1])
    def test_not_sum_ytd_periods(self):self.assertNotEqual(ttm(sec_fixture(),['RevenueFromContractWithCustomerExcludingAssessedTax'],CUTOFF,1)['value'],205)
    def test_future_filing_excluded(self):
        f=sec_fixture();row=f['facts']['us-gaap']['OperatingIncomeLoss']['units']['USD'][-1];row['val']=999e6;row['filed']='2026-09-20';self.assertIsNone(ttm(f,['OperatingIncomeLoss'],CUTOFF,1,'2026-06-30'))
    def test_latest_restated_at_cutoff(self):
        f=sec_fixture();rows=f['facts']['us-gaap']['OperatingIncomeLoss']['units']['USD'];rows.append(dict(rows[-1],val=20e6,filed='2026-09-01',form='10-Q/A'));self.assertEqual(ttm(f,['OperatingIncomeLoss'],CUTOFF,1)['value'],31)
    def test_missing_prior_ytd_not_invented(self):
        f=sec_fixture();f['facts']['us-gaap']['OperatingIncomeLoss']['units']['USD'].pop(1);self.assertIsNone(ttm(f,['OperatingIncomeLoss'],CUTOFF,1,'2026-06-30'))
    def test_wrong_currency_ignored(self):
        f=sec_fixture();u=f['facts']['us-gaap']['OperatingIncomeLoss']['units'];u['EUR']=u.pop('USD');self.assertIsNone(ttm(f,['OperatingIncomeLoss'],CUTOFF,1))
    def test_instant_not_weighted_shares(self):
        f=sec_fixture();f['facts']['dei']['EntityCommonStockSharesOutstanding']['units']['shares'][0]['start']='2026-01-01';self.assertIsNone(instant(f,['EntityCommonStockSharesOutstanding'],'shares',CUTOFF,1,namespace='dei'))
    def test_debt_total_not_double_count_components(self):self.assertEqual(debt_at(sec_fixture(),CUTOFF,1,'2026-06-30')['value'],32)
    def test_debt_components_when_no_total(self):
        f=sec_fixture();del f['facts']['us-gaap']['LongTermDebtCurrentAndNoncurrent'];self.assertEqual(debt_at(f,CUTOFF,1,'2026-06-30')['value'],32)
    def test_missing_debt_unknown_not_zero(self):
        f=sec_fixture();f['facts']['us-gaap']={k:v for k,v in f['facts']['us-gaap'].items() if 'Debt' not in k and 'Borrow' not in k};self.assertIsNone(debt_at(f,CUTOFF,1,'2026-06-30'))
    def pack(self,f=None,s=None,q=None):return assemble(f or sec_fixture(),s or {'tickers':['EXM'],'sic':'3674'},q or {'date':'2026-09-08','close':20,'splits':[]},'EXM',CUTOFF)
    def test_assemble_aligned_periods_and_units(self):
        p=self.pack();self.assertEqual(p['input']['revenue'],115);self.assertEqual(p['input']['shares'],2);self.assertEqual(p['input']['operating_income'],23);self.assertEqual(p['api_calls'],0)
    def test_foreign_symbol_rejected(self):
        with self.assertRaises(FundamentalsError):self.pack(s={'tickers':['OTHER'],'sic':'3674'})
    def test_multiple_classes_rejected(self):
        with self.assertRaises(FundamentalsError):self.pack(s={'tickers':['EXM','EXMB'],'sic':'3674'})
    def test_bank_rejected(self):
        with self.assertRaises(FundamentalsError):self.pack(s={'tickers':['EXM'],'sic':'6020'})
    def test_split_mismatch_flagged(self):self.assertIn('split_since_share_count',self.pack(q={'date':'2026-09-08','close':20,'splits':[{'date':'2026-08-10','ratio':10}]})['missing'])
    def test_no_silent_consensus(self):self.assertEqual(self.pack()['consensus']['status'],'NOT_AVAILABLE')
    def test_source_provenance(self):self.assertIn('/Archives/edgar/data/1/',self.pack()['facts']['revenue']['facts'][0]['url'])
    def test_contact_not_exposed_in_status(self):
        with tempfile.TemporaryDirectory() as tmp:
            s=FundamentalsStore(Path(tmp));s.set_contact('test@example.com');self.assertNotIn('test@example.com',json.dumps(s.status()));self.assertTrue(s.status()['contact_configured'])
    def test_injected_contact_rejected(self):
        with tempfile.TemporaryDirectory() as tmp:
            s=FundamentalsStore(Path(tmp));s.save('sec_contact.json',{'email':'bad@example.com\r\nInjected: yes'});self.assertFalse(s.contact())
    def test_remote_url_not_arbitrary(self):
        with tempfile.TemporaryDirectory() as tmp:
            s=FundamentalsStore(Path(tmp))
            for url in ['https://127.0.0.1/key','https://data.sec.gov/submissions/CIK/../../private','https://www.sec.gov/files/company_tickers.json?x']:
                with self.subTest(url=url),self.assertRaises(FundamentalsError):s.get_json(url)
    def test_cached_load_no_network(self):
        with tempfile.TemporaryDirectory() as tmp:
            s=FundamentalsStore(Path(tmp));s.save('EXM.json',self.pack())
            with patch.object(s,'get_json',side_effect=AssertionError('NO NETWORK')):self.assertTrue(s.load('EXM')['cache_hit'])

def context_fixture():
    return {'symbol':'EXM','context_hash':'fixture-only','events':[dict(event_id='local-exm',title='Example earnings call',category='EARNINGS',source_ids=['E1'],calendar_only=True,archived=False)],'risks':[],'sources':[dict(id='E1',title='Example transcript',url='https://example.com/call',text='Our earnings call is scheduled for October 14.',basis='LOCAL_TEXT_DATE_CANDIDATE')],'research_date':TODAY.isoformat()}
def response_fixture():
    event=dict(event_id='local-exm',direction='WAITING',importance='HIGH',reason='실적 발표의 결과를 기다려야 합니다.',economic_channel='REVENUE',novelty='UNKNOWN',novelty_reason='신규 결과 없음',positive_condition='전망이 개선되는 경우',negative_condition='전망이 약해지는 경우',watch='매출과 이익률',evidence_ids=['E1'],quantification='NOT_QUANTIFIED',model_inclusion='UNKNOWN',uncertainty='결과 미확인')
    data=dict(price_reading='기준 시나리오와 조건부 성장률을 비교하세요.',market_expectation_limit='시장 예상치 미확보',next_check='다음 실적',events=[event],risks=[],assumption_review=[])
    return {'status':'completed','output':[{'type':'message','role':'assistant','phase':'final_answer','content':[{'type':'output_text','text':json.dumps(data,ensure_ascii=False)}]}]}
def modify_response(fn):
    r=response_fixture();d=json.loads(r['output'][0]['content'][0]['text']);fn(d);r['output'][0]['content'][0]['text']=json.dumps(d);return r
class DecisionTests(unittest.TestCase):
    def test_strict_schema_no_web_tools(self):
        b=request_body(context_fixture(),calculate(req()),'gpt-5-mini',{});self.assertNotIn('tools',b);self.assertTrue(b['text']['format']['strict']);self.assertFalse(b['store'])
    def test_good_response(self):self.assertEqual(parse(response_fixture(),context_fixture(),{})['events'][0]['direction'],'WAITING')
    def test_calendar_not_hype(self):
        r=parse(modify_response(lambda d:d['events'][0].update(direction='POSITIVE',reason='무조건 좋은 소식')),context_fixture(),{});self.assertEqual(r['events'][0]['direction'],'WAITING');self.assertNotIn('무조건',r['events'][0]['reason'])
    def test_conference_attendance_low_neutral(self):
        c=context_fixture();c['events'][0]['category']='CONFERENCE';x=parse(response_fixture(),c,{})['events'][0];self.assertEqual((x['direction'],x['importance']),('NEUTRAL','LOW'))
    def test_unknown_source_rejected(self):
        with self.assertRaises(ResearchError):parse(modify_response(lambda d:d['events'][0].update(evidence_ids=['E999'])),context_fixture(),{})
    def test_nested_refs_safe_failure(self):
        with self.assertRaises(ResearchError):parse(modify_response(lambda d:d['events'][0].update(evidence_ids=[{}])),context_fixture(),{})
    def test_nested_direction_safe_failure(self):
        with self.assertRaises(ResearchError):parse(modify_response(lambda d:d['events'][0].update(direction=[])),context_fixture(),{})
    def test_nested_importance_safe_failure(self):
        with self.assertRaises(ResearchError):parse(modify_response(lambda d:d['events'][0].update(importance={})),context_fixture(),{})
    def test_null_list_safe_failure(self):
        with self.assertRaises(ResearchError):parse(modify_response(lambda d:d.update(events=None)),context_fixture(),{})
    def test_nonstring_id_safe_failure(self):
        with self.assertRaises(ResearchError):parse(modify_response(lambda d:d['events'][0].update(event_id=[])),context_fixture(),{})
    def test_incomplete_no_accept(self):
        r=response_fixture();r['status']='incomplete'
        with self.assertRaises(ResearchError):parse(r,context_fixture(),{})
    def test_empty_final_no_500(self):
        with self.assertRaises(ResearchError):parse({'status':'completed','output':[]},context_fixture(),{})
    def test_user_inclusion_overrides_model_claim(self):
        r=parse(response_fixture(),context_fixture(),{'local-exm':'INCLUDED_BY_USER'});self.assertEqual(r['events'][0]['model_inclusion'],'INCLUDED_BY_USER')
    def test_archived_cannot_claim_new(self):
        c=context_fixture();c['events'][0]['archived']=True;r=parse(modify_response(lambda d:d['events'][0].update(novelty='NEW')),c,{});self.assertEqual(r['events'][0]['novelty'],'UNKNOWN')
    def test_no_source_review_insufficient(self):
        r=parse(modify_response(lambda d:d.update(assumption_review=[dict(parameter='GROWTH',judgment='SUPPORTED',reason='no source',evidence_ids=[])])),context_fixture(),{});self.assertEqual(r['assumption_review'][0]['judgment'],'INSUFFICIENT')
    def test_explicit_paid_one_then_cache_free(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);(root/'.env.signaldesk').write_text('OPENAI_API_KEY=sk-'+('x'*60)+'\nOPENAI_MODEL=gpt-5-mini\n');r=ResearchService(root);svc=DecisionService(root,r)
            with patch('app.decision.context',return_value=context_fixture()),patch('app.decision.call_openai',return_value=response_fixture()) as call:
                first=svc.analyze('EXM',req(),True,False,{},TODAY);second=svc.analyze('EXM',req(),False,False,{},TODAY)
                self.assertEqual(call.call_count,1);self.assertTrue(second['cache_hit']);self.assertEqual(first['web_search_calls'],0)
    def test_no_consent_no_attempt(self):
        with tempfile.TemporaryDirectory() as tmp:
            svc=DecisionService(Path(tmp),ResearchService(Path(tmp)))
            with patch('app.decision.context',return_value=context_fixture()),patch('app.decision.call_openai') as call:
                with self.assertRaises(ResearchError):svc.analyze('EXM',None,False,False,{},TODAY)
                call.assert_not_called()
    def test_no_valuation_no_hypothetical_target(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);(root/'.env.signaldesk').write_text('OPENAI_API_KEY=sk-'+('x'*60)+'\n');svc=DecisionService(root,ResearchService(root))
            with patch('app.decision.context',return_value=context_fixture()),patch('app.decision.call_openai',return_value=response_fixture()):self.assertIn('계산 전',svc.analyze('EXM',None,True,False,{},TODAY)['price_reading'])
    def test_keys_contact_absent_ai_payload(self):
        self.assertNotIn('sec_contact',json.dumps(request_body(context_fixture(),calculate(req()),'gpt-5-mini',{})));self.assertNotIn('OPENAI_API_KEY',json.dumps(request_body(context_fixture(),None,'gpt-5-mini',{})))

class DecisionAPITests(unittest.TestCase):
    def setUp(self):
        clock_patch=patch('app.valuation_api.datetime',FixedDateTime)
        clock_patch.start();self.addCleanup(clock_patch.stop)
        self.tmp=tempfile.TemporaryDirectory();self.root=Path(self.tmp.name);self.research=ResearchService(self.root);app=FastAPI()
        @app.exception_handler(ResearchError)
        async def err(request,exc):return JSONResponse(status_code=exc.status,content={'error':{'code':exc.code,'message':exc.message}})
        install_routes(app,self.root,self.research);self.client=TestClient(app);self.headers={'X-SignalDesk-AI':self.research.csrf_token}
    def tearDown(self):self.client.close();self.tmp.cleanup()
    def test_get_state_no_network_or_key(self):
        with patch('app.fundamentals.FundamentalsStore.get_json',side_effect=AssertionError('NO NETWORK')),patch('app.decision.call_openai',side_effect=AssertionError('NO AI')):
            r=self.client.get('/api/v1/decision/state?symbol=EXM');self.assertEqual(r.status_code,200);self.assertEqual(r.json()['api_calls'],0)
    def test_missing_csrf_rejected(self):self.assertEqual(self.client.post('/api/v1/decision/calculate',json=req().model_dump(mode='json')).status_code,403)
    def test_cross_origin_rejected(self):self.assertEqual(self.client.post('/api/v1/decision/calculate',json=req().model_dump(mode='json'),headers=self.headers|{'Origin':'https://evil.example'}).status_code,403)
    def test_same_origin_pure_math(self):
        r=self.client.post('/api/v1/decision/calculate',json=req().model_dump(mode='json'),headers=self.headers);self.assertEqual(r.status_code,200,r.text);self.assertEqual(r.json()['ai_calls'],0)
    def test_false_sec_claim_downgraded(self):
        body=req().model_dump(mode='json');body['financials']['input_kind']='SEC';r=self.client.post('/api/v1/decision/calculate',json=body,headers=self.headers);self.assertEqual(r.status_code,200,r.text);self.assertEqual(r.json()['financials']['input_kind'],'USER')
    def test_sec_gap_blocks_unmodified_price_calculation(self):
        body=req().model_dump(mode='json');body['financials']['input_kind']='SEC';FundamentalsStore(self.root).save('EXM.json',{'input':body['financials'],'missing':['split_since_share_count']});r=self.client.post('/api/v1/decision/calculate',json=body,headers=self.headers);self.assertEqual(r.status_code,422)
    def test_public_fetch_requires_consent(self):
        r=self.client.post('/api/v1/decision/financials',json={'symbol':'EXM'},headers=self.headers);self.assertEqual(r.status_code,400)
    def test_record_snapshot_dedup_and_no_history_invention(self):
        for i in range(2):r=self.client.post('/api/v1/decision/save',json={'calculation':req().model_dump(mode='json')},headers=self.headers)
        self.assertEqual(r.status_code,200,r.text);self.assertEqual(len(r.json()['history']),1);self.assertEqual(r.json()['api_calls'],0)
