import { mkdir, writeFile } from 'node:fs/promises';
import path from 'node:path';
import PptxGenJSModule from 'pptxgenjs';
import type { Deck } from './schema.js';
import { pdf, screenshots } from './browser.js';

// pptxgenjs's default export is the class under Node's ESM loader but a
// namespace with .default under CJS interop (tsx, vitest); accept both.
type PptxCtor = typeof PptxGenJSModule.default;
const PptxGenJS: PptxCtor = (PptxGenJSModule as unknown as { default?: PptxCtor }).default
  ?? (PptxGenJSModule as unknown as PptxCtor);

export type ExportFormat = 'pdf' | 'pptx' | 'png';

/**
 * Writes an export into <deck>/exports/ and returns the file names.
 * PPTX is image-per-slide (pixel-identical to the preview, speaker notes kept),
 * not editable shapes: re-creating this typography and these layouts as native
 * PowerPoint objects would lose exactly the design the deck exists for.
 */
export async function exportDeck(deckDir: string, deck: Deck, format: ExportFormat): Promise<string[]> {
  const outDir = path.join(deckDir, 'exports');
  await mkdir(outDir, { recursive: true });
  const base = 'deck';

  if (format === 'pdf') {
    await writeFile(path.join(outDir, `${base}.pdf`), await pdf(deckDir));
    return [`exports/${base}.pdf`];
  }

  const shots = await screenshots(deckDir, undefined, 1);
  if (format === 'png') {
    const names = [];
    for (const s of shots) {
      const name = `slide-${String(s.slide).padStart(2, '0')}.png`;
      await writeFile(path.join(outDir, name), s.png);
      names.push(`exports/${name}`);
    }
    return names;
  }

  const pptx = new PptxGenJS();
  pptx.layout = 'LAYOUT_WIDE'; // 13.33 × 7.5 in, 16:9
  pptx.title = deck.title;
  for (const s of shots) {
    const slide = pptx.addSlide();
    slide.addImage({ data: `data:image/png;base64,${s.png.toString('base64')}`, x: 0, y: 0, w: 13.333, h: 7.5 });
    const notes = deck.slides[s.slide - 1]?.notes;
    if (notes) slide.addNotes(notes);
  }
  const buf = await pptx.write({ outputType: 'nodebuffer' }) as Buffer;
  await writeFile(path.join(outDir, `${base}.pptx`), buf);
  return [`exports/${base}.pptx`];
}
