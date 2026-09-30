import { describe, expect, it } from 'vitest';
import { formatPerformancePercent, formatPerformanceValue } from './performance-format';

describe('performance values', () => {
  it('keeps ordinary measurements and unavailable values readable', () => {
    expect(formatPerformanceValue(123.45, 'ms')).toBe('123.45 ms');
    expect(formatPerformanceValue(0, 'ms')).toBe('0 ms');
    for (const value of [null, Infinity, -Infinity, NaN]) {
      expect(formatPerformanceValue(value, 'ms')).toBe('Unavailable');
    }
  });
  it('bounds the display of extreme finite measurements without clipping them', () => {
    expect(formatPerformanceValue(1.2e308, 'ms')).toBe('1.20000e+308 ms');
    for (const value of [1e308, -1e308, Number.MAX_VALUE, Number.MIN_VALUE]) {
      const formatted = formatPerformanceValue(value, 'ms');
      expect(formatted.length).toBeLessThan(32);
      expect(formatted).toContain('e');
      expect(formatted).not.toMatch(/Infinity|NaN|Unavailable/);
      expect(formatted.startsWith('0 ')).toBe(false);
    }
  });
});

describe('performance percentages', () => {
  it('preserves ordinary signed changes, tolerances and unavailable values', () => {
    expect(formatPerformancePercent(0.2, true)).toBe('+20.0%');
    expect(formatPerformancePercent(-0.2, true)).toBe('-20.0%');
    expect(formatPerformancePercent(0.1, false, 0)).toBe('10%');
    expect(formatPerformancePercent(0, true)).toBe('+0.0%');
    for (const value of [null, Infinity, -Infinity, NaN]) {
      expect(formatPerformancePercent(value)).toBe('Unavailable');
    }
  });
  it('shows finite ratios whose percentages exceed floating point range', () => {
    expect(formatPerformancePercent(1e308, true)).toBe('+1.0e310%');
    expect(formatPerformancePercent(-1e308, true)).toBe('-1.0e310%');
    for (const value of [Number.MAX_VALUE, -Number.MAX_VALUE, 1e308, -1e308]) {
      for (const digits of [0, 1]) {
        const result = formatPerformancePercent(value, false, digits);
        expect(result).not.toMatch(/Infinity|NaN|Unavailable/);
        expect(result).toContain('e310%');
      }
    }
  });
  it('keeps subnormal and small nonzero changes visible', () => {
    expect(formatPerformancePercent(Number.MIN_VALUE, true)).toBe('+4.9e-322%');
    expect(formatPerformancePercent(-Number.MIN_VALUE, true)).toBe('-4.9e-322%');
    expect(formatPerformancePercent(1e-8)).toBe('1.0e-6%');
  });
});
