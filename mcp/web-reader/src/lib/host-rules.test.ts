import { describe, it, expect } from 'vitest';
import { HostRuleSet, deriveLocaleFromUrl } from './host-rules.js';

describe('HostRuleSet', () => {
  it('parses an empty spec without rules', () => {
    const rs = new HostRuleSet(undefined);
    expect(rs.forUrl('https://example.com/')).toBeNull();
    expect(rs.describe()).toBe('none');
  });

  it('parses a single exact domain rule', () => {
    const rs = new HostRuleSet('avito.ru=humanPreset:careful');
    // Exact match (no wildcard) only matches the bare host, not subdomains.
    expect(rs.forUrl('https://avito.ru/')?.humanPreset).toBe('careful');
    expect(rs.forUrl('https://www.avito.ru/')).toBeNull();
  });

  it('wildcard matches the base and all subdomains', () => {
    const rs = new HostRuleSet('*.avito.ru=locale:ru-RU');
    expect(rs.forUrl('https://avito.ru/')?.locale).toBe('ru-RU');
    expect(rs.forUrl('https://www.avito.ru/')?.locale).toBe('ru-RU');
    expect(rs.forUrl('https://m.avito.ru/foo')?.locale).toBe('ru-RU');
    expect(rs.forUrl('https://notavito.ru/')?.locale).toBeUndefined();
  });

  it('parses multiple flags per domain', () => {
    const rs = new HostRuleSet('*.avito.ru=humanPreset:careful,viewport:1280x720,proxy');
    const r = rs.forUrl('https://www.avito.ru/');
    expect(r?.humanPreset).toBe('careful');
    expect(r?.viewport).toEqual({ width: 1280, height: 720 });
    // "proxy" without value is treated as a no-op boolean (proxy needs a URL).
    expect(r?.proxy).toBeUndefined();
  });

  it('keeps `user:pass@host` together when splitting comma-separated keys', () => {
    const rs = new HostRuleSet('*.x.ru=proxy:socks5://u:p@host:1080,locale:ru-RU');
    const r = rs.forUrl('https://m.x.ru/');
    expect(r?.proxy).toBe('socks5://u:p@host:1080');
    expect(r?.locale).toBe('ru-RU');
  });

  it('parses semicolon-separated rules', () => {
    const rs = new HostRuleSet('a.com=locale:en-US;b.ru=locale:ru-RU');
    expect(rs.forUrl('https://a.com/')?.locale).toBe('en-US');
    expect(rs.forUrl('https://b.ru/')?.locale).toBe('ru-RU');
  });

  it('returns null for an unparseable URL', () => {
    const rs = new HostRuleSet('example.com=locale:en-US');
    expect(rs.forUrl('not a url')).toBeNull();
  });

  it('describe lists parsed hosts', () => {
    const rs = new HostRuleSet('*.avito.ru=humanPreset:careful;example.com=locale:en-US');
    expect(rs.describe()).toBe('*.avito.ru,example.com');
  });
});

describe('deriveLocaleFromUrl', () => {
  it('maps .ru to ru-RU', () => {
    expect(deriveLocaleFromUrl('https://avito.ru/foo')).toBe('ru-RU');
    expect(deriveLocaleFromUrl('https://www.avito.ru/foo')).toBe('ru-RU');
  });

  it('maps .co.uk / .com.au to en-GB / en-AU', () => {
    expect(deriveLocaleFromUrl('https://example.co.uk/')).toBe('en-GB');
    expect(deriveLocaleFromUrl('https://example.com.au/')).toBe('en-AU');
  });

  it('falls back to en-US for .com / .org', () => {
    expect(deriveLocaleFromUrl('https://example.com/')).toBe('en-US');
    expect(deriveLocaleFromUrl('https://wikipedia.org/')).toBe('en-US');
  });

  it('returns fallback for invalid URL', () => {
    expect(deriveLocaleFromUrl('garbage')).toBe('en-US');
  });

  it('maps Asian TLDs', () => {
    expect(deriveLocaleFromUrl('https://example.cn')).toBe('zh-CN');
    expect(deriveLocaleFromUrl('https://example.jp')).toBe('ja-JP');
  });
});
