import { useEffect, useMemo, useRef, useState, useSyncExternalStore } from 'react';
import type { Analysis, Principal } from './api';
import { canCancelProvider, canInvokeProvider, providerApi, providerCostLabel, providerEvidenceUrl, providerStateLabel, providerTerminal, type ProviderInvocation, type ProviderPreview, type ProviderPricing, type ProviderScope, type ProviderStatus } from './provider-api';
import { ProviderSession } from './provider-session';

const readable = (value: string): string => value.replaceAll('_', ' ');
const availabilityLabel = (value: ProviderStatus['availability']): string => value === 'ready' ? 'Configured for requests' : readable(value);
function Pricing({ pricing }: { pricing: ProviderPricing | null }) {
  if (!pricing || pricing.input_price_per_million === null || pricing.output_price_per_million === null || !pricing.currency || !pricing.source || !pricing.date) return <p className="provider-warning"><strong>Unknown cost.</strong> Complete dated pricing is unavailable. Unknown cost does not mean zero; submitted attempts may incur charges.</p>;
  return <div className="provider-pricing"><p><strong>Configured cost estimate only.</strong> {pricing.input_price_per_million} {pricing.currency} per million input tokens; {pricing.output_price_per_million} {pricing.currency} per million output tokens.</p><p>Pricing source: {pricing.source} · dated {pricing.date}. Actual charges and total token use may differ.</p></div>;
}
function Configuration({ value }: { value: ProviderStatus }) {
  return <>
    <p><strong>{availabilityLabel(value.availability)}</strong>{value.reason ? ` · ${readable(value.reason)}` : ''}</p>
    <p>Configuration status does not verify live provider connectivity. Configuration and credentials are managed by the operator.</p>
    {value.notice && <p className="muted">{value.notice}</p>}
    {value.destination && <dl className="provider-facts"><div><dt>Provider</dt><dd>{value.destination.provider_identity}</dd></div><div><dt>Destination origin</dt><dd>{value.destination.endpoint}</dd></div><div><dt>Model</dt><dd>{value.destination.model}</dd></div></dl>}
    {value.configuration_digest && <p className="provider-digest">Configuration identity: <code>{value.configuration_digest}</code></p>}
    {value.limits && <dl className="provider-facts"><div><dt>Maximum attempts per submission</dt><dd>{value.limits.max_attempts}</dd></div><div><dt>Output token limit per attempt</dt><dd>{value.limits.max_output_tokens}</dd></div><div><dt>Context / response byte limits</dt><dd>{value.limits.max_context_bytes} / {value.limits.max_response_bytes}</dd></div><div><dt>Run request ceiling</dt><dd>{value.limits.max_run_requests}</dd></div><div><dt>Run reserved-token ceiling</dt><dd>{value.limits.max_run_reserved_tokens}</dd></div><div><dt>Concurrency / spacing / timeout</dt><dd>{value.limits.concurrency} / {value.limits.min_interval_seconds}s / {value.limits.timeout_seconds}s</dd></div></dl>}
    {value.admission && <p className="muted">Active attempts: {value.admission.active_permits}/{value.admission.concurrency}. Worker: {value.admission.worker_available ? 'recent configured heartbeat' : 'unavailable'}.{value.admission.next_allowed_at ? ` Next admission: ${value.admission.next_allowed_at}.` : ''}{value.admission.circuit_open_until ? ` Circuit open until ${value.admission.circuit_open_until}.` : ''}{value.admission.recovery_required ? ' Operator recovery is required; an uncertain request will not be automatically resent.' : ''}</p>}
    <Pricing pricing={value.pricing} />
  </>;
}

export function ProviderSettings({ projectId }: { projectId: string }) {
  const [status, setStatus] = useState<ProviderStatus | null>(null);
  const [error, setError] = useState('');
  const [loading, setLoading] = useState(true);
  const [revision, setRevision] = useState(0);
  useEffect(() => {
    const controller = new AbortController(); setStatus(null); setError(''); setLoading(true);
    void providerApi.status(projectId, controller.signal).then(value => { if (!controller.signal.aborted) setStatus(value); }).catch((reason: unknown) => { if (!controller.signal.aborted) setError(reason instanceof Error ? reason.message : 'Provider status unavailable.'); }).finally(() => { if (!controller.signal.aborted) setLoading(false); });
    return () => controller.abort();
  }, [projectId, revision]);
  return <section className="settings-block provider-settings" aria-labelledby="provider-settings-heading">
    <h3 id="provider-settings-heading">Optional provider status</h3>
    <p>Disabled by default. Deterministic analysis works without a model provider.</p>
    {loading && <p role="status">Loading provider configuration status…</p>}
    {error && <p role="alert">{error}</p>}
    {status && <Configuration value={status} />}
    <button type="button" disabled={loading} onClick={() => setRevision(value => value + 1)}>Refresh provider status</button>
  </section>;
}

function EvidenceLinks({ ids }: { ids: string[] }) {
  if (!ids.length) return <span>No citations supplied</span>;
  return <ul className="provider-citations">{ids.map(id => <li key={id}><a href={providerEvidenceUrl(id)} target="_blank" rel="noreferrer">Evidence {id}<span className="sr-only"> (opens a new tab)</span></a></li>)}</ul>;
}
function Preview({ value }: { value: ProviderPreview }) {
  return <div className="provider-preview">
    <Configuration value={value} />
    <dl className="provider-facts"><div><dt>Exact analysis revision</dt><dd>{value.analysis_revision}</dd></div><div><dt>Prompt version</dt><dd>{value.prompt_version}</dd></div><div><dt>Reserved tokens per attempt</dt><dd>{value.reserved_tokens_per_attempt ?? 'Unavailable'}</dd></div></dl>
    <p className="provider-digest">Analysis identity: <code>{value.analysis_digest ?? 'Unavailable'}</code></p>
    <p className="provider-digest">Evidence identity: <code>{value.evidence_digest ?? 'Unavailable'}</code></p>
    <p className="provider-digest">Preview identity: <code>{value.preview_digest ?? 'Unavailable'}</code></p>
    {value.budget && <p>Current run budget: {value.budget.requests}/{value.budget.max_requests} requests · {value.budget.reserved_tokens}/{value.budget.max_reserved_tokens} reserved tokens. Persisted ceilings can only tighten.</p>}
    <p><strong>Approved evidence scope: {value.evidence.length} records.</strong> Only the listed approved excerpts for this exact analysis may be sent. Evidence is rechecked before each attempt.</p>
    {value.evidence.length > 0 && <details><summary>Inspect approved evidence scope</summary><ul className="provider-evidence">{value.evidence.map(item => <li key={item.id}><a href={providerEvidenceUrl(item.id)} target="_blank" rel="noreferrer">Evidence {item.id}<span className="sr-only"> (opens a new tab)</span></a><pre>{item.excerpt}</pre></li>)}</ul></details>}
    <p className="muted">Token reservations are conservative accounting limits, not a guaranteed currency spending cap. Every retry consumes another request and reservation.</p>
  </div>;
}
export function ProviderInvocationView({ job, category, canCancel, busy, cancel }: { job: ProviderInvocation; category: Analysis['category']; canCancel: boolean; busy: boolean; cancel: () => void }) {
  const pricing = job.attempts.find(attempt => attempt.pricing.currency)?.pricing ?? null;
  return <article className="provider-invocation" aria-label={`Provider job ${job.invocation_id}`}>
    <div className="provider-job-heading"><h4>{providerStateLabel(job)}</h4>{canCancel && !providerTerminal(job) && <button type="button" disabled={busy || Boolean(job.cancel_requested_at)} onClick={cancel}>{job.cancel_requested_at ? 'Cancellation requested' : 'Request cancellation'}</button>}</div>
    <p className="provider-digest">Job: <code>{job.invocation_id}</code> · revision {job.analysis_revision} · {job.created_at}</p>
    {job.reason && <p><strong>Reason:</strong> {readable(job.reason)}</p>}
    {job.recovery_required && <p className="provider-warning">{job.invocation_state === 'cancelled' ? 'Cancellation is recorded. Transport termination and accounting are still pending; updates continue. If the request is stranded, operator recovery is required.' : 'The worker cannot safely establish the outcome. Operator recovery is required.'} This request will not be automatically resent and reserved usage is not refunded.</p>}
    {job.cancel_requested_at && <p>Cancellation requested at {job.cancel_requested_at}. An in-flight request may finish and incur usage; only the persisted final state confirms its outcome.</p>}
    {job.proposal && <div className="provider-proposal"><p className="provider-warning"><strong>Unverified model hypotheses.</strong> These suggestions do not change the deterministic category, risk flags, contradictions, evidence or review history.</p><p>Proposed category: <strong>{readable(job.proposal.category)}</strong>{job.proposal.category !== category ? '. Disagrees with the selected deterministic analysis.' : '. Agreement is not independent verification.'}</p><ol>{job.proposal.hypotheses.map((hypothesis, index) => <li key={index}><p>{hypothesis.text}</p><EvidenceLinks ids={hypothesis.evidence_ids} /></li>)}</ol><h5>Model-reported contradictions</h5><EvidenceLinks ids={job.proposal.contradictory_evidence_ids} /><h5>Model-reported missing evidence</h5>{job.proposal.missing_evidence.length ? <ul>{job.proposal.missing_evidence.map((item, index) => <li key={index}>{item}</li>)}</ul> : <p>None reported by the model. This does not resolve deterministic missing evidence.</p>}</div>}
    {!job.proposal && providerTerminal(job) && <p>No current safe model proposal is available. Continue with the deterministic analysis and its recorded evidence.</p>}
    <p><strong>{providerCostLabel(job.estimated_cost, job.cost_status, pricing)}</strong>{!job.cost_complete ? ' · Total cost is incomplete or unknown.' : ' · Estimate only, not actual charged cost.'}{job.known_estimated_cost !== null && !job.cost_complete ? ` Known estimated portion: ${job.known_estimated_cost} ${pricing?.currency ?? '(currency unavailable)'}.` : ''}</p>
    <p>Reported usage: {job.usage ? `${job.usage.prompt_tokens} input / ${job.usage.completion_tokens} output tokens` : 'unknown'} · {job.usage_complete ? 'complete reported accounting' : 'accounting incomplete; unreported usage may exist'}</p>
    {job.budget && <p>Run ledger: {job.budget.requests}/{job.budget.max_requests} requests · {job.budget.reserved_tokens}/{job.budget.max_reserved_tokens} reserved tokens.</p>}
    <details><summary>Inspect per-attempt accounting ({job.attempts.length})</summary>{job.attempts.length ? <ol className="provider-attempts">{job.attempts.map(attempt => <li key={attempt.number}><strong>Attempt {attempt.number}: {readable(attempt.status)}</strong><p>{attempt.reason ? `${readable(attempt.reason)} · ` : ''}Spend status: {readable(attempt.spend_status)}</p><p>Reserved: {attempt.reserved_tokens} · Accounted: {attempt.accounted_tokens} tokens</p><p>Reported usage: {attempt.usage ? `${attempt.usage.prompt_tokens} input / ${attempt.usage.completion_tokens} output tokens` : 'unknown'}</p><p>{providerCostLabel(attempt.estimated_cost, attempt.cost_status, attempt.pricing)}</p>{attempt.pricing.date && <p>Pricing source: {attempt.pricing.source} · {attempt.pricing.date}</p>}</li>)}</ol> : <p>No attempt has been recorded. Unknown eventual cost is not zero.</p>}</details>
    <details><summary>Inspect submitted identity</summary><p className="provider-digest">Analysis: <code>{job.analysis_digest}</code></p><p className="provider-digest">Evidence: <code>{job.evidence_digest}</code></p><p className="provider-digest">Configuration: <code>{job.configuration_digest}</code></p><p className="provider-digest">Preview: <code>{job.preview_digest ?? 'Unavailable'}</code></p><p>Prompt version: {job.prompt_version}</p></details>
  </article>;
}

export function OptionalProviderPanel({ scope, principal, analysis }: { scope: ProviderScope; principal: Principal; analysis: Analysis }) {
  const permitted = canInvokeProvider(principal, scope.projectId);
  const cancellationPermitted = canCancelProvider(principal, scope.projectId);
  const principalKey = `${principal.kind}:${principal.user_id ?? ''}:${permitted}:${cancellationPermitted}`;
  const session = useMemo(() => {
    let storage: Storage | undefined;
    try { storage = window.sessionStorage; } catch { /* Disabled storage is supported. */ }
    return new ProviderSession(scope, principalKey, permitted, providerApi, storage, cancellationPermitted);
  }, [scope.projectId, scope.runId, scope.analysisId, principalKey, permitted, cancellationPermitted]);
  const state = useSyncExternalStore(session.subscribe, session.getSnapshot);
  const [confirmedDigest, setConfirmedDigest] = useState<string | null>(null);
  const statusRef = useRef<HTMLParagraphElement>(null);
  useEffect(() => { setConfirmedDigest(null); session.start(); return () => session.stop(); }, [session]);
  const confirmation = Boolean(state.preview?.preview_digest && confirmedDigest === state.preview.preview_digest);
  const blocked = state.jobs.some(job => !providerTerminal(job) || job.recovery_required);
  const canSubmit = permitted && state.preview?.can_submit && state.preview.availability === 'ready' && !blocked && !state.loading && !state.busy;
  const submit = async () => { setConfirmedDigest(null); const promise = session.submit(); statusRef.current?.focus({ preventScroll: true }); await promise; };
  const cancel = (id: string) => { const promise = session.cancel(id); statusRef.current?.focus({ preventScroll: true }); void promise; };
  return <section id="optional-provider" className="optional-provider" aria-labelledby="provider-heading" aria-busy={state.loading}>
    <div className="panel-heading"><div><p className="eyebrow">OPTIONAL · UNVERIFIED</p><h3 id="provider-heading">Optional model proposal</h3></div><button type="button" disabled={state.loading || Boolean(state.busy)} onClick={() => { setConfirmedDigest(null); void session.refresh(); }}>Refresh proposal state</button></div>
    <div className="provider-content">
      <p>Deterministic category: <strong>{readable(analysis.category)}</strong>. Its risk flags, contradictions and evidence remain authoritative for this investigation.</p>
      <p>Disabled by default. Only an authenticated project administrator can request or cancel a proposal. Existing safe results are available to authorized viewers.</p>
      <p ref={statusRef} className="provider-live-status" role="status" aria-live="polite" aria-atomic="true" tabIndex={-1}>{state.loading ? 'Loading persisted provider state…' : `${state.notice || 'Persisted state loaded.'}${state.jobs[0] ? ` Latest job: ${providerStateLabel(state.jobs[0])}.` : ''}`}</p>
      {state.error && <p className="alert" role="alert">{state.error}</p>}
      {state.preview && <Preview value={state.preview} />}
      {!permitted && <p className="identity-note">{principal.kind === 'demo' ? 'The synthetic demo identity cannot invoke or cancel a provider.' : principal.kind === 'ingestion_token' ? 'Ingestion credentials cannot invoke or cancel a provider.' : principal.demo_mode && cancellationPermitted ? 'Provider requests are disabled in demo mode. Authenticated administrators can still stop an existing job.' : 'Read-only provider access. A project administrator must submit or cancel.'}</p>}
      {permitted && state.pendingSubmission && state.pendingIdentity && <div className="provider-confirmation"><p>A previous submission has an unconfirmed response. Reconcile that same reviewed request; its original identity is preserved and a changed scope will be rejected.</p><p className="provider-digest">Pending revision: {state.pendingIdentity.analysis_revision} · Preview: <code>{state.pendingIdentity.preview_digest}</code> · Configuration: <code>{state.pendingIdentity.configuration_digest}</code></p><button type="button" disabled={state.loading || Boolean(state.busy)} onClick={() => void submit()}>Reconcile previous submission</button></div>}
      {permitted && state.preview && !state.pendingSubmission && <div className="provider-confirmation"><label><input type="checkbox" checked={confirmation} disabled={!canSubmit} onChange={event => setConfirmedDigest(event.target.checked ? state.preview?.preview_digest ?? null : null)} /><span>I approve sending the listed evidence scope to this destination with the displayed revision, configuration and limits. Attempts may incur charges, including when cost is unknown.</span></label><button className="primary" type="button" disabled={!canSubmit || !confirmation} onClick={() => void submit()}>{state.busy === 'submit' ? 'Submitting…' : 'Submit reviewed proposal request'}</button>{blocked && <p>A job is active or requires recovery. Review its persisted state before another submission.</p>}</div>}
      <p className="muted">Leaving this page or signing out stops observation. It does not cancel server work. Use “Request cancellation” to persist a cancellation request.</p>
      <h4>Persisted proposal history</h4>
      {!state.loading && !state.jobs.length && <p>No provider jobs are recorded for this analysis.</p>}
      {state.truncated && <p>Showing the newest 50 jobs. Older records are omitted from this view.</p>}
      {state.jobs.map(job => <ProviderInvocationView key={job.invocation_id} job={job} category={analysis.category} canCancel={cancellationPermitted} busy={Boolean(state.busy)} cancel={() => cancel(job.invocation_id)} />)}
    </div>
  </section>;
}
