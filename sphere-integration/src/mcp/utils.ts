export type ImageContent = { type: "image"; data: string; mimeType: string };
export type TextContent = { type: "text"; text: string };
export type McpResult = { content: (ImageContent | TextContent)[]; isError?: boolean };

export function ok(text: string): McpResult {
  return { content: [{ type: "text", text }] };
}

export function err(text: string): McpResult {
  return { content: [{ type: "text", text }], isError: true };
}

export function isApiConfigured(): boolean {
  return !!(process.env.B24_WEBHOOK_URL || "");
}
