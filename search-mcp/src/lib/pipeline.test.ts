import { describe, it, expect, vi } from 'vitest';
import { WebReaderPipeline } from './pipeline.js';
import type { IHttpFetcher, IRenderer, IExtractor } from './types.js';

const URL = 'https://example.com';

function makeDeps(fetchResult: Awaited<ReturnType<IHttpFetcher['fetch']>>) {
  const fetcher: IHttpFetcher = { fetch: vi.fn().mockResolvedValue(fetchResult) };
  const renderer: IRenderer = { render: vi.fn().mockResolvedValue('<p>rendered</p>') };
  const extractor: IExtractor = { extract: vi.fn().mockResolvedValue('extracted text') };
  return { fetcher, renderer, extractor };
}

describe('WebReaderPipeline', () => {
  it('passes HTTP html to extractor when needsRendering=false', async () => {
    const { fetcher, renderer, extractor } = makeDeps({
      html: '<p>static</p>', contentType: 'text/html', needsRendering: false,
    });
    const result = await new WebReaderPipeline(fetcher, renderer, extractor).read(URL);

    expect(result).toBe('extracted text');
    expect(renderer.render).not.toHaveBeenCalled();
    expect(extractor.extract).toHaveBeenCalledWith('<p>static</p>', URL);
  });

  it('calls renderer then extractor when needsRendering=true', async () => {
    const { fetcher, renderer, extractor } = makeDeps({
      html: '', contentType: 'text/html', needsRendering: true,
    });
    const result = await new WebReaderPipeline(fetcher, renderer, extractor).read(URL);

    expect(result).toBe('extracted text');
    expect(renderer.render).toHaveBeenCalledWith(URL);
    expect(extractor.extract).toHaveBeenCalledWith('<p>rendered</p>', URL);
  });

  it('propagates fetcher errors', async () => {
    const fetcher: IHttpFetcher = { fetch: vi.fn().mockRejectedValue(new Error('HTTP 404: Not Found')) };
    const renderer: IRenderer = { render: vi.fn() };
    const extractor: IExtractor = { extract: vi.fn() };

    await expect(new WebReaderPipeline(fetcher, renderer, extractor).read(URL))
      .rejects.toThrow('HTTP 404: Not Found');
    expect(renderer.render).not.toHaveBeenCalled();
    expect(extractor.extract).not.toHaveBeenCalled();
  });

  it('propagates renderer errors', async () => {
    const { fetcher, renderer, extractor } = makeDeps({
      html: '', contentType: 'text/html', needsRendering: true,
    });
    (renderer.render as ReturnType<typeof vi.fn>).mockRejectedValue(new Error('Playwright timeout'));

    await expect(new WebReaderPipeline(fetcher, renderer, extractor).read(URL))
      .rejects.toThrow('Playwright timeout');
  });
});

describe('WebReaderPipeline content guards', () => {
  it('rejects a Chrome navigation-error page instead of extracting it', async () => {
    const errorPage = '<body><h1>Не удается получить доступ к сайту</h1><p>ERR_SOCKET_NOT_CONNECTED</p></body>';
    const { fetcher, renderer, extractor } = makeDeps({
      html: errorPage, contentType: 'text/html', needsRendering: false,
    });

    await expect(new WebReaderPipeline(fetcher, renderer, extractor).read(URL))
      .rejects.toThrow(/navigation error \(ERR_SOCKET_NOT_CONNECTED\)/);
    expect(extractor.extract).not.toHaveBeenCalled();
  });

  it('rejects canvas filler that extracts to punctuation', async () => {
    const { fetcher, renderer, extractor } = makeDeps({
      html: '<body>irrelevant</body>', contentType: 'text/html', needsRendering: false,
    });
    (extractor.extract as ReturnType<typeof vi.fn>).mockResolvedValue('.'.repeat(4000));

    await expect(new WebReaderPipeline(fetcher, renderer, extractor).read(URL))
      .rejects.toThrow(/No readable content/);
  });

  it('strips inline base64 payloads from extracted markdown', async () => {
    const { fetcher, renderer, extractor } = makeDeps({
      html: '<body>page</body>', contentType: 'text/html', needsRendering: false,
    });
    (extractor.extract as ReturnType<typeof vi.fn>)
      .mockResolvedValue(`Новость дня\n\n![](data:image/png;base64,${'C'.repeat(5000)})`);

    const result = await new WebReaderPipeline(fetcher, renderer, extractor).read(URL);
    expect(result).toBe('Новость дня');
  });
});
