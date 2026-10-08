import {continueRender, delayRender, staticFile} from 'remotion';

const CYR = 'U+0301, U+0400-045F, U+0490-0491, U+04B0-04B1, U+2116';
const LAT =
  'U+0000-00FF, U+0131, U+0152-0153, U+02BB-02BC, U+02C6, U+02DA, U+02DC, U+0304, U+0308, U+0329, U+2000-206F, U+20AC, U+2122, U+2191, U+2193, U+2212, U+2215, U+FEFF, U+FFFD';

const faces: [string, string, string, string][] = [
  ['Golos Text', 'golos-text-cyrillic-465785f8.woff2', CYR, '400 900'],
  ['Golos Text', 'golos-text-latin-83cb19f9.woff2', LAT, '400 900'],
  ['JetBrains Mono', 'jetbrains-mono-cyrillic-e3f11026.woff2', CYR, '100 800'],
  ['JetBrains Mono', 'jetbrains-mono-latin-1e034387.woff2', LAT, '100 800'],
];

let started = false;

// Variable fonts bundled from mcp/slides; block rendering until they are ready.
export const loadFonts = () => {
  if (started || typeof document === 'undefined') return;
  started = true;
  const handle = delayRender('Loading brand fonts');
  Promise.all(
    faces.map(([family, file, unicodeRange, weight]) =>
      new FontFace(family, `url(${staticFile(`fonts/${file}`)}) format('woff2')`, {
        unicodeRange,
        weight,
      })
        .load()
        .then((face) => (document.fonts as unknown as Set<FontFace>).add(face)),
    ),
  )
    .then(() => continueRender(handle))
    .catch((err) => {
      console.error(err);
      continueRender(handle);
    });
};
