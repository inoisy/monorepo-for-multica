import { mkdir, readFile, readdir, rename, writeFile, stat, copyFile, cp, rm, chmod } from 'node:fs/promises';
import { existsSync } from 'node:fs';
import { randomBytes } from 'node:crypto';
import path from 'node:path';
import { Deck } from './schema.js';
import { renderDeck } from './render.js';
import { themeFontFiles, type FontsDir } from './fonts.js';

// One directory per deck: deck.json is the source of truth, index.html is its
// rendering (rewritten on every save so the preview URL is always current),
// assets/ holds uploaded images, exports/ holds generated files.
// <root>/_fonts is a copy of the bundled fonts that every deck page links to
// as ../_fonts/<theme>.css, both over HTTP (/d/_fonts/) and from file://.

const ID_RE = /^[a-z0-9-]{4,64}$/;
const FONTS_SUBDIR = '_fonts';

export class DeckStore {
  constructor(readonly root: string, private readonly fonts: FontsDir | null = null) {}

  /** Installs bundled fonts next to the decks and re-renders every deck with the current renderer. */
  async init(): Promise<void> {
    await mkdir(this.root, { recursive: true });
    if (this.fonts) {
      const dest = path.join(this.root, FONTS_SUBDIR);
      const current = await readFile(path.join(dest, 'manifest.json'), 'utf8').catch(() => '');
      if (current !== this.fonts.manifest) {
        await rm(dest, { recursive: true, force: true });
        await cp(this.fonts.dir, dest, { recursive: true });
      }
    }
    for (const { id } of await this.list()) await this.render(id, await this.get(id));
  }

  get hasLocalFonts(): boolean {
    return this.fonts !== null;
  }

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
    await this.render(id, deck);
    return deck;
  }

  /** Rewrites index.html only; deck.json (and its mtime, used for ordering) stays untouched. */
  private async render(id: string, deck: Deck): Promise<void> {
    const fontsHref = this.fonts ? `../${FONTS_SUBDIR}/${deck.theme}.css` : undefined;
    await writeFile(path.join(this.dir(id), 'index.html'), renderDeck(deck, { fontsHref }));
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

  /**
   * Writes a self-contained static site for the deck into `outDir`
   * (replacing it): index.html in presenter mode, only the assets the slides
   * reference, the theme's font files, and optionally the PDF. Any static
   * host — e.g. `stand art publish <dir>` — can serve it as is.
   */
  async bundle(id: string, outDir: string, pdf?: Buffer): Promise<{ files: number; bytes: number }> {
    const deck = await this.get(id);
    const tmp = `${outDir}.tmp-${process.pid}`;
    await rm(tmp, { recursive: true, force: true });
    await mkdir(tmp, { recursive: true });

    const used = new Set(JSON.stringify(deck.slides).match(/assets\/[\w.-]+/g) ?? []);
    for (const rel of used) {
      const src = path.join(this.dir(id), rel);
      if (!existsSync(src)) continue; // deck_check reports it as a broken image
      await mkdir(path.join(tmp, 'assets'), { recursive: true });
      await copyFile(src, path.join(tmp, rel));
    }

    let fontsHref: string | undefined;
    if (this.fonts) {
      await mkdir(path.join(tmp, 'fonts'), { recursive: true });
      await copyFile(path.join(this.fonts.dir, `${deck.theme}.css`), path.join(tmp, 'fonts', `${deck.theme}.css`));
      for (const f of await themeFontFiles(this.fonts.dir, deck.theme)) {
        await copyFile(path.join(this.fonts.dir, f), path.join(tmp, 'fonts', f));
      }
      fontsHref = `fonts/${deck.theme}.css`;
    }
    if (pdf) await writeFile(path.join(tmp, 'deck.pdf'), pdf);
    await writeFile(path.join(tmp, 'index.html'), renderDeck(deck, { fontsHref, pdfHref: pdf ? 'deck.pdf' : undefined }));

    // The publisher copies the directory as the agent's OS user, not as the
    // user this server runs as: keep everything world-readable.
    let files = 0, bytes = 0;
    const walk = async (d: string): Promise<void> => {
      await chmod(d, 0o755);
      for (const e of await readdir(d, { withFileTypes: true })) {
        const p = path.join(d, e.name);
        if (e.isDirectory()) await walk(p);
        else { await chmod(p, 0o644); files++; bytes += (await stat(p)).size; }
      }
    };
    await walk(tmp);
    await rm(outDir, { recursive: true, force: true });
    await mkdir(path.dirname(outDir), { recursive: true });
    await rename(tmp, outDir);
    return { files, bytes };
  }
}
