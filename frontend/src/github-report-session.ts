import { GitHubReportError, loadGitHubEvidence, loadGitHubReport, type GitHubReportPreview } from './github-report';

export type ReportDownloadKind = 'markdown' | 'json' | 'evidence';
export interface ReportPanelState { report: GitHubReportPreview | null; loading: boolean; downloading: ReportDownloadKind | null; error: string; stale: boolean; notice: string }
const client = { report: loadGitHubReport, evidence: loadGitHubEvidence };
export function saveReportDownload(content: string, filename: string, type: string): void {
  const url = URL.createObjectURL(new Blob([content], { type }));
  const anchor = document.createElement('a');
  try { anchor.href = url; anchor.download = filename; anchor.click(); }
  finally { setTimeout(() => URL.revokeObjectURL(url), 1000); }
}

// One owner for observation and downloads: invalidation happens synchronously,
// including when a transport ignores cancellation or a digest finishes late.
export class GitHubReportSession {
  private state: ReportPanelState = { report: null, loading: false, downloading: null, error: '', stale: false, notice: '' };
  private listeners = new Set<() => void>();
  private active = false;
  private generation = 0;
  private request: AbortController | null = null;
  private downloadRequest: AbortController | null = null;
  constructor(private projectId: string, private runId: string, private api = client, private save = saveReportDownload) {}
  getSnapshot = (): ReportPanelState => this.state;
  subscribe = (listener: () => void): (() => void) => { this.listeners.add(listener); return () => this.listeners.delete(listener); };
  private update(patch: Partial<ReportPanelState>): void { this.state = { ...this.state, ...patch }; this.listeners.forEach(listener => listener()); }
  private invalidate(): void { this.generation++; this.request?.abort(); this.downloadRequest?.abort(); this.request = null; this.downloadRequest = null; }
  start(): void { this.active = true; void this.refresh(); }
  stop = (): void => { this.active = false; this.invalidate(); this.update({ report: null, loading: false, downloading: null, error: '', stale: false, notice: '' }); };
  async refresh(): Promise<void> {
    if (!this.active) return;
    this.invalidate();
    this.update({ report: null, loading: Boolean(this.runId), downloading: null, error: '', stale: false, notice: '' });
    if (!this.runId) return;
    const generation = this.generation; const controller = new AbortController(); this.request = controller;
    try {
      const report = await this.api.report(this.runId, controller.signal, this.projectId);
      if (this.active && generation === this.generation && !controller.signal.aborted) this.update({ report });
    } catch (error) {
      if (this.active && generation === this.generation && !controller.signal.aborted) this.update({ error: error instanceof Error ? error.message : 'Report preview unavailable. Refresh to try again.' });
    } finally {
      if (this.active && generation === this.generation && !controller.signal.aborted) this.update({ loading: false });
    }
  }
  async download(kind: ReportDownloadKind): Promise<void> {
    const report = this.state.report;
    if (!this.active || !report || this.state.loading || this.state.downloading || this.state.stale || (kind !== 'markdown' && !report.raw_json)) return;
    const generation = this.generation; const controller = new AbortController(); this.downloadRequest = controller;
    this.update({ downloading: kind, error: '', notice: '' });
    try {
      const content = kind === 'evidence' ? (await this.api.evidence(report, controller.signal)).raw_json : kind === 'json' ? report.raw_json! : report.markdown;
      if (!this.active || generation !== this.generation || controller.signal.aborted) return;
      this.save(content, kind === 'markdown' ? 'loose-thread-report.md' : kind === 'json' ? 'loose-thread-report.json' : 'evidence.json', kind === 'markdown' ? 'text/markdown;charset=utf-8' : 'application/json');
      this.update({ notice: kind === 'evidence' ? 'Approved evidence JSON verified. Browser download requested.' : 'Browser download requested.' });
    } catch (error) {
      if (!this.active || generation !== this.generation || controller.signal.aborted) return;
      this.update({ error: error instanceof Error ? error.message : 'Download unavailable. Refresh the report to try again.', stale: error instanceof GitHubReportError && error.status === 409 });
    } finally {
      if (this.active && generation === this.generation && !controller.signal.aborted) { this.downloadRequest = null; this.update({ downloading: null }); }
    }
  }
}
