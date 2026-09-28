export const evaluationNumber = (value: unknown): number | null =>
  typeof value === 'number' && Number.isFinite(value) ? value : null;
export const evaluationRecord = (value: unknown): Record<string, unknown> =>
  value !== null && typeof value === 'object' && !Array.isArray(value) ? value as Record<string, unknown> : {};
export const evaluationRate = (value: unknown): string => {
  const number = evaluationNumber(value);
  return number === null ? 'Not established' : `${(number * 100).toFixed(1)}%`;
};
export const evaluationFraction = (value: unknown): string => {
  const record = evaluationRecord(value);
  const n = evaluationNumber(record.numerator), d = evaluationNumber(record.denominator);
  return n === null || d === null || d <= 0 ? 'Not established' : `${n}/${d}`;
};
export const evaluationProvenance = (metrics: Record<string, unknown>): string => {
  if (metrics.evaluation_scope === 'production_component_challenge') return 'Executed LedgerGuard components';
  const sources = evaluationRecord(metrics.source_counts);
  const executed = evaluationNumber(sources.ledgerguard_executed);
  if (executed !== null && executed > 0) return 'Executed evidence — inspect scope';
  if ((evaluationNumber(sources.synthetic) ?? 0) > 0) return 'Synthetic regression evidence';
  return 'Provenance not established';
};
