import { useEffect, useState } from 'react';
import { loadGitHubReport, type GitHubReportPreview } from './github-report';

export function GitHubReportPanel({ runId }: { runId: string }) {
  const [report, setReport] = useState<GitHubReportPreview | null>(null);
  const [error, setError] = useState('');
  const [loading, setLoading] = useState(false);
  const [revision, setRevision] = useState(0);
  useEffect(() => {
    const controller = new AbortController();
    setReport(null); setError(''); setLoading(Boolean(runId));
    if (runId) void loadGitHubReport(runId, controller.signal).then(value => {
      if (!controller.signal.aborted) setReport(value);
    }).catch((reason: unknown) => {
      if (!controller.signal.aborted) setError(reason instanceof Error ? reason.message : 'Report preview unavailable');
    }).finally(() => { if (!controller.signal.aborted) setLoading(false); });
    return () => controller.abort();
  }, [runId, revision]);
  const download = () => {
    if (!report) return;
    const url = URL.createObjectURL(new Blob([report.markdown], { type: 'text/markdown;charset=utf-8' }));
    const anchor = document.createElement('a');
    anchor.href = url; anchor.download = 'loose-thread-report.md'; anchor.click();
    setTimeout(() => URL.revokeObjectURL(url), 1000);
  };
  return <section id="github-report" className="panel" aria-labelledby="github-report-heading">
    <div className="panel-heading"><div><p className="eyebrow">ADVISORY · READ-ONLY PREVIEW</p><h2 id="github-report-heading">GitHub report</h2></div>
      <button type="button" disabled={!runId || loading} onClick={() => setRevision(value => value + 1)}>Refresh report</button></div>
    <p>This preview does not post a comment or approve a release. Publication requires a separately configured trusted publisher.</p>
    {!runId && <p className="empty">Select a run to inspect its report.</p>}
    {loading && <p role="status">Loading report preview…</p>}
    {error && <p role="alert">{error}</p>}
    {report && <><p>Completeness: <strong>{report.completeness}</strong> · Analyses: {report.analysis_count} · Omitted detail: {report.omitted_analyses}</p>
      <p>Report digest: <code>{report.report_digest}</code></p>
      <button type="button" onClick={download}>Download Markdown report</button>
      <details><summary>Inspect sanitized report text</summary><pre className="github-report-preview" aria-label="Sanitized GitHub report">{report.markdown}</pre></details></>}
  </section>;
}
