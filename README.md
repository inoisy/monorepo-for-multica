# monorepo-for-multica

External project storage used by Multica.

## Purpose

Multica runs inside a workspace sandbox and cannot reliably push brand-new
projects/services out to arbitrary hosts. When an issue requires Multica to
build a new project or service, Multica pushes that work here, into this
monorepo. The monorepo is therefore the canonical "outbound" storage for
Multica-authored code.

## Layout

Each top-level directory holds one self-contained Multica project:

```
<project-name>/
  src/
  tests/
  README.md
```

Projects are independent — there is no shared build graph, lockfile, or
tooling version pinned at the monorepo root. Each project ships its own.

## Current projects

- `sphere-integration/` — MCP server + CLI for Bitrix24 Sphere task
  management (Node.js, TypeScript). See `sphere-integration/README.md`.

## Conventions

- One directory per project. No nesting of projects inside other projects.
- Keep project-level `README.md` self-explanatory; the monorepo README only
  documents cross-cutting storage conventions.
- Use the project's own commit/PR workflow — branches here are not gated by
  Multica's normal review path.
