import { useCallback, useEffect, useRef, useState, type FormEvent } from 'react';
import { binaryApi, BinaryError, verifyLocalImage, type BinaryEvidence, type BinaryPage, type ImageComparison, type PixelMask, type TracePage } from './binary-api';

const message = (error: unknown) => error instanceof Error ? error.message : 'Evidence request failed.';
const currentBinary = () => new URLSearchParams(window.location.search).get('binary') ?? '';
const initialTraceOffset = () => {
  const value = Number(new URLSearchParams(window.location.search).get('trace_event') ?? '0');
  return Number.isSafeInteger(value) && value >= 0 ? Math.floor(value / 10) * 10 : 0;
};
function evidenceUrl(item: BinaryEvidence, index?: number): string {
  const url = new URL(window.location.href);
  url.searchParams.set('project', item.project_id);
  url.searchParams.set('run', item.run_id);
  url.searchParams.set('binary', item.input_id);
  if (index !== undefined) url.searchParams.set('trace_event', String(index));
  else url.searchParams.delete('trace_event');
  url.hash = 'safe-evidence';
  return `${url.pathname}${url.search}${url.hash}`;
}

export function BinaryEvidencePanel({ runId, canReview }: { runId: string; canReview: boolean }) {
  const [page, setPage] = useState<BinaryPage | null>(null);
  const [offset, setOffset] = useState(0);
  const [selected, setSelected] = useState(currentBinary);
  const [error, setError] = useState('');
  const [revision, setRevision] = useState(0);
  const [expectedId, setExpectedId] = useState('');
  const [actualId, setActualId] = useState('');
  const [comparison, setComparison] = useState<ImageComparison | null>(null);
  const [comparing, setComparing] = useState(false);
  const comparisonEpoch = useRef(0);
  useEffect(() => () => { comparisonEpoch.current++; }, []);
  useEffect(() => {
    const controller = new AbortController();
    setError('');
    binaryApi.list(runId, offset, controller.signal).then(setPage).catch(error => {
      if (!controller.signal.aborted) { setError(message(error)); setPage(null); }
    });
    return () => controller.abort();
  }, [runId, offset, revision]);
  useEffect(() => {
    const onHistory = () => setSelected(currentBinary());
    window.addEventListener('popstate', onHistory);
    return () => window.removeEventListener('popstate', onHistory);
  }, []);
  const changed = useCallback(() => {
    setRevision(value => value + 1); setComparison(null); comparisonEpoch.current++;
  }, []);
  const pick = (id: string) => {
    setSelected(id);
    const url = new URL(window.location.href);
    if (id) url.searchParams.set('binary', id); else url.searchParams.delete('binary');
    url.searchParams.delete('trace_event');
    window.history.replaceState(window.history.state, '', `${url.pathname}${url.search}${url.hash}`);
  };
  const items = page?.items ?? [];
  const approved = items.filter(item => item.state === 'approved' && item.derivative?.approved && !item.derivative.restricted);
  async function compare(event: FormEvent) {
    event.preventDefault(); setComparing(true); setError(''); setComparison(null);
    const epoch = ++comparisonEpoch.current;
    try {
      const result = await binaryApi.compare(expectedId, actualId);
      if (epoch === comparisonEpoch.current) setComparison(result);
    } catch (error) { if (epoch === comparisonEpoch.current) setError(message(error)); }
    finally { if (epoch === comparisonEpoch.current) setComparing(false); }
  }
  return <section id="safe-evidence" className="panel binary-panel" aria-labelledby="binary-heading">
    <div className="panel-heading"><div><p className="eyebrow">CONTROLLED ARTIFACT INSPECTION</p><h2 id="binary-heading">Screenshots and trace evidence</h2></div><span>{page?.total ?? '…'} inputs</span></div>
    <p>Original screenshots and traces remain restricted. Only approved pixel derivatives and sanitized trace events are available here. Approval never changes the original run’s completeness.</p>
    {error && <p role="alert">{error}</p>}
    {!page && !error && <p role="status">Loading binary evidence…</p>}
    {page && <>
      {page.total === 0 ? <div className="empty">This run has no declared screenshot or trace inputs.</div> : <div className="binary-toolbar">
        <label>Binary evidence input<select value={selected} onChange={event => pick(event.target.value)}>
          <option value="">Select an input</option>
          {selected && !items.some(item => item.input_id === selected) && <option value={selected}>Linked evidence outside this page</option>}
          {items.map(item => <option key={item.input_id} value={item.input_id}>{item.manifest_input_id} · {item.state}</option>)}
        </select></label>
        <button type="button" disabled={offset === 0} onClick={() => setOffset(Math.max(0, offset - 25))}>Previous inputs</button>
        <button type="button" disabled={offset + page.limit >= page.total} onClick={() => setOffset(offset + 25)}>Next inputs</button>
        <span>Inputs {page.total ? offset + 1 : 0}–{Math.min(offset + page.limit, page.total)} of {page.total}</span>
      </div>}
      {selected && <BinaryInspector key={selected} inputId={selected} runId={runId} canReview={canReview} changed={changed} />}
      <details className="binary-comparison"><summary>Compare approved expected and actual images</summary>
        <p>Choose images on this input page. Both must belong to the same explicitly associated execution and compatible browser, operating system, viewport, scale, and comparison group.</p>
        <form onSubmit={compare} className="binary-toolbar">
          <label>Expected approved image<select value={expectedId} onChange={event => { setExpectedId(event.target.value); setComparison(null); comparisonEpoch.current++; setComparing(false); }}>
            <option value="">Select expected image</option>{approved.filter(item => item.relationship === 'expected').map(item => <option key={item.input_id} value={item.derivative!.id}>{item.manifest_input_id}</option>)}
          </select></label>
          <label>Actual approved image<select value={actualId} onChange={event => { setActualId(event.target.value); setComparison(null); comparisonEpoch.current++; setComparing(false); }}>
            <option value="">Select actual image</option>{approved.filter(item => item.relationship === 'actual').map(item => <option key={item.input_id} value={item.derivative!.id}>{item.manifest_input_id}</option>)}
          </select></label>
          <button type="submit" disabled={!expectedId || !actualId || comparing}>Compare approved images</button>
        </form>
        {comparison && <div role="status"><strong>{comparison.status}</strong><p>{comparison.similarity === null ? comparison.reasons.join(' · ') : `Perceptual similarity ${(comparison.similarity * 100).toFixed(1)}% (${comparison.algorithm})`}</p><p>{comparison.advisory}</p></div>}
      </details>
    </>}
  </section>;
}

function BinaryInspector({ inputId, runId, canReview, changed }: { inputId: string; runId: string; canReview: boolean; changed: () => void }) {
  const [item, setItem] = useState<BinaryEvidence | null>(null);
  const [error, setError] = useState('');
  const [notice, setNotice] = useState('');
  const [busy, setBusy] = useState(false);
  const [reason, setReason] = useState('');
  const [confirmed, setConfirmed] = useState(false);
  const [file, setFile] = useState<File | null>(null);
  const [draftVersion, setDraftVersion] = useState<number | null>(null);
  const [masks, setMasks] = useState<PixelMask[]>([]);
  const [rectangle, setRectangle] = useState<PixelMask>({ x: 0, y: 0, width: 1, height: 1 });
  const [bitmapRevision, setBitmapRevision] = useState(0);
  const [trace, setTrace] = useState<TracePage | null>(null);
  const [traceOffset, setTraceOffset] = useState(initialTraceOffset);
  const [decisionOffset, setDecisionOffset] = useState(0);
  const [previewFailed, setPreviewFailed] = useState(false);
  const canvas = useRef<HTMLCanvasElement>(null);
  const bitmap = useRef<ImageBitmap | null>(null);
  const alive = useRef(true);
  const fileEpoch = useRef(0);
  const requestEpoch = useRef(0);
  useEffect(() => {
    alive.current = true;
    return () => { alive.current = false; fileEpoch.current++; requestEpoch.current++; bitmap.current?.close(); };
  }, []);
  const update = useCallback((value: BinaryEvidence) => {
    if (value.run_id !== runId || value.input_id !== inputId) throw new Error('Linked artifact does not belong to this investigation.');
    setItem(value); setPreviewFailed(false);
  }, [runId, inputId]);
  const load = useCallback(async () => {
    const epoch = ++requestEpoch.current;
    try {
      const value = await binaryApi.get(inputId, decisionOffset);
      if (alive.current && epoch === requestEpoch.current) update(value);
    } catch (error) {
      if (alive.current && epoch === requestEpoch.current) {
        setItem(null); setTrace(null); setFile(null); bitmap.current?.close(); bitmap.current = null;
        setError(message(error));
      }
    }
  }, [inputId, decisionOffset, update]);
  useEffect(() => {
    void load();
    const timer = window.setInterval(() => { if (!document.hidden) void load(); }, 5000);
    return () => { window.clearInterval(timer); requestEpoch.current++; };
  }, [load]);
  const derivativeId = item?.derivative?.id;
  useEffect(() => {
    setTrace(null);
    if (!item || item.kind !== 'playwright-trace' || item.state !== 'safe_index_available') return;
    const controller = new AbortController();
    binaryApi.trace(inputId, traceOffset, controller.signal).then(setTrace).catch(error => {
      if (!controller.signal.aborted) setError(message(error));
    });
    return () => controller.abort();
  }, [inputId, item?.state, derivativeId, traceOffset]);
  useEffect(() => {
    const target = canvas.current;
    const image = bitmap.current;
    if (!target || !image) return;
    const scale = Math.min(1, 1024 / image.width, 768 / image.height);
    target.width = Math.max(1, Math.round(image.width * scale)); target.height = Math.max(1, Math.round(image.height * scale));
    const context = target.getContext('2d');
    if (!context) return;
    context.drawImage(image, 0, 0, target.width, target.height);
    context.fillStyle = '#000';
    for (const mask of masks) context.fillRect(mask.x * scale, mask.y * scale, mask.width * scale, mask.height * scale);
  }, [bitmapRevision, masks, file]);
  async function localImage(next: File | undefined) {
    const epoch = ++fileEpoch.current;
    setFile(null); setConfirmed(false); setMasks([]); setError('');
    bitmap.current?.close(); bitmap.current = null;
    if (!next || !item) return;
    const version = item.version;
    try {
      await verifyLocalImage(next, item);
      const image = await createImageBitmap(next, { imageOrientation: 'from-image' });
      if (!alive.current || epoch !== fileEpoch.current) { image.close(); return; }
      if (image.width !== item.width || image.height !== item.height) { image.close(); throw new Error('The local image orientation/dimensions do not match the validated source.'); }
      bitmap.current = image; setFile(next); setDraftVersion(version); setBitmapRevision(v => v + 1);
      setNotice('Local digest verified. The original is not uploaded until you submit the review.');
    } catch (error) { if (alive.current && epoch === fileEpoch.current) setError(message(error)); }
  }
  function addMask() {
    if (!item?.width || !item.height || masks.length >= 64) return;
    if (Object.values(rectangle).some(value => !Number.isSafeInteger(value)) || rectangle.x < 0 || rectangle.y < 0 || rectangle.width < 1 || rectangle.height < 1 || rectangle.x + rectangle.width > item.width || rectangle.y + rectangle.height > item.height) {
      setError('Mask coordinates must be integer pixels inside the oriented image.'); return;
    }
    setError(''); setMasks(previous => [...previous, { ...rectangle }]); setConfirmed(false);
  }
  async function save(event: FormEvent) {
    event.preventDefault(); if (!item || !file || !confirmed || draftVersion === null) return;
    setBusy(true); setError(''); setNotice(''); requestEpoch.current++;
    try {
      const value = await binaryApi.review({ ...item, version: draftVersion }, file, reason, masks);
      if (!alive.current) return;
      requestEpoch.current++; update(value); setFile(null); bitmap.current?.close(); bitmap.current = null;
      setConfirmed(false); setNotice(`Approved masked derivative saved as review revision ${value.version}. Original remains restricted.`); changed();
    } catch (error) { if (alive.current) setError(`${message(error)}${error instanceof BinaryError && error.status === 409 ? ' Reselect the original after reviewing the latest revision.' : ''}`); }
    finally { if (alive.current) setBusy(false); }
  }
  async function decide(decision: 'reject' | 'revoke') {
    if (!item) return;
    setBusy(true); setError(''); setNotice(''); requestEpoch.current++;
    try {
      const value = await binaryApi.decide(item, decision, reason);
      if (alive.current) {
        requestEpoch.current++; update(value); setFile(null); bitmap.current?.close(); bitmap.current = null; setConfirmed(false);
        setNotice(`Evidence ${value.state}. All earlier derivative URLs for this input are closed.`); changed();
      }
    } catch (error) { if (alive.current) setError(message(error)); }
    finally { if (alive.current) setBusy(false); }
  }
  return <article className="binary-inspector" aria-label="Selected binary evidence">
    {error && <p role="alert">{error}</p>}{notice && <p role="status">{notice}</p>}
    {!item ? <p>{error ? 'No other artifact has been substituted for this link.' : 'Loading the selected evidence…'}</p> : <>
      <div className="panel-heading"><h3>{item.manifest_input_id}</h3><span className="state">{item.state} · revision {item.version}</span></div>
      <dl className="binary-metadata"><div><dt>Source</dt><dd>{item.path ?? 'Missing source path'}</dd></div><div><dt>Original status</dt><dd>{item.source_status}</dd></div><div><dt>Test association</dt><dd>{item.correlation} · {item.execution_id ?? 'No unambiguous execution'}</dd></div><div><dt>SHA-256</dt><dd><code>{item.source_digest ?? 'No source received'}</code></dd></div></dl>
      <a href={evidenceUrl(item)}>Permanent investigation link</a>
      {!!item.warnings.length && <p>{item.warnings.join(' · ')}</p>}
      {item.derivative?.approved && !item.derivative.restricted && <div className="binary-approved">
        <p>Approved derivative <code>{item.derivative.digest}</code></p>
        <a href={binaryApi.content(item.derivative.id, '?download=true')}>Download approved derivative</a>
        {item.kind === 'screenshot' && (previewFailed ? <p role="alert">Approved preview is unavailable. Reload the evidence to check expiry or revocation.</p> : <img src={binaryApi.content(item.derivative.id, '?preview=true')} alt={`Approved ${item.relationship ?? ''} screenshot: ${item.manifest_input_id}`} onError={() => setPreviewFailed(true)} />)}
      </div>}
      {item.kind === 'screenshot' && <p>{item.width ?? '?'} × {item.height ?? '?'} oriented pixels. Originals are not retained for download. A reviewer must select the exact local original to mask it.</p>}
      {canReview && item.source_status === 'restricted' && <form onSubmit={save} className="binary-review">
        {item.kind === 'screenshot' && <>
          <h4>Review and irreversibly mask pixels</h4>
          <label>Exact local original PNG or JPEG<input type="file" accept="image/png,image/jpeg" onChange={event => void localImage(event.target.files?.[0])} disabled={busy} /></label>
          {file && <>
            <canvas ref={canvas} className="binary-canvas" aria-label="Local image with proposed masks">Local image preview. Use the labeled coordinate controls to define opaque masks.</canvas>
            <p>Mask coordinates use full-size, orientation-normalized pixels, not the scaled preview. Mask all sensitive areas before approving. This draft uses review revision {draftVersion}.</p>
            <fieldset><legend>Opaque pixel mask</legend><div className="binary-mask-fields">{(['x', 'y', 'width', 'height'] as const).map(key => <label key={key}>Mask {key}<input type="number" min={key === 'x' || key === 'y' ? 0 : 1} step={1} value={rectangle[key]} onChange={event => setRectangle(previous => ({ ...previous, [key]: Number(event.target.value) }))} /></label>)}</div>
              <button type="button" disabled={busy || masks.length >= 64} onClick={addMask}>Add opaque mask</button>
            </fieldset>
            <ol>{masks.map((mask, index) => <li key={index}>({mask.x}, {mask.y}) — {mask.width} × {mask.height}<button type="button" disabled={busy} onClick={() => { setMasks(previous => previous.filter((_, i) => i !== index)); setConfirmed(false); }} aria-label={`Remove mask ${index + 1}`}>Remove</button></li>)}</ol>
            <label className="binary-confirm"><input type="checkbox" checked={confirmed} onChange={event => setConfirmed(event.target.checked)} />I reviewed the visible pixels and confirm the masked derivative is safe for project members.</label>
          </>}
        </>}
        <label>Evidence review reason<textarea minLength={10} maxLength={1000} required value={reason} onChange={event => setReason(event.target.value)} rows={3} /></label>
        <div className="binary-toolbar">
          {item.kind === 'screenshot' && <button type="submit" className="primary" disabled={busy || !file || !confirmed || reason.trim().length < 10}>Save approved masked derivative</button>}
          <button type="button" disabled={busy || reason.trim().length < 10} onClick={() => void decide(item.derivative ? 'revoke' : 'reject')}>{item.derivative ? 'Revoke approved evidence' : 'Reject this evidence'}</button>
        </div>
      </form>}
      {item.kind === 'playwright-trace' && <>
        <h4>Safe trace event index</h4>
        <p>No DOM, scripts, headers, bodies, or resource pixels are executed or published here. Inspect an original only in a local trusted environment after verifying its SHA-256: <code>failurelens trace-inspect path/to/trace.zip --sha256 {item.source_digest ?? '<recorded-digest>'}</code>. The command validates the local archive and prints pinned viewer instructions; it does not start a browser or install software.</p>
        {trace && <>
          <p>{trace.total} indexed events. {String(trace.summary.omitted_index_events ?? 0)} additional eligible events omitted by the index limit. {String(trace.summary.event_count ?? 0)} source events validated.</p>
          {trace.events.map(event => <article className="binary-trace-event" key={event.evidence_id}>
            <h5>Event {event.index}: {String(event.event.type)}</h5><p>{event.source_locator.entry} · line {event.source_locator.line} · archive entry {event.source_locator.entry_index}</p>
            <pre>{event.text}</pre><p>Entry SHA-256 <code>{event.source_locator.entry_digest}</code></p>
            <a href={evidenceUrl(item, event.index)}>Link to event {event.index}</a>{' · '}<a href={binaryApi.content(event.evidence_derivative_id, '?download=true')}>Download cited safe event</a>
          </article>)}
          <div className="binary-toolbar"><button type="button" disabled={traceOffset === 0} onClick={() => setTraceOffset(Math.max(0, traceOffset - 10))}>Previous trace events</button><button type="button" disabled={traceOffset + trace.limit >= trace.total} onClick={() => setTraceOffset(traceOffset + 10)}>Next trace events</button><span>Events {traceOffset}–{Math.min(traceOffset + trace.limit, trace.total)} of {trace.total}</span></div>
        </>}
      </>}
      <details className="binary-history"><summary>Review history ({item.decisions_total})</summary>
        {item.decisions.map(decision => <article key={decision.id}><strong>Revision {decision.version}: {decision.decision}</strong><p>{decision.actor_display} · {new Date(decision.created_at).toLocaleString()}</p><p>{decision.reason}</p><p>{decision.masks.length} pixel masks</p></article>)}
        <div className="binary-toolbar"><button type="button" disabled={decisionOffset === 0} onClick={() => setDecisionOffset(Math.max(0, decisionOffset - 20))}>Newer reviews</button><button type="button" disabled={decisionOffset + 20 >= item.decisions_total} onClick={() => setDecisionOffset(decisionOffset + 20)}>Older reviews</button></div>
      </details>
    </>}
  </article>;
}
