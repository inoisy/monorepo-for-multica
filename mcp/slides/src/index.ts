#!/usr/bin/env node
import { McpServer } from '@modelcontextprotocol/sdk/server/mcp.js';
import { StdioServerTransport } from '@modelcontextprotocol/sdk/server/stdio.js';
import { StreamableHTTPServerTransport } from '@modelcontextprotocol/sdk/server/streamableHttp.js';
import express from 'express';
import path from 'node:path';
import { DeckStore } from './store.js';
import { registerTools } from './tools.js';
import { closeBrowser } from './browser.js';
import { esc } from './text.js';
import { findFonts } from './fonts.js';

const PORT = Number(process.env.PORT ?? 3000);
const dataDir = path.resolve(process.env.SLIDES_DIR ?? './data/decks');
const store = new DeckStore(dataDir, await findFonts());
// Bundles for publishing. SLIDES_BUNDLE_HOST_DIR is the same directory as
// agents on the host see it, when this server runs in a container.
const bundleDir = path.resolve(process.env.SLIDES_BUNDLE_DIR ?? path.join(dataDir, '..', 'bundles'));
const bundleHostDir = process.env.SLIDES_BUNDLE_HOST_DIR ?? bundleDir;
const isHttp = process.argv.includes('--http');
// Links handed back to agents. In HTTP mode default to localhost; set
// SLIDES_PUBLIC_URL to the address people actually open (http://host:3076).
const publicUrl = (process.env.SLIDES_PUBLIC_URL ?? (isHttp ? `http://localhost:${PORT}` : '')).replace(/\/+$/, '');

// stdout belongs to JSON-RPC in stdio mode.
const log = (...a: unknown[]) => console.error('[slides]', ...a);

function createServer(): McpServer {
  const s = new McpServer({ name: 'slides', version: '0.1.0' });
  registerTools(s, { store, publicUrl, bundleDir, bundleHostDir });
  return s;
}

async function main() {
  await store.init();
  log(`fonts: ${store.hasLocalFonts ? 'bundled' : 'Google Fonts (no bundled fonts found)'}, bundles: ${bundleHostDir}`);
  if (!isHttp) {
    await createServer().connect(new StdioServerTransport());
    log(`stdio, decks in ${store.root}`);
    return;
  }
  const app = express();
  app.use(express.json({ limit: '25mb' }));

  // Stateless MCP: a fresh server per request, so concurrent agents never share a transport.
  app.post('/message', async (req, res) => {
    const s = createServer();
    const transport = new StreamableHTTPServerTransport({ sessionIdGenerator: undefined });
    res.on('close', () => { transport.close(); s.close(); });
    await s.connect(transport);
    await transport.handleRequest(req, res, req.body);
  });

  app.get('/', async (_req, res) => {
    const decks = await store.list();
    res.type('html').send(`<!doctype html><meta charset="utf-8"><title>Slides</title>
<style>body{font:16px/1.5 system-ui;background:#0d0e11;color:#eee;max-width:900px;margin:48px auto;padding:0 16px}
a{color:#c8f031;text-decoration:none}li{padding:10px 0;border-bottom:1px solid #222;list-style:none;display:flex;justify-content:space-between}
span{color:#888}</style><h1>Decks</h1><ul>${decks.map(d =>
      `<li><a href="/d/${d.id}/">${esc(d.title)}</a><span>${d.slides} slides · ${d.updated.slice(0, 16).replace('T', ' ')}</span></li>`).join('') || '<li>No decks yet.</li>'}</ul>`);
  });

  // Decks are static files: index.html (re-rendered on every save), assets/, exports/.
  app.use('/d', express.static(store.root, { dotfiles: 'ignore', index: 'index.html', fallthrough: true }));
  app.get('/healthz', (_req, res) => { res.send('ok'); });

  app.listen(PORT, () => log(`http on :${PORT}, MCP at POST /message, previews at ${publicUrl}/d/<id>/, decks in ${store.root}`));
}

for (const sig of ['SIGINT', 'SIGTERM'] as const) {
  process.on(sig, () => { closeBrowser().finally(() => process.exit(0)); });
}

main().catch(err => { log('fatal', err); process.exit(1); });
