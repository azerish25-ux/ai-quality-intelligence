import { afterEach, describe, expect, it, vi } from 'vitest';
import { ProviderApiError, type providerApi, type ProviderInvocation, type ProviderInvocationPage } from './provider-api';
import { ProviderSession } from './provider-session';
import { providerTestJob as job, providerTestPreview as preview, providerTestScope as scope } from './provider-fixtures';

const page = (items: ProviderInvocation[] = []): ProviderInvocationPage => ({ schema_version: '1.0', items, limit: 50, truncated: false });
const deferred = <T>() => { let resolve!: (value: T) => void; const promise = new Promise<T>(done => { resolve = done; }); return { promise, resolve }; };
const tick = async () => { for (let i = 0; i < 8; i++) await Promise.resolve(); };
function setup(allowed = true, storage?: Pick<Storage, 'getItem' | 'setItem' | 'removeItem'>) {
  const client = { status: vi.fn(), preview: vi.fn().mockResolvedValue(preview), list: vi.fn().mockResolvedValue(page()), submit: vi.fn().mockResolvedValue(job), cancel: vi.fn().mockResolvedValue({ ...job, invocation_state: 'cancelled' }) } satisfies typeof providerApi;
  const session = new ProviderSession(scope, 'user-1', allowed, client, storage); return { client, session };
}
afterEach(() => { vi.useRealTimers(); });
describe('provider observation and durable mutation controller', () => {
  it('loads preview and persisted history together, then restores existing active jobs', async () => {
    const { session, client } = setup(); client.list.mockResolvedValue(page([job])); session.start(); await tick();
    expect(session.getSnapshot()).toMatchObject({ preview, jobs: [job], loading: false }); session.stop();
  });
  it('suppresses older GETs after a newer refresh even if transport ignores abort', async () => {
    const { session, client } = setup(); const old = deferred<ProviderInvocationPage>(); client.list.mockReturnValueOnce(old.promise);
    session.start(); await session.refresh(); old.resolve(page([job])); await tick();
    expect(session.getSnapshot().jobs).toEqual([]); session.stop();
  });
  it('does not publish an old selected analysis response after navigation or logout', async () => {
    const { session, client } = setup(); const old = deferred<ProviderInvocationPage>(); client.list.mockReturnValue(old.promise);
    session.start(); session.stop(); old.resolve(page([job])); await tick();
    expect(session.getSnapshot().jobs).toEqual([]); expect(client.cancel).not.toHaveBeenCalled();
    expect(client.list.mock.calls[0][1]?.aborted).toBe(true);
  });
  it('survives StrictMode observation cleanup and restart', async () => {
    const { session } = setup(); session.start(); session.stop(); session.start(); await tick();
    expect(session.getSnapshot().preview).toEqual(preview); session.stop();
  });
  it('serializes double clicks and retains the same idempotency key after an ambiguous failure', async () => {
    const { session, client } = setup(); const submitted = deferred<ProviderInvocation>(); client.submit.mockReturnValueOnce(submitted.promise);
    session.start(); await tick(); const first = session.submit(); const duplicate = session.submit();
    expect(client.submit).toHaveBeenCalledTimes(1); submitted.resolve(job); await Promise.all([first, duplicate]); session.stop();
    const second = setup(); second.client.submit.mockRejectedValueOnce(new ProviderApiError(0, 'network failure'));
    second.session.start(); await tick(); await second.session.submit(); const body = second.client.submit.mock.calls[0][1];
    expect(second.session.getSnapshot().pendingSubmission).toBe(true); await second.session.submit();
    expect(second.client.submit.mock.calls[1][1]).toEqual(body); second.session.stop();
  });
  it('restores a pending idempotency identity after refresh without automatically submitting', async () => {
    const values = new Map<string, string>(); const storage = { getItem: (key: string) => values.get(key) ?? null, setItem: (key: string, value: string) => { values.set(key, value); }, removeItem: (key: string) => { values.delete(key); } };
    const first = setup(true, storage); first.client.submit.mockRejectedValue(new ProviderApiError(0, 'network failure'));
    first.session.start(); await tick(); await first.session.submit(); const body = first.client.submit.mock.calls[0][1]; first.session.stop();
    const next = setup(true, storage); next.session.start(); await tick(); expect(next.client.submit).not.toHaveBeenCalled();
    await next.session.submit(); expect(next.client.submit.mock.calls[0][1]).toEqual(body); expect(values.size).toBe(0); next.session.stop();
  });
  it('leaves server submission running after UI teardown without pretending to cancel it', async () => {
    const { session, client } = setup(); const submitted = deferred<ProviderInvocation>(); client.submit.mockReturnValueOnce(submitted.promise);
    session.start(); await tick(); const result = session.submit(); session.stop(); submitted.resolve(job); await result;
    expect(session.getSnapshot().jobs).toEqual([]); expect(client.cancel).not.toHaveBeenCalled();
  });
  it('prevents an older poll from replacing a persisted cancellation response', async () => {
    const { session, client } = setup(); client.list.mockResolvedValue(page([job])); session.start(); await tick();
    const old = deferred<ProviderInvocationPage>(); client.list.mockReturnValueOnce(old.promise); const poll = session.refresh(false);
    await session.cancel(job.invocation_id); old.resolve(page([job])); await poll;
    expect(session.getSnapshot().jobs[0].invocation_state).toBe('cancelled'); session.stop();
  });
  it('shows server truth when completion wins a cancellation race', async () => {
    const { session, client } = setup(); client.list.mockResolvedValue(page([job])); client.cancel.mockResolvedValue({ ...job, invocation_state: 'proposed', cancel_requested_at: null });
    session.start(); await tick(); await session.cancel(job.invocation_id);
    expect(session.getSnapshot().jobs[0].invocation_state).toBe('proposed'); expect(session.getSnapshot().notice).toContain('final job state'); session.stop();
  });
  it('does not mark a failed cancellation as cancelled', async () => {
    const { session, client } = setup(); client.list.mockResolvedValue(page([job])); client.cancel.mockRejectedValue(new ProviderApiError(503, 'unavailable'));
    session.start(); await tick(); await session.cancel(job.invocation_id);
    expect(session.getSnapshot().jobs[0].invocation_state).toBe('queued'); expect(session.getSnapshot().notice).toContain('Cancellation is unconfirmed'); session.stop();
  });
  it('blocks demo/viewer mutation and duplicates while active or recovery is required', async () => {
    const denied = setup(false); denied.client.list.mockResolvedValue(page([job])); denied.session.start(); await tick(); await denied.session.submit(); await denied.session.cancel(job.invocation_id);
    expect(denied.client.submit).not.toHaveBeenCalled(); expect(denied.client.cancel).not.toHaveBeenCalled(); denied.session.stop();
    for (const state of [job, { ...job, invocation_state: 'uncertain' as const, recovery_required: true }]) {
      const current = setup(); current.client.list.mockResolvedValue(page([state])); current.session.start(); await tick(); await current.session.submit(); expect(current.client.submit).not.toHaveBeenCalled(); current.session.stop();
    }
  });
  it('requires a fresh reviewed preview after a stale-configuration rejection', async () => {
    const { session, client } = setup(); client.submit.mockRejectedValue(new ProviderApiError(409, 'changed'));
    session.start(); await tick(); await session.submit(); expect(session.getSnapshot()).toMatchObject({ preview: null, pendingSubmission: false }); session.stop();
  });
  it('can stop an existing job after demo-mode submission is disabled', async () => {
    const { client } = setup(); client.list.mockResolvedValue(page([job]));
    const session = new ProviderSession(scope, 'demo-authenticated-admin', false, client, undefined, true);
    session.start(); await tick(); await session.submit(); await session.cancel(job.invocation_id);
    expect(client.submit).not.toHaveBeenCalled(); expect(client.cancel).toHaveBeenCalledWith(scope, job.invocation_id); session.stop();
  });
  it('reconciles the original idempotent submission even after preview or configuration changes', async () => {
    const { session, client } = setup(); client.submit.mockRejectedValueOnce(new ProviderApiError(0, 'network failure'));
    session.start(); await tick(); await session.submit(); const original = client.submit.mock.calls[0][1];
    client.preview.mockResolvedValue({ ...preview, availability: 'disabled', can_submit: false, preview_digest: null }); await session.refresh();
    await session.submit(); expect(client.submit.mock.calls[1][1]).toEqual(original); expect(session.getSnapshot().pendingSubmission).toBe(false); session.stop();
  });
  it('keeps observing cancellation until the server confirms transport accounting is settled', async () => {
    vi.useFakeTimers(); const { session, client } = setup();
    client.list.mockResolvedValueOnce(page([{ ...job, invocation_state: 'cancelled', recovery_required: true }])).mockResolvedValue(page([{ ...job, invocation_state: 'cancelled', recovery_required: false }]));
    session.start(); await tick(); await vi.advanceTimersByTimeAsync(1500); expect(client.list).toHaveBeenCalledTimes(2);
    await vi.advanceTimersByTimeAsync(10000); expect(client.list).toHaveBeenCalledTimes(2); session.stop();
  });
  it('polls active jobs and stops once final persisted state arrives', async () => {
    vi.useFakeTimers(); const { session, client } = setup(); client.list.mockResolvedValueOnce(page([job])).mockResolvedValue(page([{ ...job, invocation_state: 'fallback' }]));
    session.start(); await tick(); await vi.advanceTimersByTimeAsync(1500); expect(client.list).toHaveBeenCalledTimes(2);
    await vi.advanceTimersByTimeAsync(10000); expect(client.list).toHaveBeenCalledTimes(2); session.stop();
  });
});
