// Curated themes. Each one is a finished design decision — palette, font
// pairing, corner radius, display weight — so an agent chooses a mood instead
// of composing colors. Every font here ships Cyrillic glyphs on Google Fonts:
// decks are often written in Russian, and a Latin-only display face silently
// falls back to the system font for Cyrillic headlines.

export interface Theme {
  id: string;
  name: string;
  mood: string;
  dark: boolean;
  fonts: { display: string; body: string; mono: string };
  /** Google Fonts css2 family specs, e.g. "Inter:wght@400;600". */
  googleFonts: string[];
  displayWeight: number;
  displayTracking: string;
  /** Average digit/letter advance of the display face, in em. Sizes stat numbers to their box. */
  displayWidth: number;
  radius: number;
  colors: {
    bg: string;
    surface: string;
    surface2: string;
    border: string;
    text: string;
    muted: string;
    accent: string;
    /** Text color on an accent-filled tile. */
    onAccent: string;
    accent2: string;
    onAccent2: string;
  };
}

const THEMES_LIST = [
  {
    id: 'graphite',
    name: 'Graphite',
    mood: 'Dark, technical, confident. Product launches, engineering reviews, metrics.',
    dark: true,
    fonts: { display: 'Inter Tight', body: 'Inter', mono: 'JetBrains Mono' },
    googleFonts: ['Inter+Tight:wght@500;600;700', 'Inter:wght@400;500;600', 'JetBrains+Mono:wght@500'],
    displayWeight: 600,
    displayTracking: '-0.035em',
    displayWidth: 0.58,
    radius: 28,
    colors: {
      bg: '#0D0E11', surface: '#17191E', surface2: '#21242B', border: '#2A2E36',
      text: '#F4F5F7', muted: '#8B919C',
      accent: '#C8F031', onAccent: '#0D0E11',
      accent2: '#7C8CFF', onAccent2: '#0D0E11',
    },
  },
  {
    id: 'paper',
    name: 'Paper',
    mood: 'Light editorial, serif headlines. Strategy, research, storytelling.',
    dark: false,
    fonts: { display: 'Playfair Display', body: 'Inter', mono: 'JetBrains Mono' },
    googleFonts: ['Playfair+Display:wght@500;600;700', 'Inter:wght@400;500;600', 'JetBrains+Mono:wght@500'],
    displayWeight: 600,
    displayTracking: '-0.02em',
    displayWidth: 0.6,
    radius: 18,
    colors: {
      bg: '#F5F1E8', surface: '#FFFDF8', surface2: '#ECE6D9', border: '#DDD5C4',
      text: '#1D1B17', muted: '#6F685C',
      accent: '#C2410C', onAccent: '#FFF8F0',
      accent2: '#1F4E5F', onAccent2: '#F5F1E8',
    },
  },
  {
    id: 'aurora',
    name: 'Aurora',
    mood: 'Deep navy with violet and teal glow. Vision, AI, fundraising.',
    dark: true,
    fonts: { display: 'Unbounded', body: 'Manrope', mono: 'JetBrains Mono' },
    googleFonts: ['Unbounded:wght@500;600;700', 'Manrope:wght@400;500;600;700', 'JetBrains+Mono:wght@500'],
    displayWeight: 600,
    displayTracking: '-0.03em',
    displayWidth: 0.82,
    radius: 32,
    colors: {
      bg: '#0A0F1F', surface: '#131A31', surface2: '#1C2442', border: '#27305A',
      text: '#EEF0FF', muted: '#8F97C0',
      accent: '#8C7CFF', onAccent: '#0A0F1F',
      accent2: '#3DDCC8', onAccent2: '#0A0F1F',
    },
  },
  {
    id: 'swiss',
    name: 'Swiss',
    mood: 'White, black, one red. Minimal, grid-driven, very readable.',
    dark: false,
    fonts: { display: 'Onest', body: 'Onest', mono: 'JetBrains Mono' },
    googleFonts: ['Onest:wght@400;500;600;700;800', 'JetBrains+Mono:wght@500'],
    displayWeight: 700,
    displayTracking: '-0.04em',
    displayWidth: 0.6,
    radius: 6,
    colors: {
      bg: '#FFFFFF', surface: '#F3F3F1', surface2: '#E7E7E4', border: '#DADAD6',
      text: '#0B0B0B', muted: '#6B6B66',
      accent: '#FF3B1F', onAccent: '#FFFFFF',
      accent2: '#0B0B0B', onAccent2: '#FFFFFF',
    },
  },
  {
    id: 'forest',
    name: 'Forest',
    mood: 'Dark green and gold, serif display. Sustainability, finance, calm authority.',
    dark: true,
    fonts: { display: 'Literata', body: 'Golos Text', mono: 'JetBrains Mono' },
    googleFonts: ['Literata:opsz,wght@7..72,500;7..72,600', 'Golos+Text:wght@400;500;600', 'JetBrains+Mono:wght@500'],
    displayWeight: 500,
    displayTracking: '-0.02em',
    displayWidth: 0.6,
    radius: 22,
    colors: {
      bg: '#0E1913', surface: '#15241B', surface2: '#1D3025', border: '#29402F',
      text: '#EEF3EC', muted: '#93A597',
      accent: '#E8C468', onAccent: '#0E1913',
      accent2: '#7FC8A9', onAccent2: '#0E1913',
    },
  },
  {
    id: 'sunrise',
    name: 'Sunrise',
    mood: 'Warm light, coral and violet. Marketing, culture, onboarding, friendly.',
    dark: false,
    fonts: { display: 'Geologica', body: 'Golos Text', mono: 'JetBrains Mono' },
    googleFonts: ['Geologica:wght@500;600;700', 'Golos+Text:wght@400;500;600', 'JetBrains+Mono:wght@500'],
    displayWeight: 600,
    displayTracking: '-0.035em',
    displayWidth: 0.62,
    radius: 30,
    colors: {
      bg: '#FFF6EE', surface: '#FFFFFF', surface2: '#FBE7D8', border: '#F1D9C6',
      text: '#24160F', muted: '#8A6E5E',
      accent: '#FF6A3D', onAccent: '#FFFFFF',
      accent2: '#6F55F2', onAccent2: '#FFFFFF',
    },
  },
  {
    id: 'ocean',
    name: 'Ocean',
    mood: 'Clean light corporate blue. Client reports, sales, quarterly business reviews.',
    dark: false,
    fonts: { display: 'Manrope', body: 'Manrope', mono: 'JetBrains Mono' },
    googleFonts: ['Manrope:wght@400;500;600;700;800', 'JetBrains+Mono:wght@500'],
    displayWeight: 700,
    displayTracking: '-0.035em',
    displayWidth: 0.62,
    radius: 20,
    colors: {
      bg: '#F3F6FB', surface: '#FFFFFF', surface2: '#E4ECF7', border: '#D6E0EE',
      text: '#0B1A33', muted: '#5E6E88',
      accent: '#1E6BFF', onAccent: '#FFFFFF',
      accent2: '#0B1A33', onAccent2: '#FFFFFF',
    },
  },
  {
    id: 'terminal',
    name: 'Terminal',
    mood: 'Near-black with phosphor green, monospace display. Dev tools, infra, security.',
    dark: true,
    fonts: { display: 'JetBrains Mono', body: 'IBM Plex Sans', mono: 'JetBrains Mono' },
    googleFonts: ['JetBrains+Mono:wght@500;600;700', 'IBM+Plex+Sans:wght@400;500;600'],
    displayWeight: 600,
    displayTracking: '-0.04em',
    displayWidth: 0.62,
    radius: 10,
    colors: {
      bg: '#090C0A', surface: '#101612', surface2: '#18201A', border: '#223026',
      text: '#E6F2E9', muted: '#7D9484',
      accent: '#3DFF8C', onAccent: '#06110A',
      accent2: '#FFB547', onAccent2: '#06110A',
    },
  },
] as const satisfies readonly Theme[];

export const THEME_IDS = THEMES_LIST.map(t => t.id) as unknown as readonly [
  (typeof THEMES_LIST)[number]['id'],
  ...(typeof THEMES_LIST)[number]['id'][],
];

export type ThemeId = (typeof THEMES_LIST)[number]['id'];

export const THEMES: Record<ThemeId, Theme> = Object.fromEntries(
  THEMES_LIST.map(t => [t.id, t]),
) as unknown as Record<ThemeId, Theme>;
