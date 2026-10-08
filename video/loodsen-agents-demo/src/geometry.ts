import {getLength, getPointAtLength, getTangentAtLength} from '@remotion/paths';

// World ("nautical chart") coordinates. The camera moves over a 3840x2160 map.
export const WORLD = {w: 3840, h: 2160};

type P = {x: number; y: number};

export const START: P = {x: 640, y: 1640};
export const BUOYS: P[] = [
  {x: 1240, y: 1180},
  {x: 1960, y: 1580},
  {x: 2640, y: 1080},
  {x: 3160, y: 1500},
];
export const HARBOR: P = {x: 3420, y: 760};
export const LIGHT: P = {x: 3600, y: 380};

export const STOPS = [
  {title: 'Служебная записка', color: '#723AE8'},
  {title: 'Задача в Сфере', color: '#22B8A6'},
  {title: 'Отчёт', color: '#FF7A3D'},
  {title: 'Сообщение в LooC', color: '#3D7BFF'},
];

const pts = [START, ...BUOYS, HARBOR];

// Catmull-Rom spline through the stops, as cubic bezier segments.
const seg = (i: number) => {
  const p0 = pts[Math.max(0, i - 1)];
  const p1 = pts[i];
  const p2 = pts[i + 1];
  const p3 = pts[Math.min(pts.length - 1, i + 2)];
  const k = 1 / 6;
  const c1 = {x: p1.x + (p2.x - p0.x) * k, y: p1.y + (p2.y - p0.y) * k};
  const c2 = {x: p2.x - (p3.x - p1.x) * k, y: p2.y - (p3.y - p1.y) * k};
  return `C ${c1.x} ${c1.y} ${c2.x} ${c2.y} ${p2.x} ${p2.y}`;
};

const segs = pts.slice(0, -1).map((_, i) => seg(i));
export const ROUTE = `M ${START.x} ${START.y} ` + segs.join(' ');
export const ROUTE_LEN = getLength(ROUTE);

// Path length at each stop: start, 4 buoys, harbor.
export const STOP_LENS = pts.map((_, i) =>
  i === 0 ? 0 : getLength(`M ${START.x} ${START.y} ` + segs.slice(0, i).join(' ')),
);

export const pointAt = (len: number): P => getPointAtLength(ROUTE, Math.max(0, Math.min(ROUTE_LEN, len))) ?? START;
export const angleAt = (len: number) => {
  const t = getTangentAtLength(ROUTE, Math.max(0.1, Math.min(ROUTE_LEN - 0.1, len)));
  return t ? (Math.atan2(t.y, t.x) * 180) / Math.PI : 0;
};

// Detail cards live in the world at a tiny scale next to each buoy; the camera
// zooms into them, so "inside the buoy" is a real continuous zoom.
export const CARD = {w: 1100, h: 640, scale: 0.14};
export const cardOrigin = (k: number): P => {
  const b = BUOYS[k];
  return {x: b.x + 70, y: b.y - 60 - CARD.h * CARD.scale};
};
export const cardCenter = (k: number): P => {
  const o = cardOrigin(k);
  return {x: o.x + (CARD.w * CARD.scale) / 2, y: o.y + (CARD.h * CARD.scale) / 2};
};
export const CARD_ZOOM = 1.25 / CARD.scale;
