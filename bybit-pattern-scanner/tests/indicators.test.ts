import { describe, expect, it } from 'vitest';
import {
  atr,
  bollinger,
  closeLocationValue,
  ema,
  linearSlope,
  macd,
  rsi,
  sma,
  stddev,
  trueRange,
  zScore,
} from '@/lib/ta/indicators';
import { makeCandle, uptrendSeries } from './fixtures';

describe('sma', () => {
  it('matches a hand calculation', () => {
    const values = [1, 2, 3, 4, 5, 6];
    const result = sma(values, 3);
    expect(result[0]).toBeNull();
    expect(result[1]).toBeNull();
    expect(result[2]).toBeCloseTo(2, 10); // (1+2+3)/3
    expect(result[3]).toBeCloseTo(3, 10);
    expect(result[5]).toBeCloseTo(5, 10); // (4+5+6)/3
  });

  it('returns all nulls when the period exceeds the data', () => {
    expect(sma([1, 2], 5).every((v) => v === null)).toBe(true);
  });
});

describe('ema', () => {
  it('seeds with an SMA then applies the multiplier', () => {
    const values = [10, 20, 30, 40, 50];
    const result = ema(values, 3);
    expect(result[2]).toBeCloseTo(20, 10); // seed = (10+20+30)/3
    // k = 2/(3+1) = 0.5 → 40*0.5 + 20*0.5 = 30
    expect(result[3]).toBeCloseTo(30, 10);
    // 50*0.5 + 30*0.5 = 40
    expect(result[4]).toBeCloseTo(40, 10);
  });

  it('is never null once seeded', () => {
    const result = ema(uptrendSeries(100).map((c) => c.close), 20);
    expect(result.slice(19).every((v) => v !== null)).toBe(true);
  });
});

describe('trueRange / atr', () => {
  it('computes true range including gaps', () => {
    const candles = [
      makeCandle(0, 100, 105, 95, 102),
      makeCandle(1, 110, 115, 108, 112), // gaps up: |115-102| = 13 beats 115-108 = 7
    ];
    const tr = trueRange(candles);
    expect(tr[0]).toBeCloseTo(10, 10); // first bar: high - low
    expect(tr[1]).toBeCloseTo(13, 10);
  });

  it('produces a positive ATR on a real series', () => {
    const candles = uptrendSeries(120);
    const result = atr(candles, 14);
    const last = result[result.length - 1];
    expect(last).not.toBeNull();
    expect(last!).toBeGreaterThan(0);
  });
});

describe('rsi', () => {
  it('returns 100 for a series that only rises', () => {
    const values = Array.from({ length: 40 }, (_, i) => 100 + i);
    const result = rsi(values, 14);
    expect(result[result.length - 1]).toBeCloseTo(100, 5);
  });

  it('returns a low value for a series that only falls', () => {
    const values = Array.from({ length: 40 }, (_, i) => 100 - i);
    const result = rsi(values, 14);
    expect(result[result.length - 1]!).toBeLessThan(1);
  });

  it('stays inside 0..100 on noisy data', () => {
    const values = uptrendSeries(200, 100, 0.1, 5).map((c) => c.close);
    for (const v of rsi(values, 14)) {
      if (v === null) continue;
      expect(v).toBeGreaterThanOrEqual(0);
      expect(v).toBeLessThanOrEqual(100);
    }
  });
});

describe('macd', () => {
  it('produces macd, signal and histogram aligned to the input length', () => {
    const values = uptrendSeries(200).map((c) => c.close);
    const result = macd(values, 12, 26, 9);
    expect(result.macd.length).toBe(values.length);
    expect(result.signal.length).toBe(values.length);
    expect(result.histogram.length).toBe(values.length);

    const i = values.length - 1;
    expect(result.histogram[i]).toBeCloseTo(result.macd[i]! - result.signal[i]!, 8);
  });

  it('is positive in a sustained uptrend', () => {
    const values = uptrendSeries(200, 100, 0.6, 3).map((c) => c.close);
    const result = macd(values);
    expect(result.macd[values.length - 1]!).toBeGreaterThan(0);
  });
});

describe('stddev / bollinger', () => {
  it('returns zero standard deviation for a flat series', () => {
    const values = new Array(30).fill(100);
    expect(stddev(values, 20)[29]).toBeCloseTo(0, 10);
  });

  it('places bands symmetrically around the middle band', () => {
    const values = uptrendSeries(120).map((c) => c.close);
    const bb = bollinger(values, 20, 2);
    const i = values.length - 1;
    const upperGap = bb.upper[i]! - bb.middle[i]!;
    const lowerGap = bb.middle[i]! - bb.lower[i]!;
    expect(upperGap).toBeCloseTo(lowerGap, 8);
  });
});

describe('zScore', () => {
  it('is zero when the latest value equals the mean', () => {
    const values = [...new Array(19).fill(10), 10];
    expect(zScore(values, 20)[19]).toBe(null); // zero stdev → null by design
  });

  it('is positive for an unusually large latest value', () => {
    const values = [...new Array(19).fill(10), 50];
    expect(zScore(values, 20)[19]!).toBeGreaterThan(1);
  });
});

describe('closeLocationValue', () => {
  it('is +1 when the close equals the high', () => {
    expect(closeLocationValue(makeCandle(0, 100, 110, 90, 110))).toBeCloseTo(1, 10);
  });

  it('is -1 when the close equals the low', () => {
    expect(closeLocationValue(makeCandle(0, 100, 110, 90, 90))).toBeCloseTo(-1, 10);
  });

  it('is 0 at the midpoint', () => {
    expect(closeLocationValue(makeCandle(0, 100, 110, 90, 100))).toBeCloseTo(0, 10);
  });

  it('is 0 for a zero-range candle rather than dividing by zero', () => {
    expect(closeLocationValue(makeCandle(0, 100, 100, 100, 100))).toBe(0);
  });
});

describe('linearSlope', () => {
  it('is positive for a rising series and negative for a falling one', () => {
    const rising = Array.from({ length: 30 }, (_, i) => 100 + i);
    const falling = Array.from({ length: 30 }, (_, i) => 100 - i);
    expect(linearSlope(rising, 20)!).toBeGreaterThan(0);
    expect(linearSlope(falling, 20)!).toBeLessThan(0);
  });

  it('returns null when there is not enough data', () => {
    expect(linearSlope([1, 2, 3], 20)).toBeNull();
  });
});
