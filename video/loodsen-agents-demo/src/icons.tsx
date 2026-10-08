import React from 'react';

export const Check: React.FC<{size?: number; color?: string; stroke?: number}> = ({size = 24, color = 'currentColor', stroke = 3}) => (
  <svg width={size} height={size} viewBox="0 0 24 24" style={{display: 'inline-block', verticalAlign: 'middle'}}>
    <path d="M4 12.5l5 5L20 6.5" fill="none" stroke={color} strokeWidth={stroke} strokeLinecap="round" strokeLinejoin="round" />
  </svg>
);

// Glyphs for the four document kinds, drawn in a 24x24 box.
export const DocGlyph: React.FC<{kind: number; size?: number; color: string}> = ({kind, size = 28, color}) => {
  const common = {fill: 'none', stroke: color, strokeWidth: 2.2, strokeLinecap: 'round' as const, strokeLinejoin: 'round' as const};
  return (
    <svg width={size} height={size} viewBox="0 0 24 24">
      {kind === 0 && (
        <>
          <path d="M6 3h9l4 4v14H6z" {...common} />
          <path d="M9 11h7M9 15h7M9 7h3" {...common} />
        </>
      )}
      {kind === 1 && (
        <>
          <rect x="4" y="4" width="16" height="16" rx="4" {...common} />
          <path d="M8 12l3 3 5-6" {...common} />
        </>
      )}
      {kind === 2 && (
        <>
          <path d="M5 20V10M10 20V5M15 20v-7M20 20V8" {...common} />
        </>
      )}
      {kind === 3 && (
        <>
          <rect x="3" y="6" width="18" height="13" rx="2" {...common} />
          <path d="M3 8l9 6 9-6" {...common} />
        </>
      )}
    </svg>
  );
};

// Loodsen mark: two counter-directed arrows, traced from the site logo.
export const LOGO_A = '88,4 88,36 166,36 166,62 86,62 86,38 15,90 12,90 12,62';
export const LogoMark: React.FC<{size: number; color?: string; a?: string; b?: string}> = ({size, color = '#fff', a, b}) => (
  <svg width={size} height={(size * 152) / 178} viewBox="0 0 178 152" style={{overflow: 'visible'}}>
    <g style={{transform: a}}>
      <polygon points={LOGO_A} fill={color} />
    </g>
    <g style={{transform: b}}>
      <polygon points={LOGO_A} fill={color} transform="rotate(180 88 76)" />
    </g>
  </svg>
);
