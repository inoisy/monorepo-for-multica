export function esc(s: string): string {
  return s.replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;')
    .replace(/"/g, '&quot;').replace(/'/g, '&#39;');
}

/**
 * Minimal inline markup: **bold**, *italic*, `code`, ==highlight== (accent).
 * Line breaks become <br>. Escapes first, so input can't inject HTML.
 */
export function inline(s: string): string {
  return esc(s)
    .replace(/`([^`]+)`/g, '<code>$1</code>')
    .replace(/\*\*([^*]+)\*\*/g, '<strong>$1</strong>')
    .replace(/==([^=]+)==/g, '<mark>$1</mark>')
    .replace(/(^|[^*])\*([^*\s][^*]*)\*/g, '$1<em>$2</em>')
    .replace(/\n/g, '<br>');
}

export function plain(s: string): string {
  return s.replace(/[*`=]/g, '');
}

export function words(...parts: (string | undefined)[]): number {
  return parts.filter(Boolean).join(' ').split(/\s+/).filter(w => /[\p{L}\p{N}]/u.test(w)).length;
}
