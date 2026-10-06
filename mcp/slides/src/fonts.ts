import { existsSync } from 'node:fs';
import { readFile } from 'node:fs/promises';
import path from 'node:path';
import { fileURLToPath } from 'node:url';

// Bundled fonts: fonts/<theme>.css + woff2 files, produced by
// scripts/fetch-fonts.mjs and committed to the repo, so the image and local
// runs render the real typefaces without reaching Google Fonts.

export interface FontsDir {
  dir: string;
  manifest: string;
}

/** Locates the bundled fonts: $SLIDES_FONTS_DIR, else <package>/fonts. Null when absent. */
export async function findFonts(): Promise<FontsDir | null> {
  const here = path.dirname(fileURLToPath(import.meta.url)); // dist/ or src/
  const dir = path.resolve(process.env.SLIDES_FONTS_DIR ?? path.join(here, '..', 'fonts'));
  const file = path.join(dir, 'manifest.json');
  if (!existsSync(file)) return null;
  return { dir, manifest: await readFile(file, 'utf8') };
}

/** woff2 file names referenced by one theme's stylesheet. */
export async function themeFontFiles(dir: string, themeId: string): Promise<string[]> {
  const css = await readFile(path.join(dir, `${themeId}.css`), 'utf8');
  return [...new Set([...css.matchAll(/url\(\.\/([\w.-]+\.woff2)\)/g)].map(m => m[1]))];
}
