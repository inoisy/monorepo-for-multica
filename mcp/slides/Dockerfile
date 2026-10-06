# slides MCP server: Playwright base image brings Chromium for render checks,
# screenshots and PDF export. Playwright's npm version must match the image tag.
FROM mcr.microsoft.com/playwright:v1.60.0-noble AS builder
WORKDIR /app
RUN npm install -g pnpm@10.5.2
COPY pnpm-lock.yaml package.json tsconfig.json ./
RUN pnpm install --frozen-lockfile
COPY src ./src
RUN pnpm run build

FROM mcr.microsoft.com/playwright:v1.60.0-noble
WORKDIR /app
RUN npm install -g pnpm@10.5.2
COPY pnpm-lock.yaml package.json ./
RUN pnpm install --frozen-lockfile --prod
COPY --from=builder /app/dist ./dist
# Theme fonts are committed (fonts/, OFL): decks and PDFs render with the real
# typefaces without reaching Google Fonts at runtime.
COPY fonts ./fonts
ENV SLIDES_DIR=/data/decks \
    SLIDES_BUNDLE_DIR=/data/bundles
VOLUME /data
CMD ["node", "dist/index.js", "--http"]
