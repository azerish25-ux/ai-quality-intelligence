import { evaluationFraction, evaluationNumber, evaluationProvenance, evaluationRate, evaluationRecord } from './evaluation';
import { BenchmarkDetails } from './BenchmarkDetails';

type Props = { metrics: Record<string, unknown> | null; id?: string; title?: string };
const count = (value: unknown): string => {
  const n = evaluationNumber(value);
  return n === null ? 'Not established' : String(n);
};

export function EvaluationPanel({ metrics, id = "evaluation", title = "Deterministic evaluation" }: Props) {
  const sources = evaluationRecord(metrics?.source_counts);
  const targets = evaluationRecord(metrics?.quality_targets ?? metrics?.acceptance);
  const integrity = evaluationRecord(metrics?.integrity_acceptance);
  const families = Object.entries(evaluationRecord(metrics?.by_family)).slice(0, 100);
  const limits = Array.isArray(metrics?.limitations) ? metrics.limitations.filter((v): v is string => typeof v === 'string') : [];
  const campaign = metrics?.evaluation_scope === 'frozen_mixed_source_campaign';
  const categories = Object.entries(evaluationRecord(metrics?.per_category));
  const comparisons = Object.entries(evaluationRecord(metrics?.comparisons));
  const claimChecks = evaluationRecord(metrics?.claim_checks);
  const confusion = evaluationRecord(metrics?.confusion_matrix);
  const errors = Array.isArray(metrics?.errors) ? metrics.errors.map(evaluationRecord) : [];
  const fullstack = metrics?.evaluation_scope === 'http_postgresql_fault_proxy';
  const observations = Array.isArray(metrics?.inspection) ? metrics.inspection.map(evaluationRecord) : [];
  const legacy = metrics?.evaluation_version === 'harness-v1';
  return <section id={id} className="panel evaluation" aria-labelledby={`${id}-heading`}>
    <div className="panel-heading"><div><p className="eyebrow">CONTROLLED EVIDENCE · DECLARED SCOPE</p><h2 id={`${id}-heading`}>{title}</h2></div>
      <span className="pill insufficient-evidence">{metrics ? evaluationProvenance(metrics) : 'No evaluation loaded'}</span></div>
    {!metrics ? <div className="empty">Executed evaluation metrics are not mounted in this runtime.</div> : <>
      <div className="eval-grid">
        <div><span>Cases</span><strong>{count(metrics.case_count)}</strong></div>
        <div><span>Five-category macro F1</span><strong>{evaluationNumber(metrics.macro_f1)?.toFixed(3) ?? 'Not established'}</strong></div>
        <div><span>Product recall</span><strong>{evaluationRate(metrics.product_defect_recall)}</strong></div>
        <div><span>Dangerous dismissals</span><strong>{evaluationFraction(metrics.dangerous_dismissal)}</strong></div>
      </div>
      <p>LedgerGuard executions: <strong>{count(sources.ledgerguard_executed)}</strong>. Synthetic cases in this report: <strong>{count(sources.synthetic)}</strong>.
        {' '}Product abstentions requiring review: <strong>{count(metrics.product_abstentions)}</strong>.</p>
      {metrics.evaluation_scope === 'frozen_five_category_benchmark' && <BenchmarkDetails metrics={metrics} />}
      {campaign && <>
        <p>The headline metrics cover only the frozen test split: <strong>{count(metrics.case_count)}</strong> cases.
          {' '}The full dataset contains <strong>{count(metrics.dataset_case_count)}</strong> cases in <strong>{count(metrics.dataset_family_count)}</strong> agent-reviewed family groups.
          {' '}Retained companion executions belong to development; this campaign does not claim fresh LedgerGuard execution.</p>
        <p>Frozen input manifest: <code>{String(metrics.input_manifest_sha256 ?? 'Not established')}</code>.</p>
        <details><summary>Five-category results and confusion matrix</summary>
          <div className="table-wrap" role="region" aria-label="Five-category metrics" tabIndex={0}>
            <table><caption>Frozen test split — per-category measured results</caption><thead><tr>
              <th scope="col">Category</th><th scope="col">Cases</th><th scope="col">Precision</th><th scope="col">Recall</th><th scope="col">F1</th>
            </tr></thead><tbody>{categories.map(([name, value]) => { const row = evaluationRecord(value); return <tr key={name}>
              <td>{name.replaceAll('_', ' ')}</td><td>{count(row.support)}</td><td>{evaluationRate(row.precision)}</td><td>{evaluationRate(row.recall)}</td><td>{evaluationNumber(row.f1)?.toFixed(3) ?? 'Not established'}</td>
            </tr>; })}</tbody></table>
          </div>
          <div className="table-wrap" role="region" aria-label="Five-category confusion matrix" tabIndex={0}>
            <table><caption>True category by published category — exact counts</caption><thead><tr>
              <th scope="col">True category</th>{categories.map(([name]) => <th scope="col" key={name}>{name.replaceAll('_', ' ')}</th>)}
            </tr></thead><tbody>{categories.map(([name]) => <tr key={name}><td>{name.replaceAll('_', ' ')}</td>
              {categories.map(([predicted]) => <td key={predicted}>{count(evaluationRecord(confusion[name])[predicted])}</td>)}
            </tr>)}</tbody></table>
          </div>
        </details>
        <details><summary>Measured classifier comparisons</summary>
          <div className="table-wrap" role="region" aria-label="Classifier comparison results" tabIndex={0}>
            <table><caption>Same frozen test split — no fabricated improvement claim</caption><thead><tr>
              <th scope="col">Mode</th><th scope="col">Product recall</th><th scope="col">Macro F1</th><th scope="col">Coverage</th>
            </tr></thead><tbody>{comparisons.map(([name, value]) => { const row = evaluationRecord(value); return <tr key={name}>
              <td>{name.replaceAll('_', ' ')}</td><td>{evaluationRate(row.product_defect_recall)}</td>
              <td>{evaluationNumber(row.macro_f1)?.toFixed(3) ?? 'Not established'}</td><td>{evaluationRate(row.non_abstained_coverage)}</td>
            </tr>; })}</tbody></table>
          </div>
        </details>
        <p>Across the full replay: <strong>{count(claimChecks.supported)}/{count(claimChecks.published)}</strong> published claims match the controlled rubric.
          {' '}Unsupported published claims: <strong>{evaluationFraction(claimChecks.unsupported_rate)}</strong>. This is not a universal semantic judge.</p>
        <details><summary>Inspect test errors ({errors.length})</summary>
          <div className="table-wrap" role="region" aria-label="Frozen test error cases" tabIndex={0}>
            <table><caption>All errors remain visible; no cases are removed to improve metrics</caption><thead><tr>
              <th scope="col">Case</th><th scope="col">Expected</th><th scope="col">Published</th><th scope="col">Abstention reason</th>
            </tr></thead><tbody>{errors.map((row) => <tr key={String(row.case_id)}>
              <td><code>{String(row.case_id)}</code></td><td>{String(row.expected_category).replaceAll('_', ' ')}</td>
              <td>{String(row.predicted).replaceAll('_', ' ')}</td><td>{String(row.abstention_reason ?? 'Not an abstention')}</td>
            </tr>)}</tbody></table>
          </div>
          <p className="limitation">Retained IDs refer to the originating evaluation database. They are not links to unrelated current runs.</p>
        </details>
      </>}
      {fullstack && <>
        <p>Paired scenarios: <strong>{count(metrics.paired_scenarios)}</strong>. Independent mechanism families: <strong>{count(metrics.family_count)}</strong>.
          {' '}Transport-only controls correctly left for review: <strong>{count(metrics.control_abstentions)}/{count(metrics.control_case_count)}</strong>.</p>
        <p className="limitation">The injected defect is in the retry proxy, not the unmodified LedgerGuard service. A balanced ledger can still contain two effects for one logical request. This development slice does not replace the component benchmark or establish five-category acceptance.</p>
        <details><summary>Inspect control and intervention observations</summary>
          <div className="table-wrap" role="region" aria-label="Full-stack observed effects" tabIndex={0}>
            <table><caption>Actual committed effects and persisted classifications</caption><thead><tr>
              <th scope="col">Case</th><th scope="col">Role</th><th scope="col">Committed effects</th><th scope="col">Published category</th>
            </tr></thead><tbody>{observations.map((item, index) => <tr key={index}>
              <td><code>{String(item.case_id ?? 'Unknown')}</code></td><td>{String(item.role ?? 'Unknown')}</td>
              <td>{count(item.committed_effects)}</td><td>{String(item.category ?? 'Not established').replaceAll('_', ' ')}</td>
            </tr>)}</tbody></table>
          </div>
          <p className="limitation">Retained run and evidence identifiers refer to the originating database. Safe derivatives and report exports preserve offline inspection.</p>
        </details>
      </>}
      {legacy ? <p className="limitation">Legacy rule regression: numbered family identifiers do not establish independent mechanisms or a leakage-free held-out benchmark. These historical scores are not full-pipeline or deployment performance.</p>
        : <p className="limitation">This report covers the declared execution scope only. Passing artifact-integrity checks is not full-project acceptance or a guarantee of deployment reliability.</p>}
      {typeof metrics.source_revision === 'string' && <p>Tested FailureLens source: <code>{metrics.source_revision}</code>. Database: <strong>{String(metrics.database_dialect ?? 'Not established')}</strong>.</p>}
      {typeof metrics.ledgerguard_revision === 'string' && <p>LedgerGuard source: <code>{metrics.ledgerguard_revision}</code>.</p>}
      {Object.keys(targets).length > 0 && <div className="table-wrap evaluation-checks"><table><caption>Measured quality targets — failed targets remain visible</caption><thead><tr><th scope="col">Target</th><th scope="col">Status</th></tr></thead>
        <tbody>{Object.entries(targets).map(([name, passed]) => <tr key={name}><td>{name.replaceAll('_', ' ')}</td><td><strong>{passed === true ? 'PASS' : passed === false ? 'FAIL' : 'NOT RUN'}</strong></td></tr>)}</tbody></table></div>}
      {Object.keys(integrity).length > 0 && <details><summary>Execution and evidence-integrity checks</summary><div className="table-wrap evaluation-checks"><table><caption>Execution and evidence-integrity checks</caption><thead><tr><th scope="col">Check</th><th scope="col">Status</th></tr></thead>
        <tbody>{Object.entries(integrity).map(([name, passed]) => <tr key={name}><td>{name.replaceAll('_', ' ')}</td><td>{passed === true ? 'PASS' : 'FAIL'}</td></tr>)}</tbody></table></div></details>}
      {families.length > 0 && <details><summary>Results by fault mechanism ({families.length} shown)</summary><div className="table-wrap" role="region" aria-label="Fault mechanism results; scroll horizontally for all columns" tabIndex={0}><table><caption>Results grouped by fault mechanism</caption><thead><tr><th scope="col">Mechanism</th><th scope="col">Cases</th><th scope="col">Product recall</th><th scope="col">Dangerous dismissals</th><th scope="col">Abstentions</th></tr></thead>
        <tbody>{families.map(([name, value]) => { const family = evaluationRecord(value); return <tr key={name}><td>{name.replaceAll('-', ' ')}</td><td>{count(family.case_count)}</td><td>{evaluationRate(family.product_defect_recall)}</td><td>{evaluationFraction(family.dangerous_dismissal)}</td><td>{count(family.product_abstentions)}</td></tr>; })}</tbody></table></div></details>}
      {limits.length > 0 && <details open><summary>Evidence limits and benchmark scope</summary>{limits.map((limit) => <p className="limitation" key={limit}>{limit}</p>)}</details>}
    </>}
  </section>;
}
