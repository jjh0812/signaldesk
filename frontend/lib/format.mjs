export const pct = (v, digits = 2) => Number.isFinite(v) ? `${v > 0 ? '+' : ''}${(v * 100).toFixed(digits)}%` : '—';
export const pp = (v) => Number.isFinite(v) ? `${v > 0 ? '+' : ''}${(v * 100).toFixed(2)}%p` : '—';
export const num = (v, digits = 2) => Number.isFinite(v) ? v.toLocaleString('en-US', {minimumFractionDigits: digits, maximumFractionDigits: digits}) : '—';
export const money = (v) => Number.isFinite(v) ? `$${num(v, v < 1 ? 4 : 2)}` : '—';
export const ratio = (v) => Number.isFinite(v) ? `${v.toFixed(2)}x` : '—';
export const tone = (v) => !Number.isFinite(v) || v === 0 ? '' : v > 0 ? 'positive' : 'negative';
export function compact(v) {
  if (!Number.isFinite(v)) return '—';
  if (v >= 1e9) return `${(v / 1e9).toFixed(2)}B`;
  if (v >= 1e6) return `${(v / 1e6).toFixed(2)}M`;
  if (v >= 1e3) return `${(v / 1e3).toFixed(1)}K`;
  return v.toFixed(0);
}
export function seoulTime(value) {
  if (!value) return '—';
  const d = new Date(value);
  if (Number.isNaN(d.getTime())) return '—';
  return new Intl.DateTimeFormat('ko-KR', { timeZone: 'Asia/Seoul', year: 'numeric', month: '2-digit', day: '2-digit', hour: '2-digit', minute: '2-digit', hour12: false }).format(d);
}
export function findExactDate(rows, date) {
  return rows.find(row => row.date === date) ?? null;
}
export function chartGeometry(rows) {
  if (!rows.length) return {points: [], line: '', area: '', min: 0, max: 1};
  const values = rows.map(r => r.close);
  const lo = Math.min(...values), hi = Math.max(...values);
  const padding = Math.max((hi - lo) * 0.13, hi * 0.012, 0.005);
  const min = Math.max(0, lo - padding), max = hi + padding;
  const points = rows.map((r, i) => ({
    ...r, index: i,
    x: 30 + (rows.length === 1 ? 445 : i * 890 / (rows.length - 1)),
    y: 26 + (max - r.close) / (max - min) * 250,
  }));
  const line = points.map((p, i) => `${i ? 'L' : 'M'}${p.x.toFixed(2)},${p.y.toFixed(2)}`).join(' ');
  return { points, line, area: `${line} L${points.at(-1).x},286 L${points[0].x},286 Z`, min, max };
}
