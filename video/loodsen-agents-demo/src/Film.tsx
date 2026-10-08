import React from 'react';
import {AbsoluteFill} from 'remotion';
import {C, FONT} from './brand';
import type {FilmProps} from './data';
import {STOPS} from './geometry';
import {LogoMark} from './icons';
import {camera, cardTime} from './motion';
import {H, T, W, easeOut, ip, pop, rng, useF} from './time';
import {World, unreadCount} from './world';

const RAIN = (() => {
  const r = rng(3);
  return Array.from({length: 140}, () => ({x: r() * W * 1.3, y: r() * H, l: 40 + r() * 70, v: 38 + r() * 30}));
})();

const Storm: React.FC<{f: number}> = ({f}) => {
  const o = ip(f, [T.beam + 20, T.beam + 160], [1, 0]);
  if (o <= 0) return null;
  const flash = Math.max(0, 1 - Math.abs(f - 150) / 4) + Math.max(0, 1 - Math.abs(f - 156) / 3) * 0.6 + Math.max(0, 1 - Math.abs(f - 330) / 4);
  return (
    <AbsoluteFill style={{opacity: o}}>
      <svg width={W} height={H}>
        {RAIN.map((d, i) => {
          const y = ((d.y + f * d.v) % (H + 200)) - 100;
          const x = d.x - y * 0.3 - 200;
          return <line key={i} x1={x} y1={y} x2={x - d.l * 0.3} y2={y + d.l} stroke="rgba(200,190,255,0.35)" strokeWidth={2.5} />;
        })}
      </svg>
      <AbsoluteFill style={{background: '#EDE7FF', opacity: Math.min(0.7, flash * 0.7)}} />
    </AbsoluteFill>
  );
};

const Counter: React.FC<{f: number}> = ({f}) => {
  const n = unreadCount(f);
  const s = pop(f, 20, 12);
  const o = ip(f, [T.route - 60, T.route - 20], [1, 0]);
  if (o <= 0) return null;
  const zero = n === 0;
  return (
    <div
      style={{
        position: 'absolute',
        right: 70,
        top: 60,
        transform: `scale(${s})`,
        opacity: o,
        display: 'flex',
        alignItems: 'center',
        gap: 18,
        background: zero ? C.teal : C.red,
        color: '#fff',
        fontFamily: FONT,
        padding: '16px 30px',
        borderRadius: 24,
        boxShadow: '0 12px 30px rgba(0,0,0,0.35)',
      }}
    >
      <div style={{fontSize: 26, fontWeight: 600, lineHeight: 1.1}}>
        {zero ? 'Входящие' : 'Непрочитанных'}
        <br />
        <span style={{opacity: 0.8, fontSize: 20}}>{zero ? 'разобраны' : 'и растёт'}</span>
      </div>
      <div style={{fontSize: 68, fontWeight: 850, fontVariantNumeric: 'tabular-nums', minWidth: 130, textAlign: 'right'}}>{n}</div>
    </div>
  );
};

type Cap = {from: number; to: number; kicker: string; title: string; dark?: boolean};
const CAPTIONS: Cap[] = [
  {from: 30, to: 430, kicker: 'Обычный вторник', title: 'Письма, служебки, счета, задачи — всё сразу', dark: true},
  {from: T.beam + 40, to: T.route - 30, kicker: 'Появляется агент', title: 'Он видит весь поток и прокладывает маршрут'},
  ...STOPS.map((s, k) => ({
    from: T.route + k * T.stop + 10,
    to: T.route + (k + 1) * T.stop - 8,
    kicker: `Шаг ${k + 1} из 4`,
    title: s.title,
  })),
];

const Caption: React.FC<{f: number}> = ({f}) => {
  const c = CAPTIONS.find((x) => f >= x.from && f < x.to);
  if (!c) return null;
  const i = ip(f, [c.from, c.from + 18], [0, 1], easeOut);
  const o = ip(f, [c.to - 14, c.to], [1, 0]);
  return (
    <div
      style={{
        position: 'absolute',
        left: 70,
        bottom: 64,
        display: 'flex',
        alignItems: 'center',
        gap: 22,
        opacity: Math.min(i, o),
        transform: `translateY(${(1 - i) * 30}px)`,
        fontFamily: FONT,
      }}
    >
      <div style={{width: 76, height: 76, background: C.purple, borderRadius: 6, display: 'flex', alignItems: 'center', justifyContent: 'center'}}>
        <LogoMark size={50} />
      </div>
      <div
        style={{
          background: c.dark ? 'rgba(11,8,32,0.55)' : 'rgba(255,255,255,0.85)',
          color: c.dark ? '#fff' : C.ink,
          padding: '12px 26px',
          borderRadius: 18,
          backdropFilter: 'blur(10px)',
        }}
      >
        <div style={{fontSize: 22, fontWeight: 600, color: c.dark ? C.purpleSoft : C.purple, letterSpacing: 1, textTransform: 'uppercase'}}>{c.kicker}</div>
        <div style={{fontSize: 38, fontWeight: 700}}>{c.title}</div>
      </div>
    </div>
  );
};

// Stop-card "zoom HUD": shows how deep the camera is.
const ZoomHud: React.FC<{f: number}> = ({f}) => {
  if (f < T.route || f >= T.personal) return null;
  const k = Math.floor((f - T.route) / T.stop);
  const t = cardTime(f, k);
  const o = Math.min(ip(t, [10, 30], [0, 1]), ip(t, [115, 135], [1, 0]));
  if (o <= 0) return null;
  const z = camera(f).s / 0.5;
  return (
    <div style={{position: 'absolute', right: 70, top: 60, opacity: o, fontFamily: FONT, color: C.ink, background: 'rgba(255,255,255,0.85)', borderRadius: 16, padding: '10px 20px', fontSize: 24, fontWeight: 600}}>
      масштаб ×{z.toFixed(1)}
    </div>
  );
};

const Personal: React.FC<{f: number; props: FilmProps}> = ({f, props}) => {
  const start = T.personal + 70;
  if (f < start) return null;
  const s = pop(f, start, 15);
  const rollEnd = start + 60;
  const rolling = f < rollEnd;
  const names = props.names.length ? props.names : [props.name];
  const idx = rolling ? Math.floor((f - start) / 3) % names.length : -1;
  const shown = rolling ? names[idx] : props.name;
  const jitter = rolling ? ((f - start) % 3) * 14 - 14 : 0;
  const n1 = Math.round(ip(f, [rollEnd + 5, rollEnd + 50], [0, props.hoursSaved], easeOut));
  const n2 = Math.round(ip(f, [rollEnd + 15, rollEnd + 60], [0, props.docs], easeOut));
  const tiles: [string, string][] = [
    [`${n1} ч`, 'в месяц вернули вам'],
    [`${n2}`, 'документов сделал агент'],
    ['4', 'агента в команде'],
  ];
  return (
    <div
      style={{
        position: 'absolute',
        left: 90,
        top: 150,
        width: 900,
        padding: '48px 56px',
        borderRadius: 36,
        background: 'rgba(255,255,255,0.86)',
        backdropFilter: 'blur(16px)',
        boxShadow: '0 30px 90px rgba(27,19,64,0.3)',
        fontFamily: FONT,
        color: C.ink,
        transform: `translateX(${(1 - s) * -200}px)`,
        opacity: Math.min(1, s * 1.5),
      }}
    >
      <div style={{fontSize: 30, color: C.muted, fontWeight: 600}}>Курс проложен персонально для</div>
      <div style={{height: 150, overflow: 'hidden'}}>
        <div style={{fontSize: 136, fontWeight: 850, color: C.purple, transform: `translateY(${jitter}px)`, filter: rolling ? 'blur(2px)' : 'none'}}>{shown}</div>
      </div>
      <div style={{fontSize: 36, fontWeight: 600, opacity: rolling ? 0.3 : 1}}>{props.dept}</div>
      <div style={{display: 'flex', gap: 22, marginTop: 40}}>
        {tiles.map(([a, b], i) => (
          <div key={b} style={{flex: 1, background: '#F2EFFB', borderRadius: 22, padding: '22px 24px', opacity: ip(f, [rollEnd + i * 8, rollEnd + 15 + i * 8], [0, 1])}}>
            <div style={{fontSize: 56, fontWeight: 850, color: C.ink}}>{a}</div>
            <div style={{fontSize: 22, color: C.muted, marginTop: 4}}>{b}</div>
          </div>
        ))}
      </div>
      <div
        style={{
          marginTop: 34,
          display: 'inline-block',
          background: C.purple,
          color: '#fff',
          borderRadius: 30,
          padding: '12px 26px',
          fontSize: 24,
          fontWeight: 650,
          opacity: ip(f, [rollEnd + 70, rollEnd + 85], [0, 1]),
        }}
      >
        Версия {props.version} из {props.versions} · собрана из данных, а не вручную
      </div>
    </div>
  );
};

export const Film: React.FC<{props: FilmProps}> = ({props}) => {
  const f = useF();
  const cam = camera(f);
  return (
    <AbsoluteFill style={{background: C.night, overflow: 'hidden'}}>
      <div
        style={{
          position: 'absolute',
          left: 0,
          top: 0,
          transformOrigin: '0 0',
          transform: `translate(${W / 2}px, ${H / 2}px) rotate(${cam.rot}deg) scale(${cam.s}) translate(${-cam.x}px, ${-cam.y}px)`,
        }}
      >
        <World props={props} />
      </div>
      <Storm f={f} />
      <Counter f={f} />
      <ZoomHud f={f} />
      <Caption f={f} />
      <Personal f={f} props={props} />
    </AbsoluteFill>
  );
};
