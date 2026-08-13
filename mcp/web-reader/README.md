# @multica/web-reader

MCP server with a single tool — `web_reader` — that fetches a web page and
returns clean markdown. Pages that need JavaScript, or that answer an ordinary
HTTP client with an anti-bot interstitial, are re-fetched through CloakBrowser
(patched stealth Chromium) in a throwaway subprocess.

The package is `private: true` and is not published to npm. It runs from this
checkout, or from the Docker image built here.

## Install

```bash
pnpm install          # pnpm 10.5.2, Node 22+
pnpm run build        # tsc -> dist/
npx cloakbrowser install   # pre-fetch the stealth Chromium binary (optional; it self-downloads on first render)
```

## Run

Two transports; stdio is the default, `--http` switches to Streamable HTTP.

```bash
node dist/index.js            # stdio
node dist/index.js --http     # POST /message on $PORT (default 3000)
pnpm run dev                  # tsx watch, stdio
```

Docker (`docker-compose.yml`) builds on the Playwright base image and runs the
HTTP transport, host port `3075` → container `3000`:

```bash
docker compose up --build
```

### Claude Code / Cursor config

stdio, pointing at the built entry point:

```json
{
  "mcpServers": {
    "web-reader": {
      "command": "node",
      "args": ["/abs/path/to/mcp/web-reader/dist/index.js"]
    }
  }
}
```

HTTP, against a running container:

```json
{
  "mcpServers": {
    "web-reader": {
      "type": "http",
      "url": "http://localhost:3075/message"
    }
  }
}
```

## Usage

### Parameters

- **url** (required): URL to read. Must be HTTP or HTTPS.
- **max_chars** (optional): Maximum characters to return. Default: 20,000.
  Range: 1–1,000,000. Ignored in `passthrough` extractor mode, which always
  returns up to 1,000,000 chars so a downstream extractor gets the full payload.

```
web_reader("https://example.com")
web_reader("https://example.com", 50000)
```

## How it works

1. **Fetch** — plain `fetch()` with a desktop UA and `ru-RU` first in
   `Accept-Language` (RU sites serve foreign clients a different page).
2. **Guard content type** — PDF, images, and any non-`text/html` type are
   rejected outright.
3. **Decide whether to render** — the HTTP response is handed to the browser
   when visible text is under 200 chars, when the body matches a known block
   page, when it looks like a vendor challenge, when the status is
   render-worthy (401/403/429/5xx and friends), or when the request failed at
   the transport level.
4. **Render** — CloakBrowser loads the URL in a subprocess that never outlives
   the request, polling the live DOM instead of grabbing `page.content()` once
   navigation settles.
5. **Re-check** — a Chrome navigation error page or an anti-bot refusal is
   turned into an explicit error rather than extracted into tidy markdown.
6. **Extract** — defuddle by default, with a link-feed harvest and Readability
   as internal fallbacks.
7. **Sanitize + truncate** — data URIs and filler runs are stripped, junk-only
   output is rejected, then the text is cut to `max_chars`.

### Anti-bot handling

Qrator, Cloudflare and DDoS-Guard answer first with a small stub whose
JavaScript runs a check and then swaps in the real document — reading too early
returns a ~260-byte shell. The renderer polls and stops on the first of:

- **rich page** — enough visible text and HTML, or
- **stable page** — the DOM stopped changing (this is what keeps genuinely
  small pages fast), or
- **refusal** — a block page that persisted through the grace period, which is
  reported as an error instead of being returned as content.

Per-host rules cover the sites that need different launch options; `*.avito.ru`
and `*.wildberries.ru` ship as built-in defaults (`humanPreset:careful`,
`locale:ru-RU`). No fingerprint spoofing is injected via `addInitScript` —
CloakBrowser's C++ patches already cover it, and JS getters layered on top are
themselves a detection signal.

## Limitations

- **HTML only** — no PDF, images, JSON APIs, video or audio.
- **Timeout** — `WEB_RENDER_TIMEOUT_MS`, default 25s, must stay under the 60s
  MCP client timeout.
- **Read-only** — cannot fill forms, click through flows, or authenticate.
- **Public content** — no password-protected pages.

## Errors

All failures come back as `isError: true` with a descriptive message:

| Case | Message |
|------|---------|
| Bad URL | `Invalid URL format: not-a-url` / `... Only HTTP and HTTPS URLs are supported.` |
| Non-HTML | `Unsupported content type: PDF` / `Unsupported content type: image/png` |
| HTTP error (non render-worthy status) | `HTTP 404: Not Found` |
| Browser navigation error | `Could not load <url> — the browser hit a navigation error (<code>). ...` |
| Anti-bot refusal | `<url> refused the request — the response was an anti-bot block page, not the site. ...` |
| Nothing extractable | `No readable content at <url> — ...` |

## Configuration

| Env var | Default | Purpose |
|---------|---------|---------|
| `PORT` | `3000` | HTTP transport port (`--http` only) |
| `WEB_EXTRACTOR` | `defuddle` | `defuddle`, `readability`, `passthrough` |
| `WEB_RENDER_TIMEOUT_MS` | `25000` | Wall clock for one render |
| `WEB_PROXY_URL` | — | SOCKS5/HTTP proxy; unlocks RU geo-gated sites |
| `WEB_GEOIP` | `0` | Derive timezone/locale from the proxy IP |
| `WEB_USER_DATA_DIR` | — | Persistent browser profile (cookies survive requests) |
| `WEB_HUMANIZE` | `1` | Humanized mouse/keyboard/scroll |
| `WEB_HUMAN_PRESET` | `default` | `default` (fast) or `careful` (slower, more human-like) |
| `WEB_LOCALE` | auto | BCP 47 locale; empty derives it from the URL's TLD |
| `WEB_HOST_RULES` | — | Per-host overrides, `domain.tld=key:value,...;other.tld=...` |
| `WEB_BLOCK_NAV_HOSTS` | `sso.passport.yandex.ru` | Top-level navigations the renderer refuses; empty follows every redirect |
| `WEB_VIEWPORT_WIDTH` / `WEB_VIEWPORT_HEIGHT` | `1920` / `1080` | Browser viewport |
| `WEB_RELEASE_CHANNEL` | `stable` | `preview` gets newer fingerprint patches earlier |
| `WEB_DEBUG` | off | `1` logs every renderer poll to stderr |

See `.env.example` for the annotated version.

## Architecture

| File | Role |
|------|------|
| `index.ts` | MCP server, env schema, tool handler, stdio/HTTP transports |
| `lib/fetcher.ts` | HTTP fetch, charset decode, content-type guard, render decision |
| `lib/challenge.ts` | Anti-bot markers, page verdicts, render-worthy statuses |
| `lib/render-script.ts` | Wait policy and the in-page verdict function |
| `lib/subprocess.ts` | Spawn/timeout/cleanup plumbing; no browser outlives its request |
| `lib/playwright-subprocess.ts` | CloakBrowser renderer |
| `lib/host-rules.ts` | Per-host launch-option overrides |
| `lib/extractor-defuddle.ts` | Default extractor, with feed/Readability fallbacks |
| `lib/extractor-feed.ts` | Link-feed harvest for index pages |
| `lib/parser.ts` | Readability extractor |
| `lib/sanitize.ts` | Markdown cleanup and junk detection |
| `lib/pipeline.ts` | fetch → render → extract → sanitize |
| `lib/renderer-chain.ts` | Multi-engine fallback chain; unused since the chain collapsed to CloakBrowser alone |

## Development

```bash
pnpm run typecheck
pnpm run build
pnpm test          # vitest, 110 tests in 8 files (suite list lives in vitest.config.ts)
pnpm run smoke     # scripts/smoke.mjs against live sites
pnpm run inspect   # MCP inspector against dist/index.js
```

## License

MIT
