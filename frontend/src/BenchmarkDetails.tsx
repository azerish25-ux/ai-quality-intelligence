import { evaluationFraction, evaluationNumber, evaluationRate, evaluationRecord } from './evaluation';

const categories = ['product_defect', 'test_defect', 'infrastructure_failure', 'known_flake', 'insufficient_evidence'];
const label = (value: string) => value.replaceAll('_', ' ');
const count = (value: unknown) => evaluationNumber(value)?.toString() ?? 'Not established';

export function BenchmarkDetails({ metrics }: { metrics: Record<string, unknown> }) {
  const corpus = evaluationRecord(metrics.corpus);
  const splits = evaluationRecord(corpus.split_counts);
  const claims = evaluationRecord(metrics.claims);
  const temporal = evaluationRecord(metrics.temporal);
  const matrix = evaluationRecord(metrics.confusion_matrix);
  const baselines = Object.entries(evaluationRecord(metrics.baselines));
  const errors = Array.isArray(metrics.error_examples) ? metrics.error_examples.map(evaluationRecord) : [];
  return <div className="benchmark-details">
    <p>Headline metrics use the <strong>test split only</strong>. The complete corpus contains <strong>{count(corpus.case_count)}</strong> cases
      {' '}in <strong>{count(corpus.family_count)}</strong> authored mechanism groups. Retained LedgerGuard executions: <strong>{count(corpus.retained_ledgerguard_executions)}</strong>;
      {' '}fresh LedgerGuard executions in this campaign: <strong>{count(corpus.fresh_ledgerguard_executions)}</strong>.</p>
    <p className="limitation">Previously inspected executed cases remain development regressions. Authored family grouping is not independent expert adjudication or proof of population accuracy.</p>
    <div className="table-wrap" role="region" aria-label="Frozen split counts" tabIndex={0}>
      <table><caption>Frozen corpus partitions</caption><thead><tr><th scope="col">Partition</th><th scope="col">Cases</th></tr></thead>
        <tbody>{['development', 'calibration', 'test'].map(split => <tr key={split}><td>{split}</td><td>{count(splits[split])}</td></tr>)}</tbody></table>
    </div>
    <details><summary>Five-category confusion matrix</summary>
      <div className="table-wrap" role="region" aria-label="Confusion matrix; rows are true categories" tabIndex={0}>
        <table><caption>Test split classifications — rows are truth, columns are predictions</caption>
          <thead><tr><th scope="col">True category</th>{categories.map(category => <th scope="col" key={category}>{label(category)}</th>)}</tr></thead>
          <tbody>{categories.map(category => <tr key={category}><th scope="row">{label(category)}</th>{categories.map(predicted => <td key={predicted}>{count(evaluationRecord(matrix[category])[predicted])}</td>)}</tr>)}</tbody>
        </table>
      </div>
    </details>
    <details><summary>Baselines and component comparisons</summary>
      <div className="table-wrap" role="region" aria-label="Benchmark comparisons" tabIndex={0}>
        <table><caption>Identical frozen test cases across comparison modes</caption><thead><tr><th scope="col">Mode</th><th scope="col">Product recall</th><th scope="col">Macro F1</th><th scope="col">Dangerous dismissals</th></tr></thead>
          <tbody>{baselines.map(([mode, value]) => { const row = evaluationRecord(value); return <tr key={mode}><td>{label(mode)}</td><td>{evaluationRate(row.product_defect_recall)}</td><td>{evaluationNumber(row.macro_f1)?.toFixed(3) ?? 'Not established'}</td><td>{evaluationFraction(row.dangerous_dismissal)}</td></tr>; })}</tbody></table>
      </div>
    </details>
    <details><summary>Published claims and chronology checks</summary>
      <p>Published claims: <strong>{count(claims.published)}</strong>. Unsupported under the declared rubric: <strong>{count(claims.unsupported)}</strong>.
        {' '}Reference validity: <strong>{evaluationFraction(claims.reference_validity)}</strong>. Quotation accuracy: <strong>{evaluationFraction(claims.quotation_accuracy)}</strong>.</p>
      <p>{String(claims.rubric ?? 'Claim-scoring scope is not established.')}</p>
      <p>Later-history probes unchanged: <strong>{count(temporal.unchanged_cases)}/{count(temporal.probed_cases)}</strong>. {String(temporal.scope ?? '')}</p>
      <p className="limitation">Claim and chronology counts cover the whole campaign, not only the headline test split. Unknown-family results use the test partition; they are not an additional independent sample.</p>
    </details>
    <details><summary>Inspect all test errors ({errors.length})</summary>
      {errors.length === 0 ? <p>No test classification errors are recorded in this report.</p> : <div className="table-wrap" role="region" aria-label="Test classification errors" tabIndex={0}>
        <table><caption>Every retained test mismatch, including product abstentions</caption><thead><tr><th scope="col">Case</th><th scope="col">Expected</th><th scope="col">Published</th><th scope="col">Mechanism</th></tr></thead>
          <tbody>{errors.map((row, index) => <tr key={String(row.case_id ?? index)}><td><code>{String(row.case_id ?? 'Unknown')}</code></td><td>{label(String(row.expected ?? 'Unknown'))}</td><td>{label(String(row.predicted ?? 'Unknown'))}</td><td>{String(row.family ?? 'Unknown')}</td></tr>)}</tbody></table>
      </div>}
      <p className="limitation">Per-case reports and safe derivatives are retained with the evaluation snapshot. Originating run identifiers are not links to this runtime unless its database is the original replay database.</p>
    </details>
  </div>;
}
