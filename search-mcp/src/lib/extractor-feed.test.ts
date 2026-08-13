import { describe, it, expect } from 'vitest';
import { extractLinkFeed, countFeedItems } from './extractor-feed.js';

const page = (body: string) => `<html><body>${body}</body></html>`;

describe('extractLinkFeed', () => {
  it('harvests headline links as a markdown list', () => {
    const html = page('<a href="/news/1">Путин пообещал зеркальный ответ на захват судов</a>'
      + '<a href="/news/2">В Новороссийске ввели режим ЧС после атаки дронов</a>');
    const feed = extractLinkFeed(html, 'https://news.example.ru/');

    expect(feed).toContain('- [Путин пообещал зеркальный ответ на захват судов](https://news.example.ru/news/1)');
    expect(countFeedItems(feed)).toBe(2);
  });

  it('skips chrome: short anchors and navigation blocks', () => {
    const html = page('<nav><a href="/x">Достаточно длинный пункт меню в навигации</a></nav>'
      + '<a href="/y">Ещё</a>'
      + '<a href="/news/3">Настоящий заголовок новости об экономике</a>');
    const feed = extractLinkFeed(html, 'https://news.example.ru/');

    expect(countFeedItems(feed)).toBe(1);
    expect(feed).toContain('/news/3');
  });

  it('deduplicates repeated links and returns empty for a page without headlines', () => {
    const dup = page('<a href="/news/4">Один и тот же заголовок новости дня</a><a href="/news/4">Один и тот же заголовок новости дня</a>');
    expect(countFeedItems(extractLinkFeed(dup, 'https://news.example.ru/'))).toBe(1);
    expect(extractLinkFeed(page('<p>просто текст</p>'), 'https://news.example.ru/')).toBe('');
  });
});
