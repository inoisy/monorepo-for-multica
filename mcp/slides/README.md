# slides

A self-hosted take on Claude Slides, built as an MCP server. An agent writes a
deck as JSON: a theme, then one layout per slide with its slots filled. The
server renders it with curated themes and layouts (including bento grids),
checks the result in a real browser, exports PDF, PPTX or PNG, and bundles a
static site that agents publish to the stand (`services/stand`) as a public
link. Agents never write CSS, which is why decks stay consistent whichever
agent made them.

![Sample slides in graphite, paper and aurora](docs/preview.jpg)

Pair it with the `skills/slide-design` skill in this monorepo. The skill
teaches the agent storyline, layout choice, bento composition and the visual
self-review loop.

## What's inside

- **8 themes** (`graphite`, `paper`, `aurora`, `swiss`, `forest`, `sunrise`,
  `ocean`, `terminal`). Each one fixes a palette, a font pairing with Cyrillic
  support, a corner radius and a display weight. The fonts are bundled
  (`fonts/`, 1.3 MB), so nothing loads from Google at runtime.
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
| `deck_bundle` | Self-contained static site for publishing (presenter view, embedded fonts, used assets, optional `deck.pdf`); returns its host path and `art_publish` arguments |
| `asset_add` | Store an image from URL, host path or base64 → `assets/<name>` |

Every mutating tool answers with the preview URL and the current lint, so the
agent sees problems right after each change.

## Run

### Docker (recommended on the agents' server)

```bash
cd mcp/slides
SLIDES_PUBLIC_URL=http://<host>:3076 docker compose up -d --build
```

Data lives in `$SLIDES_DATA` on the host (default `/srv/slides`), in
`decks/` and `bundles/`. Bundles are written world-readable, because
`stand art publish` copies them as the agent's OS user.

- MCP endpoint: `http://<host>:3076/message` (Streamable HTTP, stateless).
- Deck index: `http://<host>:3076/`. A deck's preview is at `/d/<id>/`:
  arrow keys move between slides, `G` opens the overview, `F` goes
  fullscreen.
- Decks persist in `<data>/decks/<id>/`: `deck.json`, the rendered
  `index.html`, `assets/` and `exports/`. On startup the server copies the
  bundled fonts to `<data>/decks/_fonts/` and re-renders every deck with the
  current renderer.

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
| `SLIDES_BUNDLE_DIR` | `<SLIDES_DIR>/../bundles` | Where `deck_bundle` writes sites |
| `SLIDES_BUNDLE_HOST_DIR` | same as `SLIDES_BUNDLE_DIR` | That directory as agents on the host see it (set when running in Docker) |
| `SLIDES_FONTS_DIR` | `<package>/fonts` | Bundled fonts; when missing, pages fall back to Google Fonts |
| `SLIDES_CHROMIUM_PATH` | Playwright's bundled browser | Use a different Chromium binary |

## Publishing to the stand

```
deck_bundle {id}                      → /srv/slides/bundles/<id>  + art_publish args
stand art_publish {path, title, issue} → https://art-<name>-<sfx>.stand.yakutov.com
deck_update {id, published_url}       → remembered; next bundle passes name: art-…
```

The published page is the presenter view: arrows navigate, `G` opens the
overview, `F` goes fullscreen, and "PDF ↓" downloads the PDF. Republishing
with the saved `art-…` name updates the same address. Stand limits
artifacts to 20 MB; `deck_bundle` refuses bigger bundles up front.

## Fonts

`fonts/` holds the woff2 files for every theme (Cyrillic and Latin subsets,
all SIL OFL 1.1; see `fonts/README.md`). Decks link to them locally, bundles
carry only their theme's files, and PDFs embed them. After changing a theme's
fonts, regenerate the directory (needs internet) and commit it:

```bash
pnpm fonts
```

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
pnpm test       # lint rules, renderer, escaping, bundling
pnpm typecheck
```
