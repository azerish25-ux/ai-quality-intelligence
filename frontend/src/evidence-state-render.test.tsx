import { describe, expect, it } from 'vitest';
import { renderToStaticMarkup } from 'react-dom/server';
import { AnalysisEvidenceNotice } from './DiagnosticState';

describe('current evidence availability notice', () => {
  it('distinguishes unavailable support from the recorded diagnosis', () => {
    const html = renderToStaticMarkup(<AnalysisEvidenceNotice analysis={{ evidence_state: 'unavailable', recorded_category: 'known_flake' }} />);
    expect(html).toContain('role="status"');
    expect(html).toContain('prior reviewed history is currently unavailable');
    expect(html).toContain('Recorded category: known flake');
    expect(html).toContain('no longer evidence-verified');
    expect(html).not.toContain('Evidence expired.');
  });
  it('preserves the distinct retention expiry notice', () => {
    const html = renderToStaticMarkup(<AnalysisEvidenceNotice analysis={{ evidence_state: 'expired', recorded_category: 'infrastructure_failure' }} />);
    expect(html).toContain('Evidence expired.');
    expect(html).toContain('Recorded category: infrastructure failure');
  });
  it('does not invent an unavailable state or a historical category', () => {
    expect(renderToStaticMarkup(<AnalysisEvidenceNotice analysis={{ evidence_state: 'active' }} />)).toBe('');
    expect(renderToStaticMarkup(<AnalysisEvidenceNotice analysis={{}} />)).toBe('');
    expect(renderToStaticMarkup(<AnalysisEvidenceNotice analysis={{ evidence_state: 'unavailable' }} />)).toContain('Recorded category: unknown');
  });
});
