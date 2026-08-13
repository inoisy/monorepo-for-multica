import { describe, it, expect } from 'vitest';
import { isChallengePage, classifyRenderedHtml, shouldRenderStatus, detectNavErrorPage, isBlockPage } from './challenge.js';

function response(map: Record<string, string>) {
  return { headers: { get: (name: string) => map[name.toLowerCase()] ?? null } };
}

describe('isChallengePage', () => {
  it('returns true for cf-mitigated: challenge header', () => {
    expect(isChallengePage('', response({ 'cf-mitigated': 'challenge' }))).toBe(true);
  });

  it('returns true for x-datadome-botd header', () => {
    expect(isChallengePage('', response({ 'x-datadome-botd': '1' }))).toBe(true);
  });

  it.each([
    'Just a moment...',
    'Checking your browser',
    'DDoS Protection by Cloudflare',
    'Attention Required!',
    'Security Check',
    'Enable JavaScript and Cookies to continue',
  ])('returns true for challenge title: %s', (title) => {
    expect(isChallengePage(`<title>${title}</title>`, response({}))).toBe(true);
  });

  it('returns true for Yandex challenge h1 (no matching title)', () => {
    const html = '<html><head><title>Яндекс</title></head><body><h1>Checking your browser before redirecting to ya.ru</h1></body></html>';
    expect(isChallengePage(html, response({}))).toBe(true);
  });

  it('returns true for Yandex SmartCaptcha script (yandexcloud.net)', () => {
    const html = '<script src="https://smartcaptcha.yandexcloud.net/captcha.js"></script>';
    expect(isChallengePage(html, response({}))).toBe(true);
  });

  it.each([
    'https://hcaptcha.com/1/api.js',
    'https://challenges.cloudflare.com/turnstile/v0/api.js',
    'https://cdn-cgi/challenge-platform/h/b/orchestrate.js',
    'https://www.google.com/recaptcha/api.js',
    'https://captcha.yandex.com/api.js',
    'https://client.perimeterx.net/PXabc123/main.min.js',
  ])('returns true for captcha script: %s', (src) => {
    expect(isChallengePage(`<script src="${src}"></script>`, response({}))).toBe(true);
  });

  it.each(['cf-challenge-running', 'challenge-form', 'px-captcha'])(
    'returns true for challenge element id: %s', (id) => {
      expect(isChallengePage(`<div id="${id}"></div>`, response({}))).toBe(true);
    }
  );

  it('returns false for normal page', () => {
    const html = '<html><head><title>Hello World</title></head><body><p>Normal content here.</p></body></html>';
    expect(isChallengePage(html, response({}))).toBe(false);
  });

  it('returns false for empty html with no matching headers', () => {
    expect(isChallengePage('', response({}))).toBe(false);
  });
});

describe('classifyRenderedHtml', () => {
  const rich = `<html><body>${'content '.repeat(50)}</body></html>`;

  it('accepts a rendered page with real text', () => {
    expect(classifyRenderedHtml(rich).verdict).toBe('ok');
  });

  it('accepts a genuinely small page (example.com is ~170 chars)', () => {
    const small = '<html><body><h1>Example Domain</h1><p>' + 'x'.repeat(100) + '</p></body></html>';
    expect(classifyRenderedHtml(small).verdict).toBe('ok');
  });

  it('flags a Qrator challenge stub as not finished and names the vendor', () => {
    const stub = '<html><head><script src="/__qrator/qauth.js"></script></head><body></body></html>';
    const r = classifyRenderedHtml(stub);
    expect(r.verdict).toBe('wait');
    expect(r.vendor).toBe('Qrator');
  });

  it('flags a Qrator refusal page as blocked and names the vendor', () => {
    const blocked = '<html><head><title>HTTP 403</title></head><body>Доступ к сайту запрещен. Guru meditation</body></html>';
    const r = classifyRenderedHtml(blocked);
    expect(r.verdict).toBe('blocked');
    expect(r.vendor).toBe('Qrator');
  });

  it('does not call a long article blocked just because it mentions 403', () => {
    const article = `<html><body>${'text about http 403 errors '.repeat(2000)}</body></html>`;
    expect(classifyRenderedHtml(article).verdict).toBe('ok');
  });

  it('flags an empty document as not finished', () => {
    expect(classifyRenderedHtml('<html><body></body></html>').verdict).toBe('wait');
  });

  it('identifies Avito block by Russian anti-bot text', () => {
    const avito = '<html><body>Иногда такое случается — подождите. Отключить VPN. Напишите в поддержку.</body></html>';
    const r = classifyRenderedHtml(avito);
    expect(r.verdict).toBe('blocked');
    expect(r.vendor).toBe('Avito-DataDome');
  });
});

describe('shouldRenderStatus', () => {
  it.each([401, 403, 429, 503])('sends status %i to the renderer', (status) => {
    expect(shouldRenderStatus(status)).toBe(true);
  });

  it.each([200, 404, 410, 301])('does not send status %i to the renderer', (status) => {
    expect(shouldRenderStatus(status)).toBe(false);
  });
});

describe('detectNavErrorPage', () => {
  const chromeErrorPage = `<html><head><title>example.com</title></head><body>
    <h1>Не удается получить доступ к сайту</h1>
    <p>Веб-страница по адресу https://sso.passport.yandex.ru/push?uuid=1 недоступна.</p>
    <div>ERR_SOCKET_NOT_CONNECTED</div>
    <img src="data:image/png;base64,${'A'.repeat(9000)}">
  </body></html>`;

  it('detects a Chrome navigation-error interstitial', () => {
    expect(detectNavErrorPage(chromeErrorPage)).toBe('ERR_SOCKET_NOT_CONNECTED');
  });

  it('detects chrome-error:// documents', () => {
    expect(detectNavErrorPage('<body>chrome-error://chromewebdata</body>')).not.toBeNull();
  });

  it('returns null for a normal page', () => {
    expect(detectNavErrorPage('<body><p>Обычная статья про сети</p></body>')).toBeNull();
  });

  it('does not flag a long article that merely mentions the error code', () => {
    const article = `<body><p>${'Разбираем ошибку ERR_TIMED_OUT в Chrome. '.repeat(200)}</p></body>`;
    expect(detectNavErrorPage(article)).toBeNull();
  });

  it('sends Wildberries 498 to the renderer', () => {
    expect(shouldRenderStatus(498)).toBe(true);
  });
});

describe('isBlockPage', () => {
  it('flags the Avito anti-bot stub that arrives with HTTP 200', () => {
    const stub = '<html><body><p>Иногда такое случается — подождите немного и обновите страницу.</p>'
      + '<ul><li>Отключить VPN.</li><li>Включить и выключить режим «В самолёте».</li></ul></body></html>';
    expect(isBlockPage(stub)).toBe(true);
  });

  it('does not flag a full page that happens to contain the phrase', () => {
    expect(isBlockPage('<body>' + 'обычный текст '.repeat(2000) + 'отключить vpn</body>')).toBe(false);
  });

  it('does not flag ordinary content', () => {
    expect(isBlockPage('<body><h1>Квартиры в Москве</h1></body>')).toBe(false);
  });
});
