import { IRenderer } from './types.js';
import { classifyRenderedHtml } from './challenge.js';
import { log } from './utils.js';

export interface NamedRenderer {
  name: string;
  renderer: IRenderer;
}

function hostOf(url: string): string {
  try { return new URL(url).host; } catch { return url; }
}

/**
 * Tries renderers in order until one returns a page that no longer looks like
 * an anti-bot interstitial.
 *
 * Rationale: even a single renderer can be blocked outright for some host, and
 * a future second engine (paid anti-bot service, residential proxy) drops in
 * here without touching call sites. With only one engine configured the loop
 * is degenerate but still correct — it returns whatever that engine produced.
 *
 * If nothing reaches a clean verdict, the largest page seen is returned rather
 * than nothing — a partial page still beats an error for the caller — and only
 * a total failure raises, with every engine's reason attached.
 */
export class FallbackRenderer implements IRenderer {
  /**
   * Host -> engine that last delivered it. With CloakBrowser as the sole
   * configured engine the map never gets a useful entry, but it costs nothing
   * and keeps the slot for a future second engine.
   */
  private readonly winners = new Map<string, string>();

  constructor(private readonly renderers: NamedRenderer[]) {
    if (renderers.length === 0) throw new Error('FallbackRenderer needs at least one renderer');
  }

  private orderFor(url: string): NamedRenderer[] {
    const winner = this.winners.get(hostOf(url));
    if (!winner) return this.renderers;
    const preferred = this.renderers.filter(r => r.name === winner);
    return preferred.length ? [...preferred, ...this.renderers.filter(r => r.name !== winner)] : this.renderers;
  }

  async render(url: string, timeout?: number): Promise<string> {
    const failures: string[] = [];
    let best = '';

    for (const { name, renderer } of this.orderFor(url)) {
      try {
        const html = await renderer.render(url, timeout);
        const { verdict, vendor } = classifyRenderedHtml(html);
        if (verdict === 'ok') {
          this.winners.set(hostOf(url), name);
          return html;
        }

        if (html.length > best.length) best = html;
        const tag = vendor ? `${verdict} by ${vendor}` : verdict;
        failures.push(`${name}: page still looked like an interstitial (${tag})`);
      } catch (err) {
        failures.push(`${name}: ${err instanceof Error ? err.message : String(err)}`);
      }
      log(`web-reader: renderer "${name}" did not deliver ${url}, trying next`);
    }

    if (best) {
      log(`web-reader: returning best-effort partial page for ${url}`);
      return best;
    }

    throw new Error(
      `Failed to render ${url}. Renderers tried:\n${failures.map(f => `  - ${f}`).join('\n')}`,
    );
  }
}
