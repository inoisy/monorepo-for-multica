import { describe, it, expect, vi } from 'vitest';
import { FallbackRenderer } from './renderer-chain.js';
import type { IRenderer } from './types.js';

const URL = 'https://example.com';
const GOOD = `<html><body><article>${'real content '.repeat(20)}</article></body></html>`;
const QRATOR_STUB = '<html><head><script src="/__qrator/qauth.js"></script></head><body></body></html>';
const BLOCK_PAGE = '<html><head><title>HTTP 403</title></head><body>Guru meditation</body></html>';

const renderer = (impl: IRenderer['render']): IRenderer => ({ render: vi.fn(impl) });

describe('FallbackRenderer', () => {
  it('returns the first clean page without touching later engines', async () => {
    const second = renderer(async () => GOOD);
    const chain = new FallbackRenderer([
      { name: 'first', renderer: renderer(async () => GOOD) },
      { name: 'second', renderer: second },
    ]);

    expect(await chain.render(URL)).toBe(GOOD);
    expect(second.render).not.toHaveBeenCalled();
  });

  it('falls through when the first engine only gets an interstitial', async () => {
    const chain = new FallbackRenderer([
      { name: 'first', renderer: renderer(async () => QRATOR_STUB) },
      { name: 'second', renderer: renderer(async () => GOOD) },
    ]);

    expect(await chain.render(URL)).toBe(GOOD);
  });

  it('falls through when the first engine throws', async () => {
    const chain = new FallbackRenderer([
      { name: 'first', renderer: renderer(async () => { throw new Error('engine unavailable'); }) },
      { name: 'second', renderer: renderer(async () => GOOD) },
    ]);

    expect(await chain.render(URL)).toBe(GOOD);
  });

  it('returns the largest partial page when no engine gets a clean one', async () => {
    const chain = new FallbackRenderer([
      { name: 'first', renderer: renderer(async () => QRATOR_STUB) },
      { name: 'second', renderer: renderer(async () => BLOCK_PAGE) },
    ]);

    const html = await chain.render(URL);
    expect(html.length).toBe(Math.max(QRATOR_STUB.length, BLOCK_PAGE.length));
  });

  it('reports every engine failure when all of them throw', async () => {
    const chain = new FallbackRenderer([
      { name: 'first', renderer: renderer(async () => { throw new Error('boom one'); }) },
      { name: 'second', renderer: renderer(async () => { throw new Error('boom two'); }) },
    ]);

    await expect(chain.render(URL)).rejects.toThrow(/boom one[\s\S]*boom two/);
  });

  it('forwards the per-engine timeout', async () => {
    const first = renderer(async () => GOOD);
    await new FallbackRenderer([{ name: 'first', renderer: first }]).render(URL, 1234);
    expect(first.render).toHaveBeenCalledWith(URL, 1234);
  });
});

describe('FallbackRenderer host memory', () => {
  it('puts the engine that worked first on the next request to that host', async () => {
    const first = renderer(async () => QRATOR_STUB);
    const second = renderer(async () => GOOD);
    const chain = new FallbackRenderer([
      { name: 'first', renderer: first },
      { name: 'second', renderer: second },
    ]);

    await chain.render('https://shop.example.com/a');
    expect(first.render).toHaveBeenCalledTimes(1);

    await chain.render('https://shop.example.com/b');
    // second engine won, so the losing engine is not tried again for this host
    expect(first.render).toHaveBeenCalledTimes(1);
    expect(second.render).toHaveBeenCalledTimes(2);
  });

  it('keeps the memory per host', async () => {
    const first = renderer(async (url) => (url.includes('other') ? GOOD : QRATOR_STUB));
    const second = renderer(async () => GOOD);
    const chain = new FallbackRenderer([
      { name: 'first', renderer: first },
      { name: 'second', renderer: second },
    ]);

    await chain.render('https://shop.example.com/a');
    await chain.render('https://other.example.com/a');
    expect(first.render).toHaveBeenCalledTimes(2);
  });
});
