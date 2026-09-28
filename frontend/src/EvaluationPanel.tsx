import { evaluationFraction, evaluationNumber, evaluationProvenance, evaluationRate, evaluationRecord } from './evaluation';

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
