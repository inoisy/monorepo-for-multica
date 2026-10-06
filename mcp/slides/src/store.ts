import { mkdir, readFile, readdir, rename, writeFile, stat, copyFile } from 'node:fs/promises';
import { randomBytes } from 'node:crypto';
import path from 'node:path';
import { Deck } from './schema.js';
import { renderDeck } from './render.js';

// One directory per deck: deck.json is the source of truth, index.html is its
// rendering (rewritten on every save so the preview URL is always current),
// assets/ holds uploaded images, exports/ holds generated files.

const ID_RE = /^[a-z0-9-]{4,64}$/;

export class DeckStore {
  constructor(readonly root: string) {}

  dir(id: string): string {
    if (!ID_RE.test(id)) throw new Error(`invalid deck id "${id}"`);
    return path.join(this.root, id);
  }

  async create(input: unknown, slug?: string): Promise<{ id: string; deck: Deck }> {
    const deck = Deck.parse(input);
    const base = (slug ?? deck.title).toLowerCase().normalize('NFKD')
      .replace(/[^a-z0-9]+/g, '-').replace(/^-+|-+$/g, '').slice(0, 40);
    const id = `${base ? base + '-' : 'deck-'}${randomBytes(3).toString('hex')}`;
    await mkdir(path.join(this.dir(id), 'assets'), { recursive: true });
    await this.save(id, deck);
    return { id, deck };
  }

  async get(id: string): Promise<Deck> {
    const raw = await readFile(path.join(this.dir(id), 'deck.json'), 'utf8').catch(() => {
      throw new Error(`deck "${id}" not found`);
    });
    return Deck.parse(JSON.parse(raw));
  }

  async save(id: string, input: unknown): Promise<Deck> {
    const deck = Deck.parse(input);
    const dir = this.dir(id);
    // Write-then-rename so a crash never leaves a half-written deck.json.
    const tmp = path.join(dir, `.deck.${process.pid}.tmp`);
    await writeFile(tmp, JSON.stringify(deck, null, 2));
    await rename(tmp, path.join(dir, 'deck.json'));
    await writeFile(path.join(dir, 'index.html'), renderDeck(deck));
    return deck;
  }

  async list(): Promise<{ id: string; title: string; slides: number; updated: string }[]> {
    await mkdir(this.root, { recursive: true });
    const out = [];
    for (const id of await readdir(this.root)) {
      if (!ID_RE.test(id)) continue;
      try {
        const deck = await this.get(id);
        const st = await stat(path.join(this.dir(id), 'deck.json'));
        out.push({ id, title: deck.title, slides: deck.slides.length, updated: st.mtime.toISOString() });
      } catch { /* not a deck directory */ }
    }
    return out.sort((a, b) => b.updated.localeCompare(a.updated));
  }

  /** Stores an asset and returns the deck-relative path to use as an image src. */
  async addAsset(id: string, name: string, data: Buffer | { fromPath: string }): Promise<string> {
    const safe = path.basename(name).replace(/[^\w.-]+/g, '_');
    if (!/\.(png|jpe?g|webp|gif|svg|avif)$/i.test(safe)) throw new Error('asset must be an image (png, jpg, webp, gif, svg, avif)');
    const dest = path.join(this.dir(id), 'assets', safe);
    await mkdir(path.dirname(dest), { recursive: true });
    if (Buffer.isBuffer(data)) await writeFile(dest, data);
    else await copyFile(data.fromPath, dest);
    return `assets/${safe}`;
  }
}
