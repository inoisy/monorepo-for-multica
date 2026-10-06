import { describe, expect, it } from 'vitest';
import { Deck } from './schema.js';
import { renderDeck } from './render.js';
import { inline } from './text.js';

describe('inline markup', () => {
  it('escapes HTML before applying markup', () => {
    expect(inline('<script>x</script> **b** ==h== *i* `c`')).toBe(
      '&lt;script&gt;x&lt;/script&gt; <strong>b</strong> <mark>h</mark> <em>i</em> <code>c</code>');
  });
});

describe('renderDeck', () => {
  it('renders every layout with theme fonts and tile placement', () => {
    const deck = Deck.parse({
      title: 'Demo',
      theme: 'aurora',
      slides: [
        { layout: 'title', title: 'Hello' },
        { layout: 'bento', grid: { cols: 3, rows: 2 }, tiles: [
          { kind: 'stat', x: 0, y: 0, w: 2, h: 2, value: '9', label: 'l' },
          { kind: 'chart', x: 2, y: 0, w: 1, h: 2, chart: { type: 'bar', series: [{ values: [1, 2] }] } },
        ] },
        { layout: 'quote', quote: 'q' },
      ],
    });
    const html = renderDeck(deck);
    expect(html).toContain('family=Unbounded');
    expect(html).toContain('grid-column:1 / span 2;grid-row:1 / span 2;');
    expect(html.match(/<section class="slide/g)).toHaveLength(3);
  });

  it('does not let slide text inject markup into attributes', () => {
    const deck = Deck.parse({ title: 't', slides: [{ layout: 'image', src: '"><script>alert(1)</script>' }] });
    expect(renderDeck(deck)).not.toContain('<script>alert(1)');
  });
});
