import { afterEach, describe, expect, it, vi } from 'vitest';
import { GitHubReportError, type GitHubEvidenceExport, type GitHubReportPreview } from './github-report';
import { reportPair } from './github-report-fixtures';
import { GitHubReportSession, saveReportDownload } from './github-report-session';
const deferred = <T>() => { let resolve!: (value: T) => void; const promise = new Promise<T>(done => { resolve = done; }); return { promise, resolve }; };
const tick = async () => { for (let i = 0; i < 8; i++) await Promise.resolve(); };
async function setup() {
  const fixture = await reportPair();
  const evidence: GitHubEvidenceExport = { raw_json: fixture.evidenceRaw, counts: fixture.report.evidence_export!.counts, evidence_digest: fixture.report.evidence_export!.digest };
  const api = { report: vi.fn<(runId: string, signal?: AbortSignal, projectId?: string) => Promise<GitHubReportPreview>>().mockResolvedValue(fixture.report), evidence: vi.fn<(report: GitHubReportPreview, signal?: AbortSignal) => Promise<GitHubEvidenceExport>>().mockResolvedValue(evidence) };
  const save = vi.fn(); const session = new GitHubReportSession('project-1', 'run-1', api, save);
  return { ...fixture, evidence, api, save, session };
}
afterEach(() => { vi.useRealTimers(); vi.unstubAllGlobals(); });
describe('report observation and download lifecycle', () => {
  it('binds report observation to the selected project and run', async () => {
    const { session, api, report } = await setup(); session.start(); await tick();
    expect(api.report).toHaveBeenCalledWith('run-1', expect.any(AbortSignal), 'project-1'); expect(session.getSnapshot()).toMatchObject({ report, loading: false }); session.stop();
  });
  it('discards older responses when a newer refresh wins even if abort is ignored', async () => {
    const { session, api, report } = await setup(); const old = deferred<GitHubReportPreview>(); api.report.mockReturnValueOnce(old.promise);
    session.start(); await session.refresh(); old.resolve({ ...report, markdown: 'old private scope' }); await tick();
    expect(session.getSnapshot().report).toEqual(report); expect(api.report.mock.calls[0][1]?.aborted).toBe(true); session.stop();
  });
  it.each(['navigation', 'sign-out'])('clears data and aborts observation during %s', async () => {
    const { session, api, report, save } = await setup(); const old = deferred<GitHubReportPreview>(); api.report.mockReturnValueOnce(old.promise);
    session.start(); session.stop(); old.resolve(report); await tick(); await session.download('markdown');
    expect(session.getSnapshot()).toMatchObject({ report: null, loading: false }); expect(api.report.mock.calls[0][1]?.aborted).toBe(true); expect(save).not.toHaveBeenCalled();
  });
  it('survives StrictMode cleanup and restart', async () => {
    const { session, report } = await setup(); session.start(); session.stop(); session.start(); await tick(); expect(session.getSnapshot().report).toEqual(report); session.stop();
  });
  it('downloads report JSON as its original bytes and Markdown as inert text', async () => {
    const { session, report, save } = await setup(); session.start(); await tick(); await session.download('json'); await session.download('markdown');
    expect(save).toHaveBeenNthCalledWith(1, report.raw_json, 'loose-thread-report.json', 'application/json');
    expect(save).toHaveBeenNthCalledWith(2, report.markdown, 'loose-thread-report.md', 'text/markdown;charset=utf-8'); session.stop();
  });
  it('allows legacy Markdown while blocking unverified JSON and evidence', async () => {
    const { session, api, report, save } = await setup(); api.report.mockResolvedValue({ ...report, raw_json: null, evidence_export: undefined });
    session.start(); await tick(); await session.download('json'); await session.download('evidence'); expect(save).not.toHaveBeenCalled(); expect(api.evidence).not.toHaveBeenCalled();
    await session.download('markdown'); expect(save).toHaveBeenCalledTimes(1); session.stop();
  });
  it('serializes repeated clicks and rechecks evidence on a later download', async () => {
    const { session, api, evidence, save } = await setup(); const pending = deferred<GitHubEvidenceExport>(); api.evidence.mockReturnValueOnce(pending.promise);
    session.start(); await tick(); const first = session.download('evidence'); await session.download('evidence'); await session.download('json');
    expect(api.evidence).toHaveBeenCalledTimes(1); expect(save).not.toHaveBeenCalled(); expect(session.getSnapshot().downloading).toBe('evidence');
    pending.resolve(evidence); await first; expect(save).toHaveBeenCalledTimes(1);
    await session.download('evidence'); expect(api.evidence).toHaveBeenCalledTimes(2); expect(save).toHaveBeenCalledTimes(2); session.stop();
  });
  it('cancels an evidence download on refresh and discards a late completion', async () => {
    const { session, api, evidence, save } = await setup(); const pending = deferred<GitHubEvidenceExport>(); api.evidence.mockReturnValueOnce(pending.promise);
    session.start(); await tick(); const download = session.download('evidence'); await session.refresh();
    expect(api.evidence.mock.calls[0][1]?.aborted).toBe(true); pending.resolve(evidence); await download;
    expect(save).not.toHaveBeenCalled(); expect(session.getSnapshot()).toMatchObject({ downloading: null, stale: false, error: '' }); session.stop();
  });
  it.each(['navigation', 'sign-out'])('never saves a late evidence response after %s', async () => {
    const { session, api, evidence, save } = await setup(); const pending = deferred<GitHubEvidenceExport>(); api.evidence.mockReturnValueOnce(pending.promise);
    session.start(); await tick(); const download = session.download('evidence'); session.stop(); pending.resolve(evidence); await download;
    expect(api.evidence.mock.calls[0][1]?.aborted).toBe(true); expect(save).not.toHaveBeenCalled(); expect(session.getSnapshot().report).toBeNull();
  });
  it('withholds stale downloads until the user refreshes the report', async () => {
    const { session, api, save } = await setup(); api.evidence.mockRejectedValueOnce(new GitHubReportError('Report changed. Refresh.', 409));
    session.start(); await tick(); await session.download('evidence'); expect(session.getSnapshot()).toMatchObject({ stale: true, downloading: null });
    await session.download('evidence'); await session.download('json'); await session.download('markdown'); expect(api.evidence).toHaveBeenCalledTimes(1); expect(save).not.toHaveBeenCalled();
    await session.refresh(); await session.download('evidence'); expect(save).toHaveBeenCalledTimes(1); expect(session.getSnapshot().stale).toBe(false); session.stop();
  });
  it('shows unavailable errors and permits a later evidence retry', async () => {
    const { session, api, save } = await setup(); api.evidence.mockRejectedValueOnce(new Error('Evidence temporarily unavailable'));
    session.start(); await tick(); await session.download('evidence'); expect(session.getSnapshot()).toMatchObject({ error: 'Evidence temporarily unavailable', downloading: null }); expect(save).not.toHaveBeenCalled();
    await session.download('evidence'); expect(save).toHaveBeenCalledTimes(1); expect(session.getSnapshot().error).toBe(''); session.stop();
  });
  it('revokes every generated download URL including after a save error', async () => {
    vi.useFakeTimers(); const revokeObjectURL = vi.fn(); const click = vi.fn();
    vi.stubGlobal('URL', { createObjectURL: vi.fn().mockReturnValue('blob:synthetic'), revokeObjectURL }); vi.stubGlobal('document', { createElement: () => ({ click }) });
    saveReportDownload('1.0', 'evidence.json', 'application/json'); expect(click).toHaveBeenCalledOnce(); await vi.advanceTimersByTimeAsync(1000); expect(revokeObjectURL).toHaveBeenCalledOnce();
    click.mockImplementation(() => { throw new Error('download blocked'); }); expect(() => saveReportDownload('1.0', 'evidence.json', 'application/json')).toThrow('blocked');
    await vi.advanceTimersByTimeAsync(1000); expect(revokeObjectURL).toHaveBeenCalledTimes(2);
  });
});
