import { chromium, type Browser, type Page } from 'playwright';
import { pathToFileURL } from 'node:url';
import path from 'node:path';
import { SLIDE_H, SLIDE_W } from './render.js';

// One long-lived headless Chromium, one fresh page per job. Every job loads
// the deck's index.html in #print mode (all slides stacked at native size)
// and waits for the page's own fit pass to finish before measuring anything.

let browser: Promise<Browser> | null = null;
let launchExtra: Parameters<typeof chromium.launch>[0] = {};
let contextExtra: Parameters<Browser['newContext']>[0] = {};

/** Test/dev hook: extra launch and context options (e.g. a proxy). */
export function configureBrowser(launch: typeof launchExtra, context: typeof contextExtra = {}): void {
  launchExtra = launch;
  contextExtra = context;
}

function getBrowser(): Promise<Browser> {
  if (!browser) {
    browser = chromium.launch({
      executablePath: process.env.SLIDES_CHROMIUM_PATH || undefined,
      // file:// pages load fonts from ../_fonts, which Chromium treats as cross-origin without this flag.
      args: ['--font-render-hinting=none', '--allow-file-access-from-files'],
      ...launchExtra,
    });
    browser.catch(() => { browser = null; });
  }
  return browser;
}

export async function closeBrowser(): Promise<void> {
  if (browser) await (await browser).close().catch(() => {});
  browser = null;
}

async function withDeckPage<T>(deckDir: string, fn: (page: Page) => Promise<T>): Promise<T> {
  const ctx = await (await getBrowser()).newContext({ viewport: { width: SLIDE_W, height: SLIDE_H }, deviceScaleFactor: 1, ...contextExtra });
  try {
    const page = await ctx.newPage();
    const url = pathToFileURL(path.join(deckDir, 'index.html')).href + '#print';
    await page.goto(url, { waitUntil: 'load', timeout: 30_000 });
    // Fonts come from Google Fonts; if the host is offline the page still
    // becomes ready once the font load settles on the fallback.
    await page.waitForFunction('window.__slidesReady === true', null, { timeout: 20_000 });
    return await fn(page);
  } finally {
    await ctx.close();
  }
}

export interface RenderReport {
  slide: number;
  overflow: string[];
  shrunk: { where: string; scale: number }[];
  brokenImages: string[];
}

export interface CheckResult {
  fontsLoaded: boolean;
  slides: RenderReport[];
}

/** Measures what lint can't: text that still overflows after auto-fit, type that had to shrink, images that failed to load. */
export async function checkRender(deckDir: string): Promise<CheckResult> {
  return withDeckPage(deckDir, page => page.evaluate(CHECK_SCRIPT) as Promise<CheckResult>);
}

// Kept as a string, not a function: tsx/esbuild wrap named functions in a
// __name() helper that does not exist inside the page.
const CHECK_SCRIPT = `(() => {
  const label = el => {
    const kind = [...el.classList].find(c => c.startsWith('kind-'));
    const tiles = el.parentElement ? [...el.parentElement.children].filter(c => c.classList.contains('tile')) : [];
    return kind ? 'tile ' + (tiles.indexOf(el) + 1) + ' (' + kind.slice(5) + ')' : 'slide body';
  };
  const slides = [...document.querySelectorAll('.slide')].map((s, i) => ({
    slide: i + 1,
    overflow: [...s.querySelectorAll('[data-overflow]')].map(label),
    shrunk: [...s.querySelectorAll('[data-shrunk]')].map(el => ({ where: label(el), scale: Number(el.getAttribute('data-shrunk')) })),
    brokenImages: [...s.querySelectorAll('img')].filter(img => !img.naturalWidth).map(img => img.getAttribute('src') || ''),
  }));
  const display = getComputedStyle(document.documentElement).getPropertyValue('--font-display').split(',')[0].trim();
  // document.fonts.check() is true when no face matches at all (stylesheet
  // never loaded), so look for an actually loaded face of the display family.
  const family = display.replace(/['"]/g, '');
  const fontsLoaded = [...document.fonts].some(f => f.family.replace(/['"]/g, '') === family && f.status === 'loaded');
  return { fontsLoaded, slides };
})()`;

/** PNG per slide. `scale` < 1 makes smaller previews (cheaper for an agent to look at). */
export async function screenshots(deckDir: string, indices: number[] | undefined, scale = 0.5): Promise<{ slide: number; png: Buffer }[]> {
  return withDeckPage(deckDir, async page => {
    const sections = await page.$$('section.slide');
    const pick = indices?.length ? indices : sections.map((_, i) => i + 1);
    const out = [];
    for (const n of pick) {
      const el = sections[n - 1];
      if (!el) throw new Error(`slide ${n} does not exist (deck has ${sections.length})`);
      const png = await el.screenshot({ type: 'png', scale: 'css' });
      out.push({ slide: n, png: scale === 1 ? png : await downscale(page, png, scale) });
    }
    return out;
  });
}

async function downscale(page: Page, png: Buffer, scale: number): Promise<Buffer> {
  const w = Math.round(SLIDE_W * scale), h = Math.round(SLIDE_H * scale);
  const dataUrl = await page.evaluate(async ({ src, w, h }) => {
    const img = new Image();
    img.src = src;
    await img.decode();
    const c = document.createElement('canvas');
    c.width = w; c.height = h;
    const g = c.getContext('2d')!;
    g.imageSmoothingQuality = 'high';
    g.drawImage(img, 0, 0, w, h);
    return c.toDataURL('image/png');
  }, { src: `data:image/png;base64,${png.toString('base64')}`, w, h });
  return Buffer.from(dataUrl.split(',')[1], 'base64');
}

export async function pdf(deckDir: string): Promise<Buffer> {
  return withDeckPage(deckDir, page => page.pdf({
    width: `${SLIDE_W}px`, height: `${SLIDE_H}px`, printBackground: true, preferCSSPageSize: true,
  }));
}
