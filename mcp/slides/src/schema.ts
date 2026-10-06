import * as z from 'zod';
import { THEME_IDS } from './themes.js';

// The deck model is deliberately narrow: an agent picks a layout and fills
// slots, it never writes CSS. Every visual decision (type scale, spacing,
// color) lives in the renderer and the theme, which is what keeps decks
// consistent no matter which agent wrote them.

/** Inline text. Supports **bold**, *italic*, `code` and ==highlight== (accent color). */
const Text = z.string().min(1);

const Accent = z.enum(['none', 'accent', 'accent2', 'muted'])
  .describe('Tile emphasis. "accent" fills the tile with the theme accent: use it on the single most important tile.');

const Series = z.object({
  label: z.string().optional(),
  values: z.array(z.number()).min(1),
});

export const Chart = z.object({
  type: z.enum(['bar', 'line', 'area', 'donut', 'progress']),
  labels: z.array(z.string()).optional().describe('Category labels (x axis, or donut segments).'),
  series: z.array(Series).min(1).max(3),
  unit: z.string().optional().describe('Suffix for values, e.g. "%" or "k".'),
  highlight: z.number().int().min(0).optional().describe('Index of the category to emphasize in accent color; the rest render muted.'),
});

const TileBase = {
  x: z.number().int().min(0),
  y: z.number().int().min(0),
  w: z.number().int().min(1),
  h: z.number().int().min(1),
  accent: Accent.optional(),
};

export const Tile = z.discriminatedUnion('kind', [
  z.object({ ...TileBase, kind: z.literal('stat'), value: z.string().min(1).max(12), label: Text, caption: z.string().optional() }),
  z.object({ ...TileBase, kind: z.literal('text'), eyebrow: z.string().optional(), title: z.string().optional(), body: z.string().optional() }),
  z.object({ ...TileBase, kind: z.literal('list'), title: z.string().optional(), items: z.array(Text).min(1).max(6) }),
  z.object({ ...TileBase, kind: z.literal('chart'), title: z.string().optional(), chart: Chart }),
  z.object({ ...TileBase, kind: z.literal('image'), src: z.string().min(1), alt: z.string().optional(), caption: z.string().optional() }),
  z.object({ ...TileBase, kind: z.literal('quote'), quote: Text, author: z.string().optional() }),
]);

const Visual = z.discriminatedUnion('kind', [
  z.object({ kind: z.literal('image'), src: z.string().min(1), alt: z.string().optional() }),
  z.object({ kind: z.literal('chart'), chart: Chart }),
  z.object({ kind: z.literal('stat'), value: z.string().min(1).max(12), label: Text }),
]);

const Common = {
  notes: z.string().optional().describe('Speaker notes. Not rendered on the slide.'),
};

export const Slide = z.discriminatedUnion('layout', [
  z.object({ ...Common, layout: z.literal('title'), eyebrow: z.string().optional(), title: Text, subtitle: z.string().optional(), meta: z.string().optional() }),
  z.object({ ...Common, layout: z.literal('section'), number: z.string().optional(), title: Text, subtitle: z.string().optional() }),
  z.object({ ...Common, layout: z.literal('statement'), eyebrow: z.string().optional(), statement: Text, support: z.string().optional() }),
  z.object({ ...Common, layout: z.literal('bullets'), eyebrow: z.string().optional(), title: Text, bullets: z.array(Text).min(1).max(6) }),
  z.object({
    ...Common,
    layout: z.literal('bento'),
    eyebrow: z.string().optional(),
    title: z.string().optional(),
    grid: z.object({ cols: z.number().int().min(2).max(6), rows: z.number().int().min(1).max(4) }),
    tiles: z.array(Tile).min(2).max(8),
  }),
  z.object({ ...Common, layout: z.literal('split'), eyebrow: z.string().optional(), title: Text, body: z.string().optional(), bullets: z.array(Text).max(5).optional(), visual: Visual, side: z.enum(['left', 'right']).optional() }),
  z.object({
    ...Common,
    layout: z.literal('stats'),
    eyebrow: z.string().optional(),
    title: z.string().optional(),
    stats: z.array(z.object({ value: z.string().min(1).max(12), label: Text, caption: z.string().optional() })).min(2).max(4),
  }),
  z.object({ ...Common, layout: z.literal('quote'), quote: Text, author: z.string().optional(), role: z.string().optional() }),
  z.object({
    ...Common,
    layout: z.literal('timeline'),
    eyebrow: z.string().optional(),
    title: Text,
    steps: z.array(z.object({ label: z.string().min(1), title: Text, body: z.string().optional() })).min(2).max(6),
  }),
  z.object({
    ...Common,
    layout: z.literal('compare'),
    eyebrow: z.string().optional(),
    title: Text,
    columns: z.array(z.object({ title: Text, items: z.array(Text).min(1).max(6), highlight: z.boolean().optional() })).length(2),
  }),
  z.object({ ...Common, layout: z.literal('image'), src: z.string().min(1), alt: z.string().optional(), title: z.string().optional(), caption: z.string().optional() }),
]);

export const Deck = z.object({
  title: z.string().min(1),
  theme: z.enum(THEME_IDS).default('graphite'),
  footer: z.string().optional().describe('Small text in every slide footer, e.g. company or event name.'),
  slides: z.array(Slide).default([]),
});

export type Deck = z.infer<typeof Deck>;
export type Slide = z.infer<typeof Slide>;
export type Tile = z.infer<typeof Tile>;
export type Chart = z.infer<typeof Chart>;
export type Layout = Slide['layout'];

export const LAYOUTS = Slide.options.map(o => o.shape.layout.value) as Layout[];
