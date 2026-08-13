import { IRenderer } from './types.js';
import { runScript, killAllSubprocesses } from './subprocess.js';
import { DEFAULT_WAIT_POLICY, verdictFunctionJs, WaitPolicy } from './render-script.js';
import { debug } from './utils.js';
import { HostRuleSet, deriveLocaleFromUrl, type HostRuleOverrides } from './host-rules.js';

export interface CloakBrowserOptions {
  /** SOCKS/HTTP proxy URL, e.g. "socks5://user:pass@host:1080". */
  proxy?: string;
  /** Auto-pick timezone/locale from proxy IP. Requires mmdb-lib. */
  geoip?: boolean;
  /** Persistent browser profile dir; cookies/storage carry over. */
  userDataDir?: string;
  /** Enable humanized mouse/keyboard/scroll. Default true. */
  humanize?: boolean;
  /** Human behavior preset: 'default' | 'careful'. */
  humanPreset?: 'default' | 'careful';
  /** BCP 47 locale, e.g. "ru-RU". Sets --lang. */
  locale?: string;
  /** Browser viewport size. Default 1920x1080. */
  viewport?: { width: number; height: number };
  /** Release channel: 'stable' | 'preview'. */
  releaseChannel?: 'stable' | 'preview';
  /**
   * Hosts whose *navigations* are aborted instead of followed. Sub-resources
   * from these hosts still load — only a top-level hop is refused, which leaves
   * the page we already have instead of replacing it.
   */
  blockNavHosts?: string[];
}

/**
 * Yandex properties (kinopoisk.ru, dzen.ru, market.yandex.ru) bounce every
 * fresh session through an SSO auto-login hop. It sets no cookie we need, and
 * from a datacenter IP it frequently dies mid-navigation — at which point the
 * *original* page is gone and Chrome's ERR_SOCKET_NOT_CONNECTED page is what we
 * scrape. Refusing the hop keeps the content that was already rendered.
 */
export const DEFAULT_BLOCK_NAV_HOSTS = ['sso.passport.yandex.ru'];

export class CloakBrowserRenderer implements IRenderer {
  constructor(
    private readonly defaultTimeout = 30_000,
    private readonly options: CloakBrowserOptions = {},
    private readonly hostRules: HostRuleSet = new HostRuleSet(undefined),
  ) {}

  async render(url: string, timeout?: number): Promise<string> {
    // Merge order: explicit options → host rule overrides (per-host `.env`)
    // → TLD-derived locale (only when locale wasn't set anywhere above).
    const ruleOverrides = this.hostRules.forUrl(url);
    const merged = mergeOptions(this.options, ruleOverrides);
    if (!merged.locale) merged.locale = deriveLocaleFromUrl(url);
    return fetchWithPlaywright(url, timeout ?? this.defaultTimeout, undefined, merged);
  }
}

function mergeOptions(base: CloakBrowserOptions, overrides: HostRuleOverrides | null): CloakBrowserOptions {
  if (!overrides) return base;
  return {
    ...base,
    ...Object.fromEntries(Object.entries(overrides).filter(([, v]) => v !== undefined)),
  };
}

/** Kept for backwards compatibility with callers of the old API. */
export function killAllProcesses(): void {
  killAllSubprocesses();
}

export { registerProcess } from './subprocess.js';

interface RenderPayload {
  html: string;
  verdict: 'ok' | 'wait' | 'blocked' | 'naverror';
  /** Chrome error code when verdict is `naverror`. */
  navError?: string | null;
  elapsedMs: number;
}

export async function fetchWithPlaywright(
  url: string,
  timeout = 30_000,
  policy: WaitPolicy = DEFAULT_WAIT_POLICY,
  options: CloakBrowserOptions = {},
): Promise<string> {
  new URL(url); // reject non-URLs before paying for a browser launch

  // Leave room for launch + teardown so the poll loop always exits before the
  // hard kill and we can return whatever the page had.
  const pollBudgetMs = Math.max(2_000, timeout - 8_000);

  // Build the launch options object. Stringified for the subprocess payload —
  // the cloakbrowser launch() runs in a separate node process that imports
  // `cloakbrowser`, so we cannot pass objects by reference.
  const launchOpts: Record<string, unknown> = {
    headless: true,
    humanize: options.humanize ?? true,
  };
  if (options.humanPreset) launchOpts.humanPreset = options.humanPreset;
  if (options.proxy) launchOpts.proxy = options.proxy;
  if (options.geoip) launchOpts.geoip = true;
  if (options.locale) launchOpts.locale = options.locale;
  if (options.viewport) launchOpts.viewport = options.viewport;
  if (options.releaseChannel) launchOpts.releaseChannel = options.releaseChannel;

  const viewport = options.viewport ?? { width: 1920, height: 1080 };
  // When userDataDir is set we use launchPersistentContext so cookies survive
  // across requests; otherwise launchContext() gives us a clean ephemeral
  // context directly (skipping the browser.contexts()[0] dance that broke
  // when cloakbrowser 0.5.x restructured the launch wrapper).
  const usePersistent = !!options.userDataDir;
  const blockNavHosts = options.blockNavHosts ?? DEFAULT_BLOCK_NAV_HOSTS;

  const script = `
import { ${usePersistent ? 'launchPersistentContext' : 'launchContext'} } from 'cloakbrowser';

${verdictFunctionJs(policy)}

const URL_TO_READ = ${JSON.stringify(url)};
const POLL_BUDGET_MS = ${pollBudgetMs};
const POLL_MS = ${policy.pollMs};
const BLOCK_GRACE_MS = ${policy.blockGraceMs};
const STABLE_POLLS = ${policy.stablePolls};
const LAUNCH_OPTS = ${JSON.stringify(launchOpts)};
const USER_DATA_DIR = ${options.userDataDir ? JSON.stringify(options.userDataDir) : 'null'};
const VIEWPORT = ${JSON.stringify(viewport)};
const BLOCK_NAV_HOSTS = ${JSON.stringify(blockNavHosts)};
const started = Date.now();

async function main() {
  let context;
  let page;
  let best = '';
  let bestVerdict = 'wait';
  let navError = null;
  try {
    if (USER_DATA_DIR) {
      context = await launchPersistentContext(USER_DATA_DIR, LAUNCH_OPTS);
      page = context.pages()[0] ?? await context.newPage();
    } else {
      context = await launchContext(LAUNCH_OPTS);
      page = await context.newPage();
    }
    await page.setViewportSize(VIEWPORT);

    // Refuse top-level hops to hosts that only ever bounce us (SSO auto-login).
    // Scoped by URL predicate so no other request pays the interception cost.
    if (BLOCK_NAV_HOSTS.length) {
      const blocked = (u) => BLOCK_NAV_HOSTS.some(h => u.hostname === h || u.hostname.endsWith('.' + h));
      await context.route(blocked, route => {
        if (route.request().isNavigationRequest()) {
          process.stderr.write('blocked nav: ' + route.request().url() + '\\n');
          return route.abort();
        }
        return route.continue();
      });
    }

    // No addInitScript fingerprint spoofing here, deliberately. CloakBrowser
    // already patches canvas/WebGL/screen/hardware at the C++ level; layering
    // JS getters on top produces inconsistencies that anti-bot vendors detect
    // (Qrator refused auchan.ru with the patches, let us straight in without).

    // Navigation itself must not eat the whole budget: sites behind a JS
    // challenge often never fire 'load', so we continue polling regardless.
    try {
      await page.goto(URL_TO_READ, { waitUntil: 'domcontentloaded', timeout: Math.min(20000, POLL_BUDGET_MS) });
    } catch (err) {
      process.stderr.write('goto: ' + err.message + '\\n');
    }

    const deadline = started + POLL_BUDGET_MS;
    let scrolled = false;
    let blockedSince = 0;
    let stableCount = 0;
    let prevLength = -1;

    // Portals embed their own feed in an iframe (mail.ru's news block is one),
    // and page.content() stops at the frame boundary. Splice child-frame bodies
    // into the document so the extractor sees them as part of the page.
    const withFrames = async (html) => {
      let frames;
      try { frames = page.frames().filter(f => f !== page.mainFrame()); } catch { return html; }
      if (!frames.length) return html;

      const parts = [];
      for (const frame of frames.slice(0, 8)) {
        try {
          const body = await frame.evaluate(() => document.body ? document.body.innerHTML : '');
          // Ad iframes are tiny or all-markup; a feed frame carries real text.
          const text = body.replace(/<[^>]+>/g, ' ').replace(/\\s+/g, ' ').trim();
          if (text.length >= 300) parts.push('<section data-frame="' + frame.url() + '">' + body + '</section>');
        } catch {}
      }
      if (!parts.length) return html;
      process.stderr.write('frames spliced: ' + parts.length + '\\n');
      return html.replace(/<\\/body>/i, parts.join('\\n') + '</body>');
    };

    const settle = async () => {
      // One lazy-load nudge, then re-read: shops render below-fold content on scroll.
      if (scrolled) return;
      scrolled = true;
      try {
        await page.evaluate(() => window.scrollTo(0, document.body.scrollHeight / 2));
        await new Promise(r => setTimeout(r, 400));
        const after = await page.content();
        if (after.length > best.length) best = after;
      } catch {}

      // Portals reach the "rich text" bar on their shell — ads, a promo block,
      // a horoscope — and hydrate the actual feed a beat later. Keep reading
      // while the document is still growing, bounded so normal pages pay ~0.
      for (let i = 0; i < 3 && Date.now() < deadline; i++) {
        await new Promise(r => setTimeout(r, 600));
        let grown = '';
        try { grown = await page.content(); } catch { break; }
        if (grown.length <= best.length * 1.02) break;
        best = grown;
      }
    };

    while (Date.now() < deadline) {
      let html = '';
      let text = '';
      try {
        html = await page.content();
        text = await page.evaluate(() => (document.body && document.body.innerText) || '');
      } catch (err) {
        process.stderr.write('poll: ' + err.message + '\\n');
        await new Promise(r => setTimeout(r, POLL_MS));
        continue;
      }

      const state = pageState(html, text);
      process.stderr.write('poll html=' + html.length + ' text=' + text.length + ' state=' + state + '\\n');
      if (html.length > best.length) best = html;

      stableCount = html.length === prevLength ? stableCount + 1 : 0;
      prevLength = html.length;

      if (state === 'ok') {
        await settle();
        bestVerdict = 'ok';
        break;
      }
      if (state === 'naverror') {
        bestVerdict = 'naverror';
        navError = navErrorCode(html, text);
        best = html;
        break;
      }
      if (state === 'blocked') {
        if (blockedSince === 0) blockedSince = Date.now();
        if (Date.now() - blockedSince >= BLOCK_GRACE_MS) { bestVerdict = 'blocked'; break; }
      } else {
        blockedSince = 0;
      }
      // A small page that has stopped changing is simply a small page.
      if (state === 'thin' && text.length > 0 && stableCount >= STABLE_POLLS) {
        await settle();
        bestVerdict = 'ok';
        break;
      }

      await new Promise(r => setTimeout(r, POLL_MS));
    }

    if (bestVerdict === 'ok') { try { best = await withFrames(best); } catch {} }

    console.log(JSON.stringify({ html: best, verdict: bestVerdict, navError, elapsedMs: Date.now() - started }));
  } catch (err) {
    console.log(JSON.stringify({ error: err instanceof Error ? err.message : String(err) }));
  } finally {
    if (context) { try { await context.close(); } catch {} }
  }
}

main();
`;

  const payload = await runScript<RenderPayload>({
    command: process.execPath,
    script,
    extension: '.mjs',
    timeoutMs: timeout,
    label: 'cloakbrowser',
  });

  debug(`[cloakbrowser] ${url} -> ${payload.verdict} in ${payload.elapsedMs}ms (${payload.html.length}b)`);

  if (payload.verdict === 'naverror') {
    throw new Error(
      `cloakbrowser: ${url} could not be loaded — the browser hit a navigation error`
      + `${payload.navError ? ` (${payload.navError})` : ''}.`,
    );
  }
  if (payload.verdict === 'blocked') {
    throw new Error(`cloakbrowser: ${url} refused the request (anti-bot block page)`);
  }
  if (!payload.html) {
    throw new Error(`cloakbrowser: ${url} produced no HTML`);
  }
  return payload.html;
}
