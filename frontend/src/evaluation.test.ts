import { describe, expect, it } from 'vitest';
import { evaluationFraction, evaluationNumber, evaluationProvenance, evaluationRate } from './evaluation';

describe('evaluation truthfulness', () => {
  it('does not coerce missing or single-class F1 to a favorable number', () => {
    for (const value of [undefined, null, '', '1.0', {}, Number.NaN, Number.POSITIVE_INFINITY]) expect(evaluationNumber(value)).toBeNull();
    expect(evaluationRate(null)).toBe('Not established');
    expect(evaluationRate(0)).toBe('0.0%');
  });
  it('keeps dangerous dismissal numerator and denominator together', () => {
    expect(evaluationFraction({ numerator: 0, denominator: 60 })).toBe('0/60');
    expect(evaluationFraction({ numerator: 0, denominator: 0 })).toBe('Not established');
    expect(evaluationFraction({ numerator: 0 })).toBe('Not established');
  });
  it('does not relabel synthetic regression cases as real execution', () => {
    expect(evaluationProvenance({ source_counts: { synthetic: 200, ledgerguard_executed: 0 } })).toBe('Synthetic regression evidence');
    expect(evaluationProvenance({ evaluation_scope: 'production_component_challenge', source_counts: { ledgerguard_executed: 60 } })).toBe('Executed LedgerGuard components');
    expect(evaluationProvenance({})).toBe('Provenance not established');
  });
});
