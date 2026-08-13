interface ResponseLike {
  headers: { get(name: string): string | null };
}

/**
 * Markers of an interstitial the renderer must wait out (JS challenge, captcha,
 * hard block page). Kept as one source of truth: the same list is inlined into
 * the browser subprocess scripts, so a new anti-bot vendor is added once here
 * and once in `RENDER_WAIT_MARKERS_JS` / `RENDER_WAIT_MARKERS_PY`.
 *
 * Each entry pairs a substring with the vendor — lets the chain log *which*
 * anti-bot blocked us, which is the only signal we have for choosing what to
 * tune next (proxy? UA? human preset?).
 */
export const CHALLENGE_SCRIPT_MARKERS: { marker: string; vendor: string }[] = [
  { marker: 'challenges.cloudflare.com',  vendor: 'Cloudflare' },
  { marker: 'cdn-cgi/challenge-platform', vendor: 'Cloudflare' },
  { marker: '__qrator/qauth.js',          vendor: 'Qrator' },
  { marker: 'captcha.yandex.com',         vendor: 'Yandex-SmartCaptcha' },
  { marker: 'smartcaptcha.yandexcloud.net', vendor: 'Yandex-SmartCaptcha' },
  { marker: 'hcaptcha.com/1/api.js',      vendor: 'hCaptcha' },
  { marker: 'google.com/recaptcha/api.js', vendor: 'Google-reCAPTCHA' },
  { marker: 'datadome.co/tags.js',        vendor: 'DataDome' },
  { marker: 'client.perimeterx.net',      vendor: 'PerimeterX' },
  { marker: 'ddos-guard.net/check',       vendor: 'DDoS-Guard' },
];

export const CHALLENGE_SCRIPT_MARKER_STRINGS = CHALLENGE_SCRIPT_MARKERS.map(c => c.marker);

export const CHALLENGE_TITLE_MARKERS = [
  'just a moment',
  'checking your browser',
  'ddos protection',
  'attention required',
  'security check',
  'enable javascript and cookies',
  'проверка браузера',
  'подождите',
];

/** Hard block pages — waiting will not help, the request was refused. */
export const BLOCK_MARKERS: { marker: string; vendor: string }[] = [
  { marker: 'guru meditation',          vendor: 'Qrator' },
  { marker: 'http 403',                 vendor: 'generic' },
  { marker: '403 forbidden',            vendor: 'generic' },
  { marker: 'access denied',            vendor: 'generic' },
  { marker: 'доступ к сайту',           vendor: 'generic-RU' },
  { marker: 'доступ запрещен',          vendor: 'generic-RU' },
  // Russian anti-bot interstitials (Avito, etc.). These pages are static text
  // the vendor serves to flagged clients — no JS challenge to wait out.
  { marker: 'иногда такое случается',   vendor: 'Avito-DataDome' },
  { marker: 'отключить vpn',            vendor: 'Avito-DataDome' },
  { marker: 'провайдера и ip-адрес',    vendor: 'Avito-DataDome' },
  { marker: 'напишите в поддержку',     vendor: 'Avito-DataDome' },
  { marker: 'включить и выключить режим', vendor: 'Avito-DataDome' },
];

/** Plain string list for fast .some() checks. */
export const BLOCK_MARKER_STRINGS = BLOCK_MARKERS.map(b => b.marker);

/**
 * Chrome's own network-error interstitial (chrome-error://chromewebdata).
 *
 * The renderer hands these back as if they were the site: HTTP 200, a title,
 * body text, and a ~10 KB base64 sad-cloud image. Extractors happily turn that
 * into "markdown", so the agent gets a Chrome error page presented as content.
 * Kinopoisk and Dzen hit this constantly — they bounce through
 * sso.passport.yandex.ru, and when that hop fails the error page is what lands.
 */
export const NAV_ERROR_MARKERS = [
  'err_socket_not_connected',
  'err_connection_refused',
  'err_connection_reset',
  'err_connection_closed',
  'err_connection_timed_out',
  'err_connection_failed',
  'err_name_not_resolved',
  'err_internet_disconnected',
  'err_address_unreachable',
  'err_empty_response',
  'err_timed_out',
  'err_too_many_redirects',
  'err_ssl_protocol_error',
  'err_cert_authority_invalid',
  'err_tunnel_connection_failed',
  'err_proxy_connection_failed',
  'err_http2_protocol_error',
  'err_quic_protocol_error',
  'err_failed',
  'chrome-error://chromewebdata',
];

/**
 * Returns the Chrome error code when `html` is a navigation-error page, else
 * null. Requires the marker to appear in visible text, not just anywhere in the
 * document — otherwise an article *about* `ERR_TIMED_OUT` would be discarded.
 */
export function detectNavErrorPage(html: string): string | null {
  const lower = html.toLowerCase();
  const hit = NAV_ERROR_MARKERS.find(m => lower.includes(m));
  if (!hit) return null;

  // Real pages are big and say many things; the error page is a stub whose
  // whole point is the error code. Guard on both to avoid false positives.
  if (visibleTextLength(html) > 3_000) return null;
  return hit.toUpperCase();
}

/**
 * Verdict on HTML produced by a renderer. `wait` means the page is still an
 * interstitial and polling should continue; `blocked` means the site refused
 * this client and a different renderer (or an IP change) is required.
 */
export type RenderVerdict = 'ok' | 'wait' | 'blocked';

export interface ClassifyResult {
  verdict: RenderVerdict;
  /** Name of the anti-bot vendor that matched, if any. Useful for logging. */
  vendor: string | null;
}

/**
 * Chain-level acceptance check. Deliberately lenient on size — the renderer
 * already waited for the page to settle, so a short page here is a short page,
 * not an unfinished one. Only interstitials and refusals send us to the next
 * engine.
 */
export function classifyRenderedHtml(html: string, minTextLength = 50): ClassifyResult {
  const lower = html.toLowerCase();

  for (const { marker, vendor } of BLOCK_MARKERS) {
    if (lower.includes(marker) && html.length < 20_000) return { verdict: 'blocked', vendor };
  }
  for (const { marker, vendor } of CHALLENGE_SCRIPT_MARKERS) {
    if (lower.includes(marker)) return { verdict: 'wait', vendor };
  }

  const title = /<title[^>]*>([^<]*)<\/title>/i.exec(html)?.[1]?.toLowerCase() ?? '';
  if (title && CHALLENGE_TITLE_MARKERS.some(m => title.includes(m))) return { verdict: 'wait', vendor: null };

  if (/id=["'](?:cf-challenge-running|challenge-form|px-captcha)["']/i.test(html)) return { verdict: 'wait', vendor: null };

  if (visibleTextLength(html) < minTextLength) return { verdict: 'wait', vendor: null };

  return { verdict: 'ok', vendor: null };
}

/** Back-compat shim: old callers using the bare string verdict still work. */
export function classifyVerdict(html: string, minTextLength = 50): RenderVerdict {
  return classifyRenderedHtml(html, minTextLength).verdict;
}

/**
 * HTTP statuses that mean "this client was refused", not "this page is gone".
 * They are handed to a renderer instead of raised: a real browser usually gets
 * through. 404/410 stay hard errors — a browser will not conjure a missing page.
 *
 * 401 is included because Russian anti-bot edges (auchan.ru's, for one) answer
 * plain HTTP clients with 401 rather than 403.
 *
 * 498 is Wildberries' anti-bot code: their edge answers non-browser clients
 * with a bare 498 and no body. Without it here the fetcher raised "HTTP 498"
 * and the renderer — which does get through — was never given a chance.
 */
export const RENDER_WORTHY_STATUSES = [401, 403, 405, 406, 409, 418, 429, 451, 498, 499, 500, 502, 503, 520, 521, 522, 525];

export function shouldRenderStatus(status: number): boolean {
  return RENDER_WORTHY_STATUSES.includes(status);
}

/**
 * True when `html` is a vendor refusal page rather than the site.
 *
 * The renderer chain already classifies its own output; this is the same test
 * for HTML that arrived over plain HTTP. Avito answers flagged clients with a
 * 200 and a short "Иногда такое случается" page, which otherwise extracts into
 * clean markdown and reaches the agent as if it were the listing.
 */
export function isBlockPage(html: string): boolean {
  if (html.length >= 20_000) return false;
  const lower = html.toLowerCase();
  return BLOCK_MARKER_STRINGS.some(m => lower.includes(m));
}

export function visibleTextLength(html: string): number {
  return html
    .replace(/<script[\s\S]*?<\/script>/gi, '')
    .replace(/<style[\s\S]*?<\/style>/gi, '')
    .replace(/<[^>]+>/g, ' ')
    .replace(/\s+/g, ' ')
    .trim()
    .length;
}

export function isChallengePage(html: string, response: ResponseLike): boolean {
  if (response.headers.get('cf-mitigated') === 'challenge') return true;
  if (response.headers.get('x-datadome-botd')) return true;

  const title = /<title[^>]*>([^<]*)<\/title>/i.exec(html)?.[1] ?? '';
  const h1 = /<h[12][^>]*>([^<]*)<\/h[12]>/i.exec(html)?.[1] ?? '';
  if (/just a moment|checking your browser|ddos protection|attention required|security check|enable javascript and cookies/i.test(title + ' ' + h1)) return true;

  if (/src=["'][^"']*(?:captcha\.yandex\.com|smartcaptcha\.yandexcloud\.net|challenges\.cloudflare\.com|cdn-cgi\/challenge-platform|hcaptcha\.com\/1\/api\.js|google\.com\/recaptcha\/api\.js|datadome\.co\/tags\.js|client\.perimeterx\.net)/i.test(html)) return true;

  if (/id=["'](?:cf-challenge-running|challenge-form|px-captcha)["']/i.test(html)) return true;

  return false;
}
