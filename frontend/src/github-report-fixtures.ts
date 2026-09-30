// Synthetic contract fixtures. Tests separately supply Python number spellings.
import type { EvidenceCounts, GitHubReportPreview } from './github-report';
export const reportCounts: EvidenceCounts = { requested: 1, exported: 1, rejected: 0, unavailable: 0, omitted: 0, unavailable_analyses: 0, invalid_reference_entries: 0, omitted_reference_entries: 0, omitted_section_reference_hints: 0, omitted_related_run_hints: 0 };
export const evidenceFixture = {
  schema_version: 'github-evidence-v1', project_id: 'project-1', run_id: 'run-1', analysis_ids: ['analysis-1'],
  scope: 'reported_reference_subset', distribution_status: 'not_published', notice: 'A bounded approved reference subset.', counts: reportCounts,
  items: [{ evidence_id: 'evidence-1', project_id: 'project-1', run_id: 'run-1', execution_id: 'execution-1', run_input_id: 'input-1', excerpt: 'Observed résumé 😀', quotation_status: 'exact_approved_derivative_excerpt', observation: { value: 1, message: 'résumé 😀' }, omitted_observation_fields: 0, locator: { derivative: { kind: 'json-pointer', pointer: '/excerpt' }, source: { kind: 'json-pointer', pointer: '/value' }, source_status: 'immutable_parser_record', omitted_source_fields: 0 }, content_digest: 'b'.repeat(64), derivative_digest: 'c'.repeat(64), source_digest: 'd'.repeat(64), approval_state: 'auto_approved_text', parser_version: 'parser-v1', extractor_version: 'extractor-v1', redaction_version: 'redact-v3' }]
};
export const reportFixture = {
  schema_version: 'github-report-v2', project_id: 'project-1', run_id: 'run-1', tested_head: null, completeness: 'complete', analysis_count: 1, omitted_analyses: 0, markdown: 'HOLD_FOR_REVIEW · résumé 😀',
  analysis_manifest: { schema_version: 'report-analysis-revisions-v1', count: 1, digest: 'e'.repeat(64) },
  analyses: [{ analysis_id: 'analysis-1' }], baseline: { comparable_run_ids: [], items: [] }, performance: { items: [] },
  evidence_export: { schema_version: 'github-evidence-v1', digest: 'a'.repeat(64), filename: 'evidence.json', scope: 'reported_reference_subset', distribution_status: 'not_published', counts: reportCounts }
};
export function canonicalFixture(value: unknown): string {
  if (Array.isArray(value)) return `[${value.map(canonicalFixture).join(',')}]`;
  if (value && typeof value === 'object') return `{${Object.keys(value).sort().map(key => `${JSON.stringify(key)}:${canonicalFixture((value as Record<string, unknown>)[key])}`).join(',')}}`;
  return JSON.stringify(value).replace(/[\u007f-\uffff]/g, char => `\\u${char.charCodeAt(0).toString(16).padStart(4, '0')}`);
}
export async function fixtureDigest(raw: string): Promise<string> {
  return Array.from(new Uint8Array(await crypto.subtle.digest('SHA-256', new TextEncoder().encode(raw))), byte => byte.toString(16).padStart(2, '0')).join('');
}
export async function signedFixture(value: object, key: string): Promise<string> { return canonicalFixture({ ...value, [key]: await fixtureDigest(canonicalFixture(value)) }); }
export async function reportPair(evidence: object = evidenceFixture, report: object = reportFixture) {
  const evidenceRaw = await signedFixture(evidence, 'evidence_digest'); const evidenceDocument = JSON.parse(evidenceRaw);
  const reportRaw = await signedFixture({ ...report, evidence_export: { ...reportFixture.evidence_export, digest: evidenceDocument.evidence_digest, counts: evidenceDocument.counts } }, 'report_digest');
  return { evidenceRaw, reportRaw, report: { ...JSON.parse(reportRaw), raw_json: reportRaw, evidence_scope: { analysisIds: ['analysis-1'], relatedRunIds: [] } } as GitHubReportPreview };
}
