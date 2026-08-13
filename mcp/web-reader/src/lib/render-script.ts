import {
  CHALLENGE_SCRIPT_MARKERS,
  CHALLENGE_TITLE_MARKERS,
  BLOCK_MARKERS,
  NAV_ERROR_MARKERS,
} from './challenge.js';

/**
 * Wait policy shared by every renderer.
 *
 * Anti-bot interstitials (Qrator, Cloudflare, DDoS-Guard) answer with a tiny
 * page whose JS solves a challenge and then replaces the document. A renderer
 * that grabs `page.content()` right after `domcontentloaded` captures the stub,
 * not the site — that was the original "web_reader returns 260 bytes" bug.
 *
 * So instead of fixed sleeps, both renderers poll the live DOM and stop on the
 * first of two signals: the page looks rich (lots of text), or it has stopped
 * changing. The second signal is what keeps genuinely small pages fast —
 * example.com has ~170 characters and will never clear a "rich" threshold.
 */
export interface WaitPolicy {
  /** Poll interval in ms. */
  pollMs: number;
  /** Visible text length above which a page is accepted immediately. */
  minTextLength: number;
  /** HTML length above which a page is accepted immediately. */
  minHtmlLength: number;
  /** Consecutive unchanged polls that accept a small page as finished. */
  stablePolls: number;
  /**
   * How long a block page must persist before it is believed. Qrator answers
   * the first request with a 403 stub and only then runs its JS check, so an
   * instant bail-out would abandon sites that do let us in a second later.
   */
  blockGraceMs: number;
}

export const DEFAULT_WAIT_POLICY: WaitPolicy = {
  pollMs: 1000,
  minTextLength: 400,
  minHtmlLength: 4000,
  stablePolls: 2,
  blockGraceMs: 5000,
};

const json = (v: unknown) => JSON.stringify(v);

/**
 * Page states the poll loops act on:
 *   ok           — rich content, stop now
 *   thin         — real page but small; stop once it stops changing
 *   interstitial — challenge markers present, keep waiting
 *   blocked      — refusal page, stop after the grace period
 *   naverror     — Chrome's own network-error page; nothing to wait for
 */
export type PageState = 'ok' | 'thin' | 'interstitial' | 'blocked' | 'naverror';

/** JS source of the in-page state function, injected into browser scripts. */
export function verdictFunctionJs(policy: WaitPolicy = DEFAULT_WAIT_POLICY): string {
  return `
const SCRIPT_MARKERS = ${json(CHALLENGE_SCRIPT_MARKERS)};
const TITLE_MARKERS = ${json(CHALLENGE_TITLE_MARKERS)};
const BLOCK_MARKERS = ${json(BLOCK_MARKERS)};
const NAV_ERROR_MARKERS = ${json(NAV_ERROR_MARKERS)};
const MIN_TEXT = ${policy.minTextLength};
const MIN_HTML = ${policy.minHtmlLength};

/** Chrome's error interstitial — polling it forever changes nothing. */
function navErrorCode(html, text) {
  if (text.length > 3000) return null;
  const lower = html.toLowerCase();
  const hit = NAV_ERROR_MARKERS.find(m => lower.includes(m));
  return hit ? hit.toUpperCase() : null;
}

function pageState(html, text) {
  const lower = html.toLowerCase();
  if (navErrorCode(html, text)) return 'naverror';
  if (html.length < 20000 && BLOCK_MARKERS.some(m => lower.includes(m))) return 'blocked';
  if (SCRIPT_MARKERS.some(m => lower.includes(m))) return 'interstitial';
  const title = (/<title[^>]*>([^<]*)<\\/title>/i.exec(html) || [,''])[1].toLowerCase();
  if (title && TITLE_MARKERS.some(m => title.includes(m))) return 'interstitial';
  if (text.length >= MIN_TEXT && html.length >= MIN_HTML) return 'ok';
  return 'thin';
}
`;
}
