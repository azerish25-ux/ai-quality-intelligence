import { afterEach, describe, expect, it, vi } from 'vitest';
import { loadGitHubReport } from './github-report';
afterEach(() => vi.unstubAllGlobals());
const valid = { schema_version: 'github-report-v2', run_id: 'run-1', tested_head: null, completeness: 'complete', report_digest: 'a'.repeat(64), analysis_count: 1, omitted_analyses: 0, markdown: 'HOLD_FOR_REVIEW' };
describe('GitHub report preview', () => {
  it('uses the authorized run route and cancellation signal', async () => {
    const fetcher = vi.fn().mockResolvedValue(new Response(JSON.stringify(valid)));
    vi.stubGlobal('fetch', fetcher);
    const controller = new AbortController();
    expect(await loadGitHubReport('run-1', controller.signal)).toEqual(valid);
    expect(fetcher).toHaveBeenCalledWith('/api/v1/runs/run-1/github-report-preview', { signal: controller.signal });
  });
  it.each([403, 404, 500])('surfaces access/operational failure %s', async status => {
    vi.stubGlobal('fetch', vi.fn().mockResolvedValue(new Response('private body', { status })));
    await expect(loadGitHubReport('run-1')).rejects.toThrow(`(${status})`);
  });
  it.each([{ ...valid, run_id: 'other-project-run' }, { ...valid, markdown: 'x'.repeat(60_001) }, { ...valid, report_digest: 'fake' }, { ...valid, schema_version: 'unknown' }, null])('rejects an invalid or wrong-run projection', async value => {
    vi.stubGlobal('fetch', vi.fn().mockResolvedValue(new Response(JSON.stringify(value))));
    await expect(loadGitHubReport('run-1')).rejects.toThrow('Invalid report preview');
  });
});
