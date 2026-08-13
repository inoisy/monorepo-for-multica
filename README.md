# monorepo-for-multica

External project storage used by Multica.

## Purpose

Multica runs inside a workspace sandbox and cannot reliably push brand-new
projects/services out to arbitrary hosts. When an issue requires Multica to
build a new project or service, Multica pushes that work here, into this
monorepo. The monorepo is therefore the canonical "outbound" storage for
Multica-authored code.

## Layout

Top-level directories are categories. Each category holds self-contained
projects, one directory per project:

```
<category>/
  <project-name>/
    src/
    tests/
    README.md
```

Everything here is MCP servers so far, so `mcp/` is the only category. New
kinds of work get their own top-level directory (`services/`, `libs/`, …)
rather than landing next to the MCP servers.

Projects are independent — there is no shared build graph, lockfile, or
tooling version pinned at the monorepo root. Each project ships its own.

## Current projects

### `mcp/` — MCP servers

- `mcp/web-reader/` — reads a web page and returns clean markdown, falling
  back to stealth Chromium (CloakBrowser) for JS-rendered and
  anti-bot-protected sites. Node.js, TypeScript, pnpm.
  See `mcp/web-reader/README.md`.
- `mcp/sphere-tasks/` — MCP server + CLI for Bitrix24 Sphere
  (`sphere.loodsen.ru`) task management, sprint sync, and webhooks.
  Node.js, TypeScript, npm. See `mcp/sphere-tasks/README.md`.

## Conventions

- Name a directory after what it does, not after the repo it came from.
- Package identity follows the directory: `@multica/<project>` in
  `package.json`, plain `<project>` as the MCP server name clients see.
- One directory per project, inside a category. No nesting of projects inside
  other projects.
- Keep project-level `README.md` self-explanatory; the monorepo README only
  documents cross-cutting storage conventions.
- Use the project's own commit/PR workflow — branches here are not gated by
  Multica's normal review path.
