import { IHttpFetcher, IRenderer, IExtractor } from './types.js';
import { detectNavErrorPage, isBlockPage } from './challenge.js';
import { sanitizeMarkdown, detectJunkContent } from './sanitize.js';

export class WebReaderPipeline {
  constructor(
    private httpFetcher: IHttpFetcher,
    private renderer: IRenderer,
    private extractor: IExtractor,
  ) {}

  async read(url: string): Promise<string> {
    const { html, needsRendering } = await this.httpFetcher.fetch(url);
    const finalHtml = needsRendering ? await this.renderer.render(url) : html;

    // A Chrome network-error page extracts into perfectly valid markdown. Catch
    // it here, before the extractor makes it look like the site answered.
    const navError = detectNavErrorPage(finalHtml);
    if (navError) {
      throw new Error(
        `Could not load ${url} — the browser hit a navigation error (${navError}). `
        + 'The page may redirect through a host that is unreachable from here.',
      );
    }

    // The renderer classifies its own output, but HTML that came straight over
    // HTTP has had no such check — and a refusal page extracts perfectly well.
    if (isBlockPage(finalHtml)) {
      throw new Error(
        `${url} refused the request — the response was an anti-bot block page, not the site. `
        + 'A proxy (WEB_PROXY_URL) or a per-host rule may be needed for this domain.',
      );
    }

    const content = sanitizeMarkdown(await this.extractor.extract(finalHtml, url));

    // An empty string reads to the agent as "the page says nothing", which is
    // never true — it means an error page or a failed extraction. Say so.
    if (!content.trim()) {
      throw new Error(
        `No readable content at ${url} — the response was an empty document or an HTTP error page.`,
      );
    }

    const junk = detectJunkContent(content);
    if (junk) throw new Error(`No readable content at ${url} — ${junk}.`);

    return content;
  }
}
