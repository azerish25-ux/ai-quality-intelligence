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

export type ProjectRole = 'viewer' | 'reviewer' | 'administrator';

export interface AuthMembership {
  project_id: string;
  project_slug: string;
  project_name: string;
  role: ProjectRole;
}

export interface Principal {
  kind: 'demo' | 'user' | 'ingestion_token';
  user_id: string | null;
  username: string | null;
  display_name: string;
  system_admin: boolean;
  demo_mode: boolean;
  memberships: AuthMembership[];
}

export interface LoginResponse {
  principal: Principal;
  access_token: string;
  token_type: 'bearer';
  expires_at: string;
}

export interface HealthStatus {
  status: 'live' | 'ready' | string;
}

export interface UserRecord {
  lifecycle_version: number;
  id: string;
  username: string;
  display_name: string;
  is_active: boolean;
  is_system_admin: boolean;
  created_at: string;
  last_login_at: string | null;
}

export interface ProjectMembership {
  id: string;
  project_id: string;
  user_id: string;
  username: string;
  display_name: string;
  role: ProjectRole;
  granted_by_user_id: string | null;
  created_at: string;
  updated_at: string;
}

export interface IngestionTokenRecord {
  id: string;
  project_id: string;
  name: string;
  token_prefix: string;
  scopes: string[];
  created_by_user_id: string | null;
  expires_at: string | null;
  revoked_at: string | null;
  last_used_at: string | null;
  created_at: string;
  token?: string;
}

export interface AuditEvent {
  id: string;
  project_id: string | null;
  actor_kind: string;
  actor_user_id: string | null;
  actor_display: string;
  action: string;
  resource_type: string;
  resource_id: string | null;
  outcome: string;
  reason: string | null;
  correlation_id: string | null;
  details: Record<string, unknown>;
  created_at: string;
}

export interface ReviewEvent {
  id: string;
  analysis_id: string;
  actor: string;
  actor_kind: string;
  actor_user_id: string | null;
  decision: string;
  proposed_category: string | null;
  reason: string;
  supporting_evidence_ids: string[];
  contradictory_evidence_ids: string[];
  hypothesis_decisions: Array<Record<string, unknown>>;
  investigation_outcome: string | null;
  release_advice: string | null;
  version: number;
  created_at: string;
}

export interface ReviewQueueItem {
  analysis_id: string;
  failure_id: string;
  run_id: string;
  project_id: string;
  test_identity: string;
  category: Category;
  severity: string;
  summary: string;
  evidence_completeness: string;
  policy_flags: string[];
  latest_review_version: number;
  latest_review_decision: string | null;
  created_at: string;
}

export interface ReviewRequest {
  decision: 'accept' | 'reject' | 'needs_more_evidence' | 'category_correction';
  proposedCategory?: Category;
  reason: string;
  expectedVersion: number;
  supportingEvidenceIds?: string[];
  contradictoryEvidenceIds?: string[];
  investigationOutcome?: string;
  releaseAdvice?: 'HOLD_FOR_REVIEW' | 'INVESTIGATE' | 'NO_BLOCKER_IDENTIFIED_IN_OBSERVED_SCOPE';
}

export interface Project {
  id: string;
  slug: string;
  name: string;
  created_at: string;
}

export interface Run {
  evidence_expired_at?: string | null;
  source_expired_at?: string | null;
  id: string;
  project_id: string;
  external_id: string;
  repository: string | null;
  commit_sha: string | null;
  base_sha: string | null;
  branch: string | null;
  framework: string;
  run_scope: string;
  environment: string | null;
  timezone: string | null;
  worker_count: number | null;
  shard_count: number | null;
  status: string;
  completeness: string;
  expected_inputs: number | null;
  received_inputs: number;
  source_metadata: Record<string, unknown>;
  created_at: string;
}

export interface RunDetail {
  run: Run;
  failure_types: Record<string, number>;
  failure_count: number;
}

export interface RunInput {
  id: string;
  project_id: string;
  run_id: string;
  input_id: string;
  kind: string;
  path: string | null;
  required: boolean;
  status: string;
  digest: string | null;
  size_bytes: number | null;
  media_type: string;
  parser_version: string | null;
  warnings: string[];
  metadata_json: Record<string, unknown>;
  created_at: string;
}

export interface Ingestion {
  source_expired_at?: string | null;
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
  execution_id: string;
  test_identity: string;
  message: string;
  fingerprint: string;
  latest_analysis: Analysis | null;
}

export interface Analysis {
  evidence_state?: 'active' | 'expired' | 'unavailable';
  recorded_category?: Category | null;
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
  validation_version: string | null;
  validation_results: {
    status: string;
    accepted_evidence_ids: string[];
    rejected_evidence_ids: string[];
    claims: Array<Record<string, unknown>>;
    diagnostic_gap?: string | null;
    diagnostic_findings?: Array<{ evidence_id: string; contract: string | null; status: string; reason: string }>;
  } | null;
}

export interface HistoryRate {
  numerator: number;
  denominator: number;
  value: number | null;
  interval_95: number[] | null;
  status: string;
  minimum_support: number;
  definition: string;
}

export interface HistoryObservation {
  run_id: string;
  external_id: string;
  commit_sha: string | null;
  branch: string | null;
  browser: string | null;
  environment: string | null;
  run_scope: string;
  run_completeness: string;
  timezone: string | null;
  worker_count: number | null;
  shard_count: number | null;
  time_bucket: string;
  observed_at: string;
  first_outcome: string;
  final_outcome: string;
  attempt_count: number;
  attempt_numbers: number[];
  execution_ids: string[];
  first_execution_id: string;
  final_execution_id: string;
  retry_recovered: boolean;
  duration_ms: number | null;
  duplicate_attempt_numbers: boolean;
}

export interface InfrastructureEvent {
  id: string;
  project_id: string;
  repository: string | null;
  environment: string | null;
  producer: string;
  producer_event_id: string;
  event_kind: string;
  severity: string;
  status: string;
  started_at: string;
  ended_at: string | null;
  recorded_at: string;
  workflow_name: string | null;
  workflow_run_id: string | null;
  workflow_attempt: number | null;
  runner_identity: string | null;
  runner_group: string | null;
  region: string | null;
  worker_count: number | null;
  shard_identity: string | null;
  source_trust: string;
  trusted_for_correlation: boolean;
  source_digest: string;
  evidence_id: string | null;
  metadata: Record<string, unknown>;
  created_at: string;
}

export interface InfrastructureCorrelationMember {
  run_id: string;
  execution_ids: string[];
  outcome: string;
  exposed: boolean;
  event_ids: string[];
  event_kinds: string[];
  observed_at: string;
}

export interface InfrastructureCorrelation {
  snapshot_id: string | null;
  project_id: string;
  selected_run_id: string;
  selected_execution_id: string;
  policy_version: string;
  engine_version: string;
  history_input_digest: string;
  input_digest: string;
  status: string;
  cutoff_at: string;
  after_at: string | null;
  window_seconds: number;
  event_kind: string | null;
  minimum_support: number;
  accepted_event_ids: string[];
  accepted_events: InfrastructureEvent[];
  rejected_events: Array<{
    event_id: string;
    event_kind: string;
    source_trust: string;
    reasons: string[];
  }>;
  sample_sizes: Record<string, number>;
  exposed_outcomes: Record<string, number>;
  unexposed_outcomes: Record<string, number>;
  rates: {
    exposed_failure_rate?: HistoryRate;
    unexposed_failure_rate?: HistoryRate;
    absolute_failure_rate_difference?: number | null;
    relative_risk?: number | null;
  };
  associations: Array<{
    event_kind: string;
    status: string;
    exposed_run_count: number;
    unexposed_run_count: number;
    exposed_failure_rate: HistoryRate;
    unexposed_failure_rate: HistoryRate;
    absolute_failure_rate_difference: number | null;
    relative_risk: number | null;
    confounded_run_count: number;
    interpretation: string;
  }>;
  confounders: string[];
  safety: {
    association_only: boolean;
    causality_claimed: boolean;
    can_support_infrastructure_association: boolean;
    can_independently_authorize_infrastructure_classification: boolean;
    trusted_sources_only: boolean;
    prior_only: boolean;
    current_run_excluded: boolean;
    truncated: boolean;
    notes: string[];
  };
  members: InfrastructureCorrelationMember[];
  created_at: string | null;
}

export interface InfrastructureCorrelationInput {
  after?: string;
  before?: string;
  browser?: string;
  branch?: string;
  environment?: string;
  run_scope?: 'full_suite' | 'impact_selected' | 'unknown';
  timezone?: string;
  worker_count?: number;
  shard_count?: number;
  event_kind?: string;
  window_seconds?: number;
  minimum_support?: number;
}

export interface TestHistory {
  policy_version: string;
  history_input_digest: string;
  status: string;
  logical_test: Record<string, unknown>;
  window: Record<string, unknown>;
  filters: Record<string, unknown>;
  sample_sizes: Record<string, number>;
  outcomes: { first_attempt: Record<string, number>; final: Record<string, number> };
  rates: Record<string, HistoryRate>;
  breakdowns: Record<string, Array<{
    value: string;
    sample_size: number;
    outcomes: Record<string, number>;
    final_failure_rate: HistoryRate;
  }>>;
  sequences: Record<string, unknown>;
  review: { reviewed_known_flake: boolean; events: Array<Record<string, unknown>> };
  safety: {
    history_eligible_for_reassurance: boolean;
    insufficient_data_reasons: string[];
    selection_bias_present: boolean;
    truncated: boolean;
    notes: string[];
  };
  pagination: { offset: number; limit: number; returned: number; total: number };
  observations: HistoryObservation[];
  infrastructure_correlations: InfrastructureCorrelation | null;
}

export interface HistoryFilters {
  browser?: string;
  branch?: string;
  environment?: string;
  runScope?: 'full_suite' | 'impact_selected' | 'unknown';
  timezone?: string;
  workerCount?: number;
  shardCount?: number;
  limit?: number;
  offset?: number;
}

export interface Overview {
  projects: number;
  runs: number;
  ingestions: number;
  active_ingestions: number;
  failures: number;
  clusters: number;
  impact_recommendations: number;
  performance_comparisons: number;
  infrastructure_events: number;
  infrastructure_correlations: number;
  analyses: number;
  categories: Record<Category, number>;
}

export interface PerformancePolicy {
  id: string;
  project_id: string;
  version: string;
  relative_tolerance: number;
  absolute_tolerance: number;
  min_baseline_runs: number;
  max_baseline_age_days: number;
  require_trusted: boolean;
  required_dimensions: string[];
  direction_overrides: Record<string, 'lower_is_better' | 'higher_is_better' | 'neutral'>;
  created_at: string;
}

export interface PerformancePolicyInput {
  version?: string;
  relative_tolerance?: number;
  absolute_tolerance?: number;
  min_baseline_runs?: number;
  max_baseline_age_days?: number;
  require_trusted?: boolean;
  required_dimensions?: string[];
  direction_overrides?: Record<string, 'lower_is_better' | 'higher_is_better' | 'neutral'>;
}

export interface PerformanceObservation {
  id: string;
  project_id: string;
  run_id: string;
  run_input_id: string | null;
  execution_id: string | null;
  evidence_id: string;
  metric_key: string;
  metric_name: string;
  metric_scope: string;
  statistic: string;
  direction: string;
  original_value: number;
  original_unit: string;
  canonical_value: number;
  canonical_unit: string;
  sample_count: number | null;
  producer: string;
  producer_version: string | null;
  workload: string;
  dimension_signature: string;
  dimensions: Record<string, unknown>;
  threshold_status: string;
  threshold_details: Record<string, unknown>;
  source_digest: string;
  source_locator: Record<string, unknown>;
  observed_at: string;
  created_at: string;
}

export interface PerformanceBaselineMember {
  observation_id: string;
  run_id: string;
  evidence_id: string;
  external_id: string;
  commit_sha: string | null;
  observed_at: string;
  canonical_value: number;
  canonical_unit: string;
  sample_count: number | null;
  position: number;
}

export interface PerformanceBaseline {
  id: string;
  project_id: string;
  current_run_id: string;
  current_observation_id: string;
  policy_id: string;
  input_digest: string;
  status: string;
  cutoff_at: string;
  cohort_dimensions: Record<string, unknown>;
  compatibility: Record<string, unknown>;
  rejected_candidates: Array<Record<string, unknown>>;
  run_count: number;
  sample_count: number;
  baseline_value: number | null;
  baseline_min: number | null;
  baseline_max: number | null;
  baseline_mad: number | null;
  baseline_age_seconds: number | null;
  aggregation: string;
  members: PerformanceBaselineMember[];
  created_at: string;
}

export interface PerformanceComparison {
  id: string;
  project_id: string;
  current_run_id: string;
  current_observation_id: string;
  baseline_snapshot_id: string;
  policy_id: string;
  engine_version: string;
  input_digest: string;
  status: string;
  metric_name: string;
  metric_scope: string;
  statistic: string;
  direction: string;
  workload: string;
  canonical_unit: string;
  current_value: number;
  baseline_value: number | null;
  absolute_change: number | null;
  relative_change: number | null;
  allowed_absolute_change: number;
  allowed_relative_change: number;
  current_sample_count: number | null;
  baseline_run_count: number;
  baseline_sample_count: number;
  threshold_status: string;
  effect_size: number | null;
  uncertainty: Record<string, unknown>;
  compatibility: Record<string, unknown>;
  confounders: string[];
  current_evidence_id: string;
  baseline_evidence_ids: string[];
  next_measurement: string;
  summary: string;
  baseline: PerformanceBaseline;
  created_at: string;
}

export interface ImpactTestInput {
  test_key: string;
  test_identity: string;
  source_path?: string | null;
  criticality?: 'normal' | 'high' | 'critical';
  mandatory?: boolean;
  tags?: string[];
  estimated_duration_ms?: number | null;
  metadata?: Record<string, unknown>;
}

export interface ImpactMappingEdgeInput {
  source_path: string;
  target_type: 'test' | 'file';
  target_value: string;
  kind: 'file_to_test' | 'coverage' | 'api_ownership' | 'ownership' | 'historical_failure' | 'dependency';
  confidence: number;
  mapping_source: string;
  mapping_version: string;
  metadata?: Record<string, unknown>;
}

export interface ImpactMappingInput {
  version: string;
  policy_version?: string;
  trusted: boolean;
  coverage_complete: boolean;
  source_metadata?: Record<string, unknown>;
  tests: ImpactTestInput[];
  edges: ImpactMappingEdgeInput[];
}

export interface ImpactMappingSnapshot {
  id: string;
  project_id: string;
  version: string;
  policy_version: string;
  source_digest: string;
  trusted: boolean;
  coverage_complete: boolean;
  source_metadata: Record<string, unknown>;
  test_count: number;
  edge_count: number;
  created_at: string;
}

export interface ImpactRecommendationItem {
  id: string;
  test_key: string;
  test_identity: string;
  source_path: string | null;
  criticality: string;
  mandatory: boolean;
  base_selected: boolean;
  effective_selected: boolean;
  selection_source: string;
  rank: number | null;
  score: number;
  confidence: string;
  reason_codes: string[];
  reasons: Array<Record<string, unknown>>;
  mapping_edge_ids: string[];
  exclusion_reason: string | null;
}

export interface ImpactOverride {
  id: string;
  actor: string;
  action: string;
  test_key: string;
  reason: string;
  revision_before: number;
  revision_after: number;
  created_at: string;
}

export interface ImpactRecommendation {
  id: string;
  project_id: string;
  run_id: string;
  changed_input_id: string;
  mapping_snapshot_id: string;
  base_sha: string | null;
  head_sha: string | null;
  input_digest: string;
  changed_files_digest: string;
  engine_version: string;
  policy_version: string;
  status: string;
  current_revision: number;
  comparison_trusted: boolean;
  mapping_complete: boolean;
  full_suite_required: boolean;
  summary: string;
  changed_files: Array<Record<string, unknown>>;
  safety_reasons: string[];
  metrics: Record<string, number | string | null>;
  selected_tests: ImpactRecommendationItem[];
  excluded_tests: ImpactRecommendationItem[];
  overrides: ImpactOverride[];
  created_at: string;
  updated_at: string;
}

export interface ImpactOverrideRequest {
  action: 'include' | 'exclude';
  testKey: string;
  reason: string;
  expectedRevision: number;
}

export interface ClusterSummary {
  id: string;
  project_id: string;
  cluster_key: string;
  algorithm_version: string;
  feature_version: string;
  current_revision: number;
  representative_failure_id: string | null;
  representative_test_identity: string | null;
  member_count: number;
  uncertainty: string;
  status: string;
  superseded_by_cluster_id: string | null;
  created_at: string;
  updated_at: string;
}

export interface ClusterMember {
  failure_id: string;
  run_id: string;
  test_identity: string;
  message: string;
  exception_type: string | null;
  role: string;
  similarity_score: number | null;
  score_components: Record<string, number>;
  matching_signals: string[];
  conflicting_signals: string[];
  candidate_reasons: string[];
  assignment_kind: string;
}

export interface ClusterRevision {
  id: string;
  cluster_id: string;
  revision: number;
  reason: string;
  algorithm_version: string;
  feature_version: string;
  representative_failure_id: string | null;
  member_count: number;
  score_summary: Record<string, unknown>;
  uncertainty_flags: string[];
  created_at: string;
  memberships: ClusterMember[];
}

export interface ClusterDecision {
  id: string;
  cluster_id: string;
  actor: string;
  decision: string;
  reason: string;
  failure_ids: string[];
  target_cluster_id: string | null;
  revision_before: number;
  revision_after: number;
  created_at: string;
}

export interface ClusterDetail extends ClusterSummary {
  current: ClusterRevision | null;
  decisions: ClusterDecision[];
}

export interface ClusterReview {
  decision: 'confirm' | 'split' | 'merge';
  reason: string;
  expectedRevision: number;
  failureIds?: string[];
  targetClusterId?: string;
}

export interface UploadMetadata {
  externalId: string;
  expectedInputs?: number;
  repository?: string;
  commitSha?: string;
  baseSha?: string;
  branch?: string;
  runScope?: 'full_suite' | 'impact_selected' | 'unknown';
  comparisonTrust?: 'self_reported' | 'authenticated_lookup' | 'trusted_workflow';
  environment?: string;
  timezone?: string;
  workerCount?: number;
  shardCount?: number;
}

const parseResponse = async <T>(response: Response): Promise<T> => {
  if (!response.ok) {
    if (response.status === 401 && typeof window !== 'undefined') window.dispatchEvent(new Event('failurelens:session-expired'));
    const body = await response.text();
    throw new Error(`${response.status} ${response.statusText}: ${body}`);
  }
  if (response.status === 204) return undefined as T;
  return response.json() as Promise<T>;
};

const json = async <T>(url: string, init?: RequestInit): Promise<T> => {
  const response = await fetch(url, {
    ...init,
    credentials: 'include',
    headers: { 'Content-Type': 'application/json', ...(init?.headers ?? {}) }
  });
  return parseResponse<T>(response);
};

const noContent = async (url: string, init?: RequestInit): Promise<void> => {
  const response = await fetch(url, { ...init, credentials: 'include' });
  if (!response.ok) {
    if (response.status === 401 && typeof window !== 'undefined') window.dispatchEvent(new Event('failurelens:session-expired'));
    const body = await response.text();
    throw new Error(`${response.status} ${response.statusText}: ${body}`);
  }
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
  if (metadata.runScope) query.set('run_scope', metadata.runScope);
  if (metadata.comparisonTrust) query.set('comparison_trust', metadata.comparisonTrust);
  if (metadata.environment) query.set('environment', metadata.environment);
  if (metadata.timezone) query.set('timezone', metadata.timezone);
  if (metadata.workerCount !== undefined) query.set('worker_count', String(metadata.workerCount));
  if (metadata.shardCount !== undefined) query.set('shard_count', String(metadata.shardCount));

  const response = await fetch(`/api/v1/projects/${projectId}/ingestions?${query.toString()}`, {
    method: 'POST',
    credentials: 'include',
    headers: { 'Content-Type': file.type || 'application/octet-stream' },
    body: file
  });
  return parseResponse<Ingestion>(response);
};

const historyUrl = (executionId: string, filters: HistoryFilters = {}): string => {
  const query = new URLSearchParams();
  if (filters.browser) query.set('browser', filters.browser);
  if (filters.branch) query.set('branch', filters.branch);
  if (filters.environment) query.set('environment', filters.environment);
  if (filters.runScope) query.set('run_scope', filters.runScope);
  if (filters.timezone) query.set('timezone', filters.timezone);
  if (filters.workerCount !== undefined) query.set('worker_count', String(filters.workerCount));
  if (filters.shardCount !== undefined) query.set('shard_count', String(filters.shardCount));
  if (filters.limit !== undefined) query.set('limit', String(filters.limit));
  if (filters.offset !== undefined) query.set('offset', String(filters.offset));
  const suffix = query.toString();
  return `/api/v1/tests/${executionId}/history${suffix ? `?${suffix}` : ''}`;
};

export const api = {
  healthLive: () => json<HealthStatus>('/health/live'),
  healthReady: () => json<HealthStatus>('/health/ready'),
  me: () => json<Principal>('/api/v1/auth/me'),
  login: (username: string, password: string) => json<LoginResponse>('/api/v1/auth/login', {
    method: 'POST',
    body: JSON.stringify({ username, password })
  }),
  logout: () => noContent('/api/v1/auth/logout', { method: 'POST' }),
  users: () => json<UserRecord[]>('/api/v1/users'),
  createUser: (input: { username: string; displayName: string; password: string; systemAdmin?: boolean }) =>
    json<UserRecord>('/api/v1/users', {
      method: 'POST',
      body: JSON.stringify({
        username: input.username,
        display_name: input.displayName,
        password: input.password,
        system_admin: input.systemAdmin ?? false
      })
    }),
  overview: () => json<Overview>('/api/v1/overview'),
  projects: () => json<Project[]>('/api/v1/projects'),
  projectMembers: (projectId: string) =>
    json<ProjectMembership[]>(`/api/v1/projects/${projectId}/members`),
  addProjectMember: (projectId: string, username: string, role: ProjectRole) =>
    json<ProjectMembership>(`/api/v1/projects/${projectId}/members`, {
      method: 'POST',
      body: JSON.stringify({ username, role })
    }),
  updateProjectMember: (projectId: string, membershipId: string, role: ProjectRole) =>
    json<ProjectMembership>(`/api/v1/projects/${projectId}/members/${membershipId}`, {
      method: 'PATCH',
      body: JSON.stringify({ role })
    }),
  removeProjectMember: (projectId: string, membershipId: string) =>
    noContent(`/api/v1/projects/${projectId}/members/${membershipId}`, { method: 'DELETE' }),
  ingestionTokens: (projectId: string) =>
    json<IngestionTokenRecord[]>(`/api/v1/projects/${projectId}/ingestion-tokens`),
  createIngestionToken: (projectId: string, name: string, expiresAt?: string) =>
    json<IngestionTokenRecord>(`/api/v1/projects/${projectId}/ingestion-tokens`, {
      method: 'POST',
      body: JSON.stringify({ name, expires_at: expiresAt ?? null })
    }),
  revokeIngestionToken: (projectId: string, tokenId: string) =>
    json<IngestionTokenRecord>(`/api/v1/projects/${projectId}/ingestion-tokens/${tokenId}/revoke`, {
      method: 'POST'
    }),
  auditEvents: (projectId: string) =>
    json<AuditEvent[]>(`/api/v1/projects/${projectId}/audit-events?limit=500&offset=0`),
  reviewQueue: (projectId: string, pendingOnly = true) =>
    json<ReviewQueueItem[]>(`/api/v1/projects/${projectId}/review-queue?pending_only=${pendingOnly}&limit=500`),
  analysisReviews: (analysisId: string) =>
    json<ReviewEvent[]>(`/api/v1/analyses/${analysisId}/reviews`),
  reviewAnalysis: (analysisId: string, review: ReviewRequest) =>
    json<ReviewEvent>(`/api/v1/analyses/${analysisId}/reviews`, {
      method: 'POST',
      body: JSON.stringify({
        decision: review.decision,
        proposed_category: review.proposedCategory ?? null,
        reason: review.reason,
        expected_version: review.expectedVersion,
        supporting_evidence_ids: review.supportingEvidenceIds ?? [],
        contradictory_evidence_ids: review.contradictoryEvidenceIds ?? [],
        hypothesis_decisions: [],
        investigation_outcome: review.investigationOutcome ?? null,
        release_advice: review.releaseAdvice ?? null
      })
    }),
  runs: (projectId: string) => json<Run[]>(`/api/v1/projects/${projectId}/runs`),
  ingestions: (projectId: string) => json<Ingestion[]>(`/api/v1/projects/${projectId}/ingestions`),
  ingestion: (ingestionId: string) => json<Ingestion>(`/api/v1/ingestions/${ingestionId}`),
  upload,
  retryIngestion: (ingestionId: string) => json<Ingestion>(`/api/v1/ingestions/${ingestionId}/retry`, { method: 'POST' }),
  cancelIngestion: (ingestionId: string) => json<Ingestion>(`/api/v1/ingestions/${ingestionId}/cancel`, { method: 'POST' }),
  failures: (runId: string) => json<Failure[]>(`/api/v1/runs/${runId}/failures`),
  testHistory: (executionId: string, filters: HistoryFilters = {}) =>
    json<TestHistory>(historyUrl(executionId, filters)),
  clusters: (projectId: string) => json<ClusterSummary[]>(`/api/v1/projects/${projectId}/clusters`),
  runClusters: (runId: string) => json<ClusterSummary[]>(`/api/v1/runs/${runId}/clusters`),
  cluster: (clusterId: string) => json<ClusterDetail>(`/api/v1/clusters/${clusterId}`),
  clusterRevisions: (clusterId: string) => json<ClusterRevision[]>(`/api/v1/clusters/${clusterId}/revisions`),
  reviewCluster: (clusterId: string, review: ClusterReview) => json<ClusterDetail>(
    `/api/v1/clusters/${clusterId}/reviews`,
    {
      method: 'POST',
      body: JSON.stringify({
        decision: review.decision,
        reason: review.reason,
        expected_revision: review.expectedRevision,
        failure_ids: review.failureIds ?? [],
        target_cluster_id: review.targetClusterId ?? null
      })
    }
  ),
  runInputs: (runId: string) => json<RunInput[]>(`/api/v1/runs/${runId}/inputs`),
  performancePolicies: (projectId: string) =>
    json<PerformancePolicy[]>(`/api/v1/projects/${projectId}/performance-policies`),
  createPerformancePolicy: (projectId: string, policy: PerformancePolicyInput = {}) =>
    json<PerformancePolicy>(`/api/v1/projects/${projectId}/performance-policies`, {
      method: 'POST',
      body: JSON.stringify(policy)
    }),
  performanceObservations: (runId: string) =>
    json<PerformanceObservation[]>(`/api/v1/runs/${runId}/performance-observations`),
  performanceComparisons: (runId: string) =>
    json<PerformanceComparison[]>(`/api/v1/runs/${runId}/performance-comparisons`),
  createPerformanceComparisons: (
    runId: string,
    policyId?: string,
    observationIds: string[] = []
  ) => json<PerformanceComparison[]>(`/api/v1/runs/${runId}/performance-comparisons`, {
    method: 'POST',
    body: JSON.stringify({
      policy_id: policyId || null,
      observation_ids: observationIds
    })
  }),
  impactMappings: (projectId: string) =>
    json<ImpactMappingSnapshot[]>(`/api/v1/projects/${projectId}/impact-mappings`),
  createImpactMapping: (projectId: string, mapping: ImpactMappingInput) =>
    json<ImpactMappingSnapshot>(`/api/v1/projects/${projectId}/impact-mappings`, {
      method: 'POST',
      body: JSON.stringify(mapping)
    }),
  impactRecommendations: (projectId: string) =>
    json<ImpactRecommendation[]>(`/api/v1/projects/${projectId}/impact-recommendations`),
  impactRecommendation: (recommendationId: string) =>
    json<ImpactRecommendation>(`/api/v1/impact-recommendations/${recommendationId}`),
  createImpactRecommendation: (
    projectId: string,
    runId: string,
    mappingSnapshotId: string,
    changedInputId?: string,
    baseSha?: string,
    headSha?: string
  ) =>
    json<ImpactRecommendation>(`/api/v1/projects/${projectId}/impact-recommendations`, {
      method: 'POST',
      body: JSON.stringify({
        run_id: runId,
        mapping_snapshot_id: mappingSnapshotId,
        changed_input_id: changedInputId ?? null,
        base_sha: baseSha ?? null,
        head_sha: headSha ?? null
      })
    }),
  overrideImpactRecommendation: (recommendationId: string, override: ImpactOverrideRequest) =>
    json<ImpactRecommendation>(`/api/v1/impact-recommendations/${recommendationId}/overrides`, {
      method: 'POST',
      body: JSON.stringify({
        action: override.action,
        test_key: override.testKey,
        reason: override.reason,
        expected_revision: override.expectedRevision
      })
    }),
  infrastructureEvents: (projectId: string) =>
    json<InfrastructureEvent[]>(`/api/v1/projects/${projectId}/infrastructure-events`),
  createInfrastructureEvent: (
    projectId: string,
    event: Omit<InfrastructureEvent, 'id' | 'project_id' | 'trusted_for_correlation' | 'source_digest' | 'created_at'>
  ) => json<InfrastructureEvent>(`/api/v1/projects/${projectId}/infrastructure-events`, {
    method: 'POST',
    body: JSON.stringify(event)
  }),
  createInfrastructureCorrelation: (
    executionId: string,
    input: InfrastructureCorrelationInput = {}
  ) => json<InfrastructureCorrelation>(`/api/v1/tests/${executionId}/infrastructure-correlations`, {
    method: 'POST',
    body: JSON.stringify(input)
  }),
  infrastructureCorrelation: (snapshotId: string) =>
    json<InfrastructureCorrelation>(`/api/v1/infrastructure-correlations/${snapshotId}`),
  analyze: (failureId: string) => json<Analysis>(`/api/v1/failures/${failureId}/analyses`, { method: 'POST' }),
  seedDemo: () => json<{ project_id: string; run_id: string }>('/api/v1/demo/seed', { method: 'POST' }),
  campaignEvaluation: () => json<{ status: string; metrics?: Record<string, unknown> }>("/api/v1/evaluations/campaign"),
  benchmarkEvaluation: () => json<{ status: string; metrics?: Record<string, unknown>; message?: string }>("/api/v1/evaluations/benchmark"),
  fullstackEvaluation: () => json<{ status: string; metrics?: Record<string, unknown>; message?: string }>('/api/v1/evaluations/fullstack'),
  evaluation: () => json<{ status: string; metrics?: Record<string, unknown>; message?: string }>('/api/v1/evaluations/latest')
};

export interface SessionRecord {
  id: string; user_id: string; created_at: string; last_used_at: string | null;
  expires_at: string; revoked_at: string | null; current: boolean;
  state: 'active' | 'expired' | 'revoked';
}
export interface RetentionPolicy {
  project_id: string; version: number; source_days: number; evidence_days: number;
  audit_days: number; export_enabled: boolean; export_max_rows: number; updated_at: string;
}
export interface RetentionChange {
  expected_version: number; source_days: number; evidence_days: number; audit_days: number;
  export_enabled: boolean; export_max_rows: number; reason: string;
}
export interface RetentionPreview {
  project_id: string; policy_version: number; as_of: string; cutoff_source: string;
  cutoff_evidence: string; cutoff_audit: string; source_ingestions: number; source_runs: number;
  evidence_runs: number; audit_events: number; blocked_by_ingestion: boolean;
  sample_run_ids: string[]; confirmation_digest: string;
}
export interface RetentionJob {
  job_id: string; state: IngestionState; policy_version: number;
  progress: Record<string, number>; error_code: string | null;
}
export interface Tombstone {
  id: string; resource_type: string; resource_id: string; policy_version: number; reason: string; expired_at: string;
}
export interface ReviewPage {
  items: ReviewQueueItem[]; total: number; limit: number; offset: number;
}
export interface ReviewFilters {
  status: 'pending' | 'reviewed' | 'all' | 'needs_more_evidence';
  category?: Category; search?: string; sort?: 'newest' | 'oldest' | 'severity' | 'test';
  limit?: number; offset?: number;
}
export interface AuditFilters {
  action?: string; outcome?: string; search?: string; sort?: 'newest' | 'oldest';
  limit?: number; offset?: number;
}
export interface AuditPage {
  items: AuditEvent[]; total: number; limit: number; offset: number;
  actions: string[]; outcomes: string[]; export_enabled: boolean;
}
const queryString = (filters: object): string => new URLSearchParams(
  Object.entries(filters).filter(([, value]) => value !== undefined && value !== null)
    .map(([key, value]) => [key, String(value)])
).toString();

export const operations = {
  run: async (id: string): Promise<Run> => {
    const detail = await json<RunDetail>(`/api/v1/runs/${encodeURIComponent(id)}`);
    if (!detail?.run || detail.run.id !== id || typeof detail.run.project_id !== 'string') {
      throw new Error('Invalid run-detail response: expected an authorized run envelope.');
    }
    return detail.run;
  },
  sessions: (offset = 0) => json<SessionRecord[]>(`/api/v1/auth/sessions?limit=10&offset=${offset}`),
  revokeSession: (id: string) => json<void>(`/api/v1/auth/sessions/${id}/revoke`, { method: 'POST' }),
  changePassword: (currentPassword: string, newPassword: string) => json<void>('/api/v1/auth/password', {
    method: 'POST', body: JSON.stringify({ current_password: currentPassword, new_password: newPassword })
  }),
  changeAccount: (user: UserRecord, active: boolean, password: string, reason: string) =>
    json<UserRecord>(`/api/v1/users/${user.id}`, { method: 'PATCH', body: JSON.stringify({
      expected_version: user.lifecycle_version, current_password: password, reason, is_active: active
    }) }),
  issueRecovery: (user: UserRecord, password: string, reason: string) =>
    json<{ token: string; expires_at: string; user_id: string; lifecycle_version: number }>(`/api/v1/users/${user.id}/recovery`, {
      method: 'POST', body: JSON.stringify({ current_password: password, reason, expected_version: user.lifecycle_version })
    }),
  redeemRecovery: (token: string, newPassword: string) => json<void>('/api/v1/auth/recovery', {
    method: 'POST', body: JSON.stringify({ token, new_password: newPassword })
  }),
  userSessions: (id: string, offset = 0) => json<SessionRecord[]>(`/api/v1/users/${id}/sessions?limit=10&offset=${offset}`),
  revokeUserSessions: (id: string, password: string, reason: string) => json<void>(`/api/v1/users/${id}/sessions/revoke`, {
    method: 'POST', body: JSON.stringify({ current_password: password, reason })
  }),
  reviewPage: (id: string, filters: ReviewFilters, signal?: AbortSignal) =>
    json<ReviewPage>(`/api/v1/projects/${id}/review-queue/page?${queryString(filters)}`, { signal }),
  auditPage: (id: string, filters: AuditFilters, signal?: AbortSignal) =>
    json<AuditPage>(`/api/v1/projects/${id}/audit-events/page?${queryString(filters)}`, { signal }),
  exportAudit: async (id: string, filters: AuditFilters): Promise<string> => {
    const { limit: _limit, offset: _offset, ...selection } = filters;
    const response = await fetch(`/api/v1/projects/${id}/audit-events/export`, {
      method: 'POST', credentials: 'include', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(selection)
    });
    if (!response.ok) await parseResponse(response);
    return response.text();
  },
  retention: (id: string) => json<RetentionPolicy>(`/api/v1/projects/${id}/retention`),
  previewPolicy: (id: string, body: RetentionChange) => json<RetentionPreview>(`/api/v1/projects/${id}/retention/preview`, {
    method: 'POST', body: JSON.stringify(body)
  }),
  saveRetention: (id: string, body: RetentionChange) => json<RetentionPolicy>(`/api/v1/projects/${id}/retention`, {
    method: 'PUT', body: JSON.stringify(body)
  }),
  previewCleanup: (id: string) => json<RetentionPreview>(`/api/v1/projects/${id}/retention/preview`),
  queueCleanup: (id: string, preview: RetentionPreview) => json<RetentionJob>(`/api/v1/projects/${id}/retention/cleanup`, {
    method: 'POST', body: JSON.stringify({ expected_version: preview.policy_version, as_of: preview.as_of,
      confirmation_digest: preview.confirmation_digest })
  }),
  retentionJobs: (id: string) => json<RetentionJob[]>(`/api/v1/projects/${id}/retention/jobs?limit=10`),
  retentionJob: (id: string, jobId: string) => json<RetentionJob>(`/api/v1/projects/${id}/retention/jobs/${jobId}`),
  tombstones: (id: string, offset = 0) => json<Tombstone[]>(`/api/v1/projects/${id}/retention/tombstones?limit=10&offset=${offset}`)
};
