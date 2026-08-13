#!/usr/bin/env node
/**
 * End-to-end smoke test: starts the built MCP server over stdio and reads real
 * URLs through the `web_reader` tool. Run after touching the renderers —
 * unit tests cannot catch an anti-bot vendor changing its interstitial.
 *
 *   node scripts/smoke.mjs                       # default URL set
 *   node scripts/smoke.mjs https://example.com   # specific URLs
 *   WEB_DEBUG=1 node scripts/smoke.mjs           # per-poll renderer tracing
 */
import { Client } from '@modelcontextprotocol/sdk/client/index.js';
import { StdioClientTransport } from '@modelcontextprotocol/sdk/client/stdio.js';
import { fileURLToPath } from 'url';
import { dirname, join } from 'path';

const here = dirname(fileURLToPath(import.meta.url));
const serverPath = join(here, '..', 'dist', 'index.js');

const DEFAULT_URLS = [
  'https://example.com',              // static, tiny — must not wait out the budget
  'https://ya.ru',                    // plain HTTP fetch path
  'https://www.auchan.ru/',           // Qrator: nodriver is refused, CloakBrowser gets in
];

const urls = process.argv.slice(2).length ? process.argv.slice(2) : DEFAULT_URLS;

const transport = new StdioClientTransport({
  command: process.execPath,
  args: [serverPath],
  stderr: 'inherit',
  env: { ...process.env },
});
const client = new Client({ name: 'web-reader-smoke', version: '1.0.0' });
await client.connect(transport);

let failed = 0;
for (const url of urls) {
  const started = Date.now();
  let result;
  try {
    result = await client.callTool({ name: 'web_reader', arguments: { url, max_chars: 2000 } });
  } catch (err) {
    console.log(`FAIL  ${url} — ${err.message}`);
    failed++;
    continue;
  }
  const text = result.content.map(c => c.text).join('');
  const secs = ((Date.now() - started) / 1000).toFixed(1);
  if (result.isError || !text.trim()) {
    console.log(`FAIL  ${url}  ${secs}s — ${text.slice(0, 200)}`);
    failed++;
  } else {
    console.log(`ok    ${url}  ${secs}s  ${text.length} chars`);
  }
}

await client.close();
console.log(failed ? `\n${failed}/${urls.length} failed` : `\nall ${urls.length} ok`);
process.exit(failed ? 1 : 0);
