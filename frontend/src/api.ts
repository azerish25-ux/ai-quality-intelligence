export type Category =
  | 'product_defect'
  | 'test_defect'
  | 'infrastructure_failure'
  | 'known_flake'
  | 'insufficient_evidence';

export type IngestionState =
  | 'queued'
  | 'running'
  | 'succeeded'
  | 'partial'
  | 'failed'
  | 'cancelled'
  | 'dead_lettered';

export interface Project {
  id: string;
  slug: string;
  name: string;
  created_at: string;
}

export interface Run {
  id: string;
  project_id: string;
  external_id: string;
  repository: string | null;
  commit_sha: string | null;
  branch: string | null;
  framework: string;
  status: string;
  completeness: string;
  expected_inputs: number | null;
  received_inputs: number;
  created_at: string;
}

export interface Ingestion {
  id: string;
  project_id: string;
  external_id: string;
  attempt: number;
  repository: string | null;
  commit_sha: string | null;
  base_sha: string | null;
  branch: string | null;
  source_format: string;
  source_metadata: Record<string, unknown>;
  original_name: string;
  media_type: string;
  source_digest: string;
  source_size_bytes: number;
  expected_inputs: number | null;
  received_inputs: number;
  state: IngestionState;
  run_id: string | null;
  job_id: string | null;
  parser_version: string | null;
  policy_version: string;
  diagnostics: Array<Record<string, unknown>>;
  error_code: string | null;
  error_message: string | null;
  retry_count: number;
  started_at: string | null;
  completed_at: string | null;
  created_at: string;
  updated_at: string;
}

export interface Failure {
  id: string;
  test_identity: string;
  message: string;
  fingerprint: string;
  latest_analysis: Analysis | null;
}

export interface Analysis {
  analysis_id: string;
  category: Category;
  severity: string;
  summary: string;
  confidence: { value: number | null; kind: string; explanation: string };
  evidence_completeness: string;
  supporting_evidence_ids: string[];
  contradictory_evidence_ids: string[];
  missing_evidence: string[];
  policy_flags: string[];
  next_investigation: Array<{ action: string; rationale: string; evidence_ids: string[] }>;
}

export interface Overview {
  projects: number;
  runs: number;
  ingestions: number;
  active_ingestions: number;
  failures: number;
  analyses: number;
  categories: Record<Category, number>;
}

export interface UploadMetadata {
  externalId: string;
  expectedInputs?: number;
  repository?: string;
  commitSha?: string;
  baseSha?: string;
  branch?: string;
}

const parseResponse = async <T>(response: Response): Promise<T> => {
  if (!response.ok) {
    const body = await response.text();
    throw new Error(`${response.status} ${response.statusText}: ${body}`);
  }
  return response.json() as Promise<T>;
};

const json = async <T>(url: string, init?: RequestInit): Promise<T> => {
  const response = await fetch(url, {
    ...init,
    headers: { 'Content-Type': 'application/json', ...(init?.headers ?? {}) }
  });
  return parseResponse<T>(response);
};

const upload = async (
  projectId: string,
  file: File,
  metadata: UploadMetadata
): Promise<Ingestion> => {
  const query = new URLSearchParams({
    external_id: metadata.externalId,
    filename: file.name
  });
  if (metadata.expectedInputs !== undefined) query.set('expected_inputs', String(metadata.expectedInputs));
  if (metadata.repository) query.set('repository', metadata.repository);
  if (metadata.commitSha) query.set('commit_sha', metadata.commitSha);
  if (metadata.baseSha) query.set('base_sha', metadata.baseSha);
  if (metadata.branch) query.set('branch', metadata.branch);

  const response = await fetch(`/api/v1/projects/${projectId}/ingestions?${query.toString()}`, {
    method: 'POST',
    headers: { 'Content-Type': file.type || 'application/octet-stream' },
    body: file
  });
  return parseResponse<Ingestion>(response);
};

export const api = {
  overview: () => json<Overview>('/api/v1/overview'),
  projects: () => json<Project[]>('/api/v1/projects'),
  runs: (projectId: string) => json<Run[]>(`/api/v1/projects/${projectId}/runs`),
  ingestions: (projectId: string) => json<Ingestion[]>(`/api/v1/projects/${projectId}/ingestions`),
  ingestion: (ingestionId: string) => json<Ingestion>(`/api/v1/ingestions/${ingestionId}`),
  upload,
  retryIngestion: (ingestionId: string) => json<Ingestion>(`/api/v1/ingestions/${ingestionId}/retry`, { method: 'POST' }),
  cancelIngestion: (ingestionId: string) => json<Ingestion>(`/api/v1/ingestions/${ingestionId}/cancel`, { method: 'POST' }),
  failures: (runId: string) => json<Failure[]>(`/api/v1/runs/${runId}/failures`),
  analyze: (failureId: string) => json<Analysis>(`/api/v1/failures/${failureId}/analyses`, { method: 'POST' }),
  seedDemo: () => json<{ project_id: string; run_id: string }>('/api/v1/demo/seed', { method: 'POST' }),
  evaluation: () => json<{ status: string; metrics?: Record<string, unknown>; message?: string }>('/api/v1/evaluations/latest')
};
