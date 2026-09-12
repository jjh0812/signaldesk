// Presentation only. No fetch, provider calls, cache writes or invented financial claims.
import {reportLines, safeSourceUrl} from './research.mjs';

export const BRIEF_HEADINGS = ['요약: 움직인 이유','요약: 중요한 이유','요약: 주의할 점'];
export const DETAIL_HEADINGS = ['한 줄 해석','확인한 사건과 원인 후보','공개 시점 점검','가격을 해석할 때 주의할 점','아직 확인하지 못한 것','원인 미확인'];
const ALL_HEADINGS = new Set([...BRIEF_HEADINGS, ...DETAIL_HEADINGS, '상세 분석']);

export function headingOf(line) {
  const text=line.map(s=>s.text??'').join('').trim().replace(/^#{1,6}\s*/, '').replace(/^\*\*(.*?)\*\*$/, '$1').trim();
  return ALL_HEADINGS.has(text)?text:null;
}
export function lineText(line) { return line.map(s=>s.text??'').join('').trim(); }

export function splitReport(segments) {
  const sections = new Map(); let heading=null; let detailStart=-1;
  const lines=reportLines(Array.isArray(segments)?segments:[]);
  for(let i=0;i<lines.length;i++) {
    const h=headingOf(lines[i]);
    if(h) {
      heading=h;
      if(h==='상세 분석' && detailStart<0) detailStart=i+1;
      // Duplicate headings are malformed, not silently joined into a trusted short brief.
      if(sections.has(h)) sections.get(h).duplicate=true;
      else sections.set(h,{lines:[],duplicate:false});
    } else if(heading) sections.get(heading).lines.push(lines[i]);
  }
  return {sections,lines,detailLines:detailStart>=0?lines.slice(detailStart):lines};
}

function paragraphs(lines=[]) {
  const blocks=[]; let block=[];
  for(const line of lines) {
    if(!lineText(line) && !line.some(s=>s.citation)) {
      if(block.length)blocks.push(block);block=[];
    } else block.push(line);
  }
  if(block.length)blocks.push(block);
  return blocks;
}
function textLength(lines) {return lines.reduce((n,l)=>n+lineText(l).length,0);}
function hasSource(lines,refs) {return lines.some(l=>l.some(s=>refs.has(s.citation)));}
function noteLines(text) {return [[{text}]];}

export function makeBrief(result) {
  const report=splitReport(result?.segments);
  const citations=Array.isArray(result?.citations)?result.citations:[];
  const refs=new Set(citations.filter(c=>Number.isInteger(c.number)&&safeSourceUrl(c.url)).map(c=>c.number));
  const legacy=result?.prompt_version==='event-research-v0.2.0';
  if(result?.status!=='RESEARCH_READY') return {
    mode:'UNCONFIRMED', title:'원인 미확인', cards:[
      {title:'무엇을 알 수 있나?',lines:noteLines('가격 변동 수치는 확인할 수 있지만, 이를 설명할 검색·인용 근거는 충분하지 않습니다.')},
      {title:'어떻게 봐야 하나?',lines:noteLines('상승·하락만 보고 호재나 악재를 만들어 설명하지 않습니다.')},
      {title:'남은 확인',lines:noteLines('선택한 날짜의 공식 발표와 공개 시점을 추가 확인해야 합니다.')},
    ], detailLines:report.lines, legacy,
  };
  const short=BRIEF_HEADINGS.map(h=>report.sections.get(h));
  const usable=short.every(s=>s&&!s.duplicate&&textLength(s.lines)>0&&textLength(s.lines)<=220)
    && short.reduce((n,s)=>n+textLength(s.lines),0)<=660
    && short.slice(0,2).every(s=>hasSource(s.lines,refs))
    && Number(result?.unmapped_citation_count??0)===0;
  if(usable) return {
    mode:'QUICK', title:'10초 요약', legacy:false,
    cards:short.map((s,i)=>({title:['왜 움직였나?','왜 중요한가?','무엇을 조심할까?'][i],lines:s.lines.filter(l=>lineText(l)||l.some(s=>s.citation))})),
    detailLines:report.detailLines,
  };
  // Existing cache has no newly generated summary. Quote whole paragraphs only.
  // Never take the first sentence and discard a "however" qualification in the second.
  const selections=[
    ['한 줄 해석','기존 한 줄 해석','핵심 문장을 안전하게 발췌하지 못했습니다. 상세 분석을 확인하세요.'],
    ['가격을 해석할 때 주의할 점','가격 해석 주의','가격 해석의 구체적인 한계는 상세 분석과 원문에서 확인하세요.'],
    ['아직 확인하지 못한 것','미확인 사항','이 보고서는 공개 시점과 인과관계를 독립 검증한 결과가 아닙니다.'],
  ];
  return {
    mode:legacy?'LEGACY_EXCERPT':'FORMAT_FALLBACK',
    title:legacy?'저장 보고서 핵심 발췌':'보고서 발췌 · 요약 형식 확인 필요', legacy,
    cards:selections.map(([h,title,fallback])=>{
      const section=report.sections.get(h);
      const first=paragraphs(section?.lines)[0];
      // Keep one complete paragraph; do not truncate numbers, dates or uncertainty clauses.
      return {title,lines:section&&!section.duplicate&&first&&textLength(first)<=340?first:noteLines(fallback)};
    }),
    detailLines:report.lines,
  };
}

// Only formatting for displayed prose; original cached data is never modified.
export function displayProse(text) {
  if(typeof text!=='string')return '';
  return text.replace(/\$([0-9]+(?:,[0-9]{3})*\.[0-9]{3,})(?![0-9])/g,(_,n)=>{
    const value=Number(n.replaceAll(',',''));
    return Number.isFinite(value)?'$'+value.toLocaleString('en-US',{minimumFractionDigits:2,maximumFractionDigits:2}):'$'+n;
  });
}
