import { providerApi, providerNeedsObservation, providerTerminal, ProviderApiError, type ProviderInvocation, type ProviderPreview, type ProviderScope, type ProviderSubmission } from './provider-api';

export interface ProviderPanelState {
  preview: ProviderPreview | null; jobs: ProviderInvocation[]; truncated: boolean;
  loading: boolean; busy: 'submit' | 'cancel' | null; error: string; notice: string; pendingSubmission: boolean;
  pendingIdentity: Omit<ProviderSubmission, 'idempotency_key'> | null;
}
interface Storage { getItem(key: string): string | null; setItem(key: string, value: string): void; removeItem(key: string): void }
const errorMessage = (error: unknown): string => error instanceof Error ? error.message : 'Provider state could not be loaded.';

// The controller owns an exact analysis/principal scope. Stopping observation only
// aborts GETs; submission and cancellation are persisted server operations.
export class ProviderSession {
  private state: ProviderPanelState;
  private listeners = new Set<() => void>();
  private generation = 0;
  private active = false;
  private request = 0;
  private observation: AbortController | null = null;
  private timer: ReturnType<typeof setTimeout> | null = null;
  private pending: ProviderSubmission | null = null;
  private storageKey: string;
  constructor(private scope: ProviderScope, principalKey: string, private allowed: boolean, private client = providerApi, private storage?: Storage, private cancelAllowed = allowed) {
    this.storageKey = `loose-thread:provider-intent:${JSON.stringify([principalKey, scope.projectId, scope.runId, scope.analysisId])}`;
    try {
      const raw = storage?.getItem(this.storageKey);
      if (raw) {
        const value = JSON.parse(raw) as Partial<ProviderSubmission>;
        if (Number.isInteger(value.analysis_revision) && typeof value.idempotency_key === 'string' && /^[a-zA-Z0-9-]{1,200}$/.test(value.idempotency_key) && /^[a-f0-9]{64}$/.test(value.preview_digest ?? '') && /^[a-f0-9]{64}$/.test(value.configuration_digest ?? '')) this.pending = { analysis_revision: value.analysis_revision!, preview_digest: value.preview_digest!, configuration_digest: value.configuration_digest!, idempotency_key: value.idempotency_key };
      }
    } catch { /* Storage may be unavailable; a live session still retains its key. */ }
    this.state = { preview: null, jobs: [], truncated: false, loading: true, busy: null, error: '', notice: '', pendingSubmission: Boolean(this.pending), pendingIdentity: this.pending ? { analysis_revision: this.pending.analysis_revision, preview_digest: this.pending.preview_digest, configuration_digest: this.pending.configuration_digest } : null };
  }
  getSnapshot = (): ProviderPanelState => this.state;
  subscribe = (listener: () => void): (() => void) => { this.listeners.add(listener); return () => this.listeners.delete(listener); };
  private update(patch: Partial<ProviderPanelState>): void { this.state = { ...this.state, ...patch }; this.listeners.forEach(listener => listener()); }
  private current(generation: number): boolean { return this.active && generation === this.generation; }
  start(): void { this.active = true; this.generation++; void this.refresh(); }
  stop(): void {
    this.active = false; this.generation++; this.observation?.abort();
    if (this.timer) clearTimeout(this.timer);
    this.timer = null;
  }
  private schedule(): void {
    if (this.timer) clearTimeout(this.timer);
    if (this.active && this.state.jobs.some(providerNeedsObservation)) this.timer = setTimeout(() => { void this.refresh(false); }, this.state.error ? 4000 : 1500);
  }
  async refresh(withPreview = true): Promise<void> {
    if (!this.active) return;
    const generation = this.generation;
    const sequence = ++this.request;
    this.observation?.abort();
    const controller = new AbortController(); this.observation = controller;
    if (withPreview) this.update({ loading: true, error: '' });
    const results = await Promise.allSettled([
      // Refresh admission/budget truth along with jobs, including when a cancelled
      // transport settles or a terminal job exhausts its persisted run budget.
      this.client.preview(this.scope, controller.signal),
      this.client.list(this.scope, controller.signal)
    ]);
    if (!this.current(generation) || sequence !== this.request || controller.signal.aborted) return;
    const [preview, jobs] = results;
    const patch: Partial<ProviderPanelState> = { loading: false, error: '' };
    if (preview.status === 'fulfilled') patch.preview = preview.value;
    else { patch.preview = null; patch.error = errorMessage(preview.reason); }
    if (jobs.status === 'fulfilled') { patch.jobs = jobs.value.items; patch.truncated = jobs.value.truncated; }
    else patch.error = errorMessage(jobs.reason);
    this.update(patch); this.schedule();
  }
  private remember(body: ProviderSubmission | null): void {
    this.pending = body;
    try { if (body) this.storage?.setItem(this.storageKey, JSON.stringify(body)); else this.storage?.removeItem(this.storageKey); } catch { /* In-memory duplicate protection remains active. */ }
    if (this.active) this.update({ pendingIdentity: body ? { analysis_revision: body.analysis_revision, preview_digest: body.preview_digest, configuration_digest: body.configuration_digest } : null });
  }
  async submit(): Promise<void> {
    const preview = this.state.preview;
    if (!this.active || this.state.busy || this.state.loading || !this.allowed) return;
    if (!this.pending && (!preview?.can_submit || preview.availability !== 'ready' || !preview.preview_digest || !preview.configuration_digest || this.state.jobs.some(job => !providerTerminal(job) || job.recovery_required))) return;
    const generation = this.generation;
    const body = this.pending ?? { analysis_revision: preview!.analysis_revision, preview_digest: preview!.preview_digest!, configuration_digest: preview!.configuration_digest!, idempotency_key: crypto.randomUUID() };
    this.remember(body);
    this.update({ busy: 'submit', error: '', notice: 'Submitting the reviewed scope…', pendingSubmission: true });
    try {
      const job = await this.client.submit(this.scope, body);
      this.remember(null);
      if (!this.current(generation)) return;
      // Invalidate older GETs, including a poll started before this mutation.
      this.request++; this.observation?.abort();
      this.update({ jobs: [job, ...this.state.jobs.filter(item => item.invocation_id !== job.invocation_id)], pendingSubmission: false, notice: 'Submission persisted. Navigating away stops updates; it does not cancel this job.' });
    } catch (error) {
      if (!this.current(generation)) return;
      if (error instanceof ProviderApiError && error.status >= 400 && error.status < 500 && error.status !== 408 && error.status !== 429) this.remember(null);
      this.update({ error: errorMessage(error), pendingSubmission: Boolean(this.pending), notice: this.pending ? 'Submission outcome is unconfirmed. Retry uses the same idempotency key; it will not request a duplicate attempt.' : 'Refresh the preview and confirm its current scope before trying again.', preview: this.pending ? this.state.preview : null });
    } finally {
      if (this.current(generation)) { this.update({ busy: null }); this.schedule(); }
    }
  }
  async cancel(id: string): Promise<void> {
    const job = this.state.jobs.find(item => item.invocation_id === id);
    if (!this.active || !this.cancelAllowed || this.state.busy || !job || providerTerminal(job) || job.cancel_requested_at) return;
    const generation = this.generation;
    this.update({ busy: 'cancel', error: '', notice: 'Persisting cancellation request…' });
    try {
      const updated = await this.client.cancel(this.scope, id);
      if (!this.current(generation)) return;
      this.request++; this.observation?.abort();
      this.update({ jobs: this.state.jobs.map(item => item.invocation_id === id ? updated : item), notice: providerTerminal(updated) ? 'The server returned the final job state. Any recorded usage remains accounted for.' : 'Cancellation requested on the server. In-flight work may finish and still incur usage.' });
    } catch (error) {
      if (this.current(generation)) this.update({ error: errorMessage(error), notice: 'Cancellation is unconfirmed. The job may continue; refresh its persisted state.' });
    } finally {
      if (this.current(generation)) { this.update({ busy: null }); this.schedule(); }
    }
  }
}
