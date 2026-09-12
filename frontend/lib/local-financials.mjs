// Browser-file selection is local. The caller posts only after explicit consent.
export const LOCAL_BUNDLE_SCHEMA='signaldesk-sec-local-bundle-1';
export const MAX_LOCAL_BYTES=16*1024*1024;
export function inputOriginLabel(kind){return kind==='SEC_LOCAL'?'사용자 제공 SEC 파일':kind==='SEC'?'SEC 연결값':'사용자 입력/수정값';}
export function inspectLocalBundle(text,symbol){
 if(typeof text!=='string'||new TextEncoder().encode(text).length>MAX_LOCAL_BYTES)throw new Error('파일이 16 MiB 한도를 넘었습니다.');
 let data;try{data=JSON.parse(text.replace(/^\uFEFF/,''));}catch{throw new Error('JSON을 읽지 못했습니다. 오류 HTML이나 잘린 텍스트가 아닌 묶음 JSON을 선택하세요.');}
 if(data?.schema!==LOCAL_BUNDLE_SCHEMA||!data?.submission||!data?.companyfacts)throw new Error('기업정보와 재무가 함께 있는 SignalDesk SEC Bundle JSON을 선택하세요.');
 if(data.symbol!==symbol)throw new Error('현재 조회 티커와 파일 티커가 다릅니다.');
 const sub=data.submission,facts=data.companyfacts;
 if(!/^[0-9]{1,10}$/.test(String(sub.cik))||String(Number(sub.cik))!==String(Number(facts.cik)))throw new Error('기업정보와 재무 파일의 CIK가 다릅니다.');
 if(!Array.isArray(sub.tickers)||!sub.tickers.some(t=>typeof t==='string'&&t.replace('.','-').toUpperCase()===symbol))throw new Error('기업정보 파일의 티커가 조회 종목과 다릅니다.');
 return {symbol,name:sub.name??facts.entityName,cik:String(sub.cik),text};
}
export async function readLocalBundle(file,symbol){
 if(!file||typeof file.text!=='function')throw new Error('먼저 SEC Bundle JSON 파일을 선택하세요.');
 if(file.size>MAX_LOCAL_BYTES)throw new Error('파일은 16 MiB 이하만 허용합니다.');
 return inspectLocalBundle(await file.text(),symbol);
}
export function localImportPayload(text,symbol,consent,mode,price,date){
 if(consent!==true)throw new Error('로컬 파일 불러오기 동의를 확인하세요.');
 if(!['SAVED','MANUAL'].includes(mode))throw new Error('가격 선택을 확인하세요.');
 const p={symbol,bundle_text:text,allow_local_import:true,quote_mode:mode,manual_quote:null};
 if(mode==='MANUAL'){
  const n=typeof price==='boolean'||String(price??'').trim()===''?NaN:Number(price);
  if(!Number.isFinite(n)||n<=0||!/^\d{4}-\d{2}-\d{2}$/.test(date??''))throw new Error('직접 확인한 양수 가격과 기준일을 입력하세요.');
  p.manual_quote={close:n,date};
 }
 return p;
}
