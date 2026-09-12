'use client';
import {useEffect,useMemo,useRef,useState} from 'react';
import {initialAssumptions,blankFinancials,buildCalculation,dollars,percent,decimal,splitPeers,safeJsonDownload,referenceLabel} from '../lib/decision.mjs';
import {safeSourceUrl} from '../lib/research.mjs';
import {seoulTime} from '../lib/format.mjs';
import {financialApiError,cikInputValid,stepName,stepStatus} from '../lib/financial-fetch.mjs';
import DecisionEvidenceReview from './DecisionEvidenceReview';
import FilingRiskPanel from './FilingRiskPanel';
import {readLocalBundle,localImportPayload,inputOriginLabel} from '../lib/local-financials.mjs';

const mandatory=[['price','가격 · USD/주'],['price_date','가격 기준일','date'],['revenue','최근 12개월 매출'],['period_end','재무기간 종료일','date'],['operating_income','최근 12개월 영업이익'],['shares','시점 보통주 수 · 백만 주'],['cash','현금·현금성자산'],['debt','부채'],['other_claims','기타 청구권·운영필요 현금']];
const optional=[['net_income','최근 12개월 순이익'],['operating_cash_flow','최근 12개월 영업현금흐름'],['capex','최근 12개월 설비투자'],['stock_compensation','최근 12개월 주식보상']];
const clone=x=>JSON.parse(JSON.stringify(x));
const initialRefs=()=>['CONSENSUS','GUIDANCE'].map(kind=>({kind,value:'',period_start:'',period_end:'',published_date:'',source_url:'',note:''}));
function Field({label,type='number',value,onChange,min,max,step='any',disabled=false}){return <label className="v07-field"><span>{label}</span><input type={type} min={min} max={max} step={step} value={value??''} disabled={disabled} onChange={e=>onChange(e.target.value)}/></label>;}
function KPI({label,value,note}){return <div className="v07-kpi"><span>{label}</span><strong>{value}</strong><small>{note}</small></div>;}
async function readResponse(res){const b=await res.json();if(!res.ok)throw financialApiError(b,res.status);return b;}
function Link({url,children}){const u=safeSourceUrl(url);return u?<a href={u} target="_blank" rel="noopener noreferrer">{children??'원문 ↗'}</a>:<span>원문 주소 미확인</span>;}

function Workbench({data,onInsights}){
 const symbol=data.symbol;
 const [f,setF]=useState(()=>blankFinancials(symbol)),[a,setA]=useState(()=>clone(initialAssumptions)),[refs,setRefs]=useState(initialRefs);
 const [state,setState]=useState(null),[status,setStatus]=useState(null),[pack,setPack]=useState(null),[result,setResult]=useState(null),[history,setHistory]=useState([]);
 const [context,setContext]=useState(null),[interpretation,setInterpretation]=useState(null),[inclusions,setInclusions]=useState({});
 const [email,setEmail]=useState(''),[contactReady,setContactReady]=useState(false),[dataConsent,setDataConsent]=useState(false),[paidConsent,setPaidConsent]=useState(false);
 const [loading,setLoading]=useState(''),[calculating,setCalculating]=useState(false),[error,setError]=useState(''),[calcError,setCalcError]=useState('');
 const [peerText,setPeerText]=useState(''),[peerPacks,setPeerPacks]=useState([]),[peerReview,setPeerReview]=useState(false),[peerResult,setPeerResult]=useState(null);
 const [demo,setDemo]=useState(false);
 const [cik,setCik]=useState(''),[diagnostic,setDiagnostic]=useState(null),[partialQuote,setPartialQuote]=useState(null);
 const [localFile,setLocalFile]=useState(null),[localConsent,setLocalConsent]=useState(false),[localQuoteMode,setLocalQuoteMode]=useState('SAVED'),[manualPrice,setManualPrice]=useState(''),[manualDate,setManualDate]=useState('');
 const mounted=useRef(true),flight=useRef(false),revision=useRef(0);
 const body=useMemo(()=>buildCalculation(f,a,refs),[f,a,refs]);
 const requestKey=JSON.stringify(body);
 const csrf=status?.csrf_token??state?.csrf_token;
 function changed(){revision.current++;setInterpretation(null);onInsights?.(null);}
 function setFinancial(k,v){changed();setF(old=>({...old,[k]:v}));}
 function setAssumption(k,v){changed();setA(old=>({...old,[k]:v}));}
 function setScenario(i,k,v){changed();setA(old=>({...old,scenarios:old.scenarios.map((s,j)=>i===j?{...s,[k]:v}:s)}));}
 async function post(path,payload,signal){return readResponse(await fetch(path,{method:'POST',headers:{'Content-Type':'application/json','X-SignalDesk-AI':csrf},body:JSON.stringify(payload),signal}));}
 function usePack(p){
  const input=p.input??{};setDiagnostic(p.retrieval??null);setPartialQuote(p.quote??null);setPack(p);setF({...blankFinancials(symbol),...input});setDemo(false);
  const margin=input.revenue>0&&input.operating_income>0?Math.min(75,Math.max(1,input.operating_income/input.revenue*100)):20;
  setA({...clone(initialAssumptions),scenarios:initialAssumptions.scenarios.map(s=>({...s,target_margin:Number(margin.toFixed(2))}))});changed();setPeerResult(null);
 }
 useEffect(()=>{mounted.current=true;const ac=new AbortController();onInsights?.(null);
  Promise.all([fetch(`/api/v1/decision/state?symbol=${encodeURIComponent(symbol)}`,{signal:ac.signal,cache:'no-store'}).then(readResponse),fetch('/api/v1/ai/status',{signal:ac.signal,cache:'no-store'}).then(readResponse)]).then(([s,t])=>{if(!mounted.current)return;setState(s);setStatus(t);setContext(s.context);setContactReady(s.data_settings.contact_configured);setHistory(s.history??[]);if(s.financial_pack)usePack(s.financial_pack);if(s.financial_diagnostic&&s.financial_pack?.import_mode!=='USER_SAVED_SEC_JSON')setDiagnostic(s.financial_diagnostic);if(s.quote_pack?.quote&&s.financial_pack?.import_mode!=='USER_SAVED_SEC_JSON')setPartialQuote(s.quote_pack.quote);}).catch(e=>{if(mounted.current&&e.name!=='AbortError')setError(e.message);});
  return()=>{mounted.current=false;ac.abort();};
 },[symbol]);
 useEffect(()=>{setInterpretation(null);onInsights?.(null);setPeerResult(null);if(!body||!csrf){setResult(null);setCalcError('');setCalculating(false);return;}
  const ac=new AbortController();let live=true;setCalculating(true);setCalcError('');setResult(null);
  const timer=setTimeout(()=>post('/api/v1/decision/calculate',body,ac.signal).then(r=>{if(live)setResult(r);}).catch(e=>{if(live&&e.name!=='AbortError')setCalcError(e.message);}).finally(()=>{if(live)setCalculating(false);}),280);
  return()=>{live=false;clearTimeout(timer);ac.abort();};
 },[requestKey,csrf]);
 async function task(label,fn){if(flight.current)return;flight.current=true;setLoading(label);setError('');try{await fn();}catch(e){if(mounted.current){setError(e.message);if(e.diagnostic)setDiagnostic(e.diagnostic);if(e.partialQuote)setPartialQuote(e.partialQuote);}}finally{flight.current=false;if(mounted.current)setLoading('');}}
 async function saveContact(){await task('설정 저장',async()=>{const r=await post('/api/v1/decision/contact',{email});setContactReady(r.contact_configured);setEmail('');});}
 async function fetchData(refresh=false){await task('SEC·종가 수집',async()=>{const r=await post('/api/v1/decision/financials',{symbol,allow_public_fetch:dataConsent,refresh,cik:cik.trim()||null});if(mounted.current)usePack(r);});}
 async function importLocal(){await task('저장 SEC JSON 불러오기 · 외부 요청 없음',async()=>{
  if((pack||body)&&!window.confirm('선택한 파일의 재무와 가격 기준으로 입력을 바꾸고 검토 체크·시나리오 시작값을 초기화합니다. 기존 원문·AI 보고서는 삭제하지 않습니다. 계속할까요?'))return;
  const loaded=await readLocalBundle(localFile,symbol);
  const payload=localImportPayload(loaded.text,symbol,localConsent,localQuoteMode,manualPrice,manualDate);
  const r=await post('/api/v1/decision/local-financials',payload);
  if(mounted.current){usePack(r);setCik(String(r.cik??''));setLocalConsent(false);}
 });}
 async function refreshContext(){await task('저장 근거 확인',async()=>{const s=await fetch(`/api/v1/decision/state?symbol=${encodeURIComponent(symbol)}`,{cache:'no-store'}).then(readResponse);if(mounted.current){setContext(s.context);setInclusions({});changed();}});}
 async function reviewSaved(){await task('저장 결과 근거 점검 · 무료',async()=>{
  const seq=revision.current;
  const r=await post('/api/v1/decision/review',{symbol,calculation:result&&!demo?body:null});
  if(mounted.current&&seq===revision.current){setInterpretation(r);onInsights?.(r);}
 });}
 async function runInterpret(){await task('AI 연결 해석',async()=>{
  const seq=revision.current;const r=await post('/api/v1/decision/interpret',{symbol,calculation:result&&!demo?body:null,allow_paid:paidConsent,refresh:false,inclusions});
  if(mounted.current&&seq===revision.current){setInterpretation(r);onInsights?.(r);}
 });}
 async function saveSnapshot(){await task('비교 기록 저장',async()=>{const r=await post('/api/v1/decision/save',{calculation:body});if(mounted.current)setHistory(r.history);});}
 async function loadPeers(){await task('비교 기업 조회',async()=>{const ps=[];for(const s of splitPeers(peerText,symbol))ps.push(await post('/api/v1/decision/financials',{symbol:s,allow_public_fetch:dataConsent,refresh:false}));if(mounted.current){setPeerPacks(ps);setPeerReview(false);setPeerResult(null);}});}
 async function compare(){await task('배수 비교',async()=>{const peers=peerPacks.filter(p=>p.status==='READY_FOR_REVIEW').map(p=>({...p.input,share_basis_checked:peerReview,claims_checked:peerReview}));const r=await post('/api/v1/decision/peers',{target:body.financials,peers});if(mounted.current)setPeerResult(r);});}
 function example(){changed();setDemo(true);setPack(null);setF({...blankFinancials('DEMO'),company_name:'가상기업 · 사용법 예제',price:100,price_date:data.meta.data_end,period_end:data.meta.data_end,revenue:10000,operating_income:2000,cash:1000,debt:1000,shares:300,other_claims:0,net_income:1500,sic:'3570',input_kind:'USER',sources_note:'가상 합성 예제. 실제 기업 데이터가 아닙니다.'});setA(clone(initialAssumptions));}
 const disabled=Boolean(loading), base=result?.base;
 const readyForAI=paidConsent&&status?.configured&&Boolean(context?.sources?.length)&&!disabled&&!demo&&!calculating;
 const rangeMax=result?Math.max(f.price,...result.scenarios.map(s=>s.fair_value))*1.08:1;
 return <div className="v07-body">
  <div className="v07-top-note">수치 계산 → 가정 검토 → 뉴스 연결. <b>시장 컨센서스·회사 전망·내 모형 가정은 서로 구분합니다.</b></div>
  {error&&<div className="error-banner" role="alert">{error}<span>재무 조회 오류는 아래 수집 진단을 확인하세요. AI 분석 버튼으로 재시도하지 마세요.</span></div>}
  {loading&&<p className="v07-status" role="status"><span className="spinner"/>{loading} 중. 화면을 떠나도 이미 보낸 요청은 계속될 수 있습니다.</p>}
  <details className="v07-fold" open={!pack&&!body||undefined}>
   <summary>01 · 재무와 가격 확보 <small>수집 0.7.1 / 파일 0.7.2 · {pack?`${pack.status==='READY_FOR_REVIEW'?'구성 완료 · 사용자 검토 전':'일부 미확보'} · ${pack.input?.price_date}`:'SEC·종가 조회 또는 직접 입력'}</small></summary>
   <div className="v07-fold-inner">
    <p>미국 USD 비금융 일반주식·US-GAAP·양의 영업이익을 우선 지원합니다. SEC 자동 연결이 부족하면 빈 항목을 표시하며, 가짜 데이터로 대체하지 않습니다.</p>
    <div className="v072-import">
     <div className="v072-title"><b>저장한 SEC JSON 불러오기</b><span>파일 0.7.2 · 외부 요청 0</span></div>
     <p>브라우저에서 확보한 기업정보·재무 묶음 파일을 읽습니다. SEC·Yahoo·OpenAI에 다시 접속하지 않으며 자동 수집이 복구됐다는 뜻은 아닙니다.</p>
     <label className="v07-field"><span>SignalDesk SEC Bundle JSON · 최대 16 MiB</span><input aria-label="SEC 묶음 JSON 파일" type="file" accept=".json,application/json" disabled={disabled} onChange={e=>{setLocalFile(e.target.files?.[0]??null);setLocalConsent(false);setError('');}}/></label>
     {localFile&&<small>선택: {localFile.name} · 선택만으로 전송하지 않습니다.</small>}
     <label className="v07-field"><span>함께 사용할 가격</span><select aria-label="로컬 불러오기 가격 선택" value={localQuoteMode} disabled={disabled} onChange={e=>setLocalQuoteMode(e.target.value)}><option value="SAVED">기존에 확보한 가치평가용 종가 · 새 조회 없음</option><option value="MANUAL">내가 확인한 USD 종가 직접 입력</option></select></label>
     {localQuoteMode==='SAVED'&&<p className="v07-muted">{partialQuote?`저장 가격: ${dollars(partialQuote.close)} · ${partialQuote.date}`:'저장 종가가 없으면 직접 입력으로 전환하세요.'} · 가격의 원래 날짜를 유지합니다. 차트 수정종가를 복사하지 않습니다.</p>}
     {localQuoteMode==='MANUAL'&&<div className="v07-fields"><Field label="직접 확인한 USD 종가" value={manualPrice} onChange={setManualPrice} disabled={disabled}/><Field label="직접 입력 가격 기준일" type="date" value={manualDate} onChange={setManualDate} disabled={disabled}/></div>}
     <label className="consent-label"><input type="checkbox" checked={localConsent} disabled={disabled} onChange={e=>setLocalConsent(e.target.checked)}/><span>선택 파일을 이 PC의 SignalDesk 서버로 보내 현재 입력을 교체합니다. 기존 설정·원문·AI 보고서는 유지하며 <b>가정·주식 수·부채 검토 체크는 초기화</b>합니다.</span></label>
     <button className="primary-button" disabled={!localFile||!localConsent||disabled||!csrf} onClick={()=>void importLocal()}>저장 JSON 불러오기 · 외부 요청 없음</button>
     {pack?.import_mode==='USER_SAVED_SEC_JSON'&&<div className="v072-success"><b>로컬 재무 구성 완료 · 검토 전</b><p>파일 → CIK·티커 대조 → 기간 맞춤 → 계산 입력. 추가 외부 요청 0 · AI 호출 0.</p><small>불러온 시각은 공시일이 아닙니다. 원본 진위·최신성은 자동 확인하지 않았습니다.</small></div>}
    </div>
    {!contactReady&&<div className="v07-contact"><Field label="SEC 자동 접근용 연락 이메일 · OpenAI에 보내지 않음" type="email" value={email} onChange={setEmail} disabled={disabled}/><button className="secondary-button" disabled={!email||disabled||!csrf} onClick={()=>void saveContact()}>연락 이메일 저장</button><small>SEC 자료 요청의 User-Agent에만 사용합니다. 로컬 .cache에 저장되며 API 키·결제 정보가 아닙니다.</small></div>}
    {contactReady&&<p className="positive">SEC 연락 설정 저장됨 · 실제 값은 이 화면에 표시하지 않습니다.</p>}
    <div className="v07-contact"><Field label="SEC 기업 번호 · CIK (선택 · 숫자 1~10자리)" type="text" value={cik} onChange={setCik} disabled={disabled}/><small>번호를 알고 있으면 전체 티커 목록을 요청하지 않고, SEC의 기업별 제출 자료에서 티커 일치부터 확인합니다. API 키가 아닙니다. 비우면 기존 자동 검색을 사용합니다.</small></div>
    {!cikInputValid(cik)&&<p className="v07-warning">CIK는 0보다 큰 1~10자리 숫자입니다. URL이나 API 키를 넣지 마세요.</p>}
    <label className="consent-label"><input type="checkbox" checked={dataConsent} onChange={e=>setDataConsent(e.target.checked)} disabled={disabled}/><span>SEC와 Yahoo에 티커·자료를 요청하는 데 동의합니다. <b>OpenAI 호출과 유료 AI 비용은 없습니다.</b></span></label>
    <div className="v07-actions"><button className="primary-button" disabled={!dataConsent||!contactReady||disabled||!csrf||!cikInputValid(cik)} onClick={()=>void fetchData(false)}>재무·종가 가져오기 · AI 비용 없음</button><button className="secondary-button" disabled={!dataConsent||!contactReady||disabled||!pack||!cikInputValid(cik)} onClick={()=>void fetchData(true)}>공개 자료 새로 받기</button><button className="text-button" disabled={disabled} onClick={example}>가상 예제로 계산 방법 보기</button></div>
    {diagnostic?.result==='FAILED'&&partialQuote&&<div className="v07-source-status"><b>종가는 별도 확보 · 재무 자동 조회는 미완료</b><p>{dollars(partialQuote.close)} · {partialQuote.date} · 배당수정하지 않은 제공처 종가. 차트의 수정종가를 복사한 값이 아닙니다.</p><p>이 가격만으로 가치평가하지 않습니다. 아래의 기존 재무 입력값은 새 자료로 바꾸지 않았습니다.</p></div>}
    {diagnostic&&<details className="v07-minor" open={diagnostic.result==='FAILED'||undefined}><summary>수집 진단 · {diagnostic.error_code??diagnostic.result} · OpenAI 호출 0</summary><div className="v07-fold-inner"><p>{seoulTime(diagnostic.generated_at)} KST · {diagnostic.symbol} · 수집기 {diagnostic.diagnostic_version}. 아래 HTTP 코드는 SEC 응답이며 서버의 502와 구분됩니다.</p>{diagnostic.steps?.map((s,i)=><div key={i}><b>{stepName(s.stage)} · {stepStatus(s)}</b>{s.url&&<p><Link url={s.url}>{s.url}</Link></p>}</div>)}{diagnostic.error_code==='SEC_HTTP_403'&&<p className="v07-warning">해당 SEC 자료에 접근이 거절됐습니다. 프로그램은 접근 제한을 우회하거나 자동 재시도하지 않습니다. 기업별 주소에서도 실패하면 반복 클릭하지 마세요.</p>}<p>키·연락 이메일·HTTP 헤더·응답 본문은 진단에 포함하지 않습니다. 회사 수치의 정확성을 검증한 보고서는 아닙니다.</p><button className="secondary-button" type="button" onClick={()=>safeJsonDownload(diagnostic,`SignalDesk_${symbol}_FinancialFetch.json`)}>수집 진단 JSON 저장 · 추가 요청 없음</button></div></details>}
    {pack&&<div className="v07-source-status"><b>{pack.input.company_name} · {pack.import_mode==='USER_SAVED_SEC_JSON'?'사용자 제공 SEC 파일':pack.cache_hit?'저장 데이터':'수집 데이터'}</b><p>{pack.import_mode==='USER_SAVED_SEC_JSON'?'불러옴':'수집'} {seoulTime(pack.generated_at)} KST · 최근 12개월 종료 {pack.input.period_end} · 배당수정하지 않은 종가 {pack.quote?.date}</p>{pack.missing?.length>0&&<p className="v07-warning">미확보/지원 제한: {pack.missing.join(', ')}. 필요한 항목을 검토하기 전에는 평가할 수 없습니다.</p>}<p>다음 입력의 금액 단위는 <b>백만 달러</b>, 주식 수는 <b>백만 주</b>입니다. 예: 10억 달러 = 1,000.</p></div>}
    {Object.entries(pack?.source_consistency??{}).filter(([,v])=>v.status==='SOURCE_DIFFERENCE').map(([k,v])=><p className="v07-warning" key={k}>원자료 산식 차이 · {k==='revenue'?'매출':k==='net_income'?'순이익':'영업이익'}: 현재 입력 {decimal(v.selected_ttm)}백만 USD / 개별 분기 합 {decimal(v.four_quarter_sum)}백만 USD. 차이의 원인은 미확인입니다. 누적값 기준 산식을 유지하고 원자료를 수정하지 않았습니다.</p>)}
    {pack?.import_mode==='USER_SAVED_SEC_JSON'&&<details className="v07-minor"><summary>불러온 파일의 계산 근거 · 포함하지 않은 항목</summary><div className="v07-fold-inner"><p>파일 지문: {pack.local_provenance?.bundle_sha256}</p><p>{pack.local_provenance?.notice}</p>{Object.entries(pack.supplemental_facts??{}).map(([k,v])=><div key={k}><b>{k==='productive_assets_spend'?'생산자산 취득 지출 · 기존 설비투자와 정의 다름':'운영리스 부채 · 별도 참고'}: {decimal(v.value)} 백만 USD</b><p>{v.note}</p>{v.facts?.map((r,i)=><p key={i}>{r.sign===-1?'차감':'가산'} {r.tag} · {decimal(r.val)} {r.unit} · {r.start?`${r.start} ~ `:''}{r.end} <Link url={r.url}/></p>)}</div>)}</div></details>}
    {demo&&<div className="v07-warning"><b>가상 예제 모드 · NVDA 등 실제 종목의 가치가 아닙니다.</b> 종목에 대한 AI 연결은 비활성화됩니다.</div>}
    <div className="v07-fields">{mandatory.map(([k,label,type])=><Field key={k} label={label} type={type??'number'} value={f[k]} onChange={v=>setFinancial(k,v)} disabled={disabled}/>)}</div>
    <div className="v07-checks"><label><input type="checkbox" checked={f.share_basis_checked} disabled={disabled} onChange={e=>setFinancial('share_basis_checked',e.target.checked)}/>가격과 주식 수의 종류·분할 기준 및 미래 주식 수 고정 가정을 확인했습니다.</label><label><input type="checkbox" checked={f.claims_checked} disabled={disabled} onChange={e=>setFinancial('claims_checked',e.target.checked)}/>현금·부채·기타 청구권의 포함범위와 누락 가능성을 검토했습니다.</label></div>
    <details className="v07-minor"><summary>보조 재무 · 데이터 출처 확인</summary><div className="v07-fields">{optional.map(([k,label])=><Field key={k} label={label} value={f[k]} onChange={v=>setFinancial(k,v)} disabled={disabled}/>)}</div><Field label="SIC 업종 코드 · 비교 기업 적합성 확인용" type="text" value={f.sic} onChange={v=>setFinancial('sic',v)} disabled={disabled}/><Field label="직접 입력 출처·가정 메모" type="text" value={f.sources_note} onChange={v=>setFinancial('sources_note',v)} disabled={disabled}/>{pack?.warnings?.map((w,i)=><p className="v07-muted" key={i}>{w}</p>)}{pack?.facts&&Object.entries(pack.facts).filter(([,v])=>v).map(([k,v])=><details className="v07-fact" key={k}><summary>{k} · {decimal(v.value)} · {v.method} · {v.period_end}</summary>{v.facts?.map((x,i)=><p key={i}>{x.sign===-1?'차감':'가산'} {x.tag}: {decimal(x.val)} {x.unit} · {x.start?`${x.start} ~ `:''}{x.end} · 공시 {x.filed} <Link url={x.url}/></p>)}</details>)}</details>
   </div>
  </details>
  <details className="v07-fold" open={body&&!a.reviewed||undefined}>
   <summary>02 · 평가 가정 <small>초기값은 회사·시장 전망이 아님 · 변경 시 무료 재계산</small></summary>
   <div className="v07-fold-inner"><p>모형은 <b>매출 → 세후 영업이익 − 재투자 → 기업가치 → 현금·부채 조정 → 주당가치</b> 순서입니다. 초기 목표 이익률은 조회된 과거 이익률을 유지한 값이며 미래 예측이 아닙니다.</p>
    <div className="v07-scenario-inputs">{a.scenarios.map((s,i)=><div key={s.name}><h4>{s.name} 시나리오</h4><Field label="예측기간 연 매출 성장률 %" value={s.growth} onChange={v=>setScenario(i,'growth',v)} disabled={disabled}/><Field label="마지막 해 영업이익률 %" value={s.target_margin} onChange={v=>setScenario(i,'target_margin',v)} disabled={disabled}/></div>)}</div>
    <div className="v07-fields">{[['years','예측기간 · 년'],['discount_rate','할인율 WACC · %'],['terminal_growth','이후 영구성장률 · %'],['tax_rate','모형 세율 · %'],['sales_to_capital','매출/투하자본 · 배'],['terminal_roic','안정기 투자수익률 · %']].map(([k,l])=><Field key={k} label={l} value={a[k]} onChange={v=>setAssumption(k,v)} disabled={disabled}/>)}</div>
    <p className="v07-muted">매출/투하자본 3배: 매출 3이 늘 때 순투자 1이 필요하다는 가정입니다. 이후 안정기 재투자율은 영구성장률 ÷ 안정기 투자수익률입니다. 분모가 달라 같은 지표가 아닙니다.</p>
    <label className="consent-label"><input type="checkbox" checked={a.reviewed} disabled={disabled} onChange={e=>setAssumption('reviewed',e.target.checked)}/><span>입력 가정이 실제 컨센서스가 아니라는 점을 이해하고, 이 가정에 따른 조건부 평가로 검토합니다.</span></label>
   </div>
  </details>
  {calcError&&<div className="v07-warning" role="alert">{calcError}</div>}
  {calculating&&<p className="v07-status">가정 변경을 계산 중 · AI 호출 0회</p>}
  {!body&&!calculating&&<div className="v07-empty"><h3>현재 가격이 요구하는 성과부터 확인하세요.</h3><p>재무·비배당수정 종가를 가져오거나 필수 항목을 입력하면 세 시나리오의 가치와 역산 성장률이 표시됩니다.</p><small>빈 항목을 0으로 바꾸지 않습니다. 은행·적자기업에 같은 공식을 적용하지 않습니다.</small></div>}
  {result&&<>
   <div className={`v07-verdict v07-${result.verdict.toLowerCase()}`}><span>{demo?'가상 예제':`${symbol} · ${inputOriginLabel(result.financials.input_kind)}`} / 조건부 가치평가</span><h3>{result.verdict_label}</h3><p>{result.decision_ready?`현재가 ${dollars(f.price)}와 기준 모형 가치 ${dollars(base.fair_value)}를 비교했습니다.`:result.verdict==='STALE_DATA'?'가격 또는 재무 자료가 오래돼 현재 고평가·저평가 판정을 보류합니다. 아래는 보관 입력에 따른 계산입니다.':'가정·주식 수·청구권 검토를 마치기 전입니다. 아래 수치는 모형 실험이며 투자 결론이 아닙니다.'}</p></div>
   <div className="v07-kpis"><KPI label="현재가 · 완료 일봉" value={dollars(f.price)} note={f.price_date}/><KPI label="시나리오 가치 범위 · 오늘 가치" value={`${dollars(result.range[0])} – ${dollars(result.range[1])}`} note="신뢰구간·미래 목표주가 아님"/><KPI label={`이 가격에 필요한 ${a.years}년 매출 성장률`} value={result.reverse.growth===null?'하나로 계산 못함':`${percent(result.reverse.growth)} / 년`} note="다른 가정 고정 · 실제 컨센서스 아님"/></div>
   <div className="v07-scenario-result">{result.scenarios.map(s=><div className="v07-scenario-row" key={s.name}><span>{s.name}<small>매출 {percent(s.growth)} · 이익률 {percent(s.target_margin)}</small></span><div className="v07-bar-area"><div style={{width:`${Math.max(0,Math.min(100,s.fair_value/rangeMax*100))}%`}}/><i style={{left:`${f.price/rangeMax*100}%`}} title="현재가"/></div><strong>{dollars(s.fair_value)}<small>현재가 대비 가치 차이 {percent(s.upside_from_price)}</small></strong></div>)}<p className="v07-muted">세로선 = 현재가 · 막대 = 가정별 오늘의 주당가치. 성장 비용이 큰 경우 낙관 성장 시나리오의 가치가 오히려 낮을 수 있습니다.</p></div>
   <div className="v07-slider-row"><label>기준 성장률 {a.scenarios[1].growth}%<input aria-label="기준 성장률 슬라이더" type="range" min={a.scenarios[0].growth} max={a.scenarios[2].growth} step=".5" value={a.scenarios[1].growth} disabled={disabled} onChange={e=>setScenario(1,'growth',e.target.value)}/></label><label>할인율 {a.discount_rate}%<input aria-label="할인율 슬라이더" type="range" min="6" max="20" step=".5" value={a.discount_rate} disabled={disabled} onChange={e=>setAssumption('discount_rate',e.target.value)}/></label><small>움직일 때마다 계산만 갱신합니다. AI 설명은 자동 재생성하지 않습니다.</small></div>
   <details className="v07-fold"><summary>계산 민감도·현금흐름·한계 <small>주가 판단이 어느 가정에 의존하나</small></summary><div className="v07-fold-inner"><p>역산 탐색 범위: 연 매출 성장률 −30%~100%. 같은 가격을 설명하는 해가 여러 개이거나 범위 안에 없으면 하나의 수치를 표시하지 않습니다.</p><div className="v07-table-wrap"><table><caption>기준 목표 이익률 고정 · 할인율 × 매출 성장률에 따른 오늘 가치</caption><thead><tr><th>할인율 / 성장률</th>{result.sensitivity.growths.map(g=><th key={g}>{percent(g)}</th>)}</tr></thead><tbody>{result.sensitivity.discount_rates.map((w,i)=><tr key={w}><th>{percent(w)}</th>{result.sensitivity.values[i].map((x,j)=><td key={j}>{dollars(x)}</td>)}</tr>)}</tbody></table></div><div className="v07-table-wrap"><table><caption>기준 시나리오 · 금액 백만 달러</caption><thead><tr><th>연도</th><th>매출</th><th>세후영업이익</th><th>순재투자</th><th>FCFF</th></tr></thead><tbody>{base.rows.map(r=><tr key={r.year}><td>{r.year}년</td><td>{decimal(r.revenue,0)}</td><td>{decimal(r.nopat,0)}</td><td>{decimal(r.reinvestment,0)}</td><td>{decimal(r.fcff,0)}</td></tr>)}</tbody></table></div><p>예측기간 이후 가치 비중: {percent(base.terminal_weight)}. 부채·현금 조정 전 기업가치 기준입니다.</p>{result.warnings.map((w,i)=><p className="v07-muted" key={i}>{w}</p>)}<p>{result.classification_rule}</p></div></details>
  </>}
  <details className="v07-fold"><summary>03 · 시장 기대·회사 전망·비교기업 <small>미확보를 추정 숫자로 채우지 않습니다</small></summary><div className="v07-fold-inner">
   <div className="v07-reference-cards"><div><b>시장 컨센서스</b><p>{refs[0].value?'사용자 입력 · 원문 대조 필요':'자동 피드 미연결 · 미확보'}</p></div><div><b>회사 가이던스</b><p>{refs[1].value?'사용자 입력 · 원문 대조 필요':'자동 추출 미연결 · 미확보'}</p></div><div><b>우리 모형의 성장률</b><p>{a.scenarios[1].growth}% · {a.years}년 / 사용자 가정</p></div></div>
   <p>현재는 SEC 실적 수치가 자동 연결되며 미래 예상치 피드는 연결하지 않았습니다. 확보한 전망을 직접 넣을 때는 발표일·대상 기간·원문을 함께 입력하세요. 단기 전망과 여러 해의 역산 성장률은 같은 숫자가 아닙니다.</p>
   {refs.map((r,i)=><details className="v07-minor" key={r.kind}><summary>{referenceLabel(r)} 직접 입력 · 선택</summary><div className="v07-fields">{[['value','전망 매출 · 백만 USD','number'],['period_start','전망 기간 시작','date'],['period_end','전망 기간 종료','date'],['published_date','자료 공개일','date'],['source_url','원문 URL','url'],['note','조건·집계 기준 메모','text']].map(([k,l,t])=><Field key={k} label={l} type={t} value={r[k]} onChange={v=>{changed();setRefs(old=>old.map((x,j)=>i===j?{...x,[k]:v}:x));}} disabled={disabled}/>)}</div></details>)}
   {result?.references.map(r=><p className="v07-muted" key={r.kind}>{referenceLabel(r)}: {r.note} {r.source_url&&<Link url={r.source_url}/>}</p>)}
   {result&&<div className="v07-kpis"><KPI label="이익 대비 가격 · PER" value={result.multiples.pe===null?'미계산':`${decimal(result.multiples.pe)}배`} note="최근 12개월 순이익 기준"/><KPI label="기업가치 / 매출" value={result.multiples.ev_sales===null?'미계산':`${decimal(result.multiples.ev_sales)}배`} note="최근 12개월 매출 기준"/><KPI label="영업현금−설비투자 수익률" value={percent(result.multiples.cfo_minus_capex_yield)} note="FCFF 수익률과 다름"/></div>}
   <div className="v07-peer-controls"><Field label="비교할 기업 티커 · 최대 3개, 쉼표로 구분" type="text" value={peerText} onChange={setPeerText} disabled={disabled}/><button className="secondary-button" disabled={!dataConsent||!contactReady||disabled||!splitPeers(peerText,symbol).length||demo} onClick={()=>void loadPeers()}>비교기업 재무 조회 · AI 비용 없음</button></div>
   {peerPacks.map(p=><details className="v07-minor" key={p.symbol}><summary>{p.symbol} · {p.status==='READY_FOR_REVIEW'?'비교 입력 확보':'일부 미확보'}</summary><p>주식 수 {decimal(p.input.shares)}백만 주 · 부채 {decimal(p.input.debt)}백만 달러 · 종가 {p.input.price_date} · 재무 {p.input.period_end}</p>{p.warnings.map((w,i)=><p key={i}>{w}</p>)}{p.sources.map(u=><p key={u}><Link url={u}/></p>)}</details>)}
   {peerPacks.length>0&&<><label className="consent-label"><input type="checkbox" checked={peerReview} onChange={e=>setPeerReview(e.target.checked)} disabled={disabled}/><span>위 비교기업의 주식·부채 기준을 확인했습니다. 동일 업종이어도 성장·위험이 다를 수 있습니다.</span></label><button className="secondary-button" disabled={!peerReview||!result||disabled||!f.share_basis_checked||!f.claims_checked} onClick={()=>void compare()}>배수 비교 계산 · 무료</button></>}
   {peerResult&&<div><p>{peerResult.note}</p>{peerResult.rows.map(p=><p key={p.symbol}>{p.symbol}: {p.eligible?'기초 비교 조건 충족':p.reasons.join(' · ')} · PER {decimal(p.metrics.pe)}</p>)}{Object.entries(peerResult.comparison).map(([k,v])=><p key={k}>{k}: 비교 중앙값 {decimal(v.median)} · 표본 {v.sample_count}개 · 상대 프리미엄 {percent(v.premium)}</p>)}{result&&peerResult.comparison.pe.premium!==null&&((result.verdict==='ABOVE_BASE_VALUE'&&peerResult.comparison.pe.premium<-.1)||(result.verdict==='BELOW_BASE_VALUE'&&peerResult.comparison.pe.premium>.1))&&<p className="v07-warning">평가 엇갈림: 현금흐름 모형과 PER 상대 비교의 방향이 다릅니다. 성장·수익성 차이를 검토하세요.</p>}</div>}
  </div></details>
  <details className="v07-fold"><summary>04 · 과거 저장값과 비교 <small>과거 시장 전체를 재구성한 데이터가 아닙니다</small></summary><div className="v07-fold-inner"><p>모형 계산을 저장한 시점끼리만 비교합니다. 현재 재무를 과거 가격에 대입해서 ‘당시 고평가’였다고 만들지 않습니다.</p><button className="secondary-button" disabled={!result||disabled||demo} onClick={()=>void saveSnapshot()}>현재 계산 저장 · 무료</button><div className="v07-table-wrap"><table><thead><tr><th>저장일</th><th>가격일</th><th>가격</th><th>기준 가치</th><th>판정</th></tr></thead><tbody>{history.slice(-10).reverse().map((x,i)=><tr key={i}><td>{seoulTime(x.saved_at)}</td><td>{x.price_date}</td><td>{dollars(x.price)}</td><td>{dollars(x.base_value)}</td><td>{x.verdict}</td></tr>)}</tbody></table></div>{history.length<2&&<p>저장 비교 표본이 2개 미만입니다. 과거 고평가·저평가 순위를 계산하지 않습니다.</p>}</div></details>
  {!demo&&<FilingRiskPanel symbol={symbol} calculation={result?body:null} csrf={csrf} disabled={disabled||calculating}/>}
  <div className="v07-ai-section"><div className="v07-ai-heading"><div><span className="eyebrow">05 / IMPACT × EXPECTATIONS</span><h3>좋은 소식인가? 이 가격에도 중요한가?</h3></div><button className="text-button" disabled={disabled} onClick={()=>void refreshContext()}>저장 근거 다시 읽기 · 무료</button></div>
   <p>아래 촉매 카드에는 지금도 유형별 방향·관찰 중요도가 표시됩니다. 여기서는 저장된 실제 근거와 {result?'지금 계산한 가치 가정':'가격 계산 없이 사건'}을 AI가 연결합니다. <b>새 웹 검색은 없고, 최신성 확인을 대신하지 않습니다.</b></p>
   <details className="v07-minor"><summary>뉴스를 현재 모형에 이미 반영했나요? · 선택 {context?.events?.length??0}개</summary><p>사용자의 시나리오 포함 여부이지 시장의 선반영률이 아닙니다. 모르는 경우 미확인 그대로 두세요.</p>{context?.events?.map(e=><label className="v07-inclusion" key={e.event_id}><span>{e.title}</span><select value={inclusions[e.event_id]??'UNKNOWN'} disabled={disabled} onChange={x=>{changed();setInclusions(old=>({...old,[e.event_id]:x.target.value}));}}><option value="UNKNOWN">포함 여부 미확인</option><option value="INCLUDED_BY_USER">내 모형에 포함</option><option value="NOT_INCLUDED_BY_USER">내 모형에는 미포함</option></select></label>)}</details>
   <details className="v073-legacy"><summary>이전 AI 보고서 점검 · 보관 기록</summary><div className="v073-review-action"><span className="small-badge">근거 점검 0.7.3</span><p>저장 결과를 먼저 점검하세요. 원문 없는 위험 주장은 별도로 보존하고 새 AI 입력에서는 제외합니다. 점검은 사실 검증 완료나 새로운 유료 분석이 아닙니다.</p><button className="secondary-button" disabled={disabled||demo||calculating||!csrf} onClick={()=>void reviewSaved()}>저장 결과 근거 점검 · 무료</button></div>
   <label className="consent-label"><input type="checkbox" checked={paidConsent} onChange={e=>setPaidConsent(e.target.checked)} disabled={disabled}/><span>티커·저장 근거·재무 및 내 가정을 OpenAI로 보내 <b>별도의 유료 API 요청 1회</b>로 해석하는 데 동의합니다. SEC 연락 이메일은 보내지 않습니다. 자동 재시도·웹 검색은 없습니다.</span></label>
   <button className="primary-button" disabled={!readyForAI} onClick={()=>void runInterpret()}>뉴스 방향·중요도 + 가격 연결 해석 · 유료 1회</button><p className="v07-muted">같은 자료·가정·설정의 결과는 6시간 재사용합니다. 기존 조사들과 하루 합산 20회 시도 한도를 공유합니다. 데이터 수집·슬라이더·표 펼치기는 AI 호출 0회입니다.</p>
   {!context?.sources?.length&&<p>저장된 사건 근거가 없습니다. 기존 촉매·위험 조사나 원문 확인 후 ‘저장 근거 다시 읽기’를 눌러주세요.</p>}
   {demo&&<p className="v07-warning">가상 예제 모드에서는 실제 종목의 AI 해석을 요청하지 않습니다. 재무·종가 가져오기로 실제 입력을 복구하세요.</p>}
   {interpretation&&<DecisionEvidenceReview report={interpretation}/>}</details>
  </div>
  <div className="v07-export"><button className="secondary-button" disabled={!result} onClick={()=>safeJsonDownload({version:'0.7.0',calculation:result,interpretation,peer_comparison:peerResult},`SignalDesk_${f.symbol}_Decision.json`)}>계산·근거 JSON 내보내기</button><span>키·연락 이메일은 포함하지 않습니다. 사용자 입력 메모는 포함됩니다.</span></div>
 </div>;
}
export default function Valuation({data,onInsights}){return <section className="panel valuation07" id="decision-workbench"><div className="v07-heading"><div><span className="eyebrow">07 / VALUE & EXPECTATIONS</span><h2>지금 가격, 얼마나 잘돼야 할까?</h2><p>좋은 회사인가를 넘어, 이 가격을 뒷받침할 성장과 위험을 확인합니다.</p></div><span className="small-badge">계산은 코드 · 해석은 AI</span></div>{data?<Workbench key={data.symbol} data={data} onInsights={onInsights}/>:<div className="v07-empty"><p>티커를 조회한 뒤 재무 기반 가치평가를 시작하세요. 가짜 예측·선반영률을 표시하지 않습니다.</p></div>}</section>;}
