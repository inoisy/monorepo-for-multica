import type { McpServer } from '@modelcontextprotocol/sdk/server/mcp.js';
import * as z from 'zod';
import { Deck, Slide } from './schema.js';
import { THEMES } from './themes.js';
import { lintDeck, type Issue } from './lint.js';
import { checkRender, screenshots } from './browser.js';
import { exportDeck } from './export.js';
import type { DeckStore } from './store.js';

export interface ToolContext {
  store: DeckStore;
  /** Base URL where the HTTP server serves decks, e.g. http://host:3076. Empty when only stdio runs. */
  publicUrl: string;
}

type Content = { type: 'text'; text: string } | { type: 'image'; data: string; mimeType: string };

const ok = (text: string, extra: Content[] = []) => ({ content: [{ type: 'text' as const, text }, ...extra] });
const fail = (err: unknown) => ({
  content: [{ type: 'text' as const, text: `Error: ${formatError(err)}` }],
  isError: true,
});

function formatError(err: unknown): string {
  if (err instanceof z.ZodError) {
    return 'invalid deck data:\n' + err.issues.map(i => `  - ${i.path.join('.') || '(root)'}: ${i.message}`).join('\n');
  }
  return err instanceof Error ? err.message : String(err);
}

function formatIssues(issues: Issue[]): string {
  if (!issues.length) return 'Design lint: clean.';
  return `Design lint (${issues.length}):\n` + issues
    .map(i => `  - [${i.level}] ${i.slide ? `slide ${i.slide}` : 'deck'}: ${i.message}`).join('\n');
}

const Id = z.string().describe('Deck id returned by deck_create.');
const Index = z.number().int().min(1).describe('1-based slide number.');

export function registerTools(server: McpServer, ctx: ToolContext): void {
  const { store } = ctx;
  const links = (id: string) => ctx.publicUrl
    ? `Preview: ${ctx.publicUrl}/d/${id}/  (G — overview, F — fullscreen)`
    : `Preview file: ${store.dir(id)}/index.html`;

  async function afterWrite(id: string, deck: Deck, what: string) {
    return ok(`${what}\nDeck "${deck.title}" (${id}) — ${deck.slides.length} slides, theme ${deck.theme}.\n${links(id)}\n${formatIssues(lintDeck(deck))}\n` +
      'Next: fix lint warnings, then call deck_check and deck_preview to look at the result.');
  }

  async function mutate(id: string, what: string, fn: (d: Deck) => Deck | void) {
    const deck = await store.get(id);
    const next = fn(deck) ?? deck;
    const saved = await store.save(id, next);
    return afterWrite(id, saved, what);
  }

  server.registerTool('slides_catalog', {
    title: 'Slides: themes and layouts',
    description: 'List available themes (with mood) and slide layouts with their fields. Call once before building a deck.',
    inputSchema: z.object({}),
    annotations: { readOnlyHint: true },
  }, async () => {
    const themes = Object.values(THEMES).map(t => `  - ${t.id} (${t.dark ? 'dark' : 'light'}; ${t.fonts.display} / ${t.fonts.body}): ${t.mood}`).join('\n');
    const layouts = Slide.options.map(o => {
      const fields = Object.entries(o.shape).filter(([k]) => k !== 'layout' && k !== 'notes')
        .map(([k, v]) => `${k}${(v as z.ZodType).safeParse(undefined).success ? '?' : ''}`);
      return `  - ${o.shape.layout.value}: ${fields.join(', ')}`;
    }).join('\n');
    return ok(`Themes:\n${themes}\n\nLayouts (every slide also accepts notes?):\n${layouts}\n\n` +
      'Bento tiles: kind = stat | text | list | chart | image | quote; each has x, y (0-based cell), w, h (span), accent? = none|accent|accent2|muted.\n' +
      'Charts: type = bar | line | area | donut | progress; series: [{label?, values[]}], labels?, unit?, highlight? (index to emphasize).\n' +
      'Inline text supports **bold**, *italic*, `code`, ==accent highlight==, and \\n line breaks.\n' +
      'Images: absolute https URL, data: URL, or "assets/<name>" after asset_add.');
  });

  server.registerTool('deck_create', {
    title: 'Create deck',
    description: 'Create a new deck. You may pass all slides at once. Returns the deck id, preview URL and design lint.',
    inputSchema: z.object({
      title: z.string().min(1),
      theme: z.enum(Object.keys(THEMES) as [string, ...string[]]).optional(),
      footer: z.string().optional(),
      slides: z.array(Slide).optional(),
    }),
  }, async args => {
    try {
      const { id, deck } = await store.create(args);
      return afterWrite(id, deck, `Created deck ${id}.`);
    } catch (e) { return fail(e); }
  });

  server.registerTool('deck_get', {
    title: 'Get deck',
    description: 'Return the full deck JSON. Read it before editing a deck you did not just write.',
    inputSchema: z.object({ id: Id }),
    annotations: { readOnlyHint: true },
  }, async ({ id }) => {
    try { return ok(JSON.stringify(await store.get(id), null, 2)); } catch (e) { return fail(e); }
  });

  server.registerTool('deck_list', {
    title: 'List decks',
    description: 'List existing decks, newest first.',
    inputSchema: z.object({}),
    annotations: { readOnlyHint: true },
  }, async () => {
    try {
      const decks = await store.list();
      return ok(decks.length ? decks.map(d => `${d.id}  "${d.title}"  ${d.slides} slides  ${d.updated}`).join('\n') : 'No decks yet.');
    } catch (e) { return fail(e); }
  });

  server.registerTool('deck_update', {
    title: 'Update deck settings',
    description: 'Change deck title, theme or footer. Switching theme restyles every slide.',
    inputSchema: z.object({
      id: Id,
      title: z.string().min(1).optional(),
      theme: z.enum(Object.keys(THEMES) as [string, ...string[]]).optional(),
      footer: z.string().optional(),
    }),
  }, async ({ id, ...patch }) => {
    try { return await mutate(id, 'Updated deck settings.', d => ({ ...d, ...patch } as Deck)); } catch (e) { return fail(e); }
  });

  server.registerTool('slides_set', {
    title: 'Replace all slides',
    description: 'Replace the whole slide list in one call. Best for the first full draft and for big restructures.',
    inputSchema: z.object({ id: Id, slides: z.array(Slide).min(1) }),
  }, async ({ id, slides }) => {
    try { return await mutate(id, `Set ${slides.length} slides.`, d => ({ ...d, slides })); } catch (e) { return fail(e); }
  });

  server.registerTool('slide_upsert', {
    title: 'Replace or insert one slide',
    description: 'mode "replace" overwrites slide N; mode "insert" puts the new slide at position N and shifts the rest. Use index = slides+1 to append.',
    inputSchema: z.object({ id: Id, index: Index, slide: Slide, mode: z.enum(['replace', 'insert']).default('replace') }),
  }, async ({ id, index, slide, mode }) => {
    try {
      return await mutate(id, `${mode === 'insert' ? 'Inserted' : 'Replaced'} slide ${index}.`, d => {
        const max = mode === 'insert' ? d.slides.length + 1 : d.slides.length;
        if (index > max) throw new Error(`index ${index} out of range (1..${max})`);
        d.slides.splice(index - 1, mode === 'insert' ? 0 : 1, slide);
      });
    } catch (e) { return fail(e); }
  });

  server.registerTool('slide_delete', {
    title: 'Delete slide',
    description: 'Remove slide N.',
    inputSchema: z.object({ id: Id, index: Index }),
    annotations: { destructiveHint: true },
  }, async ({ id, index }) => {
    try {
      return await mutate(id, `Deleted slide ${index}.`, d => {
        if (index > d.slides.length) throw new Error(`index ${index} out of range (1..${d.slides.length})`);
        d.slides.splice(index - 1, 1);
      });
    } catch (e) { return fail(e); }
  });

  server.registerTool('slide_move', {
    title: 'Move slide',
    description: 'Move slide from position `from` to position `to`.',
    inputSchema: z.object({ id: Id, from: Index, to: Index }),
  }, async ({ id, from, to }) => {
    try {
      return await mutate(id, `Moved slide ${from} → ${to}.`, d => {
        if (from > d.slides.length || to > d.slides.length) throw new Error(`index out of range (1..${d.slides.length})`);
        const [s] = d.slides.splice(from - 1, 1);
        d.slides.splice(to - 1, 0, s);
      });
    } catch (e) { return fail(e); }
  });

  server.registerTool('deck_check', {
    title: 'Check deck rendering',
    description: 'Render the deck in a real browser and report text that overflows its box, type that auto-shrank, broken images, missing fonts, plus design lint. Run before showing a deck to anyone.',
    inputSchema: z.object({ id: Id }),
    annotations: { readOnlyHint: true },
  }, async ({ id }) => {
    try {
      const deck = await store.get(id);
      const r = await checkRender(store.dir(id));
      const lines: string[] = [];
      if (!r.fontsLoaded) lines.push('  - [warn] deck: theme fonts did not load (host offline from Google Fonts?); preview uses a fallback font');
      for (const s of r.slides) {
        for (const o of s.overflow) lines.push(`  - [error] slide ${s.slide}: ${o} overflows even at minimum type size — cut text or give it more space`);
        for (const x of s.shrunk) if (x.scale < 0.9) lines.push(`  - [warn] slide ${s.slide}: ${x.where} auto-shrank to ${Math.round(x.scale * 100)}% — trim text so it renders at full size`);
        for (const b of s.brokenImages) lines.push(`  - [error] slide ${s.slide}: image failed to load: ${b}`);
      }
      return ok(`${lines.length ? `Render check (${lines.length}):\n${lines.join('\n')}` : 'Render check: clean.'}\n${formatIssues(lintDeck(deck))}`);
    } catch (e) { return fail(e); }
  });

  server.registerTool('deck_preview', {
    title: 'Preview slides as images',
    description: 'Screenshot slides so you can see them. Look at every slide you changed and fix anything that looks unbalanced, cramped or empty.',
    inputSchema: z.object({
      id: Id,
      slides: z.array(Index).max(12).optional().describe('Slide numbers; default all (max 12 per call).'),
      scale: z.number().min(0.25).max(1).default(0.5).describe('0.5 = 960×540, enough to judge layout.'),
    }),
    annotations: { readOnlyHint: true },
  }, async ({ id, slides, scale }) => {
    try {
      const deck = await store.get(id);
      const pick = slides?.length ? slides : deck.slides.map((_, i) => i + 1).slice(0, 12);
      const shots = await screenshots(store.dir(id), pick, scale);
      const images: Content[] = shots.flatMap(s => [
        { type: 'text' as const, text: `Slide ${s.slide} (${deck.slides[s.slide - 1]?.layout ?? 'empty'})` },
        { type: 'image' as const, data: s.png.toString('base64'), mimeType: 'image/png' },
      ]);
      const more = !slides?.length && deck.slides.length > 12 ? ` Showing 1–12 of ${deck.slides.length}; pass slides to see the rest.` : '';
      return ok(`${shots.length} slide(s).${more}`, images);
    } catch (e) { return fail(e); }
  });

  server.registerTool('deck_export', {
    title: 'Export deck',
    description: 'Export to pdf (vector text, best for sharing), pptx (one full-slide image per slide, speaker notes kept) or png (one file per slide).',
    inputSchema: z.object({ id: Id, format: z.enum(['pdf', 'pptx', 'png']) }),
  }, async ({ id, format }) => {
    try {
      const deck = await store.get(id);
      const files = await exportDeck(store.dir(id), deck, format);
      const where = files.map(f => ctx.publicUrl ? `${ctx.publicUrl}/d/${id}/${f}` : `${store.dir(id)}/${f}`);
      return ok(`Exported ${format}:\n${where.join('\n')}`);
    } catch (e) { return fail(e); }
  });

  server.registerTool('asset_add', {
    title: 'Add image asset',
    description: 'Store an image in the deck from a URL, a local file path on the slides host, or base64. Returns the src to use in slides ("assets/<name>").',
    inputSchema: z.object({
      id: Id,
      name: z.string().describe('File name with extension, e.g. team.jpg'),
      url: z.string().url().optional(),
      path: z.string().optional(),
      base64: z.string().optional(),
    }),
  }, async ({ id, name, url, path, base64 }) => {
    try {
      let src: string;
      if (url) {
        const res = await fetch(url, { signal: AbortSignal.timeout(20_000) });
        if (!res.ok) throw new Error(`download failed: HTTP ${res.status}`);
        const buf = Buffer.from(await res.arrayBuffer());
        if (buf.length > 15 * 1024 * 1024) throw new Error('image larger than 15 MB');
        src = await store.addAsset(id, name, buf);
      } else if (path) {
        src = await store.addAsset(id, name, { fromPath: path });
      } else if (base64) {
        src = await store.addAsset(id, name, Buffer.from(base64.replace(/^data:[^,]+,/, ''), 'base64'));
      } else {
        throw new Error('pass one of url, path or base64');
      }
      return ok(`Stored. Use src: "${src}"`);
    } catch (e) { return fail(e); }
  });
}

