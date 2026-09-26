export type Category =
  | 'product_defect'
  | 'test_defect'
  | 'infrastructure_failure'
  | 'known_flake'
  | 'insufficient_evidence';

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
  failures: number;
  analyses: number;
  categories: Record<Category, number>;
}

const json = async <T>(url: string, init?: RequestInit): Promise<T> => {
  const response = await fetch(url, {
    ...init,
    headers: { 'Content-Type': 'application/json', ...(init?.headers ?? {}) }
  });
  if (!response.ok) {
    const body = await response.text();
    throw new Error(`${response.status} ${response.statusText}: ${body}`);
  }
  return response.json() as Promise<T>;
};

export const api = {
  overview: () => json<Overview>('/api/v1/overview'),
  projects: () => json<Project[]>('/api/v1/projects'),
  runs: (projectId: string) => json<Run[]>(`/api/v1/projects/${projectId}/runs`),
  failures: (runId: string) => json<Failure[]>(`/api/v1/runs/${runId}/failures`),
  analyze: (failureId: string) => json<Analysis>(`/api/v1/failures/${failureId}/analyses`, { method: 'POST' }),
  seedDemo: () => json<{ project_id: string; run_id: string }>('/api/v1/demo/seed', { method: 'POST' }),
  evaluation: () => json<{ status: string; metrics?: Record<string, unknown>; message?: string }>('/api/v1/evaluations/latest')
};
