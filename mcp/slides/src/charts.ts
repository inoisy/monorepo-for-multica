import type { Chart } from './schema.js';
import { esc } from './text.js';

// Charts are plain HTML/CSS where possible (bars, progress) so their labels
// use the theme's real type scale, and SVG only for the geometry (line, area,
// donut). Colors come from CSS custom properties set by the theme.

function fmt(v: number, unit?: string): string {
  const s = Number.isInteger(v) ? String(v) : v.toFixed(1);
  return esc(unit ? `${s}${unit}` : s);
}

function seriesClass(i: number): string {
  return ['s-accent', 's-accent2', 's-muted'][i] ?? 's-muted';
}

function legend(chart: Chart): string {
  if (chart.series.length < 2) return '';
  return `<div class="chart-legend">${chart.series.map((s, i) =>
    `<span><i class="${seriesClass(i)}"></i>${esc(s.label ?? `Series ${i + 1}`)}</span>`).join('')}</div>`;
}

function bar(chart: Chart): string {
  const n = Math.max(...chart.series.map(s => s.values.length));
  const max = Math.max(...chart.series.flatMap(s => s.values), 0) || 1;
  const single = chart.series.length === 1;
  const groups: string[] = [];
  for (let i = 0; i < n; i++) {
    const dim = chart.highlight !== undefined && chart.highlight !== i;
    const bars = chart.series.map((s, si) => {
      const v = s.values[i] ?? 0;
      const cls = single ? (dim ? 's-dim' : 's-accent') : seriesClass(si);
      return `<div class="bar ${cls}" style="height:${Math.max(2, (v / max) * 100).toFixed(2)}%">` +
        (single ? `<span class="bar-value${dim ? ' dim' : ''}">${fmt(v, chart.unit)}</span>` : '') + `</div>`;
    }).join('');
    groups.push(`<div class="bar-group"><div class="bar-stack">${bars}</div>` +
      `<div class="bar-label${dim ? ' dim' : ''}">${esc(chart.labels?.[i] ?? '')}</div></div>`);
  }
  return `<div class="chart chart-bar">${legend(chart)}<div class="bars">${groups.join('')}</div></div>`;
}

function line(chart: Chart, area: boolean): string {
  const W = 1000, H = 400, pad = 16;
  const all = chart.series.flatMap(s => s.values);
  const max = Math.max(...all), min = Math.min(0, ...all);
  const span = max - min || 1;
  const paths = chart.series.map((s, si) => {
    const step = s.values.length > 1 ? (W - pad * 2) / (s.values.length - 1) : 0;
    const pts = s.values.map((v, i) => [pad + i * step, pad + (1 - (v - min) / span) * (H - pad * 2)] as const);
    const d = pts.map(([x, y], i) => `${i ? 'L' : 'M'}${x.toFixed(1)},${y.toFixed(1)}`).join(' ');
    const fill = area && si === 0
      ? `<path class="area ${seriesClass(si)}" d="${d} L${pts.at(-1)![0].toFixed(1)},${H} L${pts[0][0].toFixed(1)},${H} Z"/>`
      : '';
    return `${fill}<path class="line ${seriesClass(si)}" d="${d}" vector-effect="non-scaling-stroke"/>`;
  }).join('');
  // End-point marker and value are HTML, positioned in %, so they stay round
  // and legible under the non-uniform SVG stretch.
  const s0 = chart.series[0];
  const last = s0.values.at(-1)!;
  const lx = s0.values.length > 1 ? ((W - pad) / W) * 100 : 50;
  const ly = ((pad + (1 - (last - min) / span) * (H - pad * 2)) / H) * 100;
  const labels = chart.labels?.length
    ? `<div class="line-labels">${chart.labels.map(l => `<span>${esc(l)}</span>`).join('')}</div>` : '';
  return `<div class="chart chart-line">${legend(chart)}<div class="line-plot">` +
    `<svg viewBox="0 0 ${W} ${H}" preserveAspectRatio="none">${paths}</svg>` +
    `<span class="line-dot" style="left:${lx.toFixed(2)}%;top:${ly.toFixed(2)}%"></span>` +
    `<span class="line-value" style="left:${lx.toFixed(2)}%;top:${ly.toFixed(2)}%">${fmt(last, chart.unit)}</span>` +
    `</div>${labels}</div>`;
}

function donut(chart: Chart): string {
  const values = chart.series[0].values;
  const total = values.reduce((a, b) => a + b, 0) || 1;
  const r = 80, c = 2 * Math.PI * r;
  let offset = 0;
  const palette = ['s-accent', 's-accent2', 's-muted', 's-dim', 's-surface'];
  const segs = values.map((v, i) => {
    const len = (v / total) * c;
    const seg = `<circle class="seg ${palette[i % palette.length]}" r="${r}" cx="100" cy="100" ` +
      `stroke-dasharray="${len.toFixed(2)} ${(c - len).toFixed(2)}" stroke-dashoffset="${(-offset).toFixed(2)}"/>`;
    offset += len;
    return seg;
  }).join('');
  const lead = chart.highlight ?? 0;
  const pct = Math.round(((values[lead] ?? 0) / total) * 100);
  const items = values.map((v, i) =>
    `<span><i class="${palette[i % palette.length]}"></i>${esc(chart.labels?.[i] ?? `#${i + 1}`)} <b>${fmt(v, chart.unit)}</b></span>`).join('');
  return `<div class="chart chart-donut"><div class="donut"><svg viewBox="0 0 200 200">` +
    `<g transform="rotate(-90 100 100)">${segs}</g></svg><div class="donut-center">${pct}%</div></div>` +
    `<div class="chart-legend vertical">${items}</div></div>`;
}

function progress(chart: Chart): string {
  const values = chart.series[0].values;
  const max = chart.unit === '%' ? 100 : Math.max(...values) || 1;
  const rows = values.map((v, i) => {
    const dim = chart.highlight !== undefined && chart.highlight !== i;
    return `<div class="progress-row${dim ? ' dim' : ''}"><div class="progress-head"><span>${esc(chart.labels?.[i] ?? '')}</span>` +
      `<b>${fmt(v, chart.unit)}</b></div><div class="progress-track"><div class="progress-fill ${dim ? 's-dim' : 's-accent'}" ` +
      `style="width:${Math.min(100, (v / max) * 100).toFixed(2)}%"></div></div></div>`;
  }).join('');
  return `<div class="chart chart-progress">${rows}</div>`;
}

export function renderChart(chart: Chart): string {
  switch (chart.type) {
    case 'bar': return bar(chart);
    case 'line': return line(chart, false);
    case 'area': return line(chart, true);
    case 'donut': return donut(chart);
    case 'progress': return progress(chart);
  }
}
