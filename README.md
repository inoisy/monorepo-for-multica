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

Categories so far are `mcp/` and `skills/`. New kinds of work get their own
top-level directory (`services/`, `libs/`, …) rather than landing next to an
existing category.

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

### `skills/` — agent skills

- `skills/agents-init/` — builds a project's `AGENTS.md` from repository recon
  and audits an existing one. Markdown only, no build step; installed by
  symlinking into `~/.claude/skills/` or copying into a project's
  `.claude/skills/`. See `skills/agents-init/README.md`.

## Conventions

- Name a directory after what it does, not after the repo it came from.
- A project without a build step (a skill, a prompt pack) still gets its own
  directory and `README.md`, same as a service.
- Package identity follows the directory: unscoped `<project>` in
  `package.json`, and the same `<project>` as the MCP server name clients see.
- One directory per project, inside a category. No nesting of projects inside
  other projects.
- Keep project-level `README.md` self-explanatory; the monorepo README only
  documents cross-cutting storage conventions.
- Use the project's own commit/PR workflow — branches here are not gated by
  Multica's normal review path.
