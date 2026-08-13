import * as z from 'zod';

// stderr-only wrapper (stdout reserved for JSON-RPC in stdio transport)
export const log = (...args: unknown[]): void => {
  console.error(...args);
};

// verbose renderer tracing, off unless WEB_DEBUG=1
export const debug = (...args: unknown[]): void => {
  if (process.env.WEB_DEBUG === '1' || process.env.WEB_DEBUG === 'true') console.error(...args);
};

// hard cap on text length returned to the agent
export function truncate(text: string, maxChars = 20_000): string {
  if (text.length <= maxChars) return text;
  return text.slice(0, maxChars) + `\n\n[Truncated: ${text.length - maxChars} chars omitted]`;
}

// standard isError result shape for MCP tool failures
export function toError(msg: string): { content: [{ type: 'text'; text: string }]; isError: true } {
  return {
    content: [{ type: 'text' as const, text: msg }],
    isError: true,
  };
}

// fail-fast env validation via Zod
export function loadConfig<T extends z.ZodObject<z.ZodRawShape>>(schema: T): z.infer<T> {
  const result = schema.safeParse(process.env);
  if (!result.success) {
    const missing = result.error.issues.map(i => i.path.join('.')).join(', ');
    console.error(`[web-reader] Missing required env vars: ${missing}`);
    process.exit(1);
  }
  return result.data;
}
