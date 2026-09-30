import type { Principal } from './api';
import type { ProviderInvocation, ProviderPreview, ProviderScope } from './provider-api';

export const providerTestScope: ProviderScope = { projectId: 'project-1', runId: 'run-1', analysisId: 'analysis-1' };
export const providerTestPrincipal: Principal = { kind: 'user', user_id: 'user-1', username: 'admin', display_name: 'Admin', system_admin: false, demo_mode: false, memberships: [{ project_id: 'project-1', project_slug: 'test', project_name: 'Test', role: 'administrator' }] };
export const providerTestPreview: ProviderPreview = {
  schema_version: '1.0', project_id: 'project-1', run_id: 'run-1', analysis_id: 'analysis-1', analysis_revision: 1,
  analysis_digest: 'a'.repeat(64), evidence_digest: 'b'.repeat(64), configuration_digest: 'c'.repeat(64), preview_digest: 'd'.repeat(64),
  prompt_version: 'proposal-only-v1', availability: 'ready', reason: null, can_submit: true,
  destination: { provider_identity: 'fixture', endpoint: 'https://fixture.invalid', model: 'test-fixture-not-a-model' },
  evidence: [{ id: 'evidence-1', excerpt: 'Approved synthetic evidence' }],
  limits: { max_attempts: 2, max_output_tokens: 500, max_context_bytes: 32000, max_response_bytes: 40000, max_run_requests: 5, max_run_reserved_tokens: 20000, concurrency: 2, min_interval_seconds: 1, timeout_seconds: 20 },
  pricing: null, reserved_tokens_per_attempt: 800, cost_status: 'unknown', notice: 'No live connection has been tested.',
  admission: { active_permits: 0, concurrency: 2, next_allowed_at: null, circuit_open_until: null, recovery_required: false, worker_available: true }
};
export const providerTestJob: ProviderInvocation = {
  schema_version: '1.0', project_id: 'project-1', run_id: 'run-1', analysis_id: 'analysis-1', invocation_id: 'invocation-1', invocation_state: 'queued',
  status: 'fallback', deterministic_category: 'product_defect', proposal: null, reason: 'invocation_queued', usage: null, usage_complete: false,
  estimated_cost: null, known_estimated_cost: null, cost_complete: false, cost_status: 'unknown', prompt_version: 'proposal-only-v1', validation_status: 'unverified_hypotheses_only', attempts: [], budget: null,
  job_id: 'job-1', analysis_revision: 1, analysis_digest: 'a'.repeat(64), evidence_digest: 'b'.repeat(64), configuration_digest: 'c'.repeat(64), preview_digest: 'd'.repeat(64),
  created_at: '2026-09-30T12:00:00Z', completed_at: null, cancel_requested_at: null, recovery_required: false
};
