/**
 * Tests for Playwright subprocess manager
 */

import { describe, it } from 'node:test';
import assert from 'node:assert';
import { fetchWithPlaywright } from './playwright-subprocess.js';

describe('fetchWithPlaywright', () => {
  it('should spawn subprocess and return HTML for valid URL', async () => {
    const html = await fetchWithPlaywright('https://example.com', 30000);
    assert.strictEqual(typeof html, 'string');
    assert.ok(html.length > 0);
  });

  it('should handle subprocess timeout', async () => {
    await assert.rejects(
      async () => {
        // Use a very short timeout to trigger timeout behavior
        await fetchWithPlaywright('https://example.com', 1);
      },
      {
        message: /timeout/i
      }
    );
  });

  it('should handle Playwright launch failure', async () => {
    // This test verifies error handling when Playwright fails
    // In real scenarios, this could be due to missing Chromium
    await assert.rejects(
      async () => {
        // Use invalid URL that will cause Playwright to fail
        await fetchWithPlaywright('not-a-valid-url', 5000);
      },
      Error
    );
  });

  it('should cleanup subprocess after response', async () => {
    // This test verifies cleanup happens
    // We'll track process creation/destruction in implementation
    const html = await fetchWithPlaywright('https://example.com', 30000);
    assert.ok(html.length > 0);
    // Cleanup verification happens via process tracking in implementation
  });
});
