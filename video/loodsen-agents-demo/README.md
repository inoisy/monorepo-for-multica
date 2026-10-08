# loodsen-agents-demo

A 90-second Remotion video for presenting AI agents to Loodsen's administrative
staff. The film is generated from data, which is the point: it shows things that
are impractical to build by hand in PowerPoint or a video editor.

## Story (30 fps, 2700 frames)

| Frames | Scene | What only code can do |
|---|---|---|
| 0–450 | **Storm**: 48 documents float on a night sea, the unread counter climbs | procedural waves, rain, per-document physics |
| 450–900 | **Lighthouse**: the beam sweeps, day spreads outward from the lighthouse, documents fly into 4 buoys, the route is drawn | clip-path reveal, 48 independent bezier flights |
| 900–1800 | **Route**: the ship sails; at each buoy the camera dives about 18× into a card that lives *inside* the map (memo, Sphere task, report, LooC) | one continuous camera, log-scale zoom with no cuts |
| 1800–2250 | **Personal**: "the route was plotted for Anna", with that person's numbers | the whole film is re-rendered from props |
| 2250–2700 | **Reveal**: the film shrinks into an editor window and replays at 15×; then the logo assembles | the film is a component, so it can be nested in itself |

## Run

```bash
pnpm install
pnpm studio                       # interactive preview
REMOTION_BROWSER=/path/to/chrome-headless-shell pnpm render   # optional browser override
node scripts/render-personal.mjs  # one MP4 per persona in src/data.ts
node scripts/render-personal.mjs olga
```

## Customising

- `src/data.ts`: viewer names, departments and numbers (**demo values, replace
  them with real ones**), plus the agent log shown in the reveal.
- `src/brand.ts`: colours sampled from loodsen.ru.
- `src/icons.tsx`: the logo mark, traced from the site. Swap in the official
  SVG if you have it.
- `src/time.ts`: scene timings. `src/geometry.ts`: route and buoys on the map.

Fonts (Golos Text, JetBrains Mono) are copied from `mcp/slides/fonts`.
