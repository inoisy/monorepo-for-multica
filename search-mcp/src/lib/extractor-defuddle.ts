import { JSDOM } from 'jsdom';
import Defuddle from 'defuddle';
import TurndownService from 'turndown';
import { IExtractor } from './types.js';
import { parseHTML } from './parser.js';
import { extractLinkFeed, countFeedItems } from './extractor-feed.js';
import { debug } from './utils.js';

/** The links an extraction kept, images excluded. */
function countMarkdownLinks(markdown: string): number {
  return (markdown.match(/(?<!!)\]\(\s*(?!#)[^)\s]+\)/g) ?? []).length;
}

const normalize = (s: string) => s.replace(/\s+/g, ' ').trim();

/**
 * Headline-shaped anchor texts, found with a regex rather than a DOM parse —
 * this runs on every extraction, and a 400 KB portal page costs ~300ms in JSDOM.
 * Long anchor text is the signal: chrome links say "Ещё", headlines say a
 * sentence.
 */
function headlineAnchors(html: string): string[] {
  const seen = new Set<string>();
  for (const m of html.matchAll(/<a\s[^>]*href=["'](?!#|javascript:|mailto:|tel:)[^"']+["'][^>]*>([\s\S]{20,400}?)<\/a>/gi)) {
    const text = normalize(m[1].replace(/<[^>]+>/g, ' '));
    if (text.length >= 20) seen.add(text);
  }
  return [...seen];
}

/** Share of the page's headlines that survived into the extracted markdown. */
function headlineCoverage(markdown: string, headlines: string[]): number {
  if (headlines.length === 0) return 1;
  const haystack = normalize(markdown);
  // Compare on a prefix: extractors reflow and re-punctuate long titles.
  const hits = headlines.filter(h => haystack.includes(h.slice(0, 40))).length;
  return hits / headlines.length;
}

function extractPaginationLinks(html: string, baseUrl: string): string {
  const dom = new JSDOM(html, { url: baseUrl });
  const doc = dom.window.document;

  // Grab all <a> inside pagination nav elements
  const navLinks = doc.querySelectorAll('nav a[href], [aria-label*="страниц"] a[href], [class*="pagination"] a[href], [class*="pager"] a[href]');
  const seen = new Set<string>();
  const links: string[] = [];

  navLinks.forEach((a: Element) => {
    const href = (a as HTMLAnchorElement).href;
    const text = a.textContent?.trim();
    if (!href || seen.has(href) || !text) return;
    // Only numeric page links and next/prev
    if (/^\d+$/.test(text) || /след|next|пред|prev/i.test(text)) {
      seen.add(href);
      links.push(`[${text}](${href})`);
    }
  });

  return links.length ? `\n\n---\nСтраницы: ${links.join(' · ')}` : '';
}

export class DefuddleExtractor implements IExtractor {
  async extract(html: string, url: string): Promise<string> {
    const dom = new JSDOM(html, { url });
    const result = new Defuddle(dom.window.document as unknown as Document, { url }).parse();
    if (!result?.content?.trim()) return '';
    const td = new TurndownService({ headingStyle: 'atx', bulletListMarker: '-', codeBlockStyle: 'fenced' });
    td.addRule('cleanEmptyLinks', {
      filter: (node: any) => node.nodeName === 'A' && !node.textContent?.trim(),
      replacement: () => '',
    });
    const markdown = td.turndown(result.content).replace(/\n{3,}/g, '\n\n').trim();
    const pagination = extractPaginationLinks(html, url);
    return this.preferLinkRichAlternative(markdown, html, url) + pagination;
  }

  /**
   * Defuddle optimises for *articles*: on a portal front page it locks onto one
   * story-shaped block and drops the feed. mail.ru is the clean example — it
   * returned the horoscope sidebar and none of the news.
   *
   * The test is headline coverage, not link count. Link ratios misfire in both
   * directions: a news front page has hundreds of chrome links (so a good
   * extraction still looks "lossy"), while Readability's `body.innerHTML`
   * fallback looks link-rich while being mostly ad markup. Asking "how many of
   * this page's headlines are still in the output" measures the thing we care
   * about directly.
   */
  private preferLinkRichAlternative(markdown: string, html: string, url: string): string {
    // Under 40 headline-shaped anchors the page is an article or a small
    // section page — the article extractor is the right tool and stays.
    const headlines = headlineAnchors(html);
    if (headlines.length < 40) return markdown;

    const coverage = headlineCoverage(markdown, headlines);
    if (coverage >= 0.3) return markdown;

    // Harvest the feed before trying Readability: on a page this link-dense
    // Readability falls back to the raw body, which is worse than a clean list.
    try {
      const feed = extractLinkFeed(html, url);
      const feedItems = countFeedItems(feed);
      if (feedItems >= 20) {
        debug(`[defuddle] ${url}: kept ${Math.round(coverage * 100)}% of ${headlines.length} headlines, using link feed (${feedItems})`);
        return feed;
      }
    } catch { /* keep whatever the article extractors produced */ }

    try {
      const alternative = parseHTML(html, url);
      if (alternative.trim() && headlineCoverage(alternative, headlines) > coverage) {
        debug(`[defuddle] ${url}: using readability (headline coverage ${Math.round(coverage * 100)}% -> better)`);
        return alternative;
      }
    } catch { /* fallback is best-effort; the defuddle result still stands */ }

    return markdown;
  }
}
