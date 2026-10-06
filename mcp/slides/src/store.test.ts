import { afterAll, describe, expect, it } from 'vitest';
import { mkdtemp, readdir, readFile, rm, stat } from 'node:fs/promises';
import { tmpdir } from 'node:os';
import path from 'node:path';
import { DeckStore } from './store.js';
import { findFonts, themeFontFiles } from './fonts.js';

const tmp = await mkdtemp(path.join(tmpdir(), 'slides-store-'));
afterAll(() => rm(tmp, { recursive: true, force: true }));

describe('DeckStore with bundled fonts', async () => {
  const fonts = await findFonts();
  const store = new DeckStore(path.join(tmp, 'decks'), fonts);
  await store.init();

  it('finds the committed fonts and links decks to the local copy', async () => {
    expect(fonts).not.toBeNull();
    const { id } = await store.create({ title: 'Local', theme: 'paper', slides: [{ layout: 'title', title: 'x' }] });
    const html = await readFile(path.join(store.dir(id), 'index.html'), 'utf8');
    expect(html).toContain('href="../_fonts/paper.css"');
    expect(html).not.toContain('fonts.googleapis.com');
    expect((await stat(path.join(tmp, 'decks', '_fonts', 'paper.css'))).isFile()).toBe(true);
  });

  it('bundles a self-contained site: only used assets, only the theme fonts, world-readable', async () => {
    const { id } = await store.create({
      title: 'Bundle', theme: 'forest',
      slides: [{ layout: 'image', src: 'assets/used.svg' }],
    });
    await store.addAsset(id, 'used.svg', Buffer.from('<svg xmlns="http://www.w3.org/2000/svg"/>'));
    await store.addAsset(id, 'unused.svg', Buffer.from('<svg xmlns="http://www.w3.org/2000/svg"/>'));
    const out = path.join(tmp, 'bundles', id);
    const pdf = Buffer.from('%PDF-1.4 test');
    await store.bundle(id, out, pdf);

    expect((await readdir(out)).sort()).toEqual(['assets', 'deck.pdf', 'fonts', 'index.html']);
    expect(await readdir(path.join(out, 'assets'))).toEqual(['used.svg']);
    const expected = [...await themeFontFiles(fonts!.dir, 'forest'), 'forest.css'].sort();
    expect((await readdir(path.join(out, 'fonts'))).sort()).toEqual(expected);
    const html = await readFile(path.join(out, 'index.html'), 'utf8');
    expect(html).toContain('href="fonts/forest.css"');
    expect(html).toContain('href="deck.pdf"');
    expect((await stat(path.join(out, 'index.html'))).mode & 0o777).toBe(0o644);
    expect((await stat(path.join(out, 'fonts'))).mode & 0o777).toBe(0o755);
  });
});
