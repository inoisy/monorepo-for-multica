# Bento composition

Coordinates are 0-based cells: `x` is the column and `y` is the row; `w` and
`h` are spans. The grid is `cols` 2–6 by `rows` 1–4. Lint rejects tiles that
leave the grid or overlap, and warns about empty cells, equal-size tiles, and
more than one `accent` tile.

## The four rules

1. **One hero.** The largest tile, 2×2 or bigger, holds the key message,
   usually a `stat` with `accent: "accent"`.
2. **Mixed sizes and kinds.** Supporting tiles differ in size and kind
   (stat, chart, text, list, quote, image). Four identical stat tiles is a
   table, not a bento. Use `stats` instead.
3. **Cover every cell.** Holes look like bugs. Resize a neighbor to fill them.
4. **Calm tones.** At most one `accent` tile, optionally one `accent2`, and
   one `muted` for variety. All the rest stay default.

## Recipes

Copy the coordinates, then swap in your content.

### A. Hero + chart + three facts (4×3) — "quarter at a glance"

```
┌───────┬───────┐
│ HERO  │ chart │
│ 2×2   │ 2×2   │
├───┬───┼───────┤
│ s │ s │ text  │
└───┴───┴───────┘
```
```json
{ "layout": "bento", "eyebrow": "Q3 в цифрах", "title": "Рост по всем ключевым метрикам", "grid": { "cols": 4, "rows": 3 },
  "tiles": [
    { "kind": "stat",  "x": 0, "y": 0, "w": 2, "h": 2, "accent": "accent", "value": "+38%", "label": "Активные команды", "caption": "1 240 → 1 712" },
    { "kind": "chart", "x": 2, "y": 0, "w": 2, "h": 2, "title": "Задач в неделю, тыс.", "chart": { "type": "area", "labels": ["Июл","Авг","Сен","Окт"], "series": [{ "values": [12,15,19,26] }], "unit": "k" } },
    { "kind": "stat",  "x": 0, "y": 2, "w": 1, "h": 1, "value": "4.7", "label": "Оценка" },
    { "kind": "stat",  "x": 1, "y": 2, "w": 1, "h": 1, "accent": "muted", "value": "11 мин", "label": "Медиана задачи" },
    { "kind": "text",  "x": 2, "y": 2, "w": 2, "h": 1, "eyebrow": "Новое", "title": "Skills в проде", "body": "Навыки из общей библиотеки." } ] }
```

### B. Tall image + stacked insights (3×2) — product or team

```
┌─────┬───────────┐
│ img │ chart 2×1 │
│ 1×2 ├─────┬─────┤
│     │ s/d │quote│
└─────┴─────┴─────┘
```
`image` x0 y0 w1 h2 · `chart` x1 y0 w2 h1 · `chart` (donut) or `stat` x1 y1 w1 h1 · `quote` with `accent2` x2 y1 w1 h1.

### C. Feature overview (3×2), with no numbers

```
┌───────────┬─────┐
│ HERO text │ txt │
│ 2×1       │     │
├─────┬─────┴─────┤
│ txt │ list 2×1  │
└─────┴───────────┘
```
Hero `text` with `accent: "accent"` and a big `title`; the others are `text`
with `eyebrow` + `title` + one short `body`.

### D. KPI wall with one winner (4×2)

```
┌───────┬───┬───┐
│ HERO  │ s │ s │
│ 2×2   ├───┴───┤
│       │ chart │
└───────┴───────┘
```
`stat` hero x0 y0 w2 h2 · `stat` x2 y0 · `stat` x3 y0 · `chart` (bar or
progress) x2 y1 w2 h1.

### E. Wide strip (4×1 or 3×1)

Use it under a bento title for 3–4 numbers that need context tiles. Make one
tile 2 wide so the sizes vary: `stat` w2 accent + `stat` w1 + `text` w1.

## Tile sizing

| Kind | Min size | Sweet spot | Content budget |
|---|---|---|---|
| stat | 1×1 | 1×1 to 2×2 | value of 6 characters or fewer in 1-col tiles (4+ col grid); label of 4 words or fewer |
| text | 1×1 | 2×1 | title of 6 words or fewer, body of 12 words or fewer per cell |
| list | 2 cells | 1×2, 2×1 | 3–4 items of 6 words or fewer |
| chart | 2 cells (donut/progress fit 1×1) | 2×1, 2×2 | 4–8 points |
| quote | 1×1 | 1×1, 2×1 | 12 words or fewer |
| image | 1×1 | 1×2 (portrait), 2×2 | real image only |

## Anti-patterns

- **Equal tiles** (2×2 grid of 1×1 stats) — use a `stats` slide instead.
- **Paragraphs in tiles.** If a tile auto-shrinks, cut the text. A smaller
  font is not the fix.
- **Accent confetti.** Three colored tiles means none of them stands out.
- **Hero in a corner.** Don't put the hero bottom-right where it's read last.
- **Bento for one fact.** One fact belongs on a `statement`, `stats` or
  `split` with a stat visual.
- **More than 6 tiles.** 7–8 is allowed but rarely reads. Split it into two
  slides.
