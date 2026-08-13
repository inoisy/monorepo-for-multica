import { JSDOM } from 'jsdom';

/**
 * Last-resort extraction for portal front pages.
 *
 * Article extractors (defuddle, Readability) are built to find *one* story and
 * throw the rest away. On a front page there is no one story: mail.ru's home
 * page made both of them return the horoscope block and drop several hundred
 * headlines. What the agent actually wants there is the feed — headline plus
 * link — so harvest the anchors directly.
 *
 * Deliberately narrow: only used when the article extractors have already been
 * shown to have dropped nearly every link on the page.
 */

/** Anchor text shorter than this is chrome ("Ещё", "Войти"), not a headline. */
const MIN_HEADLINE_CHARS = 20;

/** Cap the output so a link farm cannot blow the whole token budget. */
const MAX_ITEMS = 300;

const CHROME_SELECTORS = 'nav, header, footer, aside, [role="navigation"], [role="banner"], [role="contentinfo"]';

export function extractLinkFeed(html: string, url: string): string {
  const dom = new JSDOM(html, { url });
  const doc = dom.window.document;

  doc.querySelectorAll('script, style, noscript, template').forEach(el => el.remove());
  doc.querySelectorAll(CHROME_SELECTORS).forEach(el => el.remove());

  const seen = new Set<string>();
  const items: string[] = [];

  for (const a of Array.from(doc.querySelectorAll('a[href]'))) {
    const text = a.textContent?.replace(/\s+/g, ' ').trim() ?? '';
    if (text.length < MIN_HEADLINE_CHARS) continue;

    const href = (a as HTMLAnchorElement).href;
    if (!href || !/^https?:/i.test(href)) continue;
    if (seen.has(href)) continue;
    seen.add(href);

    items.push(`- [${text}](${href})`);
    if (items.length >= MAX_ITEMS) break;
  }

  return items.join('\n');
}

/** How many headlines the harvest would yield — used to decide whether to use it. */
export function countFeedItems(markdown: string): number {
  return markdown ? markdown.split('\n').length : 0;
}
