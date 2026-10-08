import React from 'react';
import {AbsoluteFill, useCurrentFrame} from 'remotion';
import {C, FONT, MONO} from './brand';
import {agentLog, agentStats, type FilmProps} from './data';
import {Film} from './Film';
import {Check, LogoMark} from './icons';
import {FrameContext, H, T, W, easeInOut, easeOut, ip, mix, pop} from './time';

const PREVIEW = {x: 740, y: 96, w: 1140};
const PS = PREVIEW.w / W;

const specLines = (p: FilmProps) => [
  '{',
  '  "brand": "Лоция",',
  '  "fps": 30, "seconds": 90,',
  '  "scenes": [',
  '    { "id": "storm", "docs": 48 },',
  '    { "id": "lighthouse", "route": 4 },',
  '    { "id": "memo", "zoom": 9 },',
  '    { "id": "sphere", "task": "акты" },',
  '    { "id": "report", "data": "1С" },',
  '    { "id": "looc", "to": "' + p.name + '" },',
  '    { "id": "personal",',
  '      "for": "' + p.name + '", "hours": ' + p.hoursSaved + ' },',
  '    { "id": "reveal" }',
  '  ]',
  '}',
];

const Token: React.FC<{line: string}> = ({line}) => {
  const parts = line.split(/("[^"]*"\s*:?|\d+)/g);
  return (
    <>
      {parts.map((p, i) => {
        let color = '#A9A3C9';
        if (/^"[^"]*"\s*:$/.test(p)) color = C.purpleSoft;
        else if (/^"/.test(p)) color = '#FFB38A';
        else if (/^\d+$/.test(p)) color = '#5FE0CF';
        return (
          <span key={i} style={{color}}>
            {p}
          </span>
        );
      })}
    </>
  );
};

const TRACKS = [
  ['Шторм', 0, T.beam, '#4B3A8C'],
  ['Маяк', T.beam, T.route, '#6A4BD0'],
  ['Маршрут · 4 зума', T.route, T.personal, C.purple],
  ['Персонально', T.personal, T.reveal, C.orange],
] as const;

const Editor: React.FC<{f: number; filmFrame: number; props: FilmProps}> = ({f, filmFrame, props}) => {
  const t = f - T.reveal;
  const p = ip(t, [0, 45], [0, 1], easeInOut);
  const chrome = ip(t, [20, 50], [0, 1]);
  const lines = specLines(props);
  const scale = mix(1, PS, p);
  const x = mix(0, PREVIEW.x, p);
  const y = mix(0, PREVIEW.y, p);
  const playhead = filmFrame / T.reveal;
  return (
    <AbsoluteFill style={{background: '#0B0820', fontFamily: FONT}}>
      <div style={{opacity: chrome}}>
        <div style={{position: 'absolute', left: 0, right: 0, top: 0, height: 64, display: 'flex', alignItems: 'center', gap: 12, padding: '0 40px', color: '#CFC8F0', fontSize: 22}}>
          {['#FF5F57', '#FEBC2E', '#28C840'].map((c) => (
            <div key={c} style={{width: 16, height: 16, borderRadius: 8, background: c}} />
          ))}
          <span style={{marginLeft: 18}}>loodsen-agents-demo — Remotion</span>
          <span style={{marginLeft: 'auto', background: C.purple, color: '#fff', borderRadius: 20, padding: '6px 18px', fontWeight: 650}}>агент: готово</span>
        </div>
        <div style={{position: 'absolute', left: 40, top: 96, width: 660, height: 560, background: '#140F33', borderRadius: 18, padding: '22px 26px', boxSizing: 'border-box', fontFamily: MONO, fontSize: 21, lineHeight: 1.6, overflow: 'hidden'}}>
          <div style={{color: '#6E6896', fontSize: 18, marginBottom: 8}}>film.json · сгенерировано агентом</div>
          {lines.map((l, i) => (
            <div key={i} style={{whiteSpace: 'pre', opacity: ip(t, [30 + i * 4, 36 + i * 4], [0, 1])}}>
              <Token line={l} />
            </div>
          ))}
        </div>
        <div style={{position: 'absolute', left: 40, top: 676, width: 660, height: 364, background: '#140F33', borderRadius: 18, padding: '22px 26px', boxSizing: 'border-box', fontFamily: MONO, fontSize: 21, lineHeight: 1.7, color: '#CFC8F0'}}>
          <div style={{color: '#8D86B8'}}>$ agent run «ролик для админ-персонала»</div>
          {agentLog.map((l, i) => {
            const at = 70 + i * 22;
            if (t < at) return null;
            return (
              <div key={l} style={{display: 'flex', alignItems: 'center', gap: 12, opacity: ip(t, [at, at + 6], [0, 1])}}>
                <Check size={22} color="#5FE0CF" stroke={3.5} />
                {l}
              </div>
            );
          })}
          {t >= 70 + agentLog.length * 22 && <div style={{color: C.orange, marginTop: 4, fontWeight: 700}}>= {agentStats}</div>}
        </div>
        <div style={{position: 'absolute', left: PREVIEW.x, top: 770, width: PREVIEW.w, height: 270, background: '#140F33', borderRadius: 18, padding: 24, boxSizing: 'border-box'}}>
          {TRACKS.map(([name, a, b, color], i) => (
            <div
              key={name}
              style={{
                position: 'absolute',
                left: 24 + ((PREVIEW.w - 48) * a) / T.reveal,
                width: ((PREVIEW.w - 48) * (b - a)) / T.reveal - 6,
                top: 30 + (i % 2) * 70,
                height: 56,
                background: color,
                borderRadius: 12,
                color: '#fff',
                fontSize: 20,
                fontWeight: 650,
                display: 'flex',
                alignItems: 'center',
                padding: '0 14px',
                boxSizing: 'border-box',
                whiteSpace: 'nowrap',
                overflow: 'hidden',
              }}
            >
              {name}
            </div>
          ))}
          <div style={{position: 'absolute', left: 24, right: 24, top: 180, height: 50, display: 'flex', gap: 3, alignItems: 'flex-end'}}>
            {Array.from({length: 90}, (_, i) => (
              <div key={i} style={{flex: 1, height: 8 + Math.abs(Math.sin(i * 1.7) * Math.cos(i * 0.31)) * 40, background: '#3A2F73', borderRadius: 2}} />
            ))}
          </div>
          <div style={{position: 'absolute', top: 14, bottom: 14, left: 24 + (PREVIEW.w - 48) * playhead, width: 4, background: '#fff', borderRadius: 2}} />
        </div>
      </div>
      <div
        style={{
          position: 'absolute',
          left: x,
          top: y,
          width: W,
          height: H,
          transformOrigin: '0 0',
          transform: `scale(${scale})`,
          borderRadius: 24 / Math.max(scale, 0.01),
          overflow: 'hidden',
          boxShadow: `0 0 0 ${4 / scale}px rgba(185,162,246,${p * 0.6})`,
        }}
      >
        <FrameContext.Provider value={filmFrame}>
          <Film props={props} />
        </FrameContext.Provider>
      </div>
    </AbsoluteFill>
  );
};

const Outro: React.FC<{f: number}> = ({f}) => {
  const t = f - T.outro;
  const wipe = ip(t, [0, 26], [0, 1], easeInOut);
  const a = pop(t, 18, 12);
  const b = pop(t, 26, 12);
  const word = ip(t, [44, 62], [0, 1], easeOut);
  const shift = ip(t, [80, 104], [0, 1], easeInOut);
  const tag = ip(t, [96, 118], [0, 1], easeOut);
  const sub = ip(t, [112, 132], [0, 1], easeOut);
  return (
    <AbsoluteFill
      style={{
        background: `radial-gradient(circle at 50% 40%, #8A5CF0, ${C.purple} 45%, ${C.purpleDeep})`,
        clipPath: `circle(${wipe * 2100}px at ${PREVIEW.x + (PREVIEW.w / 2)}px ${PREVIEW.y + (H * PS) / 2}px)`,
        fontFamily: FONT,
        color: '#fff',
        alignItems: 'center',
        justifyContent: 'center',
      }}
    >
      <div style={{display: 'flex', flexDirection: 'column', alignItems: 'center', transform: `translateY(${-shift * 150}px) scale(${mix(1, 0.8, shift)})`}}>
        <LogoMark
          size={300}
          a={`translate(${(1 - a) * 260}px, ${(1 - a) * -260}px) rotate(${(1 - a) * -60}deg)`}
          b={`translate(${(1 - b) * -260}px, ${(1 - b) * 260}px) rotate(${(1 - b) * -60}deg)`}
        />
        <div style={{marginTop: 46, fontSize: 150, fontWeight: 800, letterSpacing: 6 + (1 - word) * 40, opacity: word, lineHeight: 1}}>ЛОЦИЯ</div>
        <div style={{fontSize: 56, fontWeight: 500, opacity: word, marginTop: 8}}>ит-компания</div>
      </div>
      <div style={{position: 'absolute', top: 760, textAlign: 'center'}}>
        <div style={{fontSize: 70, fontWeight: 800, opacity: tag, transform: `translateY(${(1 - tag) * 40}px)`}}>Этот ролик никто не монтировал</div>
        <div style={{fontSize: 38, opacity: sub * 0.85, marginTop: 16, transform: `translateY(${(1 - sub) * 30}px)`}}>
          Его собрал агент — из данных, за минуты
        </div>
      </div>
    </AbsoluteFill>
  );
};

export const Main: React.FC<FilmProps> = (props) => {
  const f = useCurrentFrame();
  if (f < T.reveal) {
    return (
      <FrameContext.Provider value={f}>
        <Film props={props} />
      </FrameContext.Provider>
    );
  }
  // In the editor the preview replays the whole film at ~15x, playhead included.
  const t = f - T.reveal;
  const filmFrame = t < 60 ? f : Math.round(ip(t, [60, 230], [0, T.reveal - 1], easeInOut));
  return (
    <AbsoluteFill>
      <Editor f={f} filmFrame={filmFrame} props={props} />
      {f >= T.outro && <Outro f={f} />}
    </AbsoluteFill>
  );
};
