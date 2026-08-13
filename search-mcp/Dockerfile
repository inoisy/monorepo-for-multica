# Multi-stage build for web-reader MCP server (parses protected sites)
FROM mcr.microsoft.com/playwright:v1.60.0-noble AS builder
WORKDIR /app

RUN npm install -g pnpm@10.5.2

COPY pnpm-lock.yaml package.json tsconfig.json ./
COPY src ./src
COPY scripts ./scripts
COPY test ./test
COPY vitest.config.ts ./

RUN pnpm install --frozen-lockfile
RUN pnpm run build

FROM mcr.microsoft.com/playwright:v1.60.0-noble
WORKDIR /app

RUN npm install -g pnpm@10.5.2

COPY pnpm-lock.yaml package.json ./
COPY src ./src

RUN pnpm install --frozen-lockfile --prod

COPY --from=builder /app/dist ./dist

# Pre-download CloakBrowser stealth binary so container needs no network on first run
RUN npx cloakbrowser install

CMD ["node", "dist/index.js", "--http"]
