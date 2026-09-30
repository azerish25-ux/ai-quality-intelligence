export interface GitHubReportPreview {
  schema_version: 'github-report-v2';
  run_id: string;
  tested_head: string | null;
  completeness: string;
  report_digest: string;
  analysis_count: number;
  omitted_analyses: number;
  markdown: string;
}

export async function loadGitHubReport(runId: string, signal?: AbortSignal): Promise<GitHubReportPreview> {
  const response = await fetch(`/api/v1/runs/${encodeURIComponent(runId)}/github-report-preview`, { signal });
  if (response.status === 401 && typeof window !== 'undefined') window.dispatchEvent(new Event('failurelens:session-expired'));
  if (!response.ok) throw new Error(`Report preview unavailable (${response.status}). Check project access and retained evidence.`);
  const value: unknown = await response.json();
  if (!value || typeof value !== 'object') throw new Error('Invalid report preview');
  const item = value as Partial<GitHubReportPreview>;
  if (item.schema_version !== 'github-report-v2' || item.run_id !== runId || typeof item.markdown !== 'string' ||
      item.markdown.length > 60_000 || typeof item.report_digest !== 'string' || !/^[a-f0-9]{64}$/.test(item.report_digest) ||
      typeof item.analysis_count !== 'number' || typeof item.omitted_analyses !== 'number' || typeof item.completeness !== 'string') {
    throw new Error('Invalid report preview');
  }
  return item as GitHubReportPreview;
}
