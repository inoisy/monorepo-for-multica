/**
 * Post-extraction cleanup of the markdown handed to the agent.
 *
 * Extractors faithfully convert whatever the DOM held — including inline
 * `data:` images and pages whose "text" is layout filler. Both are pure cost to
 * a language model: a single base64 sad-cloud from a Chrome error page is ~10k
 * characters, half of a default `max_chars` budget, and carries no information.
 */

/** Longest `data:` payload kept inline. Anything above this is dropped. */
const DATA_URI_KEEP_LIMIT = 256;

/**
 * Replace inline `data:` URIs with a short placeholder.
 *
 * Images lose the payload entirely (the alt text is the only part an agent can
 * use); links keep their anchor text so the sentence still reads. Small URIs
 * (tracking pixels, tiny SVG icons) are left alone — they cost nothing and
 * removing them would churn otherwise-clean output.
 */
export function stripDataUris(markdown: string): string {
  return markdown
    // ![alt](data:image/png;base64,....) -> ![alt](inline-image) or nothing
    .replace(/!\[([^\]]*)\]\(\s*data:[^)\s]{256,}\s*\)/g, (_m, alt: string) =>
      alt.trim() ? `![${alt}]` : '')
    // [text](data:....) -> text
    .replace(/\[([^\]]*)\]\(\s*data:[^)\s]{256,}\s*\)/g, (_m, text: string) => text)
    // Bare payloads that survived as plain text (turndown emits these for
    // <img> without a wrapping link when the alt is empty).
    .replace(new RegExp(`data:[a-z0-9.+-]+/[a-z0-9.+-]+;base64,[A-Za-z0-9+/=]{${DATA_URI_KEEP_LIMIT},}`, 'gi'), '[inline-data omitted]')
    .replace(/\n{3,}/g, '\n\n');
}

/**
 * Drop long runs of one repeated punctuation character.
 *
 * Canvas-first apps use them as layout filler: 2gis.ru's map shell extracts to
 * ~1400 leading dots before the first real link. Markdown's own rules (`---`,
 * `***`) are far shorter than the threshold, so they survive.
 */
export function stripFillerRuns(markdown: string): string {
  return markdown
    .replace(/([^\p{L}\p{N}\s])\1{19,}/gu, '')
    .replace(/\n{3,}/g, '\n\n');
}

/**
 * Detect content that is technically non-empty but carries nothing readable.
 *
 * Canvas-first SPAs (2gis.ru) render into WebGL and leave the DOM holding
 * layout filler — the extractor returns thousands of dots. Returning that to
 * the agent is worse than an error: it looks like an answer.
 *
 * Returns a human-readable reason, or null when the content is usable.
 */
export function detectJunkContent(text: string): string | null {
  const trimmed = text.trim();
  if (!trimmed) return 'the extractor produced an empty document';
  if (trimmed.length < 200) return null; // short pages are judged by the caller

  const letters = (trimmed.match(/[\p{L}\p{N}]/gu) ?? []).length;
  const ratio = letters / trimmed.length;
  if (ratio < 0.1) {
    return 'the page body contained almost no letters or digits '
      + `(${Math.round(ratio * 100)}% of ${trimmed.length} chars) — likely a canvas/WebGL app that renders no text DOM`;
  }

  // One character repeated for most of the document (".....", "─────").
  const longestRun = (trimmed.match(/(.)\1{40,}/g) ?? [])
    .reduce((max, run) => Math.max(max, run.length), 0);
  if (longestRun / trimmed.length > 0.5) {
    return `the page body was ${Math.round((longestRun / trimmed.length) * 100)}% a single repeated character — layout filler, not content`;
  }

  return null;
}

/** Full post-extraction pass: drop inline payloads and filler, tidy whitespace. */
export function sanitizeMarkdown(markdown: string): string {
  return stripFillerRuns(stripDataUris(markdown))
    .replace(/[ \t]+$/gm, '')
    .trim();
}
