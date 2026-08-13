#!/usr/bin/env node
import 'dotenv/config';
import { McpServer } from '@modelcontextprotocol/sdk/server/mcp.js';
import { StdioServerTransport } from '@modelcontextprotocol/sdk/server/stdio.js';
import { StreamableHTTPServerTransport } from '@modelcontextprotocol/sdk/server/streamableHttp.js';
import * as z from 'zod';
import { toError, log, truncate, loadConfig } from './lib/utils.js';
import express from 'express';
import { NativeFetcher } from './lib/fetcher.js';
import { CloakBrowserRenderer, DEFAULT_BLOCK_NAV_HOSTS } from './lib/playwright-subprocess.js';
import { HostRuleSet, DEFAULT_HOST_RULES } from './lib/host-rules.js';
import { killAllSubprocesses, cleanTempDir } from './lib/subprocess.js';
import type { IRenderer } from './lib/types.js';
import { ReadabilityExtractor } from './lib/parser.js';
import { DefuddleExtractor } from './lib/extractor-defuddle.js';
import { WebReaderPipeline } from './lib/pipeline.js';
import type { IExtractor } from './lib/types.js';

const config = loadConfig(z.object({
  PORT: z.coerce.number().optional().default(3000),
  // defuddle is the working path: it picks the article, and falls back to a
  // headline harvest or Readability on pages that are feeds, not articles.
  // readability forces the older single-strategy extractor; passthrough returns
  // raw HTML for a downstream extractor to chew on.
  WEB_EXTRACTOR: z.enum(['readability', 'defuddle', 'passthrough']).optional().default('defuddle'),
  // Per-engine wall clock. Must stay under the 60s MCP client timeout.
  WEB_RENDER_TIMEOUT_MS: z.coerce.number().min(5_000).max(300_000).optional().default(25_000),
  // CloakBrowser launch options. All optional; defaults match cloakbrowser's
  // own. Setting WEB_PROXY_URL unlocks RU geo-gated sites without buying a
  // residential plan — pair with WEB_GEOIP=1 so the IP, timezone, and locale
  // line up for the target URL's region.
  WEB_PROXY_URL: z.string().optional(),
  WEB_GEOIP: z.enum(['0', '1', 'true', 'false']).optional().default('0'),
  WEB_USER_DATA_DIR: z.string().optional(),
  WEB_HUMANIZE: z.enum(['0', '1', 'true', 'false']).optional().default('1'),
  WEB_HUMAN_PRESET: z.enum(['default', 'careful']).optional().default('default'),
  WEB_LOCALE: z.string().optional().default(''),
  // Per-host overrides. Format: "domain.tld=key:value,key:value;other.tld=..."
  // See src/lib/host-rules.ts for the full grammar.
  WEB_HOST_RULES: z.string().optional().default(''),
  // Comma-separated hosts whose top-level navigations the renderer refuses.
  // Empty string disables the built-in list (see DEFAULT_BLOCK_NAV_HOSTS).
  WEB_BLOCK_NAV_HOSTS: z.string().optional(),
  WEB_VIEWPORT_WIDTH: z.coerce.number().min(320).max(7680).optional().default(1920),
  WEB_VIEWPORT_HEIGHT: z.coerce.number().min(240).max(4320).optional().default(1080),
  WEB_RELEASE_CHANNEL: z.enum(['stable', 'preview']).optional().default('stable'),
}));

const extractor: IExtractor =
  config.WEB_EXTRACTOR === 'defuddle'    ? new DefuddleExtractor() :
  config.WEB_EXTRACTOR === 'passthrough' ? { extract: async (html: string) => html } as IExtractor :
                                           new ReadabilityExtractor();

// User rules first: HostRuleSet returns the first match, so an explicit entry
// overrides the built-in one for the same host.
const hostRules = new HostRuleSet(
  [config.WEB_HOST_RULES, DEFAULT_HOST_RULES].filter(Boolean).join(';'),
);

const blockNavHosts = config.WEB_BLOCK_NAV_HOSTS === undefined
  ? DEFAULT_BLOCK_NAV_HOSTS
  : config.WEB_BLOCK_NAV_HOSTS.split(',').map(h => h.trim()).filter(Boolean);

const renderer: IRenderer = new CloakBrowserRenderer(config.WEB_RENDER_TIMEOUT_MS, {
  proxy: config.WEB_PROXY_URL,
  geoip: config.WEB_GEOIP === '1' || config.WEB_GEOIP === 'true',
  userDataDir: config.WEB_USER_DATA_DIR,
  humanize: config.WEB_HUMANIZE === '1' || config.WEB_HUMANIZE === 'true',
  humanPreset: config.WEB_HUMAN_PRESET,
  locale: config.WEB_LOCALE || undefined,
  viewport: { width: config.WEB_VIEWPORT_WIDTH, height: config.WEB_VIEWPORT_HEIGHT },
  releaseChannel: config.WEB_RELEASE_CHANNEL,
  blockNavHosts,
}, hostRules);

log(`web-reader renderer: cloakbrowser (${config.WEB_RENDER_TIMEOUT_MS}ms), extractor: ${config.WEB_EXTRACTOR}`
  + (config.WEB_PROXY_URL ? `, proxy: ${redactProxy(config.WEB_PROXY_URL)}` : '')
  + (config.WEB_USER_DATA_DIR ? `, profile: ${config.WEB_USER_DATA_DIR}` : '')
  + `, host-rules: ${hostRules.describe()}`
  + (blockNavHosts.length ? `, blocked-nav: ${blockNavHosts.join(',')}` : ''));

/** Strip user:pass from a proxy URL so credentials don't leak into logs. */
function redactProxy(url: string): string {
  return url.replace(/\/\/[^@]+@/, '//***@');
}

cleanTempDir();

const pipeline = new WebReaderPipeline(
  new NativeFetcher(),
  renderer,
  extractor,
);

const server = new McpServer({ name: 'web-reader', version: '0.1.0' });

server.registerTool(
  'web_reader',
  {
    title: 'Web Reader',
    description: 'Read web pages and extract clean markdown content. Handles JavaScript-rendered pages via stealth Chromium.',
    inputSchema: z.object({
      url: z.string().url().describe('URL to read (must be HTTP or HTTPS)'),
      max_chars: z.number().min(1).max(1_000_000).optional()
        .describe('Maximum characters to return. Default: 20_000. Set high in passthrough mode, where a downstream extractor needs the full payload.'),
    }),
    annotations: { readOnlyHint: true, idempotentHint: true },
  },
  async ({ url, max_chars }) => {
    try {
      const markdown = await pipeline.read(url);
      // passthrough mode returns raw HTML for a downstream extractor; never
      // truncate it mid-tag, which would break the markup it has to parse.
      const limit = config.WEB_EXTRACTOR === 'passthrough' ? 1_000_000 : max_chars ?? 20_000;
      const truncated = truncate(markdown, limit);

      return {
        content: [{ type: 'text' as const, text: truncated }],
        isError: false,
      };
    } catch (err) {
      const message = err instanceof Error ? err.message : 'Unknown error';
      log(`web_reader error: ${message}`);
      return toError(message);
    }
  }
);

// Stateless HTTP transport: each request gets a fresh McpServer so concurrent
// callers don't share a single transport (which crashes after first request).
function createStatelessServer(): McpServer {
  const s = new McpServer({ name: 'web-reader', version: '0.1.0' });
  s.registerTool(
    'web_reader',
    {
      title: 'Web Reader',
      description: 'Read web pages and extract clean markdown content. Handles JavaScript-rendered pages via stealth Chromium.',
      inputSchema: z.object({
        url: z.string().url().describe('URL to read (must be HTTP or HTTPS)'),
        max_chars: z.number().min(1).max(1_000_000).optional()
          .describe('Maximum characters to return. Default: 20_000. Set high in passthrough mode, where a downstream extractor needs the full payload.'),
      }),
      annotations: { readOnlyHint: true, idempotentHint: true },
    },
    async ({ url, max_chars }) => {
      try {
        const markdown = await pipeline.read(url);
        const limit = config.WEB_EXTRACTOR === 'passthrough' ? 1_000_000 : max_chars ?? 20_000;
        const truncated = truncate(markdown, limit);
        return {
          content: [{ type: 'text' as const, text: truncated }],
          isError: false,
        };
      } catch (err) {
        const message = err instanceof Error ? err.message : 'Unknown error';
        log(`web_reader error: ${message}`);
        return toError(message);
      }
    }
  );
  return s;
}

async function main() {
  const isHttp = process.argv.includes('--http');
  if (isHttp) {
    log(`web-reader MCP server starting (HTTP on port ${config.PORT})`);
    const app = express();
    app.use(express.json());
    app.post('/message', async (req, res) => {
      const s = createStatelessServer();
      const transport = new StreamableHTTPServerTransport({ sessionIdGenerator: undefined });
      await s.connect(transport);
      await transport.handleRequest(req, res, req.body);
      await transport.close();
    });
    app.listen(config.PORT, () => {
      log(`web-reader MCP server listening on port ${config.PORT}`);
    });
  } else {
    log('web-reader MCP server starting (stdio)');
    const transport = new StdioServerTransport();
    await server.connect(transport);
  }
}

// Setup signal handlers for cleanup
function setupSignalHandlers(): void {
  const shutdown = (signal: string) => {
    log(`Received ${signal}, killing browser subprocesses...`);
    killAllSubprocesses();
    process.exit(0);
  };

  process.on('SIGINT', () => shutdown('SIGINT'));
  process.on('SIGTERM', () => shutdown('SIGTERM'));
  // Client disconnect closes stdio and ends the process — browsers must not survive it.
  process.on('exit', () => killAllSubprocesses());
}

main().catch(err => {
  log('Fatal:', err);
  process.exit(1);
});

// Register signal handlers after main() starts
setupSignalHandlers();
