import type { Deck, Slide, Tile } from './schema.js';
import { THEMES, type Theme } from './themes.js';
import { renderChart } from './charts.js';
import { esc, inline } from './text.js';

// Renders a whole deck into one self-contained HTML page. The same page serves
// three modes, picked by the URL hash: the presenter view (default), an
// overview grid (#grid), and print (#print — every slide stacked at native
// 1920×1080, used for PDF, screenshots, and render checks).

export const SLIDE_W = 1920;
export const SLIDE_H = 1080;
const PAD_X = 120;
const PAD_TOP = 100;
const PAD_BOTTOM = 130;
const GAP = 24;

function themeVars(t: Theme): string {
  const c = t.colors;
  return `--bg:${c.bg};--surface:${c.surface};--surface2:${c.surface2};--border:${c.border};` +
    `--text:${c.text};--muted:${c.muted};--accent:${c.accent};--on-accent:${c.onAccent};` +
    `--accent2:${c.accent2};--on-accent2:${c.onAccent2};--radius:${t.radius}px;` +
    `--font-display:'${t.fonts.display}',system-ui,sans-serif;--font-body:'${t.fonts.body}',system-ui,sans-serif;` +
    `--font-mono:'${t.fonts.mono}',ui-monospace,monospace;--display-weight:${t.displayWeight};` +
    `--display-tracking:${t.displayTracking};--dw:${t.displayWidth};`;
}

const attr = esc;
const opt = (s: string | undefined, f: (s: string) => string) => (s ? f(s) : '');
const eyebrow = (s?: string) => opt(s, v => `<div class="eyebrow">${inline(v)}</div>`);

// ---------------------------------------------------------------- bento

interface Box { w: number; h: number }

/** Pixel size of a tile, so type can be sized to the box instead of guessed. */
function tileBox(tile: Tile, cols: number, rows: number, hasHeader: boolean): Box {
  const gridW = SLIDE_W - PAD_X * 2;
  const gridH = SLIDE_H - PAD_TOP - PAD_BOTTOM - (hasHeader ? 130 : 0);
  const cw = (gridW - GAP * (cols - 1)) / cols;
  const ch = (gridH - GAP * (rows - 1)) / rows;
  return { w: cw * tile.w + GAP * (tile.w - 1), h: ch * tile.h + GAP * (tile.h - 1) };
}

function clamp(v: number, lo: number, hi: number): number {
  return Math.max(lo, Math.min(hi, v));
}

function tileHtml(tile: Tile, box: Box, charW: number): string {
  const pos = `grid-column:${tile.x + 1} / span ${tile.w};grid-row:${tile.y + 1} / span ${tile.h};`;
  const acc = tile.accent && tile.accent !== 'none' ? ` tone-${tile.accent}` : '';
  // A display size that a short heading can carry in this box.
  const head = Math.round(clamp(Math.min(box.h * 0.16, box.w * 0.075), 30, 56));
  let inner: string;
  switch (tile.kind) {
    case 'stat': {
      const byH = box.h * (tile.caption ? 0.38 : 0.46);
      const byW = (box.w - 96) / Math.max(2.2, tile.value.length * charW);
      const size = Math.round(clamp(Math.min(byH, byW), 56, 230));
      inner = `<div class="t-label">${inline(tile.label)}</div><div class="t-spacer"></div>` +
        `<div class="t-value" style="font-size:calc(${size} * var(--u))">${esc(tile.value)}</div>` +
        opt(tile.caption, c => `<div class="t-caption">${inline(c)}</div>`);
      break;
    }
    case 'text':
      inner = opt(tile.eyebrow, e => `<div class="t-eyebrow">${inline(e)}</div>`) +
        `<div class="t-spacer"></div>` +
        opt(tile.title, t => `<div class="t-title" style="font-size:calc(${head} * var(--u))">${inline(t)}</div>`) +
        opt(tile.body, b => `<div class="t-body">${inline(b)}</div>`);
      break;
    case 'list':
      inner = opt(tile.title, t => `<div class="t-title" style="font-size:calc(${Math.min(head, 40)} * var(--u))">${inline(t)}</div>`) +
        `<ul class="t-list">${tile.items.map(i => `<li>${inline(i)}</li>`).join('')}</ul>`;
      break;
    case 'chart':
      inner = opt(tile.title, t => `<div class="t-label">${inline(t)}</div>`) + renderChart(tile.chart);
      break;
    case 'image':
      inner = `<img src="${attr(tile.src)}" alt="${attr(tile.alt ?? '')}">` +
        opt(tile.caption, c => `<div class="t-image-caption">${inline(c)}</div>`);
      break;
    case 'quote':
      inner = `<div class="t-quote-mark">“</div><div class="t-quote" style="font-size:calc(${Math.min(head, 46)} * var(--u))">${inline(tile.quote)}</div>` +
        opt(tile.author, a => `<div class="t-caption">${inline(a)}</div>`);
      break;
  }
  return `<div class="tile kind-${tile.kind}${acc}" style="${pos}" data-fit>${inner}</div>`;
}

function bento(s: Extract<Slide, { layout: 'bento' }>, theme: Theme): string {
  const header = !!(s.title || s.eyebrow);
  const tiles = s.tiles.map(t => tileHtml(t, tileBox(t, s.grid.cols, s.grid.rows, header), theme.displayWidth)).join('');
  return (header ? `<header class="head">${eyebrow(s.eyebrow)}${opt(s.title, t => `<h2 class="h-m">${inline(t)}</h2>`)}</header>` : '') +
    `<div class="bento" style="grid-template-columns:repeat(${s.grid.cols},1fr);grid-template-rows:repeat(${s.grid.rows},1fr)">${tiles}</div>`;
}

// ---------------------------------------------------------------- layouts

function visual(v: Extract<Slide, { layout: 'split' }>['visual']): string {
  switch (v.kind) {
    case 'image': return `<div class="visual visual-image"><img src="${attr(v.src)}" alt="${attr(v.alt ?? '')}"></div>`;
    case 'chart': return `<div class="visual visual-chart">${renderChart(v.chart)}</div>`;
    case 'stat': return `<div class="visual visual-stat"><div class="v-value">${esc(v.value)}</div><div class="v-label">${inline(v.label)}</div></div>`;
  }
}

function slideBody(s: Slide, theme: Theme): string {
  switch (s.layout) {
    case 'title':
      return `<div class="content" data-fit>${eyebrow(s.eyebrow)}<div class="grow"></div>` +
        `<h1 class="h-xl">${inline(s.title)}</h1>` +
        opt(s.subtitle, v => `<p class="lead">${inline(v)}</p>`) +
        opt(s.meta, v => `<div class="meta">${inline(v)}</div>`) + `</div>`;
    case 'section':
      return `<div class="content" data-fit><div class="grow"></div>` +
        opt(s.number, n => `<div class="section-number">${esc(n)}</div>`) +
        `<h1 class="h-l">${inline(s.title)}</h1>` + opt(s.subtitle, v => `<p class="lead">${inline(v)}</p>`) + `</div>`;
    case 'statement':
      return `<div class="content center-y" data-fit>${eyebrow(s.eyebrow)}<h1 class="h-statement">${inline(s.statement)}</h1>` +
        opt(s.support, v => `<p class="lead">${inline(v)}</p>`) + `</div>`;
    case 'bullets': {
      const big = s.bullets.length <= 3;
      return `<div class="content" data-fit><header class="head">${eyebrow(s.eyebrow)}<h2 class="h-m">${inline(s.title)}</h2></header>` +
        `<ol class="bullets${big ? ' big' : ''}">${s.bullets.map((b, i) =>
          `<li><span class="num">${String(i + 1).padStart(2, '0')}</span><span>${inline(b)}</span></li>`).join('')}</ol></div>`;
    }
    case 'bento':
      return `<div class="content">${bento(s, theme)}</div>`;
    case 'split': {
      const text = `<div class="split-text" data-fit>${eyebrow(s.eyebrow)}<h2 class="h-m">${inline(s.title)}</h2>` +
        opt(s.body, b => `<p class="body">${inline(b)}</p>`) +
        (s.bullets?.length ? `<ul class="ticks">${s.bullets.map(b => `<li>${inline(b)}</li>`).join('')}</ul>` : '') + `</div>`;
      return `<div class="content split${s.side === 'left' ? ' visual-left' : ''}">${text}${visual(s.visual)}</div>`;
    }
    case 'stats':
      return `<div class="content" data-fit>` +
        (s.title || s.eyebrow ? `<header class="head">${eyebrow(s.eyebrow)}${opt(s.title, t => `<h2 class="h-m">${inline(t)}</h2>`)}</header>` : '') +
        `<div class="grow"></div><div class="stats n${s.stats.length}">${s.stats.map((st, i) =>
          `<div class="stat${i === 0 ? ' lead-stat' : ''}"><div class="s-value">${esc(st.value)}</div>` +
          `<div class="s-label">${inline(st.label)}</div>${opt(st.caption, c => `<div class="s-caption">${inline(c)}</div>`)}</div>`).join('')}</div></div>`;
    case 'quote':
      return `<div class="content center-y" data-fit><div class="quote-mark">“</div><blockquote class="h-quote">${inline(s.quote)}</blockquote>` +
        (s.author ? `<div class="quote-author"><b>${inline(s.author)}</b>${opt(s.role, r => `<span>${inline(r)}</span>`)}</div>` : '') + `</div>`;
    case 'timeline':
      return `<div class="content" data-fit><header class="head">${eyebrow(s.eyebrow)}<h2 class="h-m">${inline(s.title)}</h2></header>` +
        `<div class="grow"></div><div class="timeline n${s.steps.length}">${s.steps.map(st =>
          `<div class="step"><div class="step-label">${esc(st.label)}</div><div class="step-dot"></div>` +
          `<div class="step-title">${inline(st.title)}</div>${opt(st.body, b => `<div class="step-body">${inline(b)}</div>`)}</div>`).join('')}</div><div class="grow"></div></div>`;
    case 'compare':
      return `<div class="content" data-fit><header class="head">${eyebrow(s.eyebrow)}<h2 class="h-m">${inline(s.title)}</h2></header>` +
        `<div class="compare">${s.columns.map(c =>
          `<div class="col${c.highlight ? ' hl' : ''}"><div class="col-title">${inline(c.title)}</div>` +
          `<ul>${c.items.map(i => `<li>${inline(i)}</li>`).join('')}</ul></div>`).join('')}</div></div>`;
    case 'image':
      return `<div class="full-image"><img src="${attr(s.src)}" alt="${attr(s.alt ?? '')}"></div>` +
        (s.title || s.caption ? `<div class="content image-overlay" data-fit><div class="grow"></div>` +
          opt(s.title, t => `<h2 class="h-m">${inline(t)}</h2>`) + opt(s.caption, c => `<p class="lead">${inline(c)}</p>`) + `</div>` : '');
  }
}

const GLOW_LAYOUTS = new Set(['title', 'section', 'statement', 'quote']);

function slideHtml(deck: Deck, s: Slide, i: number): string {
  const glow = GLOW_LAYOUTS.has(s.layout) ? ' glow' : '';
  const footer = s.layout === 'image' ? '' :
    `<footer class="footer"><span>${esc(deck.footer ?? '')}</span><span class="page">${String(i + 1).padStart(2, '0')}</span></footer>`;
  return `<section class="slide layout-${s.layout}${glow}" data-index="${i}">${slideBody(s, THEMES[deck.theme])}${footer}</section>`;
}

// ---------------------------------------------------------------- page

const CSS = /* css */ `
*{box-sizing:border-box;margin:0;padding:0}
:root{--u:1px}
html,body{background:#050505}
body{font-family:var(--font-body);color:var(--text);-webkit-font-smoothing:antialiased;text-rendering:geometricPrecision;font-feature-settings:"ss01","cv11"}
.slide{width:${SLIDE_W}px;height:${SLIDE_H}px;position:relative;overflow:hidden;background:var(--bg);
  padding:${PAD_TOP}px ${PAD_X}px ${PAD_BOTTOM}px;display:flex;flex-direction:column}
.slide.glow::before{content:"";position:absolute;inset:-30% -10% auto auto;width:1300px;height:1300px;border-radius:50%;
  background:radial-gradient(closest-side,color-mix(in srgb,var(--accent) 22%,transparent),transparent);pointer-events:none}
.slide.glow::after{content:"";position:absolute;left:-400px;bottom:-700px;width:1200px;height:1200px;border-radius:50%;
  background:radial-gradient(closest-side,color-mix(in srgb,var(--accent2) 12%,transparent),transparent);pointer-events:none}
[data-fit]{--fit:1;--u:calc(1px * var(--fit))}
.content{position:relative;z-index:1;flex:1;min-height:0;display:flex;flex-direction:column;overflow:hidden}
.center-y{justify-content:center}
.grow{flex:1}
.footer{position:absolute;left:${PAD_X}px;right:${PAD_X}px;bottom:48px;display:flex;justify-content:space-between;
  font-size:20px;color:var(--muted);letter-spacing:.04em;z-index:1}
.footer .page{font-family:var(--font-mono);font-variant-numeric:tabular-nums}
strong{font-weight:650;color:var(--text)}
mark{background:none;color:var(--accent)}
code{font-family:var(--font-mono);font-size:.9em;background:var(--surface2);padding:.05em .3em;border-radius:6px}

.eyebrow{font-size:calc(22 * var(--u));font-weight:600;letter-spacing:.16em;text-transform:uppercase;color:var(--accent);margin-bottom:calc(28 * var(--u))}
.h-xl,.h-l,.h-m,.h-statement,.h-quote{font-family:var(--font-display);font-weight:var(--display-weight);letter-spacing:var(--display-tracking);text-wrap:balance}
.h-xl{font-size:calc(132 * var(--u));line-height:1;max-width:1560px}
.h-l{font-size:calc(116 * var(--u));line-height:1.02;max-width:1500px}
.h-m{font-size:calc(64 * var(--u));line-height:1.06;max-width:1480px}
.h-statement{font-size:calc(84 * var(--u));line-height:1.08;max-width:1520px}
.lead{font-size:calc(36 * var(--u));line-height:1.4;color:var(--muted);margin-top:calc(36 * var(--u));max-width:1200px;text-wrap:pretty}
.body{font-size:calc(32 * var(--u));line-height:1.5;color:var(--muted);margin-top:calc(32 * var(--u));text-wrap:pretty}
.meta{margin-top:calc(56 * var(--u));padding-top:calc(28 * var(--u));border-top:1px solid var(--border);font-size:calc(24 * var(--u));color:var(--muted);max-width:1200px}
.head{margin-bottom:calc(52 * var(--u))}
.layout-bento .head{margin-bottom:0;height:130px;flex:none}
.layout-bento .head .h-m{font-size:52px}
.layout-bento .head .eyebrow{margin-bottom:18px}

.layout-section{background:var(--surface)}
.section-number{font-family:var(--font-mono);font-size:calc(28 * var(--u));color:var(--accent);margin-bottom:calc(36 * var(--u));
  padding:calc(10 * var(--u)) calc(20 * var(--u));border:1px solid var(--accent);border-radius:999px;align-self:flex-start}

.bullets{list-style:none;display:flex;flex-direction:column;gap:calc(30 * var(--u));margin:auto 0}
.bullets li{display:grid;grid-template-columns:calc(90 * var(--u)) 1fr;align-items:baseline;font-size:calc(38 * var(--u));line-height:1.35;
  padding-bottom:calc(30 * var(--u));border-bottom:1px solid var(--border);text-wrap:pretty}
.bullets li:last-child{border-bottom:none}
.bullets.big li{font-size:calc(50 * var(--u));line-height:1.25;font-family:var(--font-display);letter-spacing:var(--display-tracking);font-weight:500}
.bullets .num{font-family:var(--font-mono);font-size:calc(24 * var(--u));color:var(--accent);letter-spacing:0;font-weight:500}

.bento{flex:1;min-height:0;display:grid;gap:${GAP}px}
.tile{--fg:var(--text);--fg2:var(--muted);position:relative;background:var(--surface);border-radius:var(--radius);padding:40px;
  display:flex;flex-direction:column;overflow:hidden;color:var(--fg);min-width:0;min-height:0}
.tile.tone-accent{background:var(--accent);--fg:var(--on-accent);--fg2:color-mix(in srgb,var(--on-accent) 70%,transparent)}
.tile.tone-accent2{background:var(--accent2);--fg:var(--on-accent2);--fg2:color-mix(in srgb,var(--on-accent2) 70%,transparent)}
.tile.tone-muted{background:var(--surface2)}
.tile strong{color:var(--fg)}
.tile.tone-accent mark,.tile.tone-accent2 mark{color:var(--fg);text-decoration:underline;text-underline-offset:.15em}
.t-spacer{flex:1;min-height:12px}
.t-label,.t-eyebrow{font-size:calc(22 * var(--u));font-weight:600;color:var(--fg2);letter-spacing:.02em;line-height:1.3}
.t-eyebrow{text-transform:uppercase;letter-spacing:.14em;font-size:calc(19 * var(--u))}
.t-value{font-family:var(--font-display);font-weight:var(--display-weight);letter-spacing:-.045em;line-height:.92;font-variant-numeric:tabular-nums;white-space:nowrap}
.t-caption{font-size:calc(22 * var(--u));color:var(--fg2);margin-top:calc(14 * var(--u));line-height:1.35}
.t-title{font-family:var(--font-display);font-weight:var(--display-weight);letter-spacing:var(--display-tracking);line-height:1.08;text-wrap:balance}
.t-body{font-size:calc(24 * var(--u));line-height:1.45;color:var(--fg2);margin-top:calc(14 * var(--u));text-wrap:pretty}
.t-list{list-style:none;margin-top:calc(22 * var(--u));display:flex;flex-direction:column;gap:calc(14 * var(--u))}
.t-list li{font-size:calc(25 * var(--u));line-height:1.35;padding-left:calc(34 * var(--u));position:relative}
.t-list li::before{content:"";position:absolute;left:0;top:.5em;width:calc(12 * var(--u));height:calc(12 * var(--u));border-radius:50%;background:var(--accent)}
.tone-accent .t-list li::before,.tone-accent2 .t-list li::before{background:var(--fg)}
.kind-image{padding:0}
.kind-image img{position:absolute;inset:0;width:100%;height:100%;object-fit:cover}
.t-image-caption{position:absolute;left:0;right:0;bottom:0;padding:60px 32px 26px;font-size:22px;color:#fff;
  background:linear-gradient(transparent,rgba(0,0,0,.65))}
.t-quote-mark{font-family:var(--font-display);font-size:calc(110 * var(--u));line-height:.7;color:var(--accent);height:calc(56 * var(--u))}
.tone-accent .t-quote-mark,.tone-accent2 .t-quote-mark{color:var(--fg)}
.t-quote{font-family:var(--font-display);letter-spacing:var(--display-tracking);line-height:1.18;margin-top:auto;text-wrap:balance}
.kind-chart .chart{margin-top:calc(20 * var(--u))}

.chart{flex:1;min-height:0;display:flex;flex-direction:column;--c-accent:var(--accent);--c-accent2:var(--accent2)}
.tone-accent .chart,.tone-accent2 .chart{--c-accent:var(--fg);--c-accent2:var(--fg2)}
.s-accent{background:var(--c-accent);stroke:var(--c-accent)}
.s-accent2{background:var(--c-accent2);stroke:var(--c-accent2)}
.s-muted{background:var(--muted);stroke:var(--muted)}
.s-dim{background:color-mix(in srgb,var(--fg,var(--text)) 16%,transparent);stroke:color-mix(in srgb,var(--fg,var(--text)) 16%,transparent)}
.s-surface{background:var(--surface2);stroke:var(--surface2)}
.chart-legend{display:flex;gap:28px;font-size:20px;color:var(--fg2,var(--muted));margin-bottom:18px;flex-wrap:wrap}
.chart-legend span{display:inline-flex;align-items:center;gap:10px}
.chart-legend i{width:14px;height:14px;border-radius:4px;display:inline-block}
.chart-legend.vertical{flex-direction:column;gap:14px;font-size:22px;margin:0;justify-content:center}
.chart-legend.vertical b{color:var(--fg,var(--text));font-weight:600;margin-left:6px}
.bars{flex:1;min-height:0;display:flex;align-items:stretch;gap:3%}
.bar-group{flex:1;display:flex;flex-direction:column;min-width:0}
.bar-stack{flex:1;display:flex;align-items:flex-end;gap:6px;min-height:0;padding-top:40px}
.bar{flex:1;border-radius:calc(var(--radius) * .3) calc(var(--radius) * .3) 4px 4px;position:relative;min-height:2px}
.bar-value{position:absolute;bottom:100%;left:50%;transform:translateX(-50%);padding-bottom:8px;font-size:22px;font-weight:600;
  color:var(--fg,var(--text));white-space:nowrap;font-variant-numeric:tabular-nums}
.bar-label{font-size:19px;color:var(--fg2,var(--muted));text-align:center;margin-top:12px;white-space:nowrap;overflow:hidden;text-overflow:ellipsis}
.dim{opacity:.55}
.bar-value.dim{opacity:.7}
.line-plot{flex:1;min-height:0;position:relative}
.line-plot svg{position:absolute;inset:0;width:100%;height:100%;overflow:visible}
.line-plot .line{fill:none;stroke-width:5;stroke-linecap:round;stroke-linejoin:round;background:none}
.line-plot .area{stroke:none;opacity:.16;background:none;fill:var(--c-accent)}
.line-plot .line.s-accent2{stroke-dasharray:2 10;stroke-width:4}
.line-dot{position:absolute;width:20px;height:20px;border-radius:50%;background:var(--c-accent);transform:translate(-50%,-50%);
  box-shadow:0 0 0 8px color-mix(in srgb,var(--c-accent) 25%,transparent)}
.line-value{position:absolute;transform:translate(-100%,-150%);font-size:26px;font-weight:650;color:var(--fg,var(--text));
  white-space:nowrap;font-variant-numeric:tabular-nums;padding-right:4px}
.line-labels{display:flex;justify-content:space-between;font-size:19px;color:var(--fg2,var(--muted));margin-top:14px}
.chart-donut{flex-direction:row;align-items:center;gap:40px}
.donut{position:relative;height:100%;aspect-ratio:1;max-height:100%;min-height:0;flex:none;container-type:size}
.donut svg{width:100%;height:100%}
.donut .seg{fill:none;stroke-width:30;background:none}
.donut-center{position:absolute;inset:0;display:flex;align-items:center;justify-content:center;font-family:var(--font-display);
  font-weight:var(--display-weight);letter-spacing:-.04em;font-size:clamp(20px,calc(12cqmin / var(--dw)),64px)}
.chart-progress{justify-content:center;gap:24px}
.progress-head{display:flex;justify-content:space-between;font-size:23px;margin-bottom:10px}
.progress-head b{font-weight:600;font-variant-numeric:tabular-nums}
.progress-track{height:14px;border-radius:999px;background:color-mix(in srgb,var(--fg,var(--text)) 10%,transparent);overflow:hidden}
.progress-fill{height:100%;border-radius:999px}

.split{flex-direction:row;gap:80px;align-items:stretch}
.split.visual-left{flex-direction:row-reverse}
.split-text{flex:1 1 0;min-width:0;display:flex;flex-direction:column;justify-content:center;overflow:hidden}
.visual{flex:1 1 0;min-width:0;border-radius:var(--radius);overflow:hidden;position:relative}
.visual-image img{position:absolute;inset:0;width:100%;height:100%;object-fit:cover}
.visual-chart{background:var(--surface);padding:48px;display:flex;flex-direction:column}
.visual-stat{background:var(--accent);color:var(--on-accent);padding:56px;display:flex;flex-direction:column;justify-content:flex-end}
.v-value{font-family:var(--font-display);font-weight:var(--display-weight);font-size:220px;letter-spacing:-.05em;line-height:.9}
.v-label{font-size:34px;margin-top:24px;opacity:.8;line-height:1.3}
.ticks{list-style:none;margin-top:calc(36 * var(--u));display:flex;flex-direction:column;gap:calc(20 * var(--u))}
.ticks li{font-size:calc(30 * var(--u));line-height:1.4;padding-left:calc(46 * var(--u));position:relative}
.ticks li::before{content:"";position:absolute;left:0;top:.28em;width:calc(26 * var(--u));height:calc(26 * var(--u));border-radius:50%;
  background:color-mix(in srgb,var(--accent) 22%,transparent);box-shadow:inset 0 0 0 calc(7 * var(--u)) var(--accent)}

.stats{display:grid;gap:0}
.stats.n2{grid-template-columns:repeat(2,1fr)}.stats.n3{grid-template-columns:repeat(3,1fr)}.stats.n4{grid-template-columns:repeat(4,1fr)}
.stat{padding:0 calc(48 * var(--u));border-left:1px solid var(--border)}
.stat:first-child{padding-left:0;border-left:none}
.s-value{font-family:var(--font-display);font-weight:var(--display-weight);letter-spacing:-.05em;line-height:.95;font-variant-numeric:tabular-nums;
  font-size:calc(150 * var(--u));white-space:nowrap}
.stats.n4 .s-value{font-size:calc(116 * var(--u))}
.lead-stat .s-value{color:var(--accent)}
.s-label{font-size:calc(30 * var(--u));margin-top:calc(26 * var(--u));line-height:1.3;font-weight:500}
.s-caption{font-size:calc(22 * var(--u));margin-top:calc(10 * var(--u));color:var(--muted);line-height:1.4}

.quote-mark{font-family:var(--font-display);font-size:calc(260 * var(--u));line-height:.6;color:var(--accent);height:calc(120 * var(--u))}
.h-quote{font-size:calc(70 * var(--u));line-height:1.14;max-width:1560px}
.quote-author{margin-top:calc(56 * var(--u));font-size:calc(30 * var(--u));display:flex;gap:18px;align-items:baseline}
.quote-author b{font-weight:600}
.quote-author span{color:var(--muted)}
.quote-author span::before{content:"— "}

.timeline{display:grid;grid-auto-flow:column;grid-auto-columns:1fr;gap:40px;position:relative}
.timeline::before{content:"";position:absolute;left:0;right:0;top:calc(62 * var(--u));height:2px;background:var(--border)}
.step-label{font-family:var(--font-mono);font-size:calc(22 * var(--u));color:var(--accent);height:calc(44 * var(--u))}
.step-dot{width:calc(36 * var(--u));height:calc(36 * var(--u));border-radius:50%;background:var(--bg);border:3px solid var(--accent);
  position:relative;z-index:1;margin-bottom:calc(36 * var(--u))}
.step:first-child .step-dot{background:var(--accent)}
.step-title{font-family:var(--font-display);font-weight:var(--display-weight);letter-spacing:var(--display-tracking);font-size:calc(36 * var(--u));line-height:1.15;text-wrap:balance}
.step-body{font-size:calc(24 * var(--u));color:var(--muted);line-height:1.45;margin-top:calc(14 * var(--u));text-wrap:pretty}

.compare{margin:auto 0;display:grid;grid-template-columns:1fr 1fr;gap:${GAP}px}
.col{background:var(--surface);border-radius:var(--radius);padding:56px 56px 64px;border:2px solid transparent}
.col.hl{border-color:var(--accent);background:color-mix(in srgb,var(--accent) 7%,var(--surface))}
.col-title{font-family:var(--font-display);font-weight:var(--display-weight);letter-spacing:var(--display-tracking);font-size:calc(52 * var(--u));margin-bottom:calc(40 * var(--u))}
.col.hl .col-title{color:var(--accent)}
.col ul{list-style:none;display:flex;flex-direction:column;gap:calc(20 * var(--u))}
.col li{font-size:calc(34 * var(--u));line-height:1.4;padding-left:calc(44 * var(--u));position:relative;color:var(--muted)}
.col li::before{content:"–";position:absolute;left:0;color:var(--muted)}
.col.hl li{color:var(--text)}
.col.hl li::before{content:"✓";color:var(--accent);font-weight:700}

.layout-image{padding:0}
.full-image{position:absolute;inset:0}
.full-image img{width:100%;height:100%;object-fit:cover}
.image-overlay{position:absolute;inset:0;padding:${PAD_TOP}px ${PAD_X}px 96px;background:linear-gradient(transparent 45%,rgba(0,0,0,.72));--text:#fff;--muted:rgba(255,255,255,.8);color:#fff}

/* modes */
body.present{overflow:hidden;height:100vh}
body.present .slide{position:absolute;left:50%;top:50%;transform-origin:center;display:none}
body.present .slide.active{display:flex}
body.grid{padding:32px;display:grid;grid-template-columns:repeat(auto-fill,minmax(480px,1fr));gap:24px}
body.grid .cell{aspect-ratio:16/9;position:relative;overflow:hidden;border-radius:10px;cursor:pointer;outline:1px solid #222}
body.grid .slide{transform-origin:0 0;position:absolute;left:0;top:0}
body.print .slide{break-after:page}
@page{size:${SLIDE_W}px ${SLIDE_H}px;margin:0}
.hud{position:fixed;bottom:16px;right:20px;font:13px/1 system-ui;color:#888;z-index:10;user-select:none}
body:not(.present) .hud,body:not(.present) .hud-pdf{display:none}
.hud-pdf{position:fixed;bottom:12px;left:20px;font:13px/1 system-ui;color:#aaa;z-index:10;text-decoration:none;padding:6px 10px;border:1px solid #333;border-radius:6px;background:rgba(0,0,0,.4)}
.hud-pdf:hover{color:#fff;border-color:#666}
.hud,.hud-pdf{transition:opacity .4s}
body.idle .hud,body.idle .hud-pdf{opacity:0}
`;

const SCRIPT = /* js */ `
(function(){
  var slides=[].slice.call(document.querySelectorAll('.slide'));
  // Shrink type inside every [data-fit] box until it stops overflowing; mark
  // the ones that still overflow at the floor so render checks can report them.
  // Measured from element boxes, not el.scrollHeight: Chromium counts glyph
  // ascenders that poke out of a tight line-height as scroll overflow, which
  // would shrink a perfectly fitting headline.
  function overflowing(el){
    // Content may eat into half of the box padding before it counts as overflow.
    var r=el.getBoundingClientRect(),cs=getComputedStyle(el);
    var bottom=r.bottom-parseFloat(cs.paddingBottom)/2,right=r.right-parseFloat(cs.paddingRight)/2;
    var kids=el.querySelectorAll('*');
    for(var i=0;i<kids.length;i++){
      var k=kids[i],ks=getComputedStyle(k);
      if(ks.position==='absolute'||ks.position==='fixed')continue;
      var kr=k.getBoundingClientRect();
      if(kr.bottom>bottom+2||kr.right>right+2)return true;
      if(ks.overflowX==='visible'&&k.clientWidth&&k.scrollWidth>k.clientWidth+2)return true;
    }
    return false;
  }
  function fit(){
    document.querySelectorAll('[data-fit]').forEach(function(el){
      var f=1;el.style.setProperty('--fit','1');el.removeAttribute('data-overflow');el.removeAttribute('data-shrunk');
      while(overflowing(el)&&f>0.62){f-=0.03;el.style.setProperty('--fit',f.toFixed(2))}
      if(f<1)el.setAttribute('data-shrunk',f.toFixed(2));
      if(overflowing(el))el.setAttribute('data-overflow','1');
    });
  }
  var mode=location.hash.indexOf('print')>=0?'print':location.hash.indexOf('grid')>=0?'grid':'present';
  document.body.className=mode;
  var ready=(document.fonts&&document.fonts.ready)||Promise.resolve();
  var imgs=[].slice.call(document.images).map(function(i){return i.complete?0:new Promise(function(r){i.onload=i.onerror=r})});
  Promise.all([ready].concat(imgs)).then(function(){fit();window.__slidesReady=true});
  if(mode==='grid'){
    slides.forEach(function(s,i){var c=document.createElement('div');c.className='cell';s.parentNode.insertBefore(c,s);c.appendChild(s);
      c.onclick=function(){location.hash='slide='+(i+1);location.reload()}});
    function scaleGrid(){document.querySelectorAll('.cell').forEach(function(c){c.firstChild.style.transform='scale('+(c.clientWidth/${SLIDE_W})+')'})}
    addEventListener('resize',scaleGrid);scaleGrid();return;
  }
  if(mode!=='present')return;
  var hud=document.createElement('div');hud.className='hud';document.body.appendChild(hud);
  var m=location.hash.match(/slide=(\\d+)/),cur=m?Math.min(slides.length-1,Math.max(0,+m[1]-1)):0;
  function scale(){var k=Math.min(innerWidth/${SLIDE_W},innerHeight/${SLIDE_H});
    slides.forEach(function(s){s.style.transform='translate(-50%,-50%) scale('+k+')'})}
  function show(i){cur=Math.max(0,Math.min(slides.length-1,i));slides.forEach(function(s,j){s.classList.toggle('active',j===cur)});
    hud.textContent=(cur+1)+' / '+slides.length+'  ·  G — overview';history.replaceState(null,'','#slide='+(cur+1))}
  // Controls overlap the slide footer when the window is exactly 16:9, so
  // they only show while the mouse moves.
  var idle;function wake(){document.body.classList.remove('idle');clearTimeout(idle);idle=setTimeout(function(){document.body.classList.add('idle')},2000)}
  addEventListener('mousemove',wake);wake();
  addEventListener('resize',scale);
  addEventListener('keydown',function(e){
    if(['ArrowRight','ArrowDown','PageDown',' '].indexOf(e.key)>=0)show(cur+1);
    else if(['ArrowLeft','ArrowUp','PageUp'].indexOf(e.key)>=0)show(cur-1);
    else if(e.key==='Home')show(0);else if(e.key==='End')show(slides.length-1);
    else if(e.key==='g'||e.key==='G'){location.hash='grid';location.reload()}
    else if(e.key==='f'||e.key==='F'){document.fullscreenElement?document.exitFullscreen():document.documentElement.requestFullscreen()}
  });
  addEventListener('click',function(e){if(e.target.closest('a'))return;show(e.clientX>innerWidth/3?cur+1:cur-1)});
  scale();show(cur);
})();
`;

export interface RenderOptions {
  /** Stylesheet with local @font-face rules (relative to the page). Default: Google Fonts. */
  fontsHref?: string;
  /** PDF of the deck next to the page; adds a download link to the presenter HUD. */
  pdfHref?: string;
}

export function renderDeck(deck: Deck, opts: RenderOptions = {}): string {
  const theme = THEMES[deck.theme];
  const fonts = opts.fontsHref
    ? `<link rel="stylesheet" href="${attr(opts.fontsHref)}">`
    : `<link rel="preconnect" href="https://fonts.googleapis.com"><link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>` +
      `<link rel="stylesheet" href="https://fonts.googleapis.com/css2?${theme.googleFonts.map(f => `family=${f}`).join('&')}&display=block">`;
  const pdf = opts.pdfHref ? `<a class="hud-pdf" href="${attr(opts.pdfHref)}" download>PDF ↓</a>` : '';
  const slides = deck.slides.length
    ? deck.slides.map((s, i) => slideHtml(deck, s, i)).join('\n')
    : `<section class="slide glow"><div class="content center-y"><div class="eyebrow">Empty deck</div><h1 class="h-l">${esc(deck.title)}</h1></div></section>`;
  return `<!doctype html><html lang="ru"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">` +
    `<title>${esc(deck.title)}</title>${fonts}` +
    `<style>:root{${themeVars(theme)}}${CSS}</style></head><body class="print">${slides}${pdf}<script>${SCRIPT}</script></body></html>`;
}
