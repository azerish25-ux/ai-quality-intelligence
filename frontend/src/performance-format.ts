/** Format ratios without requiring their percentage to fit in a JS Number. */
export function formatPerformanceValue(value: number | null, unit: string): string {
  if (value === null || !Number.isFinite(value)) return 'Unavailable';
  const ordinary = new Intl.NumberFormat(undefined, { maximumSignificantDigits: 6 }).format(value);
  // Bound display width, not the measurement: scientific notation retains the
  // same six significant digits for very large or very small finite values.
  return `${ordinary.length > 28 ? value.toExponential(5) : ordinary} ${unit}`;
}

export function formatPerformancePercent(value: number | null, signed = false, digits = 1): string {
  if (value === null || !Number.isFinite(value)) return 'Unavailable';
  const prefix = signed && value >= 0 ? '+' : '';
  const scaled = value * 100;
  if (Number.isFinite(scaled) && (scaled === 0 || Math.abs(scaled) >= 0.5 * 10 ** -digits)) {
    return `${prefix}${scaled.toFixed(digits)}%`;
  }
  // Adjust the decimal exponent as text. The ratio is finite even when its
  // percentage exceeds Number.MAX_VALUE; tiny nonzero ratios also stay visible.
  const [mantissa, exponent] = value.toExponential(digits).split('e');
  return `${prefix}${mantissa}e${Number(exponent) + 2}%`;
}
