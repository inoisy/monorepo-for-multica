# @search-mcp/web-reader

MCP server tool that reads web pages and extracts clean markdown content. Handles JavaScript-rendered pages (React, Vue, Angular) via Playwright fallback.

## Installation

### Using npx (recommended)

```bash
npx -y @search-mcp/web-reader
```

### Claude Desktop Configuration

Add to your Claude Desktop MCP config:

```json
{
  "mcpServers": {
    "web-reader": {
      "command": "npx",
      "args": ["-y", "@search-mcp/web-reader"]
    }
  }
}
```

### Cursor Configuration

Add to your Cursor MCP settings:

```json
{
  "mcpServers": {
    "web-reader": {
      "command": "npx",
      "args": ["-y", "@search-mcp/web-reader"]
    }
  }
}
```

## Usage

The `web_reader` tool fetches any HTML page and returns clean markdown content.

### Parameters

- **url** (required): URL to read. Must be HTTP or HTTPS.
- **max_chars** (optional): Maximum characters to return. Default: 20,000. Range: 1-100,000.

### Example

```
web_reader("https://example.com")
```

With custom character limit:

```
web_reader("https://example.com", 50000)
```

## Features

- **Fetch any HTML page**: Works with static and dynamic websites
- **Content cleaning**: Strips navigation, footers, ads, and scripts
- **Markdown conversion**: Converts HTML to clean markdown format
- **JavaScript rendering**: Auto-detects JS-rendered pages (React, Vue, Angular)
- **Playwright fallback**: Spawns headless Chromium for SPA sites
- **Content-type guards**: Rejects PDF, images, and non-HTML content
- **Configurable output**: Truncates to your specified character limit
- **Error clarity**: Returns descriptive error messages for all failure modes

## How It Works

1. **Fetch**: Makes HTTP request to URL
2. **Validate**: Checks Content-Type header (rejects PDF, images, etc.)
3. **Detect JS-rendered**: Checks HTML length and framework markers
4. **Render if needed**: Hands the URL to the renderer chain (`nodriver`, then `cloakbrowser`)
5. **Wait for the real page**: Polls the live DOM until it is rich or has stopped changing, so anti-bot interstitials are never mistaken for content
6. **Parse**: Extracts the main content (defuddle by default)
7. **Convert**: Transforms HTML to markdown
8. **Truncate**: Limits output to max_chars

### Renderer chain

Engines are tried in order until one returns a page that is not an interstitial:

- an engine that errors, gets stuck on a challenge, or hits a refusal page hands over to the next one
- if no engine gets a clean page, the largest page seen is returned rather than nothing
- only a total failure raises, and the error lists what every engine ran into

### Anti-bot handling

The renderers do not grab `page.content()` as soon as navigation settles. Qrator,
Cloudflare and DDoS-Guard all answer first with a small stub whose JavaScript
runs a check and then swaps in the real document — reading too early returns a
260-byte shell. Instead both renderers poll and stop on the first of:

- **rich page** — enough visible text and HTML, or
- **stable page** — the DOM stopped changing (this is what keeps genuinely small pages fast), or
- **refusal** — a block page that persisted through the grace period, which fails over to the next engine.

## Limitations

- **HTML only**: Supports HTML pages only. Does NOT support:
  - PDF documents
  - Images (PNG, JPG, GIF, etc.)
  - JSON APIs
  - Video or audio files
- **Timeout**: `WEB_RENDER_TIMEOUT_MS` per engine (default 25s). Two engines stay under the 60s MCP client timeout.
- **Read-only**: Cannot fill forms, click buttons, or authenticate
- **Public content**: Cannot access password-protected pages

## Examples

### Static HTML Page

```
web_reader("https://example.com")
```

Returns markdown content from static HTML.

### JavaScript-Rendered Page (React, Vue, Angular)

```
web_reader("https://react.dev")
```

Auto-detects JS rendering, launches Playwright, returns rendered markdown.

### With Custom Character Limit

```
web_reader("https://blog.example.com/long-post", 50000)
```

Returns up to 50,000 characters instead of default 20,000.

## Error Handling

All errors return `isError: true` with descriptive messages:

### Unsupported Content Type

```
web_reader("https://example.com/doc.pdf")
```

Returns: `Unsupported content type: application/pdf. web-reader supports HTML pages only.`

```
web_reader("https://example.com/image.png")
```

Returns: `Unsupported content type: image/png. web-reader supports HTML pages only.`

### HTTP Errors

```
web_reader("https://example.com/notfound")
```

Returns: `HTTP 404: Not Found`

```
web_reader("https://example.com/internal-error")
```

Returns: `HTTP 500: Internal Server Error`

### Invalid URL

```
web_reader("not-a-url")
```

Returns: `Invalid URL: not-a-url. Must be HTTP or HTTPS.`

### Timeout (JavaScript-rendered pages)

```
web_reader("https://slow-spa.example.com")
```

Returns the reason from every engine that was tried:

```
Failed to render https://slow-spa.example.com. Renderers tried:
  - nodriver: timed out after 25000ms
  - cloakbrowser: https://slow-spa.example.com refused the request (anti-bot block page)
```

### Network Errors

```
web_reader("https://nonexistent-domain-12345.com")
```

Returns: `Failed to fetch https://nonexistent-domain-12345.com: getaddrinfo ENOTFOUND`

## Architecture

- **fetcher.ts**: HTTP fetch with content-type validation, block-page and render detection
- **challenge.ts**: anti-bot marker lists, page verdicts, and the HTTP statuses worth re-trying in a browser
- **render-script.ts**: the wait policy plus the in-page verdict function, generated once for both engines
- **subprocess.ts**: spawn/timeout/cleanup plumbing shared by the renderers — no browser outlives its request
- **playwright-subprocess.ts**: CloakBrowser (patched Chromium) renderer
- **nodriver-subprocess.ts**: Python + nodriver renderer, raw CDP
- **python.ts**: finds an interpreter that can `import nodriver` (venv first, system Python last)
- **renderer-chain.ts**: the fallback chain
- **pipeline.ts**: fetch -> render -> extract
- **index.ts**: MCP server and tool handler

## Renderers

| Renderer | Engine | Strengths |
|----------|--------|-----------|
| `nodriver` (default) | System Chrome via raw CDP | Python subprocess driving Chrome with no Playwright shim, so it does not leak `Runtime.enable` / WebSocket serialization patterns. Best against DataDome, DDoS-Guard, Cloudflare Turnstile. |
| `cloakbrowser` (default fallback) | Chromium 145 + C++ fingerprint patches | Best against Qrator (auchan.ru, many RU retailers). Binary auto-downloads on first launch; pre-fetch it with `npx cloakbrowser install`. |

Order is set by `WEB_RENDERER` (primary) and `WEB_RENDERER_FALLBACK` (comma
separated, `none` to disable). No fingerprint spoofing is injected into
CloakBrowser via `addInitScript` — its C++ patches already cover this, and JS
getters layered on top are themselves a detection signal (Qrator refuses them).

### Setting up nodriver

nodriver needs a Python interpreter with the `nodriver` package and a system
Chrome. The interpreter is auto-detected in this order: `NODRIVER_PYTHON`,
`<repo>/.venv-nodriver/bin/python`, `.venv-nodriver` next to the package or cwd,
then `python3.13` … `python3`.

```bash
python3 -m venv .venv-nodriver
.venv-nodriver/bin/pip install nodriver
```

The server logs which interpreter it picked at startup, and warns loudly if none
of them can `import nodriver` — the chain then runs on the fallback engine alone.

## Configuration

| Env var | Default | Purpose |
|---------|---------|---------|
| `WEB_RENDERER` | `nodriver` | Primary render engine |
| `WEB_RENDERER_FALLBACK` | `cloakbrowser` | Comma-separated engines tried after the primary |
| `WEB_RENDER_TIMEOUT_MS` | `25000` | Wall clock per engine |
| `WEB_NODRIVER_HEADLESS` | `1` | Set `0` to run nodriver headful (some anti-bot vendors flag headless) |
| `NODRIVER_PYTHON` | auto-detected | Explicit Python interpreter for nodriver |
| `WEB_EXTRACTOR` | `defuddle` | `defuddle`, `readability`, `passthrough` |
| `WEB_DEBUG` | off | `1` to log every poll of every renderer to stderr |


## Development

```bash
# Install dependencies
pnpm install

# Build
npm run build

# Type check
npm run typecheck

# Development mode
npm run dev
```

## License

MIT
