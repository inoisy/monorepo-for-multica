import { describe, it, expect, vi, beforeEach } from 'vitest';

import { NativeFetcher } from './fetcher.js';

const mockFetch = vi.fn();
vi.stubGlobal('fetch', mockFetch);

const enc = new TextEncoder();

function makeResponse(html: string, opts: {
  status?: number;
  ok?: boolean;
  statusText?: string;
  headers?: Record<string, string>;
} = {}) {
  const { status = 200, ok = true, statusText = 'OK', headers = {} } = opts;
  const lower: Record<string, string> = {};
  for (const [k, v] of Object.entries(headers)) lower[k.toLowerCase()] = v;
  return {
    status,
    ok,
    statusText,
    headers: { get: (k: string) => lower[k.toLowerCase()] ?? null },
    arrayBuffer: () => Promise.resolve(enc.encode(html).buffer as ArrayBuffer),
  };
}

const STATIC_HTML = '<html><body>' + 'Normal page content sentence. '.repeat(10) + '</body></html>';

describe('NativeFetcher', () => {
  let fetcher: NativeFetcher;

  beforeEach(() => {
    vi.clearAllMocks();
    fetcher = new NativeFetcher();
  });

  it('throws on invalid URL', async () => {
    await expect(fetcher.fetch('not-a-url')).rejects.toThrow('Invalid URL format');
  });

  it('throws on non-http protocol', async () => {
    await expect(fetcher.fetch('ftp://example.com')).rejects.toThrow('Invalid URL format');
  });

  it.each([403, 429, 503])('returns needsRendering=true for status %i', async (status) => {
    mockFetch.mockResolvedValue(makeResponse('', { status, ok: false }));
    const result = await fetcher.fetch('https://example.com');
    expect(result).toEqual({ html: '', contentType: 'text/html', needsRendering: true });
  });

  it('throws HTTP error for non-ok status outside [403,429,503]', async () => {
    mockFetch.mockResolvedValue(makeResponse('', { status: 404, ok: false, statusText: 'Not Found' }));
    await expect(fetcher.fetch('https://example.com')).rejects.toThrow('HTTP 404');
  });

  it('throws for PDF content type', async () => {
    mockFetch.mockResolvedValue(makeResponse('', { headers: { 'content-type': 'application/pdf' } }));
    await expect(fetcher.fetch('https://example.com')).rejects.toThrow('Unsupported content type: PDF');
  });

  it('throws for image content type', async () => {
    mockFetch.mockResolvedValue(makeResponse('', { headers: { 'content-type': 'image/png' } }));
    await expect(fetcher.fetch('https://example.com')).rejects.toThrow('Unsupported content type: image/png');
  });

  it('throws for non-html text content type', async () => {
    mockFetch.mockResolvedValue(makeResponse('{}', { headers: { 'content-type': 'application/json' } }));
    await expect(fetcher.fetch('https://example.com')).rejects.toThrow('Unsupported content type');
  });

  it('returns needsRendering=true for SPA (div#root)', async () => {
    const html = '<html><body><div id="root"></div></body></html>';
    mockFetch.mockResolvedValue(makeResponse(html, { headers: { 'content-type': 'text/html' } }));
    const result = await fetcher.fetch('https://example.com');
    expect(result.needsRendering).toBe(true);
  });

  it('returns needsRendering=true for __NEXT_DATA__ SPA marker', async () => {
    const html = `<html><body><script id="__NEXT_DATA__">{}</script></body></html>`;
    mockFetch.mockResolvedValue(makeResponse(html, { headers: { 'content-type': 'text/html' } }));
    const result = await fetcher.fetch('https://example.com');
    expect(result.needsRendering).toBe(true);
  });

  it('returns needsRendering=true for Cloudflare challenge page', async () => {
    const html = '<html><head><title>Just a moment...</title></head><body></body></html>';
    mockFetch.mockResolvedValue(makeResponse(html, { headers: { 'content-type': 'text/html' } }));
    const result = await fetcher.fetch('https://example.com');
    expect(result.needsRendering).toBe(true);
  });

  it('returns needsRendering=true when visible text < 200 chars', async () => {
    const html = '<html><body><p>Short.</p></body></html>';
    mockFetch.mockResolvedValue(makeResponse(html, { headers: { 'content-type': 'text/html' } }));
    const result = await fetcher.fetch('https://example.com');
    expect(result.needsRendering).toBe(true);
  });

  it('returns needsRendering=false and decoded html for normal static page', async () => {
    mockFetch.mockResolvedValue(makeResponse(STATIC_HTML, {
      headers: { 'content-type': 'text/html; charset=utf-8' },
    }));
    const result = await fetcher.fetch('https://example.com');
    expect(result.needsRendering).toBe(false);
    expect(result.html).toContain('Normal page content');
    expect(result.contentType).toContain('text/html');
  });

  it('returns needsRendering=true on network error', async () => {
    mockFetch.mockRejectedValue(new Error('network error'));
    const result = await fetcher.fetch('https://example.com');
    expect(result).toEqual({ html: '', contentType: 'text/html', needsRendering: true });
  });
});
