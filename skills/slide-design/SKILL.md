---
name: slide-design
description: Use when asked to make a presentation, slide deck, pitch, review, report-as-slides, or "слайды/презентацию/деку". Builds decks through the `slides` MCP server (deck_create, slides_set, deck_check, deck_preview, deck_bundle) and publishes them with the `stand` MCP server (art_publish). Covers how to make them look designed: narrative, layout choice, bento composition, copy, and the visual self-review loop.
---

# Slide design

You build decks with the `slides` MCP server. You never write HTML or CSS: you
pick a theme and a layout per slide and fill its slots with JSON. The renderer
owns typography, spacing and color. Your job is the part it can't do: **what
each slide says, which layout carries it, and checking the result with your
own eyes.**

If the `slides` tools are missing, stop and say so. Don't fall back to
hand-written HTML or a .pptx library.

## Workflow

1. **Brief.** Work out who the audience is, what decision or takeaway the deck
   drives, and how long it is. If the issue doesn't say, assume 8–12 slides for
   an internal review and 10–15 for a pitch. Write the deck in the language of
   the request.
2. **Storyline first, in plain text.** Write one sentence per slide, the
   headline that slide must land. Read only the headlines top to bottom: they
   should tell the whole story on their own. See `references/storytelling.md`.
3. **Pick a theme.** Call `slides_catalog` once and match the mood (table
   below). One theme per deck.
4. **Choose a layout per slide.** Use `references/layouts.md`. Vary the rhythm:
   never three of the same layout in a row, and bullets on at most a third of
   the slides.
5. **Draft the whole deck in one call:** `deck_create` with all slides. Fix
   every lint warning it returns before moving on.
6. **Check:** `deck_check` reports overflow, auto-shrunk text, broken images and
   missing fonts. Fix all errors, plus every warning that shrank text below 90%.
7. **Look:** `deck_preview` on every slide (12 per call). Judge each one
   against the review checklist below, fix with `slide_upsert`, then preview
   again. Expect two rounds. One round means you didn't look hard enough.
8. **Publish** (see below) and post the link in the issue with a 2–3 line
   summary of the storyline. If someone asks for a file, also `deck_export` as
   `pptx` or `pdf`.

## Publishing (deploy)

Every finished deck gets a public link on the stand. Publish it yourself;
don't ask a person to deploy it.

1. `deck_bundle` with the deck `id`. It writes a self-contained static site
   (presenter view, embedded fonts, assets, and a `deck.pdf` behind a
   "PDF ↓" button) and returns its absolute path plus ready-made
   `art_publish` arguments.
2. `art_publish` (stand MCP) with those arguments. Add `issue` with the
   Multica issue key so the artifact is tied to the task. The tool returns
   `https://art-<name>-<suffix>.stand.yakutov.com`, which lives 90 days by
   default (`ttl` up to 365).
3. `deck_update` with `published_url` set to that link. The deck remembers it,
   and the next `deck_bundle` hands you `name: art-…`, so republishing after
   edits **keeps the same address**. Always republish to the existing name
   rather than creating a second artifact.

If `art_publish` refuses with "больше 20 МБ", the images are too heavy:
replace them with smaller ones, or run `deck_bundle` with
`include_pdf: false`. If the stand tools are missing, post the slides
preview URL and the PDF from `deck_export` instead, and say that publishing
wasn't available.

## Theme by mood

| Need | Theme |
|---|---|
| Product, engineering, metrics, dark and confident | `graphite` |
| Strategy, research, editorial, serif | `paper` |
| Vision, AI, fundraising, dramatic | `aurora` |
| Minimal, neutral, any audience | `swiss` |
| Finance, sustainability, calm authority | `forest` |
| Marketing, culture, onboarding, friendly | `sunrise` |
| Client reports, QBRs, corporate | `ocean` |
| Dev tools, infra, security | `terminal` |

When the request names a brand color, take the theme whose accent is closest.
Don't apologize for it.

## The rules that make slides look designed

- **One idea per slide.** If a headline needs "and", split it.
- **Headlines are claims, not topics.** Write "Returns fell by half after
  self-review", not "Quality". The eyebrow carries the topic ("Quality").
- **Numbers become visuals.** A number in a sentence goes onto a `stats`
  slide, into a bento `stat` tile, or into a chart. Never bury "+38%" inside
  a bullet.
- **Emphasize one thing.** Use `==highlight==` once per slide at most, on
  the words that matter. In a bento, only one tile gets `accent: "accent"`.
  In a chart, `highlight` the bar the story is about; the rest go muted.
- **Word budget.** Up to 45 words per slide (60 for bento/compare), titles of
  12 words or fewer, bullets of 18 words or fewer, 3–5 bullets. Detail goes in
  `notes`.
- **Rhythm.** Alternate dense and airy. After a data-heavy bento, give a
  `statement` or `quote`. Use a `section` slide before each act in decks
  longer than 10 slides.
- **Open and close strong.** Slide 1 is `title`. Slide 2 is usually a
  `statement` with the single main takeaway. The last slide is a decision,
  ask or next step (`statement`, `timeline` or `compare`), not "Questions?".
  If you want a thank-you, use `image` or `title` with the contact in `meta`.

## Bento in one paragraph

A bento is a grid of tiles with **one hero** (the biggest tile, usually 2×2,
accent-filled), **2–4 supporting tiles** of mixed sizes, and **every cell
covered**. Mix tile kinds (stat + chart + text) so it doesn't read as a table.
Read order follows size, then top-left to bottom-right, so put the hero
top-left or on the left. Recipes and anti-patterns are in
`references/bento.md`. Read that file before your first bento.

## Visual review checklist (per preview)

- Can you get the point in 3 seconds? If not, cut text or change the layout.
- Is there one obvious focal point? Two competing accents means remove one.
- Is the slide balanced? A big empty area next to cramped text means the wrong
  layout. Try `statement`, `split` or a different bento grid.
- Do short lists look stranded? Three bullets of 4 words each work better as
  `stats`, a bento, or a `timeline`.
- Is any text tiny compared with the slide? That's auto-shrink. Trim it.
- Are the charts readable from the back of the room? Use 12 bars or fewer,
  and 5 donut segments or fewer.
- Do images crop the subject? Use a different image, or put it in a tile with
  a better aspect ratio.
- Across the deck: are there no three identical layouts in a row, and does
  the headline-only read-through tell the story?

## Images

Only use images that add information: the product, the team, a real
screenshot. Never use decorative stock. Add them with `asset_add` (URL, host
path or base64) and reference them as `assets/<name>`. If you have no real
images, don't use image layouts. The themes are designed to look complete
without them.

## References

- `references/layouts.md`: every layout, when to use it, a JSON example.
- `references/bento.md`: grid recipes, tile sizing, anti-patterns.
- `references/storytelling.md`: deck structures for reviews, pitches,
  proposals and research readouts, plus headline writing.
