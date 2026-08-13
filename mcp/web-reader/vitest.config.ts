import { defineConfig } from 'vitest/config';

export default defineConfig({
  test: {
    environment: 'node',
    include: [
      'src/lib/challenge.test.ts',
      'src/lib/extractor-defuddle.test.ts',
      'src/lib/pipeline.test.ts',
      'src/lib/fetcher.test.ts',
      'src/lib/renderer-chain.test.ts',
      'src/lib/host-rules.test.ts',
      'src/lib/sanitize.test.ts',
      'src/lib/extractor-feed.test.ts',
    ],
  },
});
