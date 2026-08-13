import { describe, it, expect } from 'vitest';
import { DefuddleExtractor } from './extractor-defuddle.js';

const URL = 'https://example.com/article';

const ARTICLE_HTML = `<!DOCTYPE html>
<html>
<head><title>How Caching Works</title></head>
<body>
  <header><nav><a href="/">Home</a></nav></header>
  <main>
    <article>
      <h1>How Caching Works</h1>
      <p>Caching stores the result of expensive operations so subsequent calls return faster.
      A cache hit means the data was found; a cache miss means the system must recompute.
      This trade-off is fundamental to systems design.</p>
      <p>There are several cache eviction policies: LRU removes the least recently used entry,
      LFU removes the least frequently used, and FIFO removes the oldest. Each has different
      performance characteristics depending on access patterns.</p>
      <h2>Distributed Caches</h2>
      <p>Redis and Memcached are the most common distributed caches. Redis supports richer
      data structures and persistence, while Memcached is simpler and purely in-memory.
      Both support horizontal scaling via consistent hashing.</p>
    </article>
  </main>
  <footer>© 2024</footer>
</body>
</html>`;

describe('DefuddleExtractor', () => {
  const extractor = new DefuddleExtractor();

  it('returns string for empty html', async () => {
    const result = await extractor.extract('<html><body></body></html>', URL);
    expect(typeof result).toBe('string');
  });

  it('extracts article content as non-empty markdown', async () => {
    const result = await extractor.extract(ARTICLE_HTML, URL);
    expect(result.length).toBeGreaterThan(0);
    expect(result).toContain('Cach');
  });

  it('uses atx headings (# prefix)', async () => {
    const result = await extractor.extract(ARTICLE_HTML, URL);
    if (result) expect(result).toMatch(/^#{1,6} /m);
  });

  it('output never has 3+ consecutive newlines', async () => {
    const result = await extractor.extract(ARTICLE_HTML, URL);
    expect(result).not.toMatch(/\n{3,}/);
  });

  it('strips empty anchor tags', async () => {
    const html = ARTICLE_HTML.replace(
      '<h1>How Caching Works</h1>',
      '<h1>How Caching Works</h1><a href="/empty"></a>'
    );
    const result = await extractor.extract(html, URL);
    if (result) expect(result).not.toMatch(/\[\s*\]\(\/empty\)/);
  });
});

describe('DefuddleExtractor portal fallback', () => {
  const feedPage = (n: number) => `<html><body><div class="teaser"><h1>Гороскоп</h1><p>${'Длинный текст гороскопа. '.repeat(40)}</p></div><div class="feed">`
    + Array.from({ length: n }, (_, i) => `<a href="https://news.example.ru/${i}">Заголовок новости номер ${i} про важное событие</a>`).join('')
    + '</div></body></html>';

  it('keeps the feed of a portal page, not just its lead block', async () => {
    const md = await new DefuddleExtractor().extract(feedPage(60), 'https://portal.example.ru/');
    expect(md).toContain('Заголовок новости номер 7');
    expect(md).toContain('news.example.ru/59');
  });

  it('leaves an article page alone', async () => {
    const article = `<html><body><article><h1>Как выпустить сертификат</h1><p>${'Текст статьи про TLS. '.repeat(80)}</p>`
      + '<a href="https://letsencrypt.org/">Let’s Encrypt документация по сертификатам</a></article></body></html>';
    const md = await new DefuddleExtractor().extract(article, 'https://blog.example.ru/tls');
    expect(md).toContain('Текст статьи про TLS');
    expect(md).not.toMatch(/^- \[/m);
  });
});
