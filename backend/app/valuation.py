"""Transparent conditional FCFF valuation. No I/O, AI, or fitted market expectations.

Units: USD millions; shares in millions. Year-end discounting. Explicit forecast
uses delta revenue / sales-to-capital as net reinvestment. Stable reinvestment
uses g / ROIC. This is a user-assumption model, not a calibrated price target.
"""
from __future__ import annotations
import math
from datetime import date
from typing import Literal
from pydantic import BaseModel, ConfigDict, Field, StrictBool, model_validator

VERSION = 'decision-workbench-0.7.0'

class StrictModel(BaseModel):
    model_config = ConfigDict(extra='forbid', allow_inf_nan=False)

class FinancialInput(StrictModel):
    symbol: str = Field(pattern=r'^[A-Z][A-Z0-9]{0,9}(?:-[A-Z])?$')
    company_name: str = Field(default='', max_length=200)
    price: float = Field(gt=0, le=1e7)
    price_date: date
    period_end: date
    revenue: float = Field(gt=0, le=1e10)
    operating_income: float = Field(gt=0, le=1e10)
    cash: float = Field(ge=0, le=1e10)
    debt: float = Field(ge=0, le=1e10)
    shares: float = Field(gt=0, le=1e9)
    other_claims: float = Field(default=0, ge=0, le=1e10)
    net_income: float | None = Field(default=None, ge=-1e10, le=1e10)
    operating_cash_flow: float | None = Field(default=None, ge=-1e10, le=1e10)
    capex: float | None = Field(default=None, ge=0, le=1e10)
    stock_compensation: float | None = Field(default=None, ge=0, le=1e10)
    revenue_growth_yoy: float | None = Field(default=None, ge=-1, le=100)
    sic: str = Field(default='', max_length=8)
    input_kind: Literal['SEC', 'SEC_LOCAL', 'USER'] = 'USER'
    sources_note: str = Field(default='', max_length=2000)
    share_basis_checked: StrictBool = False
    claims_checked: StrictBool = False
    @model_validator(mode='after')
    def coherent(self):
        if self.period_end > self.price_date: raise ValueError('재무기간 종료일이 가격 기준일보다 늦습니다.')
        if self.operating_income > self.revenue: raise ValueError('영업이익이 매출을 초과합니다. 단위·항목을 확인하세요.')
        if self.sic.isdigit() and 6000 <= int(self.sic) <= 6999:
            raise ValueError('금융·보험·REIT는 이 비금융 FCFF 모형으로 평가하지 않습니다.')
        return self

class Scenario(StrictModel):
    name: Literal['보수', '기준', '낙관']
    growth: float = Field(ge=-.3, le=1)
    target_margin: float = Field(gt=0, le=.8)

class Assumptions(StrictModel):
    years: int = Field(default=5, ge=3, le=10)
    discount_rate: float = Field(default=.10, ge=.04, le=.35)
    terminal_growth: float = Field(default=.025, ge=0, le=.05)
    tax_rate: float = Field(default=.21, ge=0, le=.50)
    sales_to_capital: float = Field(default=3.0, ge=.2, le=20)
    terminal_roic: float = Field(default=.15, ge=.03, le=.6)
    scenarios: list[Scenario] = Field(min_length=3, max_length=3)
    reviewed: StrictBool = False
    @model_validator(mode='after')
    def coherent(self):
        if self.discount_rate - self.terminal_growth < .01:
            raise ValueError('할인율은 영구성장률보다 최소 1%p 높아야 합니다.')
        if self.terminal_roic <= self.terminal_growth:
            raise ValueError('안정기 투자수익률은 영구성장률보다 높아야 합니다.')
        if [s.name for s in self.scenarios] != ['보수','기준','낙관']:
            raise ValueError('시나리오 순서는 보수·기준·낙관이어야 합니다.')
        if not self.scenarios[0].growth <= self.scenarios[1].growth <= self.scenarios[2].growth:
            raise ValueError('성장률은 보수 ≤ 기준 ≤ 낙관 순서로 입력하세요.')
        if not self.scenarios[0].target_margin <= self.scenarios[1].target_margin <= self.scenarios[2].target_margin:
            raise ValueError('목표 영업이익률은 보수 ≤ 기준 ≤ 낙관 순서로 입력하세요.')
        return self

class ReferenceEstimate(StrictModel):
    kind: Literal['CONSENSUS','GUIDANCE']
    metric: Literal['REVENUE_USD_MILLION'] = 'REVENUE_USD_MILLION'
    value: float = Field(gt=0, le=1e10)
    period_start: date
    period_end: date
    published_date: date
    source_url: str = Field(min_length=12, max_length=2000)
    note: str = Field(default='', max_length=500)
    @model_validator(mode='after')
    def validate_period(self):
        from .research import public_url
        if self.period_start > self.period_end or not public_url(self.source_url):
            raise ValueError('예상치의 기간과 공개 원문 URL을 확인하세요.')
        return self

class CalculateRequest(StrictModel):
    financials: FinancialInput
    assumptions: Assumptions
    references: list[ReferenceEstimate] = Field(default_factory=list, max_length=2)
    @model_validator(mode='after')
    def references_unique(self):
        if len({r.kind for r in self.references}) != len(self.references):
            raise ValueError('시장 예상치와 회사 전망은 각각 한 개만 입력하세요.')
        return self

def defaults(margin: float = .2) -> dict:
    # Explicit initialization only: NOT analyst consensus, management guidance,
    # current market WACC, nor fitted forward growth forecasts.
    margin = min(.75,max(.01,margin))
    return Assumptions(scenarios=[Scenario(name=n,growth=g,target_margin=margin)
        for n,g in [('보수',.05),('기준',.10),('낙관',.20)]]).model_dump(mode='json')

def project(f: FinancialInput, a: Assumptions, s: Scenario, *, keep_rows: bool=True) -> dict:
    revenue=f.revenue; initial_margin=f.operating_income/f.revenue
    pv=0.; rows=[]
    for year in range(1,a.years+1):
        next_revenue=revenue*(1+s.growth)
        margin=initial_margin+(s.target_margin-initial_margin)*year/a.years
        nopat=next_revenue*margin*(1-a.tax_rate)
        # Shrinkage does NOT automatically monetize assets. No invented release.
        reinvestment=max(next_revenue-revenue,0.)/a.sales_to_capital
        fcff=nopat-reinvestment
        discounted=fcff/(1+a.discount_rate)**year; pv+=discounted
        if keep_rows: rows.append(dict(year=year,revenue=next_revenue,operating_margin=margin,
            nopat=nopat,reinvestment=reinvestment,fcff=fcff,present_value=discounted))
        revenue=next_revenue
    terminal_nopat=revenue*(1+a.terminal_growth)*s.target_margin*(1-a.tax_rate)
    terminal_reinvestment=terminal_nopat*a.terminal_growth/a.terminal_roic
    terminal_fcff=terminal_nopat-terminal_reinvestment
    terminal_pv=terminal_fcff/(a.discount_rate-a.terminal_growth)/(1+a.discount_rate)**a.years
    ev=pv+terminal_pv
    equity=ev+f.cash-f.debt-f.other_claims
    price=max(equity,0)/f.shares
    return dict(name=s.name,enterprise_value=ev,equity_value_before_floor=equity,
        equity_value=max(equity,0),fair_value=price,upside_from_price=price/f.price-1,
        terminal_pv=terminal_pv,terminal_weight=terminal_pv/ev if ev>0 else None,
        terminal_fcff=terminal_fcff,terminal_reinvestment=terminal_reinvestment,
        growth=s.growth,target_margin=s.target_margin,rows=rows)

def reverse_growth(f: FinancialInput,a: Assumptions) -> dict:
    """Scan for multiple roots/non-monotonicity. Never clamp to a made-up answer."""
    base=a.scenarios[1]
    def fn(g):return project(f,a,Scenario(name='기준',growth=g,target_margin=base.target_margin),keep_rows=False)['fair_value']-f.price
    lo=-.30; hi=1.; step=.005; xs=[lo+i*step for i in range(261)]; ys=[fn(x) for x in xs]
    roots=[]
    for i,(x,y) in enumerate(zip(xs,ys)):
        if abs(y)<1e-7:roots.append(x)
        if i and ys[i-1]*y<0:
            left,right=xs[i-1],x; yl=ys[i-1]
            for _ in range(55):
                mid=(left+right)/2; ym=fn(mid)
                if yl*ym<=0:right=mid
                else:left,yl=mid,ym
            roots.append((left+right)/2)
    unique=[]
    for r in roots:
        if not any(abs(r-v)<1e-5 for v in unique):unique.append(r)
    increasing=all(ys[i]>=ys[i-1]-1e-7 for i in range(1,len(ys)))
    decreasing=all(ys[i]<=ys[i-1]+1e-7 for i in range(1,len(ys)))
    status='MULTIPLE_SOLUTIONS' if len(unique)>1 else 'SOLVED' if unique else 'OUTSIDE_SEARCH_RANGE'
    return {'status':status,'growth':unique[0] if len(unique)==1 else None,'solutions':unique,
        'search_range':[lo,hi],'monotonic_in_range':increasing or decreasing,
        'metric':'REVENUE_CAGR','years':a.years,
        'note':'목표 이익률·재투자·할인율·안정기 가정을 고정한 조건부 매출 성장률입니다. 실제 시장 컨센서스가 아닙니다.'}

def multiples(f: FinancialInput) -> dict:
    market_cap=f.price*f.shares; ev=market_cap+f.debt+f.other_claims-f.cash
    fcf=None if f.operating_cash_flow is None or f.capex is None else f.operating_cash_flow-f.capex
    return {'market_cap':market_cap,'enterprise_value':ev,
        'pe':market_cap/f.net_income if f.net_income is not None and f.net_income>0 else None,
        'ev_sales':ev/f.revenue if ev>0 else None,
        'ev_ebit':ev/f.operating_income if ev>0 else None,
        'cfo_minus_capex':fcf,'cfo_minus_capex_yield':fcf/market_cap if fcf is not None else None,
        'fcf_note':'영업현금흐름−설비투자는 참고 지표이며 FCFF와 같지 않습니다. 주식보상·이자·리스·인수 지출을 검토하세요.'}

def calculate(request: CalculateRequest, *, today: date|None=None) -> dict:
    f=request.financials;a=request.assumptions; today=today or date.today()
    if f.price_date>today:raise ValueError('미래 가격 기준일을 사용할 수 없습니다.')
    reports=[project(f,a,s) for s in a.scenarios];base=reports[1]
    ready=a.reviewed and f.share_basis_checked and f.claims_checked
    if not ready:verdict='ASSUMPTIONS_UNREVIEWED'
    elif (today-f.price_date).days>7 or (f.price_date-f.period_end).days>200:verdict='STALE_DATA'
    elif base['fair_value']<f.price*.9:verdict='ABOVE_BASE_VALUE'
    elif base['fair_value']>f.price*1.1:verdict='BELOW_BASE_VALUE'
    else:verdict='NEAR_BASE_VALUE'
    labels={'ASSUMPTIONS_UNREVIEWED':'가정 검토 전 · 평가 보류','STALE_DATA':'자료 시점 확인 필요 · 평가 보류',
        'ABOVE_BASE_VALUE':'기준 가정 대비 고평가 부담','BELOW_BASE_VALUE':'기준 가정 대비 저평가 가능성',
        'NEAR_BASE_VALUE':'기준 가정 가치 부근'}
    warnings=['모든 가치는 오늘 기준의 모형 추정치입니다. 미래 목표주가·상승 확률·시장 기대 반영률이 아닙니다.',
        '초기 성장률·할인율 등은 입력 시작값이며 시장 컨센서스나 회사 가이던스가 아닙니다.',
        '현재 주식 수 고정, 미래 순주식발행 0을 가정합니다. 잠재 희석과 인수·보증 의무는 별도 검토 대상입니다.',
        '부채는 공시 장부값을 시장가치의 근사로 사용합니다. 큰 차이가 있는 기업은 직접 조정해야 합니다.',
        '현금은 모두 비영업자산으로 가정합니다. 운영필요 현금·리스·우선주·소수지분은 기타 청구권에서 조정하세요.']
    if base['terminal_weight'] is not None and base['terminal_weight']>.75:
        warnings.append('기준 가치의 75% 이상이 예측기간 이후 가치에 의존합니다. 장기 가정 변화에 민감합니다.')
    if any(r['fcff']<0 for r in base['rows']):warnings.append('기준 시나리오에 음의 FCFF가 있습니다. 성장에 필요한 추가 자금과 조달 조건을 검토하세요.')
    if any(r['equity_value_before_floor']<=0 for r in reports):warnings.append('일부 시나리오의 계산상 지분가치가 0 이하입니다. 0 표시는 주가가 반드시 0이 된다는 예측이 아닙니다.')
    if not f.share_basis_checked:warnings.append('보고 주식 수와 현재 가격의 분할·주식 종류 기준을 검토하지 않았습니다.')
    if not f.claims_checked:warnings.append('부채·현금·기타 청구권의 포함범위를 검토하지 않았습니다.')
    if (today-f.price_date).days>7:warnings.append('가격 기준일이 7일 넘게 지났습니다.')
    if (f.price_date-f.period_end).days>200:warnings.append('재무기간 종료일이 가격 기준일보다 200일 이상 오래됐습니다.')
    # Sensitivity: recompute, never call an LLM.
    growths=sorted(set(round(min(1,max(-.3,a.scenarios[1].growth+d)),6) for d in [-.10,-.05,0,.05,.10]))
    rates=sorted(set(round(min(.35,max(a.terminal_growth+.01,.04,a.discount_rate+d)),6) for d in [-.02,-.01,0,.01,.02]))
    grid=[]
    for w in rates:
        aa=a.model_copy(update={'discount_rate':w})
        grid.append([project(f,aa,Scenario(name='기준',growth=g,target_margin=a.scenarios[1].target_margin),keep_rows=False)['fair_value'] for g in growths])
    refs=[]
    for kind in ['CONSENSUS','GUIDANCE']:
        ref=next((r for r in request.references if r.kind==kind),None)
        if not ref:refs.append({'kind':kind,'status':'NOT_AVAILABLE','note':'시장 예상치 미확보' if kind=='CONSENSUS' else '회사 가이던스 미확보'});continue
        if ref.published_date>f.price_date:
            refs.append(ref.model_dump(mode='json')|{'status':'AFTER_PRICE_DATE','note':'가격 기준일 이후 자료: 해당 종가에 선반영됐다고 해석할 수 없습니다.'});continue
        refs.append(ref.model_dump(mode='json')|{'status':'USER_ENTERED_NOT_VERIFIED',
            'note':'사용자 입력값 · 출처 내용 미검증 · 예측기간과 역산 성장률의 기간을 구분하세요.'})
    reverse=reverse_growth(f,a)
    if reverse['status']!='SOLVED':warnings.append('현재 가격을 설명하는 매출 성장률을 탐색 범위에서 하나로 정하지 못했습니다. 숫자를 임의로 채우지 않습니다.')
    if not reverse['monotonic_in_range']:warnings.append('성장에 따른 재투자 부담으로 가치가 단조 증가하지 않습니다. 역산값을 특히 신중히 해석하세요.')
    return {'version':VERSION,'symbol':f.symbol,'financials':f.model_dump(mode='json'),'assumptions':a.model_dump(mode='json'),
        'verdict':verdict,'verdict_label':labels[verdict],'decision_ready':ready and verdict!='STALE_DATA',
        'classification_rule':'기준 모형 가치와 현재가 ±10% 이내는 부근으로 표시하는 UI 구분 기준입니다. 통계적 신뢰구간이 아닙니다.',
        'scenarios':reports,'base':base,'range':[min(x['fair_value'] for x in reports),max(x['fair_value'] for x in reports)],
        'reverse':reverse,'sensitivity':{'growths':growths,'discount_rates':rates,'values':grid},
        'references':refs,'multiples':multiples(f),'warnings':warnings,'ai_calls':0}

def compare_peers(target: FinancialInput, peers: list[FinancialInput]) -> dict:
    """Comparability is a screening gate, not proof of identical risk/growth."""
    from statistics import median
    used=set([target.symbol]); rows=[]
    for p in peers[:3]:
        if p.symbol in used:continue
        used.add(p.symbol);reasons=[]
        if not target.sic or not p.sic or target.sic[:2]!=p.sic[:2]:reasons.append('SIC 업종 대분류 불일치/미확인')
        if p.price_date!=target.price_date:reasons.append('가격 기준일 불일치')
        if abs((p.period_end-target.period_end).days)>120:reasons.append('재무기간 종료일 차이 120일 초과')
        if not p.share_basis_checked or not p.claims_checked:reasons.append('주식·부채 기준 사용자 검토 전')
        rows.append({'symbol':p.symbol,'eligible':not reasons,'reasons':reasons,'period_end':p.period_end.isoformat(),'price_date':p.price_date.isoformat(),'metrics':multiples(p)})
    eligible=[x for x in rows if x['eligible']];med={};target_m=multiples(target)
    for metric in ['pe','ev_sales','ev_ebit']:
        values=[r['metrics'][metric] for r in eligible if r['metrics'][metric] is not None and r['metrics'][metric]>0]
        value=median(values) if len(values)>=2 else None
        med[metric]={'median':value,'sample_count':len(values),'premium':target_m[metric]/value-1 if value and target_m[metric] is not None else None}
    return {'rows':rows,'comparison':med,'note':'사용자가 선택한 기업의 상대 배수입니다. 업종 대분류가 같아도 성장·수익성·위험 차이를 통제하지 않았습니다. 높은 배수만으로 고평가를 확정하지 않습니다.'}
