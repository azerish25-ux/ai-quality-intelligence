import { evaluationFraction, evaluationNumber, evaluationProvenance, evaluationRate, evaluationRecord } from './evaluation';

type Props = { metrics: Record<string, unknown> | null };
const count = (value: unknown): string => {
  const n = evaluationNumber(value);
  return n === null ? 'Not established' : String(n);
};

export function EvaluationPanel({ metrics }: Props) {
  const sources = evaluationRecord(metrics?.source_counts);
  const targets = evaluationRecord(metrics?.quality_targets ?? metrics?.acceptance);
  const integrity = evaluationRecord(metrics?.integrity_acceptance);
  const families = Object.entries(evaluationRecord(metrics?.by_family)).slice(0, 100);
  const limits = Array.isArray(metrics?.limitations) ? metrics.limitations.filter((v): v is string => typeof v === 'string') : [];
  const legacy = metrics?.evaluation_version === 'harness-v1';
  return <section id="evaluation" className="panel evaluation" aria-labelledby="evaluation-heading">
    <div className="panel-heading"><div><p className="eyebrow">CONTROLLED EVIDENCE · DECLARED SCOPE</p><h2 id="evaluation-heading">Deterministic evaluation</h2></div>
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
      {legacy ? <p className="limitation">Legacy rule regression: numbered family identifiers do not establish independent mechanisms or a leakage-free held-out benchmark. These historical scores are not full-pipeline or deployment performance.</p>
        : <p className="limitation">This report covers the declared execution scope only. Passing artifact-integrity checks is not full-project acceptance or a guarantee of deployment reliability.</p>}
      {typeof metrics.source_revision === 'string' && <p>Tested FailureLens source: <code>{metrics.source_revision}</code>. Database: <strong>{String(metrics.database_dialect ?? 'Not established')}</strong>.</p>}
      {typeof metrics.ledgerguard_revision === 'string' && <p>LedgerGuard source: <code>{metrics.ledgerguard_revision}</code>.</p>}
      {Object.keys(targets).length > 0 && <div className="table-wrap"><table><caption>Measured quality targets — failed targets remain visible</caption><thead><tr><th>Target</th><th>Status</th></tr></thead>
        <tbody>{Object.entries(targets).map(([name, passed]) => <tr key={name}><td>{name.replaceAll('_', ' ')}</td><td><strong>{passed === true ? 'PASS' : passed === false ? 'FAIL' : 'NOT RUN'}</strong></td></tr>)}</tbody></table></div>}
      {Object.keys(integrity).length > 0 && <details><summary>Execution and evidence-integrity checks</summary><div className="table-wrap"><table><thead><tr><th>Check</th><th>Status</th></tr></thead>
        <tbody>{Object.entries(integrity).map(([name, passed]) => <tr key={name}><td>{name.replaceAll('_', ' ')}</td><td>{passed === true ? 'PASS' : 'FAIL'}</td></tr>)}</tbody></table></div></details>}
      {families.length > 0 && <details><summary>Results by fault mechanism ({families.length} shown)</summary><div className="table-wrap"><table><thead><tr><th>Mechanism</th><th>Cases</th><th>Product recall</th><th>Dangerous dismissals</th><th>Abstentions</th></tr></thead>
        <tbody>{families.map(([name, value]) => { const family = evaluationRecord(value); return <tr key={name}><td>{name.replaceAll('-', ' ')}</td><td>{count(family.case_count)}</td><td>{evaluationRate(family.product_defect_recall)}</td><td>{evaluationFraction(family.dangerous_dismissal)}</td><td>{count(family.product_abstentions)}</td></tr>; })}</tbody></table></div></details>}
      {limits.length > 0 && <details open><summary>Evidence limits and benchmark scope</summary>{limits.map((limit) => <p className="limitation" key={limit}>{limit}</p>)}</details>}
    </>}
  </section>;
}
