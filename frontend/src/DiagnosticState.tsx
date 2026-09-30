import type { Analysis } from './api';

type Validation = NonNullable<Analysis['validation_results']>;

export function AnalysisEvidenceNotice({ analysis }: { analysis: Pick<Analysis, 'evidence_state' | 'recorded_category'> }) {
  if (analysis.evidence_state !== 'expired' && analysis.evidence_state !== 'unavailable') return null;
  const category = (analysis.recorded_category ?? 'unknown').replaceAll('_', ' ');
  return <p className="alert" role="status">
    {analysis.evidence_state === 'expired' ? 'Evidence expired.' : 'Evidence or prior reviewed history is currently unavailable.'}
    {' '}Recorded category: {category}. This historical decision is no longer evidence-verified.
  </p>;
}

export function diagnosticGapLabel(value: string | null | undefined): string | null {
  const labels: Record<string, string> = {
    publication_rejection: 'The proposed diagnosis did not pass publication validation.',
    missing_or_invalid_observations: 'Required observations are missing or invalid.',
    contradictory_observations: 'The observations support conflicting interpretations.',
    unresolved_evidence_or_capability: 'The available evidence and current diagnostic capability do not resolve the cause.',
  };
  return value ? labels[value] ?? 'The diagnostic gap has not been characterized.' : null;
}

export function DiagnosticState({ validation }: { validation: Validation | null | undefined }) {
  const gap = diagnosticGapLabel(validation?.diagnostic_gap);
  const findings = validation?.diagnostic_findings ?? [];
  if (!gap && findings.length === 0) return null;
  return <section className="evidence-card" aria-label="Diagnostic evidence">
    <h3>Diagnostic evidence</h3>
    {gap && <p role="status">{gap}</p>}
    {findings.map(finding => <div key={`${finding.evidence_id}:${finding.contract}`}>
      <strong>{(finding.contract ?? 'Unknown contract').replaceAll('_', ' ')} · {finding.status}</strong>
      <p>{finding.reason}</p>
    </div>)}
    <p className="muted">A conforming narrow check does not establish that the failure or product is harmless.</p>
  </section>;
}
