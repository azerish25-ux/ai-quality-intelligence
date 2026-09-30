import { afterEach, describe, expect, it, vi } from 'vitest';
import { canCancelProvider, canInvokeProvider, providerApi, providerCostLabel, providerEvidenceUrl, providerStateLabel, providerTerminal } from './provider-api';
import { providerTestJob as job, providerTestPreview as preview, providerTestPrincipal as principal, providerTestScope as scope } from './provider-fixtures';

afterEach(() => vi.unstubAllGlobals());
function mock(value: unknown, status = 200) { const fetcher = vi.fn().mockResolvedValue(new Response(JSON.stringify(value), { status })); vi.stubGlobal('fetch', fetcher); return fetcher; }
describe('optional provider API boundary', () => {
  it('fetches the exact scoped preview with cookie credentials and GET cancellation', async () => {
    const fetcher = mock(preview); const controller = new AbortController();
    expect(await providerApi.preview(scope, controller.signal)).toEqual(preview);
    expect(fetcher).toHaveBeenCalledWith('/api/v1/projects/project-1/runs/run-1/analyses/analysis-1/provider/preview', { signal: controller.signal, credentials: 'include' });
  });
  it('loads project-level status independently of a selected analysis', async () => {
    const fetcher = mock(preview); await providerApi.status(scope.projectId);
    expect(fetcher.mock.calls[0][0]).toBe('/api/v1/projects/project-1/provider/status');
  });
  it.each(['disabled', 'invalid_configuration', 'project_not_allowed', 'evidence_unavailable', 'rate_limited', 'circuit_open', 'recovery_required', 'worker_unavailable', 'concurrency_limited', 'run_budget_exhausted'])('preserves safe unavailable state %s', async availability => {
    mock({ ...preview, availability, can_submit: false }); expect((await providerApi.preview(scope)).availability).toBe(availability);
  });
  it.each([{ ...preview, run_id: 'another-run' }, { ...preview, project_id: 'another-project' }, { ...preview, analysis_id: 'old-analysis' }, { ...preview, preview_digest: 'fake' }, { ...preview, evidence: [{ id: 'evidence-1', excerpt: 'x'.repeat(100001) }] }, { ...preview, limits: { ...preview.limits, max_output_tokens: -1 } }, { ...preview, admission: { ...preview.admission, worker_available: 'yes' } }])('rejects mismatched or malformed approval scope', async value => {
    mock(value); await expect(providerApi.preview(scope)).rejects.toThrow('Invalid provider');
  });
  it('accepts a preview excerpt above 32k under the supported 100k context configuration', async () => {
    const configured = { ...preview, limits: { ...preview.limits, max_context_bytes: 100_000 }, evidence: [{ id: 'evidence-1', excerpt: 'x'.repeat(40_000) }] };
    mock(configured); expect(await providerApi.preview(scope)).toEqual(configured);
  });
  it.each([null, 17, {}, ['nested']])('still rejects malformed preview excerpts: %j', async excerpt => {
    mock({ ...preview, evidence: [{ id: 'evidence-1', excerpt }] });
    await expect(providerApi.preview(scope)).rejects.toThrow('Invalid provider preview');
  });
  it('submits only bound identity and idempotency, with no endpoint, credential, prompt or evidence body', async () => {
    const fetcher = mock(job, 202);
    const body = { analysis_revision: 1, preview_digest: preview.preview_digest!, configuration_digest: preview.configuration_digest!, idempotency_key: 'synthetic-intent-1' };
    expect(await providerApi.submit(scope, body)).toEqual(job);
    expect(fetcher.mock.calls[0][1]).toEqual({ method: 'POST', credentials: 'include', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(body) });
    expect(fetcher.mock.calls[0][1].signal).toBeUndefined();
  });
  it('cancels with a persisted POST, never a browser abort', async () => {
    const fetcher = mock({ ...job, cancel_requested_at: '2026-09-30T12:01:00Z' });
    await providerApi.cancel(scope, job.invocation_id);
    expect(fetcher.mock.calls[0][0]).toMatch(/\/invocations\/invocation-1\/cancel$/);
    expect(fetcher.mock.calls[0][1]).toEqual({ method: 'POST', credentials: 'include', headers: { 'Content-Type': 'application/json' } });
  });
  it('rejects cancellation responses for another job', async () => {
    mock({ ...job, invocation_id: 'another-job' }); await expect(providerApi.cancel(scope, job.invocation_id)).rejects.toThrow('did not match');
  });
  it.each([403, 409, 500, 503])('does not expose error bodies for %s', async status => {
    mock({ detail: 'PRIVATE_PROVIDER_TOKEN raw response' }, status);
    await expect(providerApi.preview(scope)).rejects.toThrow(`(${status})`);
    await expect(providerApi.preview(scope)).rejects.not.toThrow('PRIVATE_PROVIDER_TOKEN');
  });
  it('expires the authenticated UI on 401', async () => {
    const dispatchEvent = vi.fn(); vi.stubGlobal('window', { dispatchEvent }); mock({}, 401);
    await expect(providerApi.list(scope)).rejects.toThrow('(401)'); expect(dispatchEvent.mock.calls[0][0].type).toBe('failurelens:session-expired');
  });
  it('bounds history and validates every returned job scope', async () => {
    mock({ schema_version: '1.0', limit: 50, truncated: false, items: [{ ...job, analysis_id: 'other' }] });
    await expect(providerApi.list(scope)).rejects.toThrow('Invalid provider invocation');
    mock({ schema_version: '1.0', limit: 50, truncated: false, items: Array(51).fill(job) });
    await expect(providerApi.list(scope)).rejects.toThrow('Invalid provider history');
  });
  it.each(['text', 'missing_evidence'] as const)('accepts exactly 1200 astral code points in proposal %s', async field => {
    const astral = '🧪'.repeat(1200);
    const proposal = { category: 'product_defect', hypotheses: [{ text: field === 'text' ? astral : 'Unverified hypothesis', evidence_ids: [] }], contradictory_evidence_ids: [], missing_evidence: field === 'missing_evidence' ? [astral] : [] };
    mock({ schema_version: '1.0', limit: 50, truncated: false, items: [{ ...job, invocation_state: 'proposed', proposal }] });
    expect((await providerApi.list(scope)).items[0].proposal).toEqual(proposal);
  });
  it.each(['text', 'missing_evidence'] as const)('rejects 1201 astral code points in proposal %s', async field => {
    const astral = '🧪'.repeat(1201);
    const proposal = { category: 'product_defect', hypotheses: [{ text: field === 'text' ? astral : 'Unverified hypothesis', evidence_ids: [] }], contradictory_evidence_ids: [], missing_evidence: field === 'missing_evidence' ? [astral] : [] };
    mock({ schema_version: '1.0', limit: 50, truncated: false, items: [{ ...job, invocation_state: 'proposed', proposal }] });
    await expect(providerApi.list(scope)).rejects.toThrow('Invalid provider proposal');
  });
  it.each(['text', 'missing_evidence'] as const)('rejects empty proposal %s entries', async field => {
    const proposal = { category: 'product_defect', hypotheses: [{ text: field === 'text' ? '' : 'Unverified hypothesis', evidence_ids: [] }], contradictory_evidence_ids: [], missing_evidence: field === 'missing_evidence' ? [''] : [] };
    mock({ schema_version: '1.0', limit: 50, truncated: false, items: [{ ...job, invocation_state: 'proposed', proposal }] });
    await expect(providerApi.list(scope)).rejects.toThrow('Invalid provider proposal');
  });
  it.each([null, 17, {}, ['nested'], 'x'.repeat(1201)])('rejects malformed or oversized missing-evidence entries: %j', async entry => {
    mock({ schema_version: '1.0', limit: 50, truncated: false, items: [{ ...job, invocation_state: 'proposed', proposal: { category: 'product_defect', hypotheses: [], contradictory_evidence_ids: [], missing_evidence: [entry] } }] });
    await expect(providerApi.list(scope)).rejects.toThrow('Invalid provider proposal');
  });
  it('encodes evidence IDs into existing authorized evidence routes', () => {
    expect(providerEvidenceUrl('id/../secret?x=1')).toBe('/api/v1/evidence/id%2F..%2Fsecret%3Fx%3D1');
  });
});
describe('authorization and truthful job labels', () => {
  it('excludes demo, ingestion and nonadministrator users even if other fields imply admin', () => {
    expect(canInvokeProvider(principal, scope.projectId)).toBe(true);
    expect(canInvokeProvider({ ...principal, user_id: null }, scope.projectId)).toBe(false);
    expect(canInvokeProvider({ ...principal, kind: 'demo', system_admin: true }, scope.projectId)).toBe(false);
    expect(canInvokeProvider({ ...principal, kind: 'ingestion_token', system_admin: true }, scope.projectId)).toBe(false);
    expect(canInvokeProvider({ ...principal, memberships: [{ ...principal.memberships[0], role: 'viewer' }] }, scope.projectId)).toBe(false);
    expect(canInvokeProvider(principal, 'other-project')).toBe(false);
  });
  it('never labels a cancellation request as completed cancellation', () => {
    const pending = { ...job, invocation_state: 'running' as const, cancel_requested_at: '2026-09-30T12:01:00Z' };
    expect(providerStateLabel(pending)).toBe('Cancellation requested'); expect(providerTerminal(pending)).toBe(false);
    expect(providerStateLabel({ ...pending, invocation_state: 'proposed' })).toBe('Unverified proposal available');
    expect(providerStateLabel({ ...job, invocation_state: 'uncertain', recovery_required: true })).toBe('Recovery required');
  });
  it('keeps unknown cost distinct from zero and requires complete dated estimate provenance', () => {
    const pricing = { input_price_per_million: 1, output_price_per_million: 2, currency: 'USD', source: 'Synthetic fixture', date: '2026-09-30' };
    expect(providerCostLabel(null, 'unknown', pricing)).toBe('Unknown cost');
    expect(providerCostLabel(0, 'unknown', pricing)).toBe('Unknown cost');
    expect(providerCostLabel(0, 'estimated', pricing)).toBe('0 USD estimated');
    expect(providerCostLabel(1, 'estimated', { ...pricing, date: null })).toBe('Unknown cost');
  });
  it('blocks submission for authenticated administrators in demo mode while permitting cancellation', () => {
    const demoAdministrator = { ...principal, demo_mode: true };
    expect(canInvokeProvider(demoAdministrator, scope.projectId)).toBe(false);
    expect(canCancelProvider(demoAdministrator, scope.projectId)).toBe(true);
    expect(canCancelProvider({ ...demoAdministrator, kind: 'demo' }, scope.projectId)).toBe(false);
  });
});
