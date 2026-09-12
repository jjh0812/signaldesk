'use client';
import {useMemo, useRef, useState} from 'react';
import {chartGeometry, compact, money, pct, tone} from '../lib/format.mjs';

export default function PriceChart({rows, selectedDate, onSelect}) {
  const svgRef = useRef(null);
  const [hoverIndex, setHoverIndex] = useState(null);
  const geometry = useMemo(() => chartGeometry(rows), [rows]);
  const selectedIndex = rows.findIndex(r => r.date === selectedDate);
  const currentIndex = hoverIndex ?? selectedIndex;
  const point = geometry.points[currentIndex] ?? null;
  const maxVolume = Math.max(1, ...rows.map(r => r.volume));
  const barWidth = Math.max(.7, Math.min(9, 790 / Math.max(rows.length, 1)));

  function indexFromEvent(event) {
    const svg = svgRef.current;
    if (!svg || !rows.length || !svg.getScreenCTM()) return null;
    const pt = svg.createSVGPoint(); pt.x = event.clientX; pt.y = event.clientY;
    const p = pt.matrixTransform(svg.getScreenCTM().inverse());
    return Math.max(0, Math.min(rows.length - 1, Math.round((p.x - 30) / 890 * (rows.length - 1))));
  }
  return <div className="price-chart">
    <div className="chart-hoverline" aria-live="polite">
      <span>{point?.date ?? '차트의 날짜를 클릭하세요'}</span>
      {point && <><b>{money(point.close)}</b><span className={tone(point.return_1d)}>{pct(point.return_1d)}</span><span>VOL {compact(point.volume)}</span></>}
    </div>
    <div className="chart-scroll">
      <svg ref={svgRef} className="chart-svg" viewBox="0 0 1000 416" role="img" aria-label="수정종가와 거래량 차트. 이상 변동 마커 또는 아래 목록을 선택할 수 있습니다."
        onPointerMove={e => setHoverIndex(indexFromEvent(e))}
        onPointerLeave={() => setHoverIndex(null)}
        onClick={e => {const i=indexFromEvent(e); if(i!==null) onSelect(rows[i]);}}>
        <defs><linearGradient id="price-area" x1="0" y1="0" x2="0" y2="1"><stop offset="0%" stopColor="#63d6be" stopOpacity="0.14"/><stop offset="100%" stopColor="#63d6be" stopOpacity="0"/></linearGradient></defs>
        {[0,1,2,3,4].map(i => <g key={i}>
          <line x1="28" x2="924" y1={26+i*62.5} y2={26+i*62.5} stroke="#202b39" strokeDasharray="3 5"/>
          <text x="938" y={30+i*62.5} className="axis-label">{money(geometry.max-(geometry.max-geometry.min)*i/4)}</text>
        </g>)}
        <path d={geometry.area} fill="url(#price-area)"/>
        <path d={geometry.line} fill="none" stroke="#73dcc4" strokeWidth="2.1" strokeLinejoin="round"/>
        <line x1="28" x2="924" y1="305" y2="305" stroke="#263342"/>
        <text x="31" y="323" className="axis-label">VOLUME</text>
        {geometry.points.map(p => <rect key={`v-${p.date}`} x={p.x-barWidth/2} y={382-p.volume/maxVolume*46} width={barWidth} height={(p.volume===0?0:Math.max(.5,p.volume/maxVolume*46))} fill={p.return_1d>=0?'#27665d':'#633d47'} opacity=".85"/>)}
        {Array.from(new Set([0,Math.floor((rows.length-1)/4),Math.floor((rows.length-1)/2),Math.floor((rows.length-1)*3/4),rows.length-1])).map(i => <text key={`date-${i}`} x={geometry.points[i]?.x ?? 30} y="406" textAnchor="middle" className="axis-label">{rows[i]?.date}</text>)}
        {point && <g pointerEvents="none">
          <line x1={point.x} x2={point.x} y1="15" y2="386" stroke="#80909f" strokeDasharray="4 4" opacity=".7"/>
          <circle cx={point.x} cy={point.y} r="4.5" fill="#d9fff4" stroke="#142d29" strokeWidth="2"/>
        </g>}
        {geometry.points.filter(p => p.is_anomaly).map(p => <g key={p.date} className="chart-marker" role="button" tabIndex={0} aria-label={`${p.date} ${pct(p.return_1d)} 이상 변동 선택`}
          onKeyDown={e => {if(e.key==='Enter'||e.key===' '){e.preventDefault();onSelect(p);}}}
          onClick={e => {e.stopPropagation();onSelect(p);}}>
          <circle cx={p.x} cy={p.y} r={p.date===selectedDate?10:7} fill={p.direction==='UP'?'#78e2bf':'#fa889a'} fillOpacity=".16"/>
          <circle cx={p.x} cy={p.y} r="4.2" fill={p.direction==='UP'?'#78e2bf':'#fa889a'} stroke="#101822" strokeWidth="1.7"/>
          <title>{p.date} · {pct(p.return_1d)}</title>
        </g>)}
      </svg>
    </div>
    <div className="chart-legend"><span><i className="dot positive-dot"/>상승 이벤트</span><span><i className="dot negative-dot"/>하락 이벤트</span><span>마커·차트 클릭 → 해당 거래일 확인</span></div>
  </div>;
}
