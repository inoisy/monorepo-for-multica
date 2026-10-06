# slides

A self-hosted take on Claude Slides, built as an MCP server. An agent writes a
deck as JSON: a theme, then one layout per slide with its slots filled. The
server renders it with curated themes and layouts (including bento grids),
checks the result in a real browser, and exports PDF, PPTX or PNG. Agents
never write CSS, which is why decks stay consistent whichever agent made them.

![Sample slides in graphite, paper and aurora](docs/preview.jpg)

Pair it with the `skills/slide-design` skill in this monorepo. The skill
teaches the agent storyline, layout choice, bento composition and the visual
self-review loop.

## What's inside

- **8 themes** (`graphite`, `paper`, `aurora`, `swiss`, `forest`, `sunrise`,
  `ocean`, `terminal`). Each one fixes a palette, a font pairing with Cyrillic
  support, a corner radius and a display weight.
- **11 layouts**: `title`, `section`, `statement`, `bullets`, `bento`,
  `split`, `stats`, `quote`, `timeline`, `compare`, `image`.
- **Bento tiles**: `stat`, `text`, `list`, `chart`, `image`, `quote`, placed
  on a 2–6 × 1–4 grid. Stat numbers are sized to their tile's pixel box and
  the theme font's width.
- **Charts**: `bar`, `line`, `area`, `donut`, `progress`, drawn in HTML/SVG
  in theme colors, with one category highlighted.
- **Two layers of checks**:
  - Design lint runs on every edit. It catches word budgets, bento overlaps
    and holes, equal-size tiles, too many accents, and monotone decks.
  - `deck_check` renders the deck in Chromium. It reports text that still
    overflows after auto-fit, type that auto-shrank, broken images, and fonts
    that failed to load.
- **`deck_preview`** returns screenshots, so the agent looks at its slides
  and fixes them.

## Tools

| Tool | Purpose |
|---|---|
| `slides_catalog` | Themes (with mood) and every layout's fields |
| `deck_create` | New deck, optionally with all slides; returns id, preview URL, lint |
| `deck_get` / `deck_list` | Read a deck / list decks |
| `deck_update` | Title, theme, footer |
| `slides_set` | Replace all slides |
| `slide_upsert` / `slide_delete` / `slide_move` | Edit single slides |
| `deck_check` | Browser render check + lint |
| `deck_preview` | PNG screenshots (up to 12 per call, 960×540 by default) |
| `deck_export` | `pdf` (vector), `pptx` (one full-slide image per slide, notes kept), `png` |
| `asset_add` | Store an image from URL, host path or base64 → `assets/<name>` |

Every mutating tool answers with the preview URL and the current lint, so the
agent sees problems right after each change.

## Run

### Docker (recommended on the Multica host)

```bash
cd mcp/slides
SLIDES_PUBLIC_URL=http://<host>:3076 docker compose up -d --build
```

- MCP endpoint: `http://<host>:3076/message` (Streamable HTTP, stateless).
- Deck index: `http://<host>:3076/`. A deck's preview is at `/d/<id>/`:
  arrow keys move between slides, `G` opens the overview, `F` goes
  fullscreen.
- Decks persist in `./data/decks/<id>/`: `deck.json`, the rendered
  `index.html`, `assets/` and `exports/`.

### Local

```bash
pnpm install && pnpm build
node dist/index.js --http      # HTTP on $PORT (default 3000)
node dist/index.js             # stdio
pnpm demo graphite             # sample deck covering every layout → data/demo/
```

| Env | Default | Meaning |
|---|---|---|
| `PORT` | `3000` | HTTP port |
| `SLIDES_DIR` | `./data/decks` | Where decks live |
| `SLIDES_PUBLIC_URL` | `http://localhost:$PORT` in HTTP mode | Base URL put into preview/export links |
| `SLIDES_CHROMIUM_PATH` | Playwright's bundled browser | Use a different Chromium binary |

Theme fonts load from Google Fonts. On an offline host, decks render with
system fallback fonts and `deck_check` warns about it.

## Connect to Multica / Claude Code

Register the server in the agent's MCP config:

```json
{
  "mcpServers": {
    "slides": { "type": "http", "url": "http://<host>:3076/message" }
  }
}
```

Then import the skill into the Multica workspace from this repo's
`skills/slide-design` directory, and assign it to the agents that should make
decks. A typical issue: "Сделай презентацию по итогам Q3 для руководства". The
agent drafts, checks, previews, fixes, exports, and posts the preview URL and
PDF link back into the issue.

## Design notes

- The deck model is deliberately narrow. Free-form HTML would give agents
  more room and produce worse slides. New visual needs should become a new
  layout or tile kind, not an escape hatch.
- Auto-fit is a safety net, not the plan. The page shrinks type inside
  overflowing boxes down to 62%, and `deck_check` reports anything below 90%,
  so agents cut text instead of relying on small type.
- The PPTX export uses images on purpose. Rebuilding these layouts as native
  PowerPoint shapes would lose the typography the deck exists for. The PDF
  keeps vector text.

## Tests

```bash
pnpm test       # lint rules, renderer, escaping
pnpm typecheck
```
