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

Categories so far are `mcp/`, `services/` and `skills/` (agent skills in the
`SKILL.md` format, importable into a Multica workspace). New kinds of work get
their own top-level directory (`libs/`, …) rather than landing next to an
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
- `mcp/slides/` — self-hosted Claude Slides analog: agents build decks as JSON
  over curated themes and layouts (incl. bento grids), with browser render
  checks, screenshot previews, and PDF/PPTX/PNG export. Node.js, TypeScript,
  pnpm. See `mcp/slides/README.md`.

### `skills/` — agent skills

Each skill is a directory with a `SKILL.md` (plus optional `references/`),
imported into Multica from its GitHub path.

- `skills/slide-design/` — how to make decks that look designed with the
  `slides` MCP server: storyline, layout choice, bento recipes, copy rules,
  and the preview-and-fix loop.

### `services/` — services of the agents' server

- `services/stand/` — branch stands and static artifacts on
  `*.stand.yakutov.com`: the `stand` CLI, its MCP server, the router and the
  static server. Bash, Python, Node.js, no build step. Deployed by hand by the
  server owner. See `services/stand/README.md`.

## Conventions

- Name a directory after what it does, not after the repo it came from.
- Package identity follows the directory: unscoped `<project>` in
  `package.json`, and the same `<project>` as the MCP server name clients see.
- One directory per project, inside a category. No nesting of projects inside
  other projects.
- Keep project-level `README.md` self-explanatory; the monorepo README only
  documents cross-cutting storage conventions.
- Use the project's own commit/PR workflow — branches here are not gated by
  Multica's normal review path.
