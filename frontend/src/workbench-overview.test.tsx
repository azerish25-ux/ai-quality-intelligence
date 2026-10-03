import { describe, expect, it } from 'vitest';
import { renderToStaticMarkup } from 'react-dom/server';
import { WorkbenchOverview } from './WorkbenchOverview';
import type { Overview } from './api';
const overview: Overview = {
  projects: 2, runs: 12, ingestions: 15, active_ingestions: 3, failures: 7, clusters: 4,
  impact_recommendations: 2, performance_comparisons: 1, infrastructure_events: 6,
  infrastructure_correlations: 3, analyses: 9,
  categories: { product_defect: 3, test_defect: 1, infrastructure_failure: 1, known_flake: 0, insufficient_evidence: 4 }
};
const render = (value: Overview | null) => renderToStaticMarkup(<WorkbenchOverview overview={value} navigate={() => {}} />);
describe('evidence workbench overview', () => {
  it('distinguishes unavailable counts from confirmed zero', () => {
    expect(render(null)).toContain('Loading records…');
    expect(render(null)).toContain('—');
    expect(render(null)).not.toContain('0 analysis revisions');
    expect(render(overview)).toContain('9 analysis revisions');
    expect(render(overview)).toContain('Known flake</span><strong>0</strong>');
  });
  it('provides functional navigation for each headline metric', () => {
    const html = render(overview);
    for (const target of ['runs', 'workspace', 'clusters', 'ingestion']) expect(html).toContain(`href="#${target}"`);
    expect(html.match(/class="desk-metric"/g)).toHaveLength(4);
  });
  it('does not conflate historical classifications with release safety', () => {
    expect(render(overview)).toContain('Historical analysis revisions, not a current release verdict');
    expect(render(overview)).toContain('Accessible projects · stored records');
    expect(render(overview)).toContain('aria-label="Recorded classification totals"');
  });
  it('retains all supporting operational totals in an inspectable inventory', () => {
    for (const label of ['Projects', 'Total ingestions', 'Impact plans', 'Performance findings', 'Infrastructure events', 'Correlation snapshots', 'Analyses']) expect(render(overview)).toContain(`<dt>${label}</dt>`);
    expect(render(overview)).toContain('<details class="desk-inventory">');
  });
  it('renders an empty but explicit distribution without nonfinite arithmetic', () => {
    const html = render({ ...overview, categories: { product_defect: 0, test_defect: 0, infrastructure_failure: 0, known_flake: 0, insufficient_evidence: 0 } });
    expect(html).toContain('0 analysis revisions');
    expect(html).toContain('distribution-empty');
    expect(html).not.toContain('NaN');
    expect(html).not.toContain('Infinity');
  });
});
