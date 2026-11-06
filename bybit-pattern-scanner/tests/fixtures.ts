/** Deterministic synthetic market fixtures. Test-only — never used at runtime. */

import type { Candle } from '@/lib/bybit/types';

const STEP_MS = 60 * 60_000; // 1h candles

/**
 * Series are anchored so the LAST candle is the most recently completed hour.
 * That keeps the verification layer's freshness path on the HEALTHY branch,
 * which is what the production scanner sees, while the price shape itself stays
 * fully deterministic.
 */
function anchorTimes(candles: Omit<Candle, 'time'>[]): Candle[] {
  const nowHour = Math.floor(Date.now() / STEP_MS) * STEP_MS;
  const start = nowHour - (candles.length - 1) * STEP_MS;
  return candles.map((c, i) => ({ ...c, time: start + i * STEP_MS }));
}

/** Standalone candle for unit tests that only care about OHLC relationships. */
export function makeCandle(
  index: number,
  open: number,
  high: number,
  low: number,
  close: number,
  volume = 1000,
): Candle {
  const nowHour = Math.floor(Date.now() / STEP_MS) * STEP_MS;
  return {
    time: nowHour - (500 - index) * STEP_MS,
    open,
    high,
    low,
    close,
    volume,
    turnover: volume * close,
  };
}

/** Deterministic pseudo-random generator so fixtures never flake. */
export function seededRandom(seed: number): () => number {
  let s = seed >>> 0;
  return () => {
    s = (s * 1664525 + 1013904223) >>> 0;
    return s / 0xffffffff;
  };
}

type Bar = Omit<Candle, 'time'>;

function bar(open: number, high: number, low: number, close: number, volume: number): Bar {
  return { open, high, low, close, volume, turnover: volume * close };
}

/**
 * A realistic trending series: net directional drift delivered through impulse
 * legs and genuine counter-trend pullbacks, so the series has actual swing
 * structure. A monotonic ramp has no swing highs by definition and would be a
 * dishonest fixture for a pattern engine.
 */
export function uptrendSeries(length = 220, start = 100, driftPct = 0.4, seed = 42): Candle[] {
  const rand = seededRandom(seed);
  const bars: Bar[] = [];
  let price = start;
  const direction = driftPct >= 0 ? 1 : -1;
  const magnitude = Math.abs(driftPct);

  let i = 0;
  while (i < length) {
    // Impulse leg: 6–12 bars pushing in the trend direction.
    const impulseBars = 6 + Math.floor(rand() * 7);
    for (let k = 0; k < impulseBars && i < length; k++, i++) {
      const open = price;
      const move = price * (magnitude / 100) * (0.8 + rand() * 1.6) * direction;
      const close = open + move;
      const high = Math.max(open, close) * (1 + rand() * 0.005);
      const low = Math.min(open, close) * (1 - rand() * 0.005);
      bars.push(bar(open, high, low, close, 900 + rand() * 600));
      price = close;
    }

    // Pullback: 3–6 bars retracing 30–60% of the leg. This is what creates the
    // swing highs and lows every structural detector depends on.
    const pullbackBars = 3 + Math.floor(rand() * 4);
    const legSize = price * (magnitude / 100) * impulseBars;
    const retrace = legSize * (0.3 + rand() * 0.3);
    for (let k = 0; k < pullbackBars && i < length; k++, i++) {
      const open = price;
      const close = open - (retrace / pullbackBars) * direction;
      const high = Math.max(open, close) * (1 + rand() * 0.004);
      const low = Math.min(open, close) * (1 - rand() * 0.004);
      bars.push(bar(open, high, low, close, 600 + rand() * 400));
      price = close;
    }
  }

  return anchorTimes(bars.slice(0, length));
}

export function downtrendSeries(length = 220, start = 200, seed = 7): Candle[] {
  return uptrendSeries(length, start, -0.4, seed);
}

/** A tight sideways range — should produce very few directional signals. */
export function rangeSeries(length = 220, center = 100, widthPct = 2, seed = 11): Candle[] {
  const rand = seededRandom(seed);
  const bars: Bar[] = [];
  for (let i = 0; i < length; i++) {
    const open = center + (Math.sin(i / 7) * (center * widthPct)) / 100;
    const close = center + (Math.sin((i + 1) / 7) * (center * widthPct)) / 100;
    const high = Math.max(open, close) * (1 + rand() * 0.002);
    const low = Math.min(open, close) * (1 - rand() * 0.002);
    bars.push(bar(open, high, low, close, 500 + rand() * 100));
  }
  return anchorTimes(bars);
}

/** Pure noise — the detectors must not manufacture patterns from this. */
export function noiseSeries(length = 220, start = 100, seed = 99): Candle[] {
  const rand = seededRandom(seed);
  const bars: Bar[] = [];
  let price = start;
  for (let i = 0; i < length; i++) {
    const open = price;
    const close = price * (1 + (rand() - 0.5) * 0.02);
    const high = Math.max(open, close) * (1 + rand() * 0.006);
    const low = Math.min(open, close) * (1 - rand() * 0.006);
    bars.push(bar(open, high, low, close, 400 + rand() * 800));
    price = close;
  }
  return anchorTimes(bars);
}

/**
 * A canonical double bottom: two comparable lows, a middle bounce to the
 * neckline, and a final close through it.
 */
export function doubleBottomSeries(): Candle[] {
  const bars: Bar[] = [];
  const push = (o: number, h: number, l: number, c: number, v = 1000) => bars.push(bar(o, h, l, c, v));

  // Approach down from 120 to ~100, with small wiggles so pivots can form.
  for (let i = 0; i < 100; i++) {
    const p = 120 - i * 0.2;
    const wiggle = Math.sin(i / 3) * 0.35;
    push(p + wiggle, p + wiggle + 0.4, p + wiggle - 0.4, p + wiggle - 0.2);
  }
  // First bottom near 99.
  for (let i = 0; i < 8; i++) push(100 - i * 0.15, 100.2 - i * 0.15, 99 - i * 0.05, 99.6 - i * 0.12);
  // Bounce up to the neckline near 104.5.
  for (let i = 0; i < 12; i++) push(98.8 + i * 0.45, 99.2 + i * 0.45, 98.6 + i * 0.45, 99.1 + i * 0.45);
  // Retrace back to the second bottom near 99.
  for (let i = 0; i < 12; i++) push(104.5 - i * 0.46, 104.8 - i * 0.46, 104.2 - i * 0.46, 104.3 - i * 0.46);
  // Rally through the neckline on expanding volume.
  for (let i = 0; i < 16; i++) push(99 + i * 0.62, 99.5 + i * 0.62, 98.8 + i * 0.62, 99.4 + i * 0.62, 1500 + i * 220);

  return anchorTimes(bars);
}
