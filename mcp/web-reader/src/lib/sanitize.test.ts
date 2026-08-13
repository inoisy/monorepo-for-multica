import { describe, test, expect } from 'vitest';
import { stripDataUris, detectJunkContent, sanitizeMarkdown } from './sanitize.js';

const bigPayload = 'A'.repeat(600);

describe('stripDataUris', () => {
  test('drops a base64 image but keeps its alt text', () => {
    const md = `before\n\n![sad cloud](data:image/png;base64,${bigPayload})\n\nafter`;
    const out = stripDataUris(md);
    expect(out).not.toContain('base64');
    expect(out).toContain('![sad cloud]');
    expect(out).toContain('after');
  });

  test('removes an alt-less base64 image entirely', () => {
    const out = stripDataUris(`text\n\n![](data:image/png;base64,${bigPayload})`);
    expect(out).not.toContain('data:');
    expect(out.trim()).toBe('text');
  });

  test('keeps link text when the href is a data URI', () => {
    const out = stripDataUris(`[download](data:text/plain;base64,${bigPayload})`);
    expect(out).toBe('download');
  });

  test('leaves small data URIs alone', () => {
    const md = '![px](data:image/gif;base64,R0lGODlhAQABAAAAACw=)';
    expect(stripDataUris(md)).toBe(md);
  });

  test('a Chrome error page shrinks to a fraction of its size', () => {
    const md = `## Не удается получить доступ к сайту\n\nERR_SOCKET_NOT_CONNECTED\n\n![](data:image/png;base64,${'B'.repeat(10_000)})`;
    expect(sanitizeMarkdown(md).length).toBeLessThan(200);
  });
});

describe('detectJunkContent', () => {
  test('flags canvas filler made of dots', () => {
    expect(detectJunkContent('.'.repeat(4000))).toMatch(/repeated character|letters or digits/);
  });

  test('flags a body with almost no letters', () => {
    expect(detectJunkContent('· '.repeat(500) + '- '.repeat(200))).not.toBeNull();
  });

  test('passes normal Russian prose', () => {
    const prose = 'Президент подписал закон о новых правилах регистрации. '.repeat(20);
    expect(detectJunkContent(prose)).toBeNull();
  });

  test('passes short pages without judging them', () => {
    expect(detectJunkContent('...')).toBeNull();
  });

  test('flags an empty document', () => {
    expect(detectJunkContent('   ')).not.toBeNull();
  });
});

describe('stripFillerRuns', () => {
  test('removes the canvas dot filler 2gis renders', () => {
    const md = '.'.repeat(1400) + '\n\n[Поиск](https://2gis.ru/moscow)';
    const out = sanitizeMarkdown(md);
    expect(out).toBe('[Поиск](https://2gis.ru/moscow)');
  });

  test('keeps markdown horizontal rules', () => {
    expect(sanitizeMarkdown('a\n\n---\n\nb')).toBe('a\n\n---\n\nb');
  });

  test('keeps ellipses and normal punctuation', () => {
    expect(sanitizeMarkdown('Он замолчал... и ушёл.')).toBe('Он замолчал... и ушёл.');
  });
});
