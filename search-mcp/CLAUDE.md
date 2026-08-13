<!-- GSD:project-start source:PROJECT.md -->
## Project

**search-mcp**

MCP-сервер на TypeScript с инструментами для AI-агентов: веб-поиск (Tavily, Yandex). Разработан для внутренней команды — позволяет агентам (Claude Code, Cursor и др.) отвечать на сложные вопросы после исследования.

**Core Value:** Агент должен уметь самостоятельно исследовать любую тему — найти релевантную информацию через веб-поиск — без ручного вмешательства.

> **Архив:** Пакеты `vision`, `github`, `web-reader`, `trafilatura-service` перенесены в `.archive/` (вне git).

### Constraints

- **Stack**: TypeScript + Node.js — команда уже использует TS
- **Транспорт**: и stdio, и HTTP/SSE — разные сценарии использования
- **Провайдеры поиска**: Tavily primary, Yandex fallback — оба ключа есть
<!-- GSD:project-end -->

<!-- GSD:stack-start source:research/STACK.md -->
## Technology Stack

## Recommended Stack
### Core Framework
| Technology | Version | Purpose | Why |
|------------|---------|---------|-----|
| `@modelcontextprotocol/sdk` | `1.29.0` | MCP server + both transports | Stable `latest` tag. The v2 split packages (`@modelcontextprotocol/server`, `@modelcontextprotocol/node`) are `2.0.0-alpha.2` — alpha, skip them. v1 SDK provides `McpServer`, `StdioServerTransport`, and `StreamableHTTPServerTransport` all from one package. |
| TypeScript | `5.8.x` (via `typescript@6.0.3`) | Language | Wait — npm shows `typescript` latest as `6.0.3`, but TS 6 is not released as stable; the `latest` tag is still `5.x` for stable. Use `~5.8.3` (npm `5.x` latest). |
| Node.js | `22.x LTS` | Runtime | Current LTS. MCP SDK requires Node 18+; 22 is the 2025 active LTS line. |
| tsx | `4.22.3` | Dev runner (ts-node replacement) | Runs `.ts` files directly without a compile step. Faster cold start than `ts-node`. Used for development; production runs compiled JS via `node dist/`. |
| Zod | `4.4.3` | Input schema validation in tools | MCP SDK peer-depends `zod: "^3.25 || ^4.0"`. Zod v4 is `latest` as of 2026-05-28. Use `import * as z from 'zod'` — v4 is the standard import. MCP's `registerTool` accepts Zod schemas directly as `inputSchema`. |
### Transport Layer
| Technology | Version | Transport | Why |
|------------|---------|-----------|-----|
| `StdioServerTransport` | (in SDK) | stdio | Zero-config for Claude Code / Cursor: agent spawns the process, communicates over stdin/stdout. No network, no auth needed. |
| `StreamableHTTPServerTransport` | (in SDK) | HTTP/SSE | The 2025 MCP standard for remote servers. Replaces the deprecated `SSEServerTransport`. Supports both streaming (SSE) and request/response over a single POST endpoint. Clients fall back to legacy SSE automatically. |
| Express | `5.2.1` | HTTP server for StreamableHTTP | MCP SDK ships `@modelcontextprotocol/express` middleware, and Express 5 is in its dependencies. Use `createMcpExpressApp()` from `@modelcontextprotocol/express` (bundled with the SDK) or plain `NodeStreamableHTTPServerTransport` with Node's `http.createServer`. Express is included; no extra install needed for basic use. |
### Web Search (`web_search` tool)
| Technology | Version | Purpose | Why |
|------------|---------|---------|-----|
| `@tavily/core` | latest | Tavily Search API wrapper | Official Tavily SDK — provides typed `TavilyClient`, handles auth, request/response, and all search params. Use instead of plain `fetch`. |
| Native `fetch` (Node 22) | built-in | HTTP calls to Yandex API | Only for Yandex (no official SDK). |
### Supporting Libraries
| Library | Version | Purpose | When to Use |
|---------|---------|---------|-------------|
| `dotenv` | `17.4.2` | Load `.env` for local dev | `import 'dotenv/config'` at entry point. API keys from environment. Not needed in production if env vars are injected externally. |
| `pino` | `10.3.1` | Structured JSON logging | Use `console.error` for MCP stdio (stdout is reserved for JSON-RPC), `pino` for HTTP mode. Lightweight, fast. |
| `@types/node` | `22.x` | TypeScript types for Node 22 | Required for `process`, `fetch`, `crypto`, etc. Use `@types/node@22` to match Node version. |
## What NOT to Use
| Rejected | Why Not |
|----------|---------|
| `@modelcontextprotocol/server` (v2 alpha) | `2.0.0-alpha.2` — not production-ready. Use stable `@modelcontextprotocol/sdk@1.29.0` instead. |
| `@modelcontextprotocol/node` (v2 alpha) | Same reason — alpha package. |
| SSEServerTransport (legacy) | Deprecated in MCP spec. `StreamableHTTPServerTransport` is the 2025 standard. Claude Code and Cursor already support it. |
| WebSocketClientTransport | Removed from SDK — not a spec-defined MCP transport. |
| `puppeteer` | Playwright is better maintained, broader API, same use case. |
| `axios` | Native `fetch` in Node 22 is sufficient. No need for extra dependency. |
| Plain `fetch` for Tavily | Use `@tavily/core` SDK instead — it provides typed client, handles auth and all search params. |
| Zod v3 (`zod@3.x`) | Zod v4 is `latest`, supported by MCP SDK peer dep `"^3.25 || ^4.0"`. Use v4. |
| `ts-node` | `tsx` is faster, more actively maintained, handles ESM/CJS correctly. |
| `@modelcontextprotocol/sdk` v2 split packages before stable release | Monitor for v2 stable release (currently alpha); migrate when it ships. |
## Installation
# Core MCP runtime
# Tool-specific
# Utilities
# Dev
## tsconfig essentials
## Sources
- MCP SDK v1 (stable) docs: https://ts.sdk.modelcontextprotocol.io/v2/ (Context7 `/websites/ts_sdk_modelcontextprotocol_io_v2`, HIGH confidence)
- MCP SDK GitHub: https://github.com/modelcontextprotocol/typescript-sdk (Context7 `/modelcontextprotocol/typescript-sdk`, HIGH confidence)
- MCP SDK v2 migration guide: https://github.com/modelcontextprotocol/typescript-sdk/blob/main/docs/migration.md (HIGH confidence)
- Cheerio docs: https://cheerio.js.org/ (Context7 `/cheeriojs/cheerio`, HIGH confidence)
- Playwright docs: https://playwright.dev/ (Context7 `/microsoft/playwright`, HIGH confidence)
- Octokit REST: https://github.com/octokit/rest.js (Context7 `/octokit/rest.js`, HIGH confidence)
- OpenAI Node SDK: https://github.com/openai/openai-node (Context7 `/openai/openai-node`, HIGH confidence)
- Zod v4: https://zod.dev/v4 (Context7 `/websites/zod_dev_v4`, HIGH confidence)
- All versions verified against npm registry on 2026-05-28
<!-- GSD:stack-end -->

<!-- GSD:conventions-start source:CONVENTIONS.md -->
## Conventions

Conventions not yet established. Will populate as patterns emerge during development.
<!-- GSD:conventions-end -->

<!-- GSD:architecture-start source:ARCHITECTURE.md -->
## Architecture

Architecture not yet mapped. Follow existing patterns found in the codebase.
<!-- GSD:architecture-end -->

<!-- GSD:skills-start source:skills/ -->
## Project Skills

No project skills found. Add skills to any of: `.claude/skills/`, `.agents/skills/`, `.cursor/skills/`, `.github/skills/`, or `.codex/skills/` with a `SKILL.md` index file.
<!-- GSD:skills-end -->

<!-- GSD:workflow-start source:GSD defaults -->
## GSD Workflow Enforcement

Before using Edit, Write, or other file-changing tools, start work through a GSD command so planning artifacts and execution context stay in sync.

Use these entry points:
- `/gsd-quick` for small fixes, doc updates, and ad-hoc tasks
- `/gsd-debug` for investigation and bug fixing
- `/gsd-execute-phase` for planned phase work

Do not make direct repo edits outside a GSD workflow unless the user explicitly asks to bypass it.
<!-- GSD:workflow-end -->



<!-- GSD:profile-start -->
## Developer Profile

> Profile not yet configured. Run `/gsd-profile-user` to generate your developer profile.
> This section is managed by `generate-claude-profile` -- do not edit manually.
<!-- GSD:profile-end -->
