import { fetchWithPlaywright } from './playwright-subprocess.js';
import { isChallengePage, isBlockPage, shouldRenderStatus } from './challenge.js';
import { IHttpFetcher, RawFetchResult } from './types.js';

const USER_AGENT = 'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/142.0.0.0 Safari/537.36';

export function decodeWithCharset(buffer: ArrayBuffer, contentTypeHeader: string): string {
  const headerCharset = contentTypeHeader.match(/charset=([^\s;]+)/i)?.[1];
  const decoder = new TextDecoder(headerCharset ?? 'utf-8', { fatal: false });
  const text = decoder.decode(buffer);
  const metaCharset = text.match(/<meta[^>]+charset=["\s]*([^\s">;]+)/i)?.[1];
  const charset = (metaCharset ?? headerCharset ?? 'utf-8').toLowerCase();
  if (charset === 'utf-8' || charset === 'utf8' || headerCharset?.toLowerCase() === charset) return text;
  try {
    return new TextDecoder(charset, { fatal: false }).decode(buffer);
  } catch {
    return text;
  }
}

function extractVisibleText(html: string): string {
  return html
    .replace(/<script[\s\S]*?<\/script>/gi, '')
    .replace(/<style[\s\S]*?<\/style>/gi, '')
    .replace(/<[^>]+>/g, '')
    .replace(/\s+/g, ' ')
    .trim();
}

export class NativeFetcher implements IHttpFetcher {
  async fetch(url: string): Promise<RawFetchResult> {
    let parsedURL: URL;
    try { parsedURL = new URL(url); } catch {
      throw new Error(`Invalid URL format: ${url}`);
    }
    if (parsedURL.protocol !== 'http:' && parsedURL.protocol !== 'https:') {
      throw new Error(`Invalid URL format: ${url}. Only HTTP and HTTPS URLs are supported.`);
    }

    try {
      const response = await fetch(url, {
        headers: {
          'User-Agent': USER_AGENT,
          'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,image/apng,*/*;q=0.8',
          // ru first: RU sites serve a different (often lighter) page to
          // clients that read as foreign, and some geo-gate outright.
          'Accept-Language': 'ru-RU,ru;q=0.9,en-US;q=0.8,en;q=0.7',
        },
      });

      if (shouldRenderStatus(response.status)) {
        return { html: '', contentType: 'text/html', needsRendering: true };
      }
      if (!response.ok) throw new Error(`HTTP ${response.status}: ${response.statusText}`);

      const ct = response.headers.get('Content-Type') ?? '';
      const base = ct.split(';')[0].trim().toLowerCase();
      if (base === 'application/pdf') throw new Error('Unsupported content type: PDF');
      if (base.startsWith('image/')) throw new Error(`Unsupported content type: ${base}`);
      if (base && base !== 'text/html') throw new Error(`Unsupported content type: ${base}`);

      const buffer = await response.arrayBuffer();
      const html = decodeWithCharset(buffer, ct);

      // A refusal page is text-rich enough to pass the length check, so it has
      // to be named explicitly — otherwise Avito's "Иногда такое случается"
      // stub extracts into tidy markdown and reaches the agent as content.
      const visibleText = extractVisibleText(html);
      const needsRendering =
        visibleText.length < 200 ||
        isBlockPage(html) ||
        isChallengePage(html, response);

      return { html, contentType: ct || 'text/html', needsRendering };
    } catch (err) {
      if (err instanceof Error && (
        err.message.startsWith('Unsupported') ||
        err.message.startsWith('Invalid') ||
        err.message.startsWith('HTTP')
      )) throw err;
      // Anything else (connection reset, protocol error, an opaque "fetch
      // failed" from an anti-bot edge) is a signal to let the browser try.
      return { html: '', contentType: 'text/html', needsRendering: true };
    }
  }
}

// Legacy wrapper — preserves existing test API
export interface FetchResult { html: string; contentType: string; }

export async function fetchHTML(url: string): Promise<FetchResult> {
  const { html, contentType, needsRendering } = await new NativeFetcher().fetch(url);
  if (needsRendering) {
    return { html: await fetchWithPlaywright(url), contentType };
  }
  return { html, contentType };
}
