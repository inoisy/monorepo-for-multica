import {createContext, useContext} from 'react';
import {Easing, interpolate, spring, useCurrentFrame} from 'remotion';

export const FPS = 30;
export const W = 1920;
export const H = 1080;

// Scene boundaries, in frames.
export const T = {
  storm: 0,
  beam: 450,
  route: 900,
  stop: 225, // frames per route stop (4 stops)
  personal: 1800,
  reveal: 2250,
  outro: 2520,
  end: 2700,
};

// The film can be replayed at another speed inside the "editor" preview,
// so every component reads its frame from this context, not useCurrentFrame.
export const FrameContext = createContext<number | null>(null);
export const useF = () => {
  const real = useCurrentFrame();
  const override = useContext(FrameContext);
  return override ?? real;
};

export const easeInOut = Easing.bezier(0.65, 0, 0.35, 1);
export const easeOut = Easing.bezier(0.16, 1, 0.3, 1);

export const ip = (
  f: number,
  input: number[],
  output: number[],
  easing: (t: number) => number = (t) => t,
) => interpolate(f, input, output, {extrapolateLeft: 'clamp', extrapolateRight: 'clamp', easing});

export const pop = (f: number, start: number, damping = 14) =>
  spring({frame: f - start, fps: FPS, config: {damping, mass: 0.8, stiffness: 140}});

export const mix = (a: number, b: number, t: number) => a + (b - a) * t;

// Deterministic PRNG so every render of a frame is identical.
export const rng = (seed: number) => () => {
  seed |= 0;
  seed = (seed + 0x6d2b79f5) | 0;
  let t = Math.imul(seed ^ (seed >>> 15), 1 | seed);
  t = (t + Math.imul(t ^ (t >>> 7), 61 | t)) ^ t;
  return ((t ^ (t >>> 14)) >>> 0) / 4294967296;
};
