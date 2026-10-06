import type { Chart, Deck, Slide } from './schema.js';
import { words } from './text.js';

// Static design checks. They encode the rules that separate a designed deck
// from a wall of text, and they run on every edit so the agent hears about a
// problem while it still has the slide in mind. "error" means the slide will
// render broken; "warn" means it will render but look worse than it should.

export interface Issue {
  slide: number | null;
  level: 'error' | 'warn';
  message: string;
}

const MAX_WORDS = 45;
const MAX_TITLE_WORDS = 12;
const MAX_BULLET_WORDS = 18;

function chartIssues(c: Chart, at: string): string[] {
  const out: string[] = [];
  const n = c.series[0].values.length;
  if (c.labels && c.labels.length !== n) {
    out.push(`${at}: ${c.labels.length} labels for ${n} values`);
  }
  if ((c.type === 'donut' || c.type === 'progress') && c.series.length > 1) {
    out.push(`${at}: ${c.type} charts use only the first series`);
  }
  if (c.type === 'bar' && n > 12) out.push(`${at}: ${n} bars is unreadable at slide size; keep it to 12 or fewer`);
  if (c.type === 'donut' && n > 5) out.push(`${at}: donut with ${n} segments; merge the small ones into "Other" (max 5)`);
  if (c.highlight !== undefined && c.highlight >= n) out.push(`${at}: highlight index ${c.highlight} is out of range`);
  return out;
}

function slideWords(s: Slide): number {
  switch (s.layout) {
    case 'title': return words(s.eyebrow, s.title, s.subtitle, s.meta);
    case 'section': return words(s.title, s.subtitle);
    case 'statement': return words(s.eyebrow, s.statement, s.support);
    case 'bullets': return words(s.eyebrow, s.title, ...s.bullets);
    case 'bento': return words(s.eyebrow, s.title, ...s.tiles.flatMap(t =>
      t.kind === 'stat' ? [t.label, t.caption] :
      t.kind === 'text' ? [t.eyebrow, t.title, t.body] :
      t.kind === 'list' ? [t.title, ...t.items] :
      t.kind === 'quote' ? [t.quote, t.author] :
      t.kind === 'chart' ? [t.title] : [t.caption]));
    case 'split': return words(s.eyebrow, s.title, s.body, ...(s.bullets ?? []));
    case 'stats': return words(s.eyebrow, s.title, ...s.stats.flatMap(x => [x.label, x.caption]));
    case 'quote': return words(s.quote, s.author, s.role);
    case 'timeline': return words(s.eyebrow, s.title, ...s.steps.flatMap(x => [x.title, x.body]));
    case 'compare': return words(s.eyebrow, s.title, ...s.columns.flatMap(c => [c.title, ...c.items]));
    case 'image': return words(s.title, s.caption);
  }
}

export function lintSlide(s: Slide): Omit<Issue, 'slide'>[] {
  const out: Omit<Issue, 'slide'>[] = [];
  const warn = (message: string) => out.push({ level: 'warn', message });
  const error = (message: string) => out.push({ level: 'error', message });

  const total = slideWords(s);
  const limit = s.layout === 'bento' || s.layout === 'compare' ? MAX_WORDS + 15 : MAX_WORDS;
  if (total > limit) warn(`${total} words on one slide (aim for ≤${limit}). Split it, or move detail into notes.`);

  const title = 'title' in s ? s.title : undefined;
  if (title && words(title) > MAX_TITLE_WORDS) warn(`title has ${words(title)} words; headlines read best at ≤${MAX_TITLE_WORDS}`);
  if (s.layout === 'statement' && words(s.statement) > 20) warn(`statement has ${words(s.statement)} words; a statement slide should land in one breath (≤20)`);
  if (s.layout === 'quote' && words(s.quote) > 40) warn(`quote has ${words(s.quote)} words; trim to the strongest sentence (≤40)`);

  if (s.layout === 'bullets') {
    s.bullets.forEach((b, i) => { if (words(b) > MAX_BULLET_WORDS) warn(`bullet ${i + 1} has ${words(b)} words (≤${MAX_BULLET_WORDS})`); });
    if (s.bullets.length > 5) warn(`${s.bullets.length} bullets; 3–5 is the readable range. Consider a bento or two slides.`);
  }
  if (s.layout === 'split') {
    if (s.visual.kind === 'chart') chartIssues(s.visual.chart, 'visual').forEach(warn);
    if (s.body && s.bullets?.length && words(s.body, ...s.bullets) > 40) warn('split text side has both body and bullets and is long; keep one of them');
  }
  if (s.layout === 'compare' && !s.columns.some(c => c.highlight)) warn('compare: mark the recommended column with highlight: true so the slide has a point');

  if (s.layout === 'bento') {
    const { cols, rows } = s.grid;
    const cells = new Map<string, number>();
    s.tiles.forEach((t, i) => {
      const at = `tile ${i + 1} (${t.kind})`;
      if (t.x + t.w > cols || t.y + t.h > rows) {
        error(`${at} at x=${t.x},y=${t.y} size ${t.w}×${t.h} does not fit the ${cols}×${rows} grid`);
        return;
      }
      for (let x = t.x; x < t.x + t.w; x++) for (let y = t.y; y < t.y + t.h; y++) {
        const k = `${x},${y}`;
        if (cells.has(k)) error(`${at} overlaps tile ${cells.get(k)! + 1} at cell ${k}`);
        else cells.set(k, i);
      }
      if (t.kind === 'chart') chartIssues(t.chart, at).forEach(warn);
      if (t.kind === 'stat' && t.w === 1 && t.value.length > 6 && cols >= 4) warn(`${at}: value "${t.value}" is long for a 1-column tile; widen it to w=2`);
      if (t.w * t.h < 2 && (t.kind === 'list' || (t.kind === 'chart' && ['bar', 'line', 'area'].includes(t.chart.type)))) {
        warn(`${at}: ${t.kind === 'list' ? 'list' : t.chart.type + ' chart'} tiles need at least 2 cells to be readable`);
      }
      if (t.kind === 'text' && t.body && words(t.body) > 12 * t.w * t.h) warn(`${at}: body is too long for a ${t.w}×${t.h} tile`);
    });
    const holes = cols * rows - cells.size;
    if (holes > 0) warn(`bento grid has ${holes} empty cell(s); resize tiles so the grid is fully covered`);
    const areas = s.tiles.map(t => t.w * t.h);
    if (s.tiles.length >= 3 && Math.max(...areas) === Math.min(...areas)) warn('all bento tiles are the same size, so nothing leads; give the key message a 2×2 (or larger) hero tile');
    const accents = s.tiles.filter(t => t.accent === 'accent').length;
    if (accents > 1) warn(`${accents} tiles use accent; keep accent fill on one tile, use accent2/muted for secondary emphasis`);
    if (accents === 0 && !s.tiles.some(t => t.accent === 'accent2')) warn('no tile is accented; fill the hero tile with accent: "accent" to anchor the eye');
  }
  return out;
}

export function lintDeck(deck: Deck): Issue[] {
  const issues: Issue[] = deck.slides.flatMap((s, i) => lintSlide(s).map(x => ({ ...x, slide: i + 1 })));
  const n = deck.slides.length;
  if (n === 0) return issues;
  if (deck.slides[0].layout !== 'title') issues.push({ slide: 1, level: 'warn', message: 'deck does not open with a title slide' });
  for (let i = 2; i < n; i++) {
    const [a, b, c] = [deck.slides[i - 2], deck.slides[i - 1], deck.slides[i]];
    if (a.layout === b.layout && b.layout === c.layout && c.layout !== 'bento') {
      issues.push({ slide: i + 1, level: 'warn', message: `three "${c.layout}" slides in a row; vary the rhythm (statement, stats, bento, split)` });
    }
  }
  const bulletShare = deck.slides.filter(s => s.layout === 'bullets').length / n;
  if (n >= 5 && bulletShare > 0.4) {
    issues.push({ slide: null, level: 'warn', message: `${Math.round(bulletShare * 100)}% of slides are bullet lists; turn numbers into stats/bento and claims into statements` });
  }
  return issues;
}
