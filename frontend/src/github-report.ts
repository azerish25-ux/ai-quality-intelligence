export interface EvidenceCounts {
  requested: number; exported: number; rejected: number; unavailable: number; omitted: number;
  unavailable_analyses: number; invalid_reference_entries: number; omitted_reference_entries: number;
  omitted_section_reference_hints: number; omitted_related_run_hints: number;
}
export interface EvidenceExportDescriptor {
  schema_version: 'github-evidence-v1'; digest: string; filename: 'evidence.json';
  scope: 'reported_reference_subset'; distribution_status: 'not_published'; counts: EvidenceCounts;
}
export interface GitHubReportPreview {
  schema_version: 'github-report-v2'; run_id: string; project_id?: string;
  tested_head: string | null; completeness: string; report_digest: string;
  analysis_count: number; omitted_analyses: number; markdown: string;
  evidence_export?: EvidenceExportDescriptor;
  analysis_manifest?: { schema_version: 'report-analysis-revisions-v1'; count: number; digest: string };
  // Keep the server bytes. JSON.stringify changes Python float spellings and escapes.
  raw_json: string | null;
  evidence_scope?: { analysisIds: string[]; relatedRunIds: string[] };
}
export interface GitHubEvidenceExport { raw_json: string; counts: EvidenceCounts; evidence_digest: string }
export class GitHubReportError extends Error {
  constructor(message: string, public status = 0) { super(message); }
}
const REPORT_BYTES = 100_000;
const EVIDENCE_BYTES = 500_000;
const countKeys = ['requested', 'exported', 'rejected', 'unavailable', 'omitted', 'unavailable_analyses', 'invalid_reference_entries', 'omitted_reference_entries', 'omitted_section_reference_hints', 'omitted_related_run_hints'] as const;
const object = (value: unknown): value is Record<string, unknown> => Boolean(value) && typeof value === 'object' && !Array.isArray(value);
const identifier = (value: unknown): value is string => typeof value === 'string' && /^[A-Za-z0-9_-]{1,100}$/.test(value);
const digest = (value: unknown): value is string => typeof value === 'string' && /^[a-f0-9]{64}$/.test(value);
const count = (value: unknown, max = 1_000_000_000): value is number => typeof value === 'number' && Number.isSafeInteger(value) && value >= 0 && value <= max;
const text = (value: unknown, max: number): value is string => typeof value === 'string' && Array.from(value).length <= max;
const keys = (value: Record<string, unknown>, expected: readonly string[]): boolean => Object.keys(value).length === expected.length && expected.every(key => Object.hasOwn(value, key));
const ids = (value: unknown, max: number): value is string[] => Array.isArray(value) && value.length <= max && value.every(identifier) && new Set(value).size === value.length;
const records = (value: unknown, max = 50): value is Record<string, unknown>[] => Array.isArray(value) && value.length <= max && value.every(object);
const invalid = (kind: string): never => { throw new GitHubReportError(`Invalid ${kind}. Refresh the report before downloading.`); };
const checkAbort = (signal?: AbortSignal): void => { signal?.throwIfAborted(); };

function validCounts(value: unknown): value is EvidenceCounts {
  return object(value) && keys(value, countKeys) && countKeys.every(key => count(value[key])) &&
    count(value.requested, 500) && count(value.exported, 100) &&
    value.requested === Number(value.exported) + Number(value.rejected) + Number(value.unavailable) + Number(value.omitted);
}
function descriptor(value: unknown): value is EvidenceExportDescriptor {
  return object(value) && keys(value, ['schema_version', 'digest', 'filename', 'scope', 'distribution_status', 'counts']) &&
    value.schema_version === 'github-evidence-v1' && digest(value.digest) && value.filename === 'evidence.json' &&
    value.scope === 'reported_reference_subset' && value.distribution_status === 'not_published' && validCounts(value.counts);
}
async function readBounded(response: Response, max: number, signal?: AbortSignal): Promise<string> {
  checkAbort(signal);
  if (Number(response.headers.get('content-length')) > max) { await response.body?.cancel(); invalid('download size'); }
  if (!response.body) invalid('empty download');
  const reader = response.body!.getReader();
  const chunks: Uint8Array[] = []; let size = 0;
  const abort = () => { void reader.cancel().catch(() => {}); };
  signal?.addEventListener('abort', abort, { once: true });
  try {
    while (true) {
      checkAbort(signal);
      const part = await reader.read();
      checkAbort(signal);
      if (part.done) break;
      size += part.value.byteLength;
      if (size > max) { await reader.cancel(); invalid('download size'); }
      chunks.push(part.value);
    }
    const bytes = new Uint8Array(size); let offset = 0;
    for (const chunk of chunks) { bytes.set(chunk, offset); offset += chunk.byteLength; }
    try { return new TextDecoder('utf-8', { fatal: true, ignoreBOM: true }).decode(bytes); }
    catch { return invalid('download encoding'); }
  } finally { signal?.removeEventListener('abort', abort); reader.releaseLock(); }
}
async function request(url: string, max: number, signal?: AbortSignal): Promise<string> {
  checkAbort(signal);
  const response = await fetch(url, { signal });
  checkAbort(signal);
  if (response.status === 401 && typeof window !== 'undefined') window.dispatchEvent(new Event('failurelens:session-expired'));
  if (!response.ok) {
    await response.body?.cancel();
    if (response.status === 409) throw new GitHubReportError('The report or approved evidence changed. Refresh the report before downloading evidence.', 409);
    throw new GitHubReportError(`Report download unavailable (${response.status}). Check project access and retained evidence.`, response.status);
  }
  return readBounded(response, max, signal);
}

// Parse structural boundaries without reserializing numbers. Validate minified
// ASCII strings, sorted unique keys, bounded depth and finite JSON values first;
// only the exact top-level digest member is removed from the signed bytes.
function unsignedCanonical(raw: string, digestKey: string): string {
  if (!/^[\x20-\x7e]+$/.test(raw)) invalid('canonical JSON');
  let position = 0; const digestRange: { value?: [number, number] } = {};
  const asciiString = (value: string) => JSON.stringify(value).replace(/[\u007f-\uffff]/g, char => `\\u${char.charCodeAt(0).toString(16).padStart(4, '0')}`);
  const readString = (): string => {
    const start = position++;
    while (position < raw.length) {
      const char = raw[position++];
      if (char === '\\') position++;
      else if (char === '"') {
        const token = raw.slice(start, position);
        let value: unknown;
        try { value = JSON.parse(token); } catch { return invalid('canonical JSON'); }
        if (typeof value !== 'string' || asciiString(value) !== token) invalid('canonical JSON');
        return value as string;
      }
    }
    return invalid('canonical JSON');
  };
  const compareKeys = (a: string, b: string): number => {
    const left = Array.from(a), right = Array.from(b);
    for (let i = 0; i < Math.min(left.length, right.length); i++) {
      const difference = left[i].codePointAt(0)! - right[i].codePointAt(0)!;
      if (difference) return difference;
    }
    return left.length - right.length;
  };
  const readValue = (depth: number): void => {
    if (depth > 40) invalid('JSON nesting');
    const char = raw[position];
    if (char === '"') { readString(); return; }
    if (char === '{') {
      position++; let previous: string | null = null;
      if (raw[position] === '}') { position++; return; }
      while (position < raw.length) {
        const start = position;
        if (raw[position] !== '"') invalid('canonical JSON');
        const key = readString();
        if (previous !== null && compareKeys(previous, key) >= 0) invalid('canonical JSON');
        previous = key;
        if (raw[position++] !== ':') invalid('canonical JSON');
        readValue(depth + 1);
        if (depth === 0 && key === digestKey) digestRange.value = [start, position];
        const separator = raw[position++];
        if (separator === '}') return;
        if (separator !== ',') invalid('canonical JSON');
      }
      invalid('canonical JSON');
    }
    if (char === '[') {
      position++;
      if (raw[position] === ']') { position++; return; }
      while (position < raw.length) {
        readValue(depth + 1);
        const separator = raw[position++];
        if (separator === ']') return;
        if (separator !== ',') invalid('canonical JSON');
      }
      invalid('canonical JSON');
    }
    const token = /^(?:true|false|null|-?(?:0|[1-9]\d*)(?:\.\d+)?(?:[eE][+-]?\d+)?)/.exec(raw.slice(position))?.[0];
    if (!token || (!['true', 'false', 'null'].includes(token) && !Number.isFinite(Number(token)))) invalid('canonical JSON');
    position += token!.length;
  };
  if (raw[0] !== '{') invalid('canonical JSON');
  readValue(0);
  if (position !== raw.length || !digestRange.value) invalid('canonical JSON');
  let [start, end] = digestRange.value!;
  if (raw[start - 1] === ',') start--;
  else if (raw[end] === ',') end++;
  return raw.slice(0, start) + raw.slice(end);
}
async function verifyDigest(raw: string, key: string, expected: string, signal?: AbortSignal): Promise<void> {
  const unsigned = unsignedCanonical(raw, key);
  if (!globalThis.crypto?.subtle) throw new GitHubReportError('Download verification requires a secure browser connection.');
  const bytes = await crypto.subtle.digest('SHA-256', new TextEncoder().encode(unsigned));
  checkAbort(signal);
  const actual = Array.from(new Uint8Array(bytes), byte => byte.toString(16).padStart(2, '0')).join('');
  if (actual !== expected) invalid('download digest');
}
function parse(raw: string): Record<string, unknown> {
  try { const value: unknown = JSON.parse(raw); if (object(value)) return value; } catch { /* Fixed error never exposes response data. */ }
  return invalid('JSON document');
}

function reportEvidenceScope(value: Record<string, unknown>): NonNullable<GitHubReportPreview['evidence_scope']> {
  if (!records(value.analyses) || !ids(value.analyses.map(item => item.analysis_id), 50) || value.analyses.length + Number(value.omitted_analyses) !== value.analysis_count) invalid('report analysis scope');
  const related = new Set<string>();
  const section = (name: string): Record<string, unknown> => {
    const item = value[name];
    if (!object(item) || !records(item.items)) invalid('report reference scope');
    return item as Record<string, unknown>;
  };
  const baseline = section('baseline');
  if (!ids(baseline.comparable_run_ids, 50)) invalid('report baseline scope');
  for (const item of baseline.items as Record<string, unknown>[]) {
    if (!ids(item.supporting_baseline_evidence_ids, 10) || !records(item.prior_observations, 10)) invalid('report baseline scope');
    if ((item.supporting_baseline_evidence_ids as string[]).length) for (const id of baseline.comparable_run_ids as string[]) related.add(id);
    for (const observation of item.prior_observations as Record<string, unknown>[]) {
      if (!identifier(observation.run_id) || !ids(observation.evidence_ids, 10)) invalid('report baseline scope');
      if ((observation.evidence_ids as string[]).length) related.add(observation.run_id as string);
    }
  }
  for (const item of section('performance').items as Record<string, unknown>[]) {
    if (!records(item.baseline_members, 50)) invalid('report performance scope');
    for (const member of item.baseline_members as Record<string, unknown>[]) {
      if (member.evidence_id !== null && !identifier(member.evidence_id)) invalid('report performance scope');
      if (member.evidence_id) {
        if (!identifier(member.run_id)) invalid('report performance scope');
        related.add(member.run_id as string);
      }
    }
  }
  related.delete(value.run_id as string);
  return { analysisIds: (value.analyses as Record<string, unknown>[]).map(item => item.analysis_id as string), relatedRunIds: [...related].sort().slice(0, 100) };
}
export async function loadGitHubReport(runId: string, signal?: AbortSignal, projectId?: string): Promise<GitHubReportPreview> {
  const raw = await request(`/api/v1/runs/${encodeURIComponent(runId)}/github-report-preview`, REPORT_BYTES, signal);
  const value = parse(raw);
  if (value.schema_version !== 'github-report-v2' || value.run_id !== runId || !text(value.markdown, 60_000) || !digest(value.report_digest) ||
      !count(value.analysis_count) || !count(value.omitted_analyses) || value.omitted_analyses > value.analysis_count ||
      !['complete', 'partial', 'unknown', 'evidence_expired'].includes(String(value.completeness)) ||
      !(value.tested_head === null || text(value.tested_head, 64)) ||
      (value.project_id !== undefined && (!identifier(value.project_id) || (projectId !== undefined && value.project_id !== projectId)))) invalid('report preview');
  // Older servers retain their existing inert preview/Markdown path. Verified
  // JSON and evidence downloads require the new signed descriptor contract.
  if (!Object.hasOwn(value, 'evidence_export')) return { ...value, raw_json: null } as unknown as GitHubReportPreview;
  if (!identifier(value.project_id) || !descriptor(value.evidence_export)) invalid('report evidence descriptor');
  const manifest = value.analysis_manifest;
  if (!object(manifest) || !keys(manifest, ['schema_version', 'count', 'digest']) || manifest.schema_version !== 'report-analysis-revisions-v1' || manifest.count !== value.analysis_count || !digest(manifest.digest)) invalid('analysis revision manifest');
  const evidence_scope = reportEvidenceScope(value);
  await verifyDigest(raw, 'report_digest', value.report_digest as string, signal);
  return { ...value, raw_json: raw, evidence_scope } as unknown as GitHubReportPreview;
}

const observationFields = ['test_identity', 'suite', 'parameterization', 'browser', 'attempt', 'outcome', 'duration_ms', 'message', 'exception_type', 'metric', 'unit', 'statistic', 'value', 'sample_count', 'threshold', 'http_status'];
const locatorFields = ['kind', 'pointer', 'line', 'start_line', 'end_line', 'column', 'index', 'input_id'];
const scalar = (value: unknown): boolean => value === null || typeof value === 'boolean' || (typeof value === 'number' && Number.isFinite(value)) || (text(value, 2000) && !/[\x00-\x08\x0b\x0c\x0e-\x1f]/.test(value));
const selectedFields = (value: unknown, allowed: string[]): boolean => object(value) && Object.entries(value).every(([key, item]) => allowed.includes(key) && scalar(item));
function evidenceItem(item: unknown, report: GitHubReportPreview, seen: Set<string>): boolean {
  if (!object(item) || !keys(item, ['evidence_id', 'project_id', 'run_id', 'execution_id', 'run_input_id', 'excerpt', 'quotation_status', 'observation', 'omitted_observation_fields', 'locator', 'content_digest', 'derivative_digest', 'source_digest', 'approval_state', 'parser_version', 'extractor_version', 'redaction_version']) ||
      !identifier(item.evidence_id) || seen.has(item.evidence_id) || item.project_id !== report.project_id ||
      (item.run_id !== report.run_id && !report.evidence_scope!.relatedRunIds.includes(String(item.run_id))) ||
      !(item.execution_id === null || identifier(item.execution_id)) || !(item.run_input_id === null || identifier(item.run_input_id)) ||
      !text(item.excerpt, EVIDENCE_BYTES) || item.quotation_status !== 'exact_approved_derivative_excerpt' ||
      !selectedFields(item.observation, observationFields) || !count(item.omitted_observation_fields) ||
      !['content_digest', 'derivative_digest', 'source_digest'].every(key => digest(item[key])) ||
      !['auto_approved_text', 'reviewed'].includes(String(item.approval_state)) ||
      !['parser_version', 'extractor_version', 'redaction_version'].every(key => typeof item[key] === 'string' && /^[A-Za-z0-9._:/-]{1,100}$/.test(item[key] as string))) return false;
  const locator = item.locator;
  if (!object(locator) || !keys(locator, ['derivative', 'source', 'source_status', 'omitted_source_fields']) ||
      !object(locator.derivative) || !keys(locator.derivative, ['kind', 'pointer']) || locator.derivative.kind !== 'json-pointer' || locator.derivative.pointer !== '/excerpt' ||
      locator.source_status !== 'immutable_parser_record' || !count(locator.omitted_source_fields) || !selectedFields(locator.source, locatorFields)) return false;
  seen.add(item.evidence_id); return true;
}
export async function loadGitHubEvidence(report: GitHubReportPreview, signal?: AbortSignal): Promise<GitHubEvidenceExport> {
  if (!report.raw_json || !report.evidence_export || !report.evidence_scope || !report.project_id) invalid('evidence export availability');
  const raw = await request(`/api/v1/runs/${encodeURIComponent(report.run_id)}/github-evidence-export?report_digest=${encodeURIComponent(report.report_digest)}`, EVIDENCE_BYTES, signal);
  const value = parse(raw);
  const descriptor = report.evidence_export!;
  if (!keys(value, ['schema_version', 'project_id', 'run_id', 'analysis_ids', 'scope', 'distribution_status', 'notice', 'counts', 'items', 'evidence_digest']) ||
      value.schema_version !== 'github-evidence-v1' || value.project_id !== report.project_id || value.run_id !== report.run_id ||
      value.scope !== 'reported_reference_subset' || value.distribution_status !== 'not_published' || !text(value.notice, 4000) ||
      value.evidence_digest !== descriptor.digest || !validCounts(value.counts) ||
      !countKeys.every(key => (value.counts as EvidenceCounts)[key] === descriptor.counts[key]) ||
      !ids(value.analysis_ids, 50) || !(value.analysis_ids as string[]).every(id => report.evidence_scope!.analysisIds.includes(id)) ||
      !Array.isArray(value.items) || value.items.length !== descriptor.counts.exported || value.items.length > 100) invalid('evidence export');
  const seen = new Set<string>();
  if (!(value.items as unknown[]).every(item => evidenceItem(item, report, seen))) invalid('evidence item scope or schema');
  await verifyDigest(raw, 'evidence_digest', descriptor.digest, signal);
  return { raw_json: raw, counts: value.counts as unknown as EvidenceCounts, evidence_digest: descriptor.digest };
}
