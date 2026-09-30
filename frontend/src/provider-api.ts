import type { Category, Principal } from './api';

export interface ProviderScope { projectId: string; runId: string; analysisId: string }
export interface ProviderPricing {
  input_price_per_million: number | null; output_price_per_million: number | null;
  source: string | null; date: string | null; currency: string | null;
}
export interface ProviderLimits {
  max_attempts: number; max_output_tokens: number; max_context_bytes: number; max_response_bytes: number;
  max_run_requests: number; max_run_reserved_tokens: number; concurrency: number; min_interval_seconds: number; timeout_seconds: number;
}
export type ProviderAvailability = 'ready' | 'disabled' | 'invalid_configuration' | 'project_not_allowed' | 'evidence_unavailable' | 'rate_limited' | 'circuit_open' | 'recovery_required' | 'worker_unavailable' | 'concurrency_limited' | 'run_budget_exhausted';
export interface ProviderBudget { requests: number; reserved_tokens: number; max_requests: number; max_reserved_tokens: number }
export interface ProviderStatus {
  schema_version: '1.0'; project_id: string; availability: ProviderAvailability; reason: string | null; can_submit: boolean;
  configuration_digest: string | null; destination: { provider_identity: string; endpoint: string; model: string } | null;
  limits: ProviderLimits | null; pricing: ProviderPricing | null; cost_status: 'unknown' | 'estimate_available'; notice: string;
  admission: { active_permits: number; concurrency: number; next_allowed_at: string | null; circuit_open_until: string | null; recovery_required: boolean; worker_available: boolean } | null;
}
export interface ProviderPreview extends ProviderStatus {
  run_id: string; analysis_id: string; analysis_revision: number; analysis_digest: string | null; evidence_digest: string | null;
  preview_digest: string | null; prompt_version: string; evidence: Array<{ id: string; excerpt: string }>;
  reserved_tokens_per_attempt: number | null;
  budget?: ProviderBudget | null;
}
export interface ProviderAttempt {
  number: number; status: string; reason: string | null; http_status: number | null; reserved_tokens: number; accounted_tokens: number;
  spend_status: string; usage: ProviderUsage | null; estimated_cost: number | null; cost_status: string; pricing: ProviderPricing;
  transport_terminated?: boolean;
}
export interface ProviderUsage { prompt_tokens: number; completion_tokens: number }
export type ProviderInvocationState = 'queued' | 'running' | 'proposed' | 'fallback' | 'cancelled' | 'uncertain';
export interface ProviderInvocation {
  schema_version: '1.0'; project_id: string; run_id: string; analysis_id: string;
  invocation_id: string; invocation_state: ProviderInvocationState; status: string; deterministic_category: Category;
  proposal: { category: Category; hypotheses: Array<{ text: string; evidence_ids: string[] }>; contradictory_evidence_ids: string[]; missing_evidence: string[] } | null;
  reason: string | null; usage: ProviderUsage | null; usage_complete: boolean; estimated_cost: number | null;
  known_estimated_cost: number | null; cost_complete: boolean; cost_status: string; prompt_version: string; validation_status: string;
  attempts: ProviderAttempt[]; budget: ProviderBudget | null;
  job_id: string | null; analysis_revision: number; analysis_digest: string; evidence_digest: string;
  configuration_digest: string; preview_digest: string | null; created_at: string; completed_at: string | null;
  cancel_requested_at: string | null; recovery_required: boolean;
}
export interface ProviderInvocationPage { schema_version: '1.0'; items: ProviderInvocation[]; limit: number; truncated: boolean }
export interface ProviderSubmission { analysis_revision: number; preview_digest: string; configuration_digest: string; idempotency_key: string }

export const providerTerminal = (job: ProviderInvocation): boolean => ['proposed', 'fallback', 'cancelled', 'uncertain'].includes(job.invocation_state);
export const providerNeedsObservation = (job: ProviderInvocation): boolean => !providerTerminal(job) || (job.invocation_state === 'cancelled' && job.recovery_required);
export const providerStateLabel = (job: ProviderInvocation): string => {
  if (job.invocation_state === 'cancelled' && job.recovery_required) return 'Cancellation recorded · accounting pending';
  if (job.recovery_required) return 'Recovery required';
  if (job.cancel_requested_at && !providerTerminal(job)) return 'Cancellation requested';
  return ({ queued: 'Queued', running: 'Running', proposed: 'Unverified proposal available', fallback: 'Deterministic fallback', cancelled: 'Cancelled', uncertain: 'Interrupted · outcome uncertain' })[job.invocation_state];
};
export function canCancelProvider(principal: Principal, projectId: string): boolean {
  return principal.kind === 'user' && Boolean(principal.user_id) && (principal.system_admin || principal.memberships.some(member => member.project_id === projectId && member.role === 'administrator'));
}
export function canInvokeProvider(principal: Principal, projectId: string): boolean {
  return !principal.demo_mode && canCancelProvider(principal, projectId);
}
export const providerEvidenceUrl = (id: string): string => `/api/v1/evidence/${encodeURIComponent(id)}`;
export function providerCostLabel(cost: number | null, status: string, pricing: ProviderPricing | null): string {
  if (status !== 'estimated' || cost === null || !Number.isFinite(cost) || !pricing?.currency || !pricing.date || !pricing.source || pricing.input_price_per_million === null || pricing.output_price_per_million === null) return 'Unknown cost';
  return `${cost.toLocaleString(undefined, { maximumFractionDigits: 8 })} ${pricing.currency} estimated`;
}

// Validate the safe public projection before it can enter the UI. Never display an
// HTTP error body: a proxy or provider error can contain raw output or secrets.
export class ProviderApiError extends Error {
  constructor(public status: number, message: string) { super(message); }
}
const object = (value: unknown): value is Record<string, unknown> => Boolean(value) && typeof value === 'object' && !Array.isArray(value);
// Python/Pydantic string bounds count Unicode code points, while JS .length
// counts UTF-16 code units. Iterate with an early exit to match the wire contract
// for astral characters without allocating an unbounded character array.
const text = (value: unknown, max = 1200, min = 0): value is string => {
  if (typeof value !== 'string') return false;
  let count = 0;
  for (const _character of value) {
    if (++count > max) return false;
  }
  return count >= min;
};
const nullableText = (value: unknown, max = 1200): boolean => value === null || text(value, max);
const number = (value: unknown): value is number => typeof value === 'number' && Number.isFinite(value) && value >= 0;
const nullableNumber = (value: unknown): boolean => value === null || number(value);
const digest = (value: unknown): boolean => typeof value === 'string' && /^[a-f0-9]{64}$/.test(value);
const nullableDigest = (value: unknown): boolean => value === null || digest(value);
const strings = (value: unknown, max = 20, minLength = 0): value is string[] => Array.isArray(value) && value.length <= max && value.every(item => text(item, 1200, minLength));
const category = (value: unknown): boolean => ['product_defect', 'test_defect', 'infrastructure_failure', 'known_flake', 'insufficient_evidence'].includes(String(value));
const usage = (value: unknown): boolean => value === null || (object(value) && number(value.prompt_tokens) && number(value.completion_tokens));
const pricing = (value: unknown): boolean => value === null || (object(value) && nullableNumber(value.input_price_per_million) && nullableNumber(value.output_price_per_million) && nullableText(value.source) && nullableText(value.date) && nullableText(value.currency));
const limitNames = ['max_attempts', 'max_output_tokens', 'max_context_bytes', 'max_response_bytes', 'max_run_requests', 'max_run_reserved_tokens', 'concurrency', 'min_interval_seconds', 'timeout_seconds'];
function validateStatus(value: unknown, projectId: string): asserts value is ProviderStatus {
  if (!object(value) || value.schema_version !== '1.0' || value.project_id !== projectId || !['ready', 'disabled', 'invalid_configuration', 'project_not_allowed', 'evidence_unavailable', 'rate_limited', 'circuit_open', 'recovery_required', 'worker_unavailable', 'concurrency_limited', 'run_budget_exhausted'].includes(String(value.availability)) || !nullableText(value.reason) || typeof value.can_submit !== 'boolean' || !nullableDigest(value.configuration_digest) || !pricing(value.pricing) || !['unknown', 'estimate_available'].includes(String(value.cost_status)) || !text(value.notice, 4000) || !(value.limits === null || (object(value.limits) && limitNames.every(key => number((value.limits as Record<string, unknown>)[key])))) || !(value.destination === null || (object(value.destination) && text(value.destination.provider_identity) && text(value.destination.endpoint, 2048) && text(value.destination.model))) || !(value.admission === null || (object(value.admission) && number(value.admission.active_permits) && number(value.admission.concurrency) && nullableText(value.admission.next_allowed_at) && nullableText(value.admission.circuit_open_until) && typeof value.admission.recovery_required === 'boolean' && typeof value.admission.worker_available === 'boolean'))) throw new Error('Invalid provider status. Refresh before requesting a proposal.');
}
function validatePreview(value: unknown, scope: ProviderScope): asserts value is ProviderPreview {
  validateStatus(value, scope.projectId);
  const item = value as unknown as Record<string, unknown>;
  // Preview contains the exact redacted request evidence. The backend enforces
  // its configured total UTF-8 JSON context ceiling (at most 100,000 bytes).
  // Match that maximum display bound; do not reconstruct provider JSON framing.
  if (item.run_id !== scope.runId || item.analysis_id !== scope.analysisId || !Number.isInteger(item.analysis_revision) || !number(item.analysis_revision) || !nullableDigest(item.analysis_digest) || !nullableDigest(item.evidence_digest) || !nullableDigest(item.preview_digest) || !text(item.prompt_version) || !nullableNumber(item.reserved_tokens_per_attempt) || !(item.budget === undefined || item.budget === null || (object(item.budget) && ['requests', 'reserved_tokens', 'max_requests', 'max_reserved_tokens'].every(key => number((item.budget as Record<string, unknown>)[key])))) || !Array.isArray(item.evidence) || item.evidence.length > 100 || !item.evidence.every(row => object(row) && text(row.id) && text(row.excerpt, 100_000))) throw new Error('Invalid provider preview. Refresh before requesting a proposal.');
}
function validateInvocation(value: unknown, scope: ProviderScope): asserts value is ProviderInvocation {
  if (!object(value) || value.schema_version !== '1.0' || value.project_id !== scope.projectId || value.run_id !== scope.runId || value.analysis_id !== scope.analysisId || !text(value.invocation_id, 200) || !['queued', 'running', 'proposed', 'fallback', 'cancelled', 'uncertain'].includes(String(value.invocation_state)) || !text(value.status) || !category(value.deterministic_category) || !nullableText(value.reason) || !usage(value.usage) || typeof value.usage_complete !== 'boolean' || !nullableNumber(value.estimated_cost) || !nullableNumber(value.known_estimated_cost) || typeof value.cost_complete !== 'boolean' || !text(value.cost_status) || !text(value.prompt_version) || !text(value.validation_status) || !Number.isInteger(value.analysis_revision) || !number(value.analysis_revision) || !['analysis_digest', 'evidence_digest', 'configuration_digest'].every(key => digest(value[key])) || !nullableDigest(value.preview_digest) || !text(value.created_at) || !nullableText(value.completed_at) || !nullableText(value.cancel_requested_at) || typeof value.recovery_required !== 'boolean' || !nullableText(value.job_id) || !Array.isArray(value.attempts) || value.attempts.length > 3 || !value.attempts.every(row => object(row) && number(row.number) && text(row.status) && nullableText(row.reason) && nullableNumber(row.http_status) && number(row.reserved_tokens) && number(row.accounted_tokens) && text(row.spend_status) && usage(row.usage) && nullableNumber(row.estimated_cost) && text(row.cost_status) && row.pricing !== null && pricing(row.pricing)) || !(value.budget === null || (object(value.budget) && ['requests', 'reserved_tokens', 'max_requests', 'max_reserved_tokens'].every(key => number((value.budget as Record<string, unknown>)[key]))))) throw new Error('Invalid provider invocation. Refresh to check persisted state.');
  const proposal = value.proposal;
  if (proposal !== null && (!object(proposal) || !category(proposal.category) || !Array.isArray(proposal.hypotheses) || proposal.hypotheses.length > 10 || !proposal.hypotheses.every(row => object(row) && text(row.text, 1200, 1) && strings(row.evidence_ids)) || !strings(proposal.contradictory_evidence_ids) || !strings(proposal.missing_evidence, 20, 1))) throw new Error('Invalid provider proposal. Deterministic analysis remains available.');
}
const base = (scope: ProviderScope) => `/api/v1/projects/${encodeURIComponent(scope.projectId)}/runs/${encodeURIComponent(scope.runId)}/analyses/${encodeURIComponent(scope.analysisId)}/provider`;
async function request(url: string, init?: RequestInit): Promise<unknown> {
  let response: Response;
  try { response = await fetch(url, { ...init, credentials: 'include' }); }
  catch (error) {
    if (error instanceof Error && error.name === 'AbortError') throw error;
    throw new ProviderApiError(0, 'Provider service could not be reached. A submitted job may still exist; refresh or retry the same submission.');
  }
  if (!response.ok) {
    if (response.status === 401 && typeof window !== 'undefined') window.dispatchEvent(new Event('failurelens:session-expired'));
    const reason = response.status === 409 ? 'The preview or configuration changed. Refresh and review the current scope.' : response.status === 403 ? 'Your session is not authorized for this provider action.' : response.status === 503 ? 'Optional provider is unavailable. Deterministic analysis remains available.' : 'Check project access and retained evidence.';
    throw new ProviderApiError(response.status, `Provider request failed (${response.status}). ${reason}`);
  }
  try { return await response.json(); } catch { throw new Error('Invalid provider response. Refresh to check persisted state.'); }
}
const post = (body?: unknown): RequestInit => ({ method: 'POST', headers: { 'Content-Type': 'application/json' }, ...(body === undefined ? {} : { body: JSON.stringify(body) }) });
export const providerApi = {
  async status(projectId: string, signal?: AbortSignal): Promise<ProviderStatus> {
    const value = await request(`/api/v1/projects/${encodeURIComponent(projectId)}/provider/status`, { signal }); validateStatus(value, projectId); return value;
  },
  async preview(scope: ProviderScope, signal?: AbortSignal): Promise<ProviderPreview> {
    const value = await request(`${base(scope)}/preview`, { signal }); validatePreview(value, scope); return value;
  },
  async list(scope: ProviderScope, signal?: AbortSignal): Promise<ProviderInvocationPage> {
    const value = await request(`${base(scope)}/invocations`, { signal });
    if (!object(value) || value.schema_version !== '1.0' || !Array.isArray(value.items) || value.items.length > 50 || value.limit !== 50 || typeof value.truncated !== 'boolean') throw new Error('Invalid provider history. Refresh to check persisted state.');
    for (const item of value.items) validateInvocation(item, scope);
    return value as unknown as ProviderInvocationPage;
  },
  async submit(scope: ProviderScope, body: ProviderSubmission): Promise<ProviderInvocation> {
    const value = await request(`${base(scope)}/invocations`, post(body)); validateInvocation(value, scope); return value;
  },
  async cancel(scope: ProviderScope, id: string): Promise<ProviderInvocation> {
    const value = await request(`${base(scope)}/invocations/${encodeURIComponent(id)}/cancel`, post()); validateInvocation(value, scope);
    if (value.invocation_id !== id) throw new Error('Cancellation response did not match the requested job. Refresh persisted state.');
    return value;
  }
};
