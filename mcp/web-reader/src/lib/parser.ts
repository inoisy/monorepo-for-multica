import { Readability } from '@mozilla/readability';
import { JSDOM } from 'jsdom';
import * as cheerio from 'cheerio';
import TurndownService from 'turndown';
import { IExtractor } from './types.js';

function stripClutter(html: string): string {
  const $ = cheerio.load(html);
  $('script, style, noscript, link[rel="stylesheet"], template').remove();
  $('[class*="cookie"], [id*="cookie"], .gdpr, .consent').remove();
  $('[class*="popup"], .modal, .overlay').remove();
  $('[class*="newsletter"], [class*="subscribe"]').remove();
  $('.ad, .ads, .advert, .advertisement, [class*="ad-"], [id*="ad-"], iframe[src*="ad"], iframe[src*="doubleclick"]').remove();
  $('[class*="banner"]:not([role="main"])').remove();
  return $.html();
}

export function countExternalLinks(html: string, baseHost: string): number {
  const matches = html.match(/href=["']https?:\/\/([^"'/]+)/gi) ?? [];
  return matches.filter(m => !m.toLowerCase().includes(baseHost)).length;
}

export function parseHTML(html: string, url: string): string {
  const cleaned = stripClutter(html);
  const dom = new JSDOM(cleaned, { url });
  const reader = new Readability(dom.window.document);
  const article = reader.parse();

  let rawContent = article?.content ?? dom.window.document.body?.innerHTML ?? '';
  if (!rawContent.trim()) return '';

  // If Readability dropped most external links, fall back to <main> element.
  // Happens on search results pages, news portals, link directories.
  try {
    const baseHost = new URL(url).hostname.replace(/^www\./, '');
    const origExtLinks = countExternalLinks(cleaned, baseHost);
    const extractedExtLinks = countExternalLinks(rawContent, baseHost);
    const ratio = origExtLinks > 0 ? extractedExtLinks / origExtLinks : 1;
    if (ratio < 0.2 && origExtLinks >= 10) {
      const dom2 = new JSDOM(cleaned, { url });
      const main = dom2.window.document.querySelector('main, [role="main"]');
      if (main) {
        main.querySelectorAll('nav, header, footer, aside, [role="navigation"], [role="banner"]').forEach(el => el.remove());
        rawContent = main.innerHTML;
      }
    }
  } catch { /* non-critical */ }

  const turndown = new TurndownService({
    headingStyle: 'atx',
    bulletListMarker: '-',
    codeBlockStyle: 'fenced',
  });

  turndown.addRule('cleanEmptyLinks', {
    filter: (node: any) => node.nodeName === 'A' && !node.textContent?.trim(),
    replacement: () => '',
  });

  return turndown.turndown(rawContent)
    .replace(/\n{3,}/g, '\n\n')
    .replace(/^[ \t]+$/gm, '')
    .trim();
}

export class ReadabilityExtractor implements IExtractor {
  async extract(html: string, url: string): Promise<string> {
    return parseHTML(html, url);
  }
}
