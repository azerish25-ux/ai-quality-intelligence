import type { MouseEvent } from 'react';
import type { Overview } from './api';

const categories = [
  ['product_defect', 'Product defect'],
  ['test_defect', 'Test defect'],
  ['infrastructure_failure', 'Infrastructure'],
  ['known_flake', 'Known flake'],
  ['insufficient_evidence', 'Insufficient evidence']
] as const;

/** Workspace totals count stored records, including historical analysis revisions. */
export function WorkbenchOverview({ overview, navigate }: {
  overview: Overview | null;
  navigate: (event: MouseEvent<HTMLAnchorElement>) => void;
}) {
  const total = categories.reduce((sum, [key]) => sum + (overview?.categories[key] ?? 0), 0);
  return <section id="overview" className="workbench-overview" aria-label="Overview metrics">
    <div className="desk-section-heading"><h2>Workspace at a glance</h2><span>Accessible projects · stored records</span></div>
    <div className="desk-metrics">
      {[
        ['Runs received', overview?.runs, '#runs', 'Inspect a run'],
        ['Failures recorded', overview?.failures, '#workspace', 'Open investigation'],
        ['Related clusters', overview?.clusters, '#clusters', 'Trace related failures'],
        ['Ingestions in progress', overview?.active_ingestions, '#ingestion', 'Inspect the pipeline']
      ].map(([label, value, href, action]) => <a className="desk-metric" href={String(href)} key={label} onClick={navigate}>
        <span>{label}</span><strong>{value ?? '—'}</strong><small>{action} <span aria-hidden="true">↗</span></small>
      </a>)}
    </div>
    <div className="analysis-distribution">
      <div className="distribution-heading"><h3>Recorded classifications</h3><span>{overview ? `${total} analysis revisions` : 'Loading records…'}</span></div>
      <div className="distribution-bar" aria-hidden="true">
        {total > 0 ? categories.map(([key]) => <span key={key} className={key.replaceAll('_', '-')} style={{ flexGrow: overview?.categories[key] ?? 0 }} />) : <span className="distribution-empty" />}
      </div>
      <ul className="distribution-legend" aria-label="Recorded classification totals">
        {categories.map(([key, label]) => <li key={key}><i className={`signal-dot ${key.replaceAll('_', '-')}`} aria-hidden="true" /><span>{label}</span><strong>{overview?.categories[key] ?? '—'}</strong></li>)}
      </ul>
      <p className="distribution-note">Historical analysis revisions, not a current release verdict. Open a failure to verify its evidence.</p>
    </div>
    <details className="desk-inventory"><summary>Pipeline &amp; supporting records</summary><dl>
      {[
        ['Projects', overview?.projects], ['Total ingestions', overview?.ingestions],
        ['Impact plans', overview?.impact_recommendations], ['Performance findings', overview?.performance_comparisons],
        ['Infrastructure events', overview?.infrastructure_events], ['Correlation snapshots', overview?.infrastructure_correlations],
        ['Analyses', overview?.analyses]
      ].map(([label, value]) => <div key={label}><dt>{label}</dt><dd>{value ?? '—'}</dd></div>)}
    </dl></details>
  </section>;
}
