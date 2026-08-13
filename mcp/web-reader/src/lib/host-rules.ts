/**
 * Per-host overrides loaded from WEB_HOST_RULES env var.
 *
 * Format: `domain.tld=key:value,key:value;other.tld=key:value`
 *   - domain is matched against the URL's host (case-insensitive)
 *   - leading `*.` matches any subdomain of that base
 *   - keys: proxy, geoip, humanize, humanPreset, locale, viewport, releaseChannel
 *
 * Example:
 *   WEB_HOST_RULES="*.avito.ru=proxy+geoip,humanPreset:careful;yandex.ru=locale:ru-RU"
 *
 * Why: a single global launch config either over-pays (always-on proxy, always-
 * careful humanization) or under-pays (no protection on tough hosts). Per-host
 * rules let cheap sites stay cheap while protected sites get their bypass.
 */

export type RuleKey = 'proxy' | 'geoip' | 'humanize' | 'humanPreset' | 'locale' | 'viewport' | 'releaseChannel';

/**
 * Built-in rules for hosts that measurably need them, appended *after* the
 * user's WEB_HOST_RULES so an explicit rule always wins (first match returns).
 *
 * Both entries are Russian marketplaces fronted by DataDome-class anti-bot:
 * with the default humanization Avito served its "Иногда такое случается"
 * interstitial and Wildberries answered 498. The careful preset slows the
 * session down enough to pass without needing a proxy.
 */
export const DEFAULT_HOST_RULES =
  '*.avito.ru=humanPreset:careful,locale:ru-RU;'
  + '*.wildberries.ru=humanPreset:careful,locale:ru-RU';

const SHORT_KEYS: Record<string, RuleKey> = {
  proxy: 'proxy',
  geoip: 'geoip',
  humanize: 'humanize',
  human: 'humanize',
  preset: 'humanPreset',
  humanpreset: 'humanPreset',
  locale: 'locale',
  lang: 'locale',
  viewport: 'viewport',
  channel: 'releaseChannel',
  release: 'releaseChannel',
  releasechannel: 'releaseChannel',
};

export type HostRuleOverrides = Partial<{
  proxy: string;
  geoip: boolean;
  humanize: boolean;
  humanPreset: 'default' | 'careful';
  locale: string;
  viewport: { width: number; height: number };
  releaseChannel: 'stable' | 'preview';
}>;

interface ParsedRule {
  /** Original pattern, normalized to lowercase. */
  pattern: string;
  /** True when the pattern starts with `*.` — matches `<pattern>.<rest>`. */
  wildcard: boolean;
  overrides: HostRuleOverrides;
}

export class HostRuleSet {
  private readonly rules: ParsedRule[];

  constructor(spec: string | undefined) {
    this.rules = (spec ?? '')
      .split(/[;\n]/)
      .map(s => s.trim())
      .filter(Boolean)
      .map(s => this.parseOne(s))
      .filter((r): r is ParsedRule => r !== null);
  }

  private parseOne(entry: string): ParsedRule | null {
    const eq = entry.indexOf('=');
    if (eq <= 0) return null;
    const pattern = entry.slice(0, eq).trim().toLowerCase();
    const body = entry.slice(eq + 1).trim();
    if (!pattern || !body) return null;

    const overrides: HostRuleOverrides = {};
    // Split on comma; values may contain `:` (proxy URL has user:pass@host).
    // Use a tiny splitter that respects `proxy=...` being the only key without `:`.
    const parts = this.splitKeys(body);
    for (const part of parts) {
      const colon = part.indexOf(':');
      if (colon < 0) {
        // Bare flags: "proxy" / "geoip" / "humanize" — boolean toggle to true.
        const key = SHORT_KEYS[part.trim().toLowerCase()];
        if (!key) continue;
        this.applyBool(overrides, key, true);
        continue;
      }
      const key = SHORT_KEYS[part.slice(0, colon).trim().toLowerCase()];
      const val = part.slice(colon + 1).trim();
      if (!key || !val) continue;
      this.applyValue(overrides, key, val);
    }
    const wildcard = pattern.startsWith('*.');
    return { pattern: wildcard ? pattern.slice(2) : pattern, wildcard, overrides };
  }

  /**
   * Split a rule body on commas. Real proxy URLs (socks5://user:pass@host:port)
   * never contain unescaped commas, so the naive split is safe — the only
   * embedded delimiter is `:` and `@`, neither of which is a comma.
   */
  private splitKeys(body: string): string[] {
    return body.split(',').filter(Boolean);
  }

  private applyBool(o: HostRuleOverrides, key: RuleKey, v: boolean): void {
    if (key === 'geoip' || key === 'humanize') o[key] = v;
  }

  private applyValue(o: HostRuleOverrides, key: RuleKey, v: string): void {
    switch (key) {
      case 'proxy': o.proxy = v; break;
      case 'humanPreset':
        if (v === 'default' || v === 'careful') o.humanPreset = v;
        break;
      case 'locale': o.locale = v; break;
      case 'viewport': {
        const m = /^(\d+)x(\d+)$/.exec(v);
        if (m) o.viewport = { width: Number(m[1]), height: Number(m[2]) };
        break;
      }
      case 'releaseChannel':
        if (v === 'stable' || v === 'preview') o.releaseChannel = v;
        break;
      // geoip / humanize have no value form; ignore.
      case 'geoip':
      case 'humanize':
        break;
    }
  }

  /** Return merged overrides for a URL's host, or null if no rule matched. */
  forUrl(url: string): HostRuleOverrides | null {
    let host: string;
    try { host = new URL(url).host.toLowerCase(); } catch { return null; }
    for (const rule of this.rules) {
      if (this.matches(host, rule)) return rule.overrides;
    }
    return null;
  }

  private matches(host: string, rule: ParsedRule): boolean {
    if (rule.wildcard) {
      // `*.avito.ru` must match exactly `avito.ru` or `*.avito.ru`.
      // Also accept `m.avito.ru` but not `notavito.ru`.
      return host === rule.pattern || host.endsWith('.' + rule.pattern);
    }
    return host === rule.pattern;
  }

  /** For diagnostics at startup. */
  describe(): string {
    if (this.rules.length === 0) return 'none';
    return this.rules.map(r => (r.wildcard ? '*.' : '') + r.pattern).join(',');
  }
}

/**
 * Best-effort locale inference from URL TLD. Used when WEB_LOCALE is unset
 * and no per-host rule supplies one — keeps Accept-Language and
 * navigator.language aligned with the site's audience.
 */
const TLD_LOCALE: Record<string, string> = {
  ru: 'ru-RU', ua: 'uk-UA', by: 'ru-BY', kz: 'ru-KZ',
  de: 'de-DE', at: 'de-AT', ch: 'de-CH',
  fr: 'fr-FR', it: 'it-IT', es: 'es-ES', pt: 'pt-PT', nl: 'nl-NL',
  cn: 'zh-CN', tw: 'zh-TW', hk: 'zh-HK', jp: 'ja-JP', kr: 'ko-KR',
  tr: 'tr-TR', pl: 'pl-PL', cz: 'cs-CZ', se: 'sv-SE', no: 'nb-NO', fi: 'fi-FI',
  gb: 'en-GB', uk: 'en-GB', au: 'en-AU', ca: 'en-CA', in: 'en-IN',
  br: 'pt-BR', mx: 'es-MX', ar: 'es-AR',
  il: 'he-IL', ae: 'ar-AE', sa: 'ar-SA', eg: 'ar-EG',
};

export function deriveLocaleFromUrl(url: string, fallback = 'en-US'): string {
  try {
    const host = new URL(url).host.toLowerCase();
    // country-code TLDs (.ru, .co.uk); generic TLDs (.com, .org) get fallback.
    const parts = host.split('.');
    if (parts.length < 2) return fallback;
    const tld = parts[parts.length - 1];
    const last2 = parts.length >= 2 ? parts[parts.length - 2] : '';
    // Handle `co.uk`, `com.au`, etc.
    if ((last2 === 'co' || last2 === 'com') && TLD_LOCALE[tld]) {
      return TLD_LOCALE[tld];
    }
    return TLD_LOCALE[tld] ?? fallback;
  } catch {
    return fallback;
  }
}
