import {CARD_ZOOM, STOP_LENS, cardCenter, pointAt} from './geometry';
import {T, easeInOut, ip, mix} from './time';

export type Cam = {x: number; y: number; s: number; rot: number};

const OVERVIEW: Cam = {x: 1920, y: 1080, s: 0.5, rot: 0};
const FOLLOW_S = 1.1;

// Ship position along the route (path length) at frame f.
export const shipLen = (f: number) => {
  if (f < T.route) return 0;
  const k = Math.floor((f - T.route) / T.stop);
  if (k < 4) {
    const start = T.route + k * T.stop;
    return ip(f, [start, start + 70], [STOP_LENS[k], STOP_LENS[k + 1]], easeInOut);
  }
  return ip(f, [T.personal, T.personal + 70], [STOP_LENS[4], STOP_LENS[5]], easeInOut);
};

// Zoom between two views so the motion feels like flying straight in:
// scale is interpolated logarithmically and the centre tracks 1/scale.
export const zoomBetween = (a: Cam, b: Cam, t: number): Cam => {
  const s = Math.exp(mix(Math.log(a.s), Math.log(b.s), t));
  const w = Math.abs(a.s - b.s) < 1e-6 ? t : (1 / s - 1 / a.s) / (1 / b.s - 1 / a.s);
  return {x: mix(a.x, b.x, w), y: mix(a.y, b.y, w), s, rot: mix(a.rot, b.rot, t)};
};

const follow = (f: number): Cam => {
  const p = pointAt(shipLen(f));
  return {x: p.x, y: p.y - 60, s: FOLLOW_S, rot: 0};
};

const storm = (f: number): Cam => ({
  x: 1120 + Math.sin(f * 0.021) * 26,
  y: 1330 + Math.cos(f * 0.017) * 18,
  s: 1 + f * 0.00022,
  rot: Math.sin(f * 0.045) * 1.4,
});

export const camera = (f: number): Cam => {
  if (f < T.beam) return storm(f);
  if (f < T.beam + 150) return zoomBetween(storm(f), OVERVIEW, ip(f, [T.beam + 10, T.beam + 150], [0, 1], easeInOut));
  if (f < T.route) return {...OVERVIEW, s: ip(f, [T.beam + 150, T.route], [0.5, 0.52])};

  if (f < T.personal) {
    const k = Math.floor((f - T.route) / T.stop);
    const t0 = T.route + k * T.stop;
    const card: Cam = {...cardCenter(k), s: CARD_ZOOM, rot: 0};
    const atBuoy = follow(t0 + 70);
    if (f < t0 + 70) {
      if (k === 0) {
        return zoomBetween({...OVERVIEW, s: 0.52}, follow(f), ip(f, [t0, t0 + 50], [0, 1], easeInOut));
      }
      return follow(f);
    }
    if (f < t0 + 105) return zoomBetween(atBuoy, card, ip(f, [t0 + 70, t0 + 105], [0, 1], easeInOut));
    if (f < t0 + 190) return {...card, s: card.s * ip(f, [t0 + 105, t0 + 190], [1, 1.035])};
    const held = {...card, s: card.s * 1.035};
    return zoomBetween(held, follow(f), ip(f, [t0 + 190, T.route + (k + 1) * T.stop], [0, 1], easeInOut));
  }
  if (f < T.personal + 80) return zoomBetween(follow(f), OVERVIEW, ip(f, [T.personal, T.personal + 80], [0, 1], easeInOut));
  return {...OVERVIEW, s: ip(f, [T.personal + 80, T.reveal], [0.5, 0.53])};
};

// Local timeline of the detail card for stop k (0 when the zoom-in starts).
export const cardTime = (f: number, k: number) => f - (T.route + k * T.stop + 70);
