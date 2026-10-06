import { describe, expect, it } from 'vitest';
import { Deck } from './schema.js';
import { lintDeck, lintSlide } from './lint.js';

const bento = (tiles: unknown[], grid = { cols: 4, rows: 2 }) => Deck.parse({ title: 't', slides: [{ layout: 'bento', grid, tiles }] }).slides[0];

describe('bento lint', () => {
  it('accepts a fully covered grid with a hero tile', () => {
    const s = bento([
      { kind: 'stat', x: 0, y: 0, w: 2, h: 2, accent: 'accent', value: '42%', label: 'a' },
      { kind: 'stat', x: 2, y: 0, w: 2, h: 1, value: '7', label: 'b' },
      { kind: 'text', x: 2, y: 1, w: 2, h: 1, title: 'c' },
    ]);
    expect(lintSlide(s)).toEqual([]);
  });

  it('reports out-of-grid and overlapping tiles as errors', () => {
    const s = bento([
      { kind: 'stat', x: 0, y: 0, w: 2, h: 2, accent: 'accent', value: '1', label: 'a' },
      { kind: 'stat', x: 1, y: 1, w: 2, h: 1, value: '2', label: 'b' },
      { kind: 'stat', x: 3, y: 0, w: 2, h: 1, value: '3', label: 'c' },
    ]);
    const errors = lintSlide(s).filter(i => i.level === 'error').map(i => i.message);
    expect(errors.some(m => m.includes('overlaps'))).toBe(true);
    expect(errors.some(m => m.includes('does not fit'))).toBe(true);
  });

  it('warns about holes, equal tiles and multiple accents', () => {
    const s = bento([
      { kind: 'stat', x: 0, y: 0, w: 1, h: 1, accent: 'accent', value: '1', label: 'a' },
      { kind: 'stat', x: 1, y: 0, w: 1, h: 1, accent: 'accent', value: '2', label: 'b' },
      { kind: 'stat', x: 2, y: 0, w: 1, h: 1, value: '3', label: 'c' },
    ]);
    const msgs = lintSlide(s).map(i => i.message).join('\n');
    expect(msgs).toMatch(/empty cell/);
    expect(msgs).toMatch(/same size/);
    expect(msgs).toMatch(/2 tiles use accent/);
  });
});

describe('deck lint', () => {
  it('flags walls of text and monotone bullet decks', () => {
    const long = Array.from({ length: 20 }, (_, i) => `слово${i}`).join(' ');
    const deck = Deck.parse({
      title: 't',
      slides: [
        { layout: 'title', title: 'Hi' },
        ...Array.from({ length: 4 }, () => ({ layout: 'bullets', title: 'x', bullets: [long, long, long] })),
      ],
    });
    const msgs = lintDeck(deck).map(i => i.message).join('\n');
    expect(msgs).toMatch(/words on one slide/);
    expect(msgs).toMatch(/three "bullets" slides in a row/);
    expect(msgs).toMatch(/bullet lists/);
  });
});
