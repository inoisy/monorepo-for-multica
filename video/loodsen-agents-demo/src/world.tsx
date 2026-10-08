import React, {useMemo} from 'react';
import {C, FONT} from './brand';
import {StopCard} from './cards';
import {BUOYS, CARD, HARBOR, LIGHT, ROUTE, ROUTE_LEN, START, STOPS, STOP_LENS, WORLD, angleAt, cardOrigin, pointAt} from './geometry';
import {Check, DocGlyph} from './icons';
import {shipLen} from './motion';
import {T, easeInOut, ip, mix, pop, rng, useF} from './time';

const KIND_LABEL = ['Служебка', 'Задача', 'Счёт', 'Письмо'];

// ---------- documents ----------
type Doc = {i: number; kind: number; bx: number; by: number; ph: number; appear: number; fly: number};

const DOCS: Doc[] = (() => {
  const r = rng(7);
  const docs = Array.from({length: 48}, (_, i) => ({
    i,
    kind: i % 4,
    bx: 240 + r() * 1760,
    by: 880 + r() * 960,
    ph: r() * Math.PI * 2,
    appear: 4 + i * 7 + Math.floor(r() * 5),
    fly: 0,
  }));
  // The beam reaches documents nearest to the lighthouse first.
  const order = [...docs].sort((a, b) => Math.hypot(b.bx - LIGHT.x, b.by - LIGHT.y) - Math.hypot(a.bx - LIGHT.x, a.by - LIGHT.y)).reverse();
  order.forEach((d, rank) => (d.fly = T.beam + 160 + rank * 3));
  return docs;
})();

const FLY = 46;
export const unreadCount = (f: number) => {
  if (f < T.beam + 160) return Math.round(ip(f, [0, 420], [47, 340]));
  const left = DOCS.filter((d) => f < d.fly + FLY).length;
  return Math.round((340 * left) / DOCS.length);
};

const waveAmp = (f: number) => ip(f, [T.beam + 20, T.beam + 250], [46, 7], easeInOut);

const stormPos = (d: Doc, f: number) => {
  const amp = ip(f, [T.beam + 30, T.beam + 190], [1, 0.35]);
  return {
    x: d.bx + Math.sin(f * 0.03 + d.ph) * 30,
    y: d.by + Math.sin(f * 0.08 + d.ph * 1.7) * 26 * amp + Math.sin((d.bx * 0.004) + f * 0.06) * waveAmp(f) * 0.6,
    rot: Math.sin(f * 0.05 + d.ph) * 16 * amp,
  };
};

const DocCard: React.FC<{d: Doc; f: number}> = ({d, f}) => {
  if (f < d.appear || f > d.fly + FLY) return null;
  const color = STOPS[d.kind].color;
  const enter = pop(f, d.appear, 11);
  const s0 = stormPos(d, Math.min(f, d.fly));
  let {x, y, rot} = s0;
  y -= (1 - enter) * 260;
  let scale = 1;
  let opacity = Math.min(1, enter * 1.4);
  if (f > d.fly) {
    const t = easeInOut((f - d.fly) / FLY);
    const b = BUOYS[d.kind];
    const cx = (s0.x + b.x) / 2;
    const cy = Math.min(s0.y, b.y) - 320;
    x = (1 - t) * (1 - t) * s0.x + 2 * (1 - t) * t * cx + t * t * b.x;
    y = (1 - t) * (1 - t) * s0.y + 2 * (1 - t) * t * cy + t * t * b.y;
    rot = mix(s0.rot, d.ph * 40, t);
    scale = mix(1, 0.15, t);
    opacity = ip(t, [0.8, 1], [1, 0]);
  }
  return (
    <div
      style={{
        position: 'absolute',
        left: x - 80,
        top: y - 50,
        width: 160,
        height: 100,
        transform: `rotate(${rot}deg) scale(${scale})`,
        opacity,
        background: '#fff',
        borderRadius: 16,
        boxShadow: '0 14px 30px rgba(8,4,30,0.45)',
        borderLeft: `8px solid ${color}`,
        padding: '14px 14px',
        boxSizing: 'border-box',
        fontFamily: FONT,
      }}
    >
      <div style={{display: 'flex', alignItems: 'center', gap: 8}}>
        <DocGlyph kind={d.kind} color={color} size={26} />
        <span style={{fontSize: 21, fontWeight: 650, color: C.ink}}>{KIND_LABEL[d.kind]}</span>
      </div>
      <div style={{marginTop: 12, height: 7, width: '88%', background: '#E6E3F2', borderRadius: 4}} />
      <div style={{marginTop: 8, height: 7, width: '60%', background: '#E6E3F2', borderRadius: 4}} />
    </div>
  );
};

// ---------- sea ----------
const wavePath = (row: number, f: number, amp: number) => {
  const y0 = 260 + row * 150;
  let d = '';
  for (let x = -100; x <= WORLD.w + 100; x += 48) {
    const y = y0 + amp * Math.sin(x * 0.004 + f * 0.06 + row) + amp * 0.5 * Math.sin(x * 0.011 - f * 0.045 + row * 2.1);
    d += (d ? ' L ' : 'M ') + x.toFixed(1) + ' ' + y.toFixed(1);
  }
  return d;
};

const DEPTHS = (() => {
  const r = rng(42);
  return Array.from({length: 70}, () => ({x: r() * WORLD.w, y: r() * WORLD.h, v: Math.floor(4 + r() * 40)}));
})();

const Compass: React.FC<{x: number; y: number; r: number; color: string}> = ({x, y, r, color}) => (
  <g transform={`translate(${x} ${y})`} opacity={0.55}>
    <circle r={r} fill="none" stroke={color} strokeWidth={3} />
    <circle r={r * 0.82} fill="none" stroke={color} strokeWidth={1.5} strokeDasharray="4 8" />
    {[0, 45, 90, 135, 180, 225, 270, 315].map((a) => (
      <polygon
        key={a}
        points={`0,${-r * (a % 90 === 0 ? 1.15 : 0.7)} ${r * 0.08},0 0,${r * 0.1} ${-r * 0.08},0`}
        fill={a === 0 ? C.purple : color}
        transform={`rotate(${a})`}
      />
    ))}
    <text y={-r * 1.25} textAnchor="middle" fontFamily={FONT} fontWeight={700} fontSize={44} fill={C.purple}>
      С
    </text>
  </g>
);

const Sea: React.FC<{f: number; day: boolean}> = ({f, day}) => {
  const amp = waveAmp(f);
  const stroke = day ? 'rgba(114,58,232,0.22)' : 'rgba(150,130,255,0.32)';
  return (
    <svg width={WORLD.w} height={WORLD.h} style={{position: 'absolute', inset: 0}}>
      <defs>
        <linearGradient id={day ? 'gd' : 'gn'} x1="0" y1="0" x2="0" y2="1">
          <stop offset="0" stopColor={day ? C.sky1 : C.night} />
          <stop offset="1" stopColor={day ? C.sky2 : C.night2} />
        </linearGradient>
      </defs>
      <rect width={WORLD.w} height={WORLD.h} fill={`url(#${day ? 'gd' : 'gn'})`} />
      {day && (
        <g>
          {Array.from({length: 13}, (_, i) => (
            <line key={'v' + i} x1={i * 320} y1={0} x2={i * 320} y2={WORLD.h} stroke={C.line} strokeWidth={2} />
          ))}
          {Array.from({length: 8}, (_, i) => (
            <line key={'h' + i} x1={0} y1={i * 320} x2={WORLD.w} y2={i * 320} stroke={C.line} strokeWidth={2} />
          ))}
          {DEPTHS.map((p, i) => (
            <text key={i} x={p.x} y={p.y} fontFamily={FONT} fontSize={26} fill="rgba(27,19,64,0.28)" fontStyle="italic">
              {p.v}
            </text>
          ))}
          <Compass x={430} y={430} r={170} color={C.ink} />
          <g transform="translate(150 1890)">
            <rect width={980} height={170} rx={12} fill="rgba(255,255,255,0.55)" stroke={C.ink} strokeOpacity={0.35} strokeWidth={3} />
            <rect x={14} y={14} width={952} height={142} rx={8} fill="none" stroke={C.ink} strokeOpacity={0.2} strokeWidth={2} />
            <text x={40} y={78} fontFamily={FONT} fontWeight={800} fontSize={46} fill={C.purple} letterSpacing={6}>
              ЛОЦИЯ
            </text>
            <text x={40} y={124} fontFamily={FONT} fontSize={30} fill={C.ink} opacity={0.75}>
              Карта фарватеров рутины · лист 1 · масштаб 1 : агент
            </text>
          </g>
        </g>
      )}
      {Array.from({length: 13}, (_, i) => (
        <path key={i} d={wavePath(i, f, amp)} fill="none" stroke={stroke} strokeWidth={day ? 2.5 : 4} strokeDasharray={day ? '14 10' : undefined} />
      ))}
    </svg>
  );
};

// ---------- lighthouse ----------
const Lighthouse: React.FC<{f: number}> = ({f}) => {
  const {x, y} = LIGHT;
  const a = ip(f, [T.beam + 20, T.beam + 130], [208, 159], easeInOut) + ip(f, [T.beam + 130, T.route], [0, 14], easeInOut);
  const beamOn = ip(f, [T.beam + 5, T.beam + 30], [0, 1]) * ip(f, [T.beam + 260, T.route], [1, 0.35]);
  const spread = Math.tan((8 * Math.PI) / 180) * 4400;
  const glow = 0.6 + 0.4 * Math.sin(f * 0.3);
  return (
    <svg width={WORLD.w} height={WORLD.h} style={{position: 'absolute', inset: 0, overflow: 'visible'}}>
      <defs>
        <linearGradient id="beam" gradientUnits="userSpaceOnUse" x1={x} y1={y} x2={x + 4400} y2={y}>
          <stop offset="0" stopColor="#FFF6D6" stopOpacity={0.85} />
          <stop offset="0.6" stopColor="#FFF6D6" stopOpacity={0.18} />
          <stop offset="1" stopColor="#FFF6D6" stopOpacity={0} />
        </linearGradient>
        <radialGradient id="lamp">
          <stop offset="0" stopColor="#FFF6D6" stopOpacity={1} />
          <stop offset="1" stopColor="#FFF6D6" stopOpacity={0} />
        </radialGradient>
      </defs>
      <g opacity={beamOn} transform={`rotate(${a} ${x} ${y})`} style={{mixBlendMode: 'screen'}}>
        <polygon points={`${x},${y - 10} ${x + 4400},${y - spread} ${x + 4400},${y + spread} ${x},${y + 10}`} fill="url(#beam)" />
      </g>
      <ellipse cx={x} cy={y + 320} rx={210} ry={50} fill={C.purpleDeep} opacity={0.85} />
      <polygon points={`${x - 62},${y + 320} ${x - 38},${y + 40} ${x + 38},${y + 40} ${x + 62},${y + 320}`} fill="#fff" />
      {[0, 1, 2].map((i) => {
        const y1 = y + 80 + i * 80;
        const y2 = y1 + 40;
        const w1 = 38 + ((y1 - y - 40) / 280) * 24;
        const w2 = 38 + ((y2 - y - 40) / 280) * 24;
        return <polygon key={i} points={`${x - w1},${y1} ${x + w1},${y1} ${x + w2},${y2} ${x - w2},${y2}`} fill={C.purple} />;
      })}
      <rect x={x - 46} y={y - 6} width={92} height={50} rx={8} fill={C.purpleDeep} />
      <circle cx={x} cy={y + 18} r={130 * (beamOn > 0 ? glow : 0.3)} fill="url(#lamp)" opacity={0.9} />
      <circle cx={x} cy={y + 18} r={20} fill="#FFF6D6" />
      <polygon points={`${x - 54},${y - 6} ${x},${y - 60} ${x + 54},${y - 6}`} fill={C.purple} />
    </svg>
  );
};

// ---------- route, buoys, ship ----------
const Route: React.FC<{f: number}> = ({f}) => {
  const draw = ip(f, [T.beam + 250, T.route - 20], [0, 1], easeInOut);
  const done = shipLen(f);
  const harborIn = pop(f, T.route - 40);
  return (
    <svg width={WORLD.w} height={WORLD.h} style={{position: 'absolute', inset: 0, overflow: 'visible'}}>
      <defs>
        <mask id="draw" maskUnits="userSpaceOnUse" x={0} y={0} width={WORLD.w} height={WORLD.h}>
          <path d={ROUTE} fill="none" stroke="#fff" strokeWidth={40} strokeDasharray={`${ROUTE_LEN} ${ROUTE_LEN}`} strokeDashoffset={ROUTE_LEN * (1 - draw)} />
        </mask>
      </defs>
      <g mask="url(#draw)">
        <path d={ROUTE} fill="none" stroke="rgba(114,58,232,0.18)" strokeWidth={34} strokeLinecap="round" />
        <path d={ROUTE} fill="none" stroke={C.purple} strokeWidth={7} strokeDasharray="24 18" strokeLinecap="round" />
      </g>
      {done > 0 && (
        <path d={ROUTE} fill="none" stroke={C.purple} strokeWidth={14} strokeLinecap="round" strokeDasharray={`${done} ${ROUTE_LEN * 2}`} />
      )}
      <circle cx={START.x} cy={START.y} r={16 * draw} fill={C.purple} />
      <g transform={`translate(${HARBOR.x} ${HARBOR.y}) scale(${harborIn})`}>
        <circle r={44} fill="#fff" stroke={C.purple} strokeWidth={8} />
        <circle r={18} fill={C.purple} />
        <rect x={-120} y={-118} width={240} height={56} rx={28} fill={C.purple} />
        <text y={-80} textAnchor="middle" fontFamily={FONT} fontWeight={700} fontSize={32} fill="#fff">
          Готово
        </text>
      </g>
    </svg>
  );
};

const Buoys: React.FC<{f: number}> = ({f}) => (
  <>
    {BUOYS.map((b, k) => {
      const s = pop(f, T.beam + 190 + k * 22, 10);
      if (s <= 0.001) return null;
      let pulse = 0;
      for (const d of DOCS) if (d.kind === k) pulse += Math.max(0, 1 - Math.abs(f - (d.fly + FLY)) / 8);
      const passed = f > T.route + k * T.stop + 160;
      const fill = passed ? C.teal : STOPS[k].color;
      return (
        <div key={k} style={{position: 'absolute', left: b.x, top: b.y, transform: `scale(${s})`}}>
          <div
            style={{
              position: 'absolute',
              left: -60,
              top: -60,
              width: 120,
              height: 120,
              borderRadius: 60,
              background: fill,
              opacity: 0.18 + Math.min(0.4, pulse * 0.2),
              transform: `scale(${1 + Math.min(1, pulse * 0.4) + 0.08 * Math.sin(f * 0.12 + k)})`,
            }}
          />
          <div
            style={{
              position: 'absolute',
              left: -34,
              top: -34,
              width: 68,
              height: 68,
              borderRadius: 34,
              background: fill,
              border: '7px solid #fff',
              boxSizing: 'border-box',
              display: 'flex',
              alignItems: 'center',
              justifyContent: 'center',
              color: '#fff',
              fontFamily: FONT,
              fontWeight: 800,
              fontSize: 30,
              boxShadow: '0 8px 22px rgba(27,19,64,0.35)',
            }}
          >
            {passed ? <Check size={32} color="#fff" stroke={4} /> : k + 1}
          </div>
          <div
            style={{
              position: 'absolute',
              top: 52,
              left: 0,
              transform: 'translateX(-50%)',
              whiteSpace: 'nowrap',
              background: '#fff',
              color: C.ink,
              fontFamily: FONT,
              fontWeight: 650,
              fontSize: 34,
              padding: '8px 22px',
              borderRadius: 30,
              boxShadow: '0 8px 22px rgba(27,19,64,0.2)',
            }}
          >
            {STOPS[k].title}
          </div>
        </div>
      );
    })}
  </>
);

const Ship: React.FC<{f: number}> = ({f}) => {
  const len = shipLen(f);
  const p = pointAt(len);
  const sailing = f >= T.route;
  const storm = ip(f, [T.beam, T.beam + 200], [1, 0.15]);
  const bob = Math.sin(f * 0.09) * 18 * storm + Math.sin(f * 0.05) * 4;
  const heading = sailing ? angleAt(len + 1) : 0;
  const rock = Math.sin(f * 0.07) * 16 * storm + Math.sin(f * 0.11) * 3;
  const flip = Math.abs(heading) > 90;
  return (
    <div style={{position: 'absolute', left: p.x, top: p.y + bob}}>
      <div style={{position: 'absolute', transform: `rotate(${(sailing ? heading * 0.35 : 0) + rock}deg) scaleX(${flip ? -1 : 1})`, left: -70, top: -96}}>
        <svg width={140} height={110} viewBox="0 0 140 110" style={{overflow: 'visible'}}>
          <path d="M12 74 L128 74 L108 102 L30 102 Z" fill={C.purple} />
          <path d="M66 8 L66 70 L24 70 Z" fill="#fff" stroke={C.purple} strokeWidth={4} strokeLinejoin="round" />
          <path d="M72 18 L72 70 L112 70 Z" fill="#fff" stroke={C.purple} strokeWidth={4} strokeLinejoin="round" />
          <path d="M69 4 L69 74" stroke={C.ink} strokeWidth={5} />
          <path d="M69 4 L92 10 L69 16 Z" fill={C.orange} />
        </svg>
      </div>
      <div
        style={{
          position: 'absolute',
          top: -170,
          left: 0,
          transform: 'translateX(-50%)',
          background: C.orange,
          color: '#fff',
          fontFamily: FONT,
          fontWeight: 750,
          fontSize: 30,
          padding: '6px 20px',
          borderRadius: 24,
          whiteSpace: 'nowrap',
        }}
      >
        Вы
      </div>
    </div>
  );
};

export const World: React.FC<{props: import('./data').FilmProps}> = ({props}) => {
  const f = useF();
  const r = ip(f, [T.beam + 110, T.beam + 290], [0, 4800], (t) => t * t);
  const cardsIn = ip(f, [T.route - 60, T.route - 10], [0, 1]);
  const docs = useMemo(() => DOCS, []);
  return (
    <div style={{position: 'absolute', width: WORLD.w, height: WORLD.h}}>
      <Sea f={f} day={false} />
      <div style={{position: 'absolute', inset: 0, clipPath: `circle(${r}px at ${LIGHT.x}px ${LIGHT.y + 18}px)`}}>
        <Sea f={f} day />
      </div>
      <Lighthouse f={f} />
      <Route f={f} />
      <Buoys f={f} />
      <Ship f={f} />
      {docs.map((d) => (
        <DocCard key={d.i} d={d} f={f} />
      ))}
      {BUOYS.map((_, k) => {
        const o = cardOrigin(k);
        return (
          <div
            key={k}
            style={{
              position: 'absolute',
              left: o.x,
              top: o.y,
              width: CARD.w,
              height: CARD.h,
              transformOrigin: '0 0',
              transform: `scale(${CARD.scale})`,
              opacity: cardsIn,
            }}
          >
            <StopCard k={k} f={f} props={props} />
          </div>
        );
      })}
    </div>
  );
};

export {STOP_LENS};
