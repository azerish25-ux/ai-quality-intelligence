import { describe, expect, it } from 'vitest';
import { diagnosticGapLabel } from './DiagnosticState';

describe('diagnostic gap wording', () => {
  it('keeps missing observations and rejected claims distinct', () => {
    expect(diagnosticGapLabel('missing_or_invalid_observations')).toContain('missing or invalid');
    expect(diagnosticGapLabel('publication_rejection')).toContain('publication validation');
    expect(diagnosticGapLabel('contradictory_observations')).toContain('conflicting');
  });
  it('does not invent observability or model competence', () => {
    expect(diagnosticGapLabel('unresolved_evidence_or_capability')).toContain('do not resolve');
    expect(diagnosticGapLabel('new_unknown_gap')).toContain('not been characterized');
    expect(diagnosticGapLabel(undefined)).toBeNull();
    expect(diagnosticGapLabel(null)).toBeNull();
  });
});
