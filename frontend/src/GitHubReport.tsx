import './github-report.css';
import { useLayoutEffect, useMemo, useSyncExternalStore } from 'react';
import { GitHubReportSession, type ReportDownloadKind, type ReportPanelState } from './github-report-session';

export function GitHubReportPanel({ projectId, runId }: { projectId: string; runId: string }) {
  const session = useMemo(() => new GitHubReportSession(projectId, runId), [projectId, runId]);
  const state = useSyncExternalStore(session.subscribe, session.getSnapshot, session.getSnapshot);
  useLayoutEffect(() => {
    window.addEventListener('failurelens:session-expired', session.stop);
    session.start();
    return () => { window.removeEventListener('failurelens:session-expired', session.stop); session.stop(); };
  }, [session]);
  return <GitHubReportView runId={runId} state={state} refresh={() => { void session.refresh(); }} download={kind => { void session.download(kind); }} />;
}

export function GitHubReportView({ runId, state, refresh, download }: { runId: string; state: ReportPanelState; refresh: () => void; download: (kind: ReportDownloadKind) => void }) {
  const { report, loading, downloading, error, stale, notice } = state;
  const evidence = report?.evidence_export;
  const disabled = loading || Boolean(downloading) || stale;
  return <section id="github-report" className="panel" aria-labelledby="github-report-heading">
    <div className="panel-heading"><div><p className="eyebrow">ADVISORY · READ-ONLY PREVIEW</p><h2 id="github-report-heading">GitHub report</h2></div>
      <button type="button" disabled={!runId || loading} onClick={refresh}>Refresh report</button></div>
    <p>This preview does not post a comment or approve a release. Publication requires a separately configured trusted publisher.</p>
    {!runId && <p className="empty">Select a run to inspect its report.</p>}
    {loading && <p role="status">Loading report preview…</p>}
    {error && <p role="alert">{error}</p>}
    {notice && <p role="status">{notice}</p>}
    {report && <><p>Completeness: <strong>{report.completeness}</strong> · Analyses: {report.analysis_count} · Omitted detail: {report.omitted_analyses}</p>
      <p>Report digest: <code>{report.report_digest}</code></p>
      {stale && <p>The displayed preview is stale. Refresh it to enable downloads.</p>}
      <div className="github-report-actions status-actions">
        <button type="button" disabled={disabled} onClick={() => download('markdown')}>Download Markdown report</button>
        <button type="button" disabled={disabled || !report.raw_json} onClick={() => download('json')}>Download JSON report</button>
        <button type="button" disabled={disabled || !evidence || !report.raw_json} onClick={() => download('evidence')}>{downloading === 'evidence' ? 'Verifying evidence…' : 'Download approved evidence JSON'}</button>
      </div>
      {downloading === 'evidence' && <p role="status">Checking current evidence availability and the report’s exact evidence digest…</p>}
      {evidence ? <div className="github-report-scope" aria-label="Evidence export scope">
        <p>Reported reference subset · Not published. {evidence.counts.exported} of {evidence.counts.requested} requested references included.</p>
        <p>Rejected: {evidence.counts.rejected} · Unavailable: {evidence.counts.unavailable} · Omitted by export limits: {evidence.counts.omitted}</p>
        <p>Unavailable analyses: {evidence.counts.unavailable_analyses} · Invalid reference entries: {evidence.counts.invalid_reference_entries} · Omitted reference entries: {evidence.counts.omitted_reference_entries} · Omitted section references: {evidence.counts.omitted_section_reference_hints} · Omitted related runs: {evidence.counts.omitted_related_run_hints}</p>
        <p>Only currently approved, validated reference excerpts and bounded metadata are included. Original files, binary bodies and unapproved evidence are excluded. Field omissions are recorded in the JSON. This is not a full evidence archive. Unknown sensitive patterns may remain; treat strings as inert data. Digests identify bytes, not producer authenticity.</p>
      </div> : <p>This server provides the legacy report preview. Verified JSON and approved evidence downloads are unavailable; Markdown remains available.</p>}
      <details><summary>Inspect sanitized report text</summary><pre className="github-report-preview" aria-label="Sanitized GitHub report">{report.markdown}</pre></details></>}
  </section>;
}
