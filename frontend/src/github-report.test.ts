import { afterEach, describe, expect, it, vi } from 'vitest';
import { loadGitHubEvidence, loadGitHubReport } from './github-report';
import { canonicalFixture, evidenceFixture, fixtureDigest, reportFixture, reportPair, signedFixture } from './github-report-fixtures';
afterEach(() => vi.unstubAllGlobals());
const legacy = { schema_version: 'github-report-v2', run_id: 'run-1', tested_head: null, completeness: 'complete', report_digest: 'a'.repeat(64), analysis_count: 1, omitted_analyses: 0, markdown: 'HOLD_FOR_REVIEW' };
const mock = (raw: string) => { const fetcher = vi.fn().mockImplementation(() => Promise.resolve(new Response(raw))); vi.stubGlobal('fetch', fetcher); return fetcher; };

describe('GitHub report preview', () => {
  it('retains legacy core/Markdown support without inventing verified JSON', async () => {
    const fetcher = mock(JSON.stringify(legacy)); const controller = new AbortController();
    expect(await loadGitHubReport('run-1', controller.signal)).toEqual({ ...legacy, raw_json: null });
    expect(fetcher).toHaveBeenCalledWith('/api/v1/runs/run-1/github-report-preview', { signal: controller.signal });
  });
  it('verifies the signed report while preserving exact server bytes', async () => {
    const { reportRaw } = await reportPair(); mock(reportRaw);
    expect(await loadGitHubReport('run-1', undefined, 'project-1')).toMatchObject({ raw_json: reportRaw, evidence_scope: { analysisIds: ['analysis-1'], relatedRunIds: [] } });
  });
  it.each([403, 404, 500])('surfaces safe access/operational failure %s', async status => {
    vi.stubGlobal('fetch', vi.fn().mockImplementation(() => Promise.resolve(new Response('private body', { status }))));
    await expect(loadGitHubReport('run-1')).rejects.toThrow(`(${status})`);
    await expect(loadGitHubReport('run-1')).rejects.not.toThrow('private body');
  });
  it('expires the session on unauthorized evidence access', async () => {
    const { report } = await reportPair(); const dispatchEvent = vi.fn(); vi.stubGlobal('window', { dispatchEvent });
    vi.stubGlobal('fetch', vi.fn().mockResolvedValue(new Response('secret', { status: 401 })));
    await expect(loadGitHubEvidence(report)).rejects.toThrow('(401)'); expect(dispatchEvent.mock.calls[0][0].type).toBe('failurelens:session-expired');
  });
  it.each([{ ...legacy, run_id: 'other-run' }, { ...legacy, markdown: 'x'.repeat(60_001) }, { ...legacy, report_digest: 'fake' }, { ...legacy, schema_version: 'unknown' }, { ...legacy, analysis_count: true }, { ...legacy, omitted_analyses: 2 }, { ...legacy, tested_head: 12 }, null])('rejects an invalid or wrong-run projection', async value => {
    mock(JSON.stringify(value)); await expect(loadGitHubReport('run-1')).rejects.toThrow('Invalid');
  });
  it('rejects a report from another selected project', async () => {
    const { reportRaw } = await reportPair(); mock(reportRaw); await expect(loadGitHubReport('run-1', undefined, 'project-2')).rejects.toThrow('Invalid');
  });
  it.each([
    { ...reportFixture.evidence_export, filename: '../private.json' }, { ...reportFixture.evidence_export, scope: 'all_evidence' },
    { ...reportFixture.evidence_export, distribution_status: 'published' }, { ...reportFixture.evidence_export, counts: { ...reportFixture.evidence_export.counts, requested: 2 } },
    { ...reportFixture.evidence_export, counts: { ...reportFixture.evidence_export.counts, exported: true } }, { ...reportFixture.evidence_export, extra: 'unreviewed' }, null
  ])('rejects malformed evidence descriptors without falling back to legacy', async evidence_export => {
    mock(await signedFixture({ ...reportFixture, evidence_export }, 'report_digest')); await expect(loadGitHubReport('run-1')).rejects.toThrow('Invalid');
  });
  it('rejects a changed report digest', async () => {
    const { reportRaw } = await reportPair(); mock(reportRaw.replace('HOLD_FOR_REVIEW', 'CHANGED_REPORT')); await expect(loadGitHubReport('run-1')).rejects.toThrow('digest');
  });
  it.each(['1.0', '-0.0', '1e-07', '1e+20', '1.2345678901234567'])('verifies Python number spelling %s and Unicode without reserialization', async numeric => {
    const unsigned = canonicalFixture({ ...reportFixture, metadata: { report_digest: 'nested-is-retained', value: 999 } }).replace('"value":999', `"value":${numeric}`);
    const signature = await fixtureDigest(unsigned); const raw = unsigned.replace(',"run_id":', `,"report_digest":"${signature}","run_id":`);
    mock(raw); const value = await loadGitHubReport('run-1'); expect(value.raw_json).toBe(raw); expect(value.markdown).toContain('résumé 😀');
  });
  it.each(['duplicate', 'whitespace', 'unsorted', 'non-ascii', 'trailing', 'nonfinite', 'bom'])('rejects %s canonical JSON anomalies', async kind => {
    let raw = await signedFixture(reportFixture, 'report_digest');
    if (kind === 'duplicate') raw = raw.replace('"run_id":"run-1"', '"run_id":"bad","run_id":"run-1"');
    if (kind === 'whitespace') raw = raw.replace('{', '{ ');
    if (kind === 'unsorted') raw = raw.replace('"schema_version":"github-report-v2","tested_head":null', '"tested_head":null,"schema_version":"github-report-v2"');
    if (kind === 'non-ascii') raw = raw.replace('\\u00e9', 'é');
    if (kind === 'trailing') raw += '\n';
    if (kind === 'nonfinite') raw = raw.replace('"analysis_count":1', '"analysis_count":1e999');
    if (kind === 'bom') raw = '\ufeff' + raw;
    mock(raw); await expect(loadGitHubReport('run-1')).rejects.toThrow('Invalid');
  });
  it('rejects oversized responses by declared bytes before reading', async () => {
    const cancel = vi.fn(); const response = new Response(new ReadableStream({ cancel }), { headers: { 'Content-Length': '100001' } }); vi.stubGlobal('fetch', vi.fn().mockResolvedValue(response));
    await expect(loadGitHubReport('run-1')).rejects.toThrow('size'); expect(cancel).toHaveBeenCalled();
  });
  it('bounds streamed bytes even without a Content-Length', async () => {
    const cancel = vi.fn(); const stream = new ReadableStream({ start(controller) { controller.enqueue(new Uint8Array(100_001)); }, cancel }); vi.stubGlobal('fetch', vi.fn().mockResolvedValue(new Response(stream)));
    await expect(loadGitHubReport('run-1')).rejects.toThrow('size'); expect(cancel).toHaveBeenCalled();
  });
  it('counts UTF-8 bytes instead of UTF-16 text length', async () => {
    mock(JSON.stringify({ ...legacy, markdown: '😀'.repeat(25_001) })); await expect(loadGitHubReport('run-1')).rejects.toThrow('size');
  });
  it('cancels a pending response stream', async () => {
    const controller = new AbortController(); const cancel = vi.fn(); vi.stubGlobal('fetch', vi.fn().mockResolvedValue(new Response(new ReadableStream({ cancel }))));
    const pending = loadGitHubReport('run-1', controller.signal); await Promise.resolve(); await Promise.resolve(); controller.abort();
    await expect(pending).rejects.toThrow(); expect(cancel).toHaveBeenCalled();
  });
});

describe('approved evidence download', () => {
  it('requests the pinned report digest and returns exact verified server bytes', async () => {
    const { evidenceRaw, report } = await reportPair(); const fetcher = mock(evidenceRaw); const controller = new AbortController();
    expect(await loadGitHubEvidence(report, controller.signal)).toMatchObject({ raw_json: evidenceRaw, evidence_digest: report.evidence_export!.digest });
    expect(fetcher).toHaveBeenCalledWith(`/api/v1/runs/run-1/github-evidence-export?report_digest=${report.report_digest}`, { signal: controller.signal });
  });
  it('reports stale scope without using an error response body', async () => {
    const { report } = await reportPair(); vi.stubGlobal('fetch', vi.fn().mockResolvedValue(new Response('private details', { status: 409 })));
    await expect(loadGitHubEvidence(report)).rejects.toMatchObject({ status: 409, message: 'The report or approved evidence changed. Refresh the report before downloading evidence.' });
  });
  it.each([
    { project_id: 'other-project' }, { run_id: 'other-run' }, { scope: 'full_archive' }, { distribution_status: 'published' }, { schema_version: 'github-evidence-v2' },
    { analysis_ids: ['unreported-analysis'] }, { analysis_ids: ['analysis-1', 'analysis-1'] }, { extra: 'field' }, { notice: 3 }
  ])('rejects mismatched or malformed evidence even with a matching digest', async patch => {
    const { evidenceRaw, report } = await reportPair({ ...evidenceFixture, ...patch }); mock(evidenceRaw); await expect(loadGitHubEvidence(report)).rejects.toThrow('Invalid');
  });
  it.each([
    { project_id: 'other-project' }, { run_id: 'unreferenced-run' }, { approval_state: 'pending' }, { quotation_status: 'unapproved' }, { source_digest: 'bad' },
    { observation: { secret: 'private' } }, { observation: { value: { nested: true } } }, { locator: { ...evidenceFixture.items[0].locator, source: { storage_path: '/private' } } }, { extra: 'field' }
  ])('rejects evidence item schema or scope mismatches', async patch => {
    const { evidenceRaw, report } = await reportPair({ ...evidenceFixture, items: [{ ...evidenceFixture.items[0], ...patch }] }); mock(evidenceRaw); await expect(loadGitHubEvidence(report)).rejects.toThrow('Invalid');
  });
  it('accepts same-project related-run evidence only from explicitly retained report scope', async () => {
    const { evidenceRaw, reportRaw } = await reportPair({ ...evidenceFixture, items: [{ ...evidenceFixture.items[0], run_id: 'base-run' }] }, { ...reportFixture, baseline: { comparable_run_ids: ['base-run'], items: [{ supporting_baseline_evidence_ids: ['evidence-1'], prior_observations: [] }] } });
    mock(reportRaw); const report = await loadGitHubReport('run-1', undefined, 'project-1'); mock(evidenceRaw); expect((await loadGitHubEvidence(report)).raw_json).toBe(evidenceRaw);
  });
  it('rejects a mutated evidence body and a different descriptor digest', async () => {
    const { evidenceRaw, report } = await reportPair(); mock(evidenceRaw.replace('Observed', 'Tampered')); await expect(loadGitHubEvidence(report)).rejects.toThrow('digest');
    mock(evidenceRaw); await expect(loadGitHubEvidence({ ...report, evidence_export: { ...report.evidence_export!, digest: 'f'.repeat(64) } })).rejects.toThrow('Invalid');
  });
  it('rejects inconsistent exported counts and duplicate items', async () => {
    for (const evidence of [{ ...evidenceFixture, items: [] }, { ...evidenceFixture, items: [evidenceFixture.items[0], evidenceFixture.items[0]], counts: { ...evidenceFixture.counts, requested: 2, exported: 2 } }]) {
      const { evidenceRaw, report } = await reportPair(evidence); mock(evidenceRaw); await expect(loadGitHubEvidence(report)).rejects.toThrow('Invalid');
    }
  });
  it('requires descriptor counts to match the evidence document', async () => {
    const { evidenceRaw, report } = await reportPair(); report.evidence_export!.counts.omitted_reference_entries = 1; mock(evidenceRaw); await expect(loadGitHubEvidence(report)).rejects.toThrow('Invalid');
  });
  it('rejects evidence larger than 500000 bytes', async () => {
    const { report } = await reportPair(); mock(' '.repeat(500_001)); await expect(loadGitHubEvidence(report)).rejects.toThrow('size');
  });
  it('preserves Python float spellings in evidence hashes and saved JSON', async () => {
    const unsigned = canonicalFixture(evidenceFixture).replace('"value":1', '"value":1.0'); const evidence_digest = await fixtureDigest(unsigned);
    const raw = unsigned.replace(',"items":', `,"evidence_digest":"${evidence_digest}","items":`);
    const { report } = await reportPair(); report.evidence_export!.digest = evidence_digest; mock(raw); expect((await loadGitHubEvidence(report)).raw_json).toBe(raw);
  });
});

describe('retained report reference limits', () => {
  it('accepts the backend limit of fifty performance baseline members', async () => {
    const { reportRaw } = await reportPair(evidenceFixture, { ...reportFixture, performance: { items: [{ baseline_members: Array.from({ length: 50 }, (_, index) => ({ evidence_id: `evidence-${index}`, run_id: `base-${index}` })) }] } });
    mock(reportRaw); const report = await loadGitHubReport('run-1'); expect(report.evidence_scope!.relatedRunIds).toHaveLength(50);
  });
  it('rejects duplicate analysis identifiers in the declared report scope', async () => {
    mock(await signedFixture({ ...reportFixture, analysis_count: 2, analysis_manifest: { ...reportFixture.analysis_manifest, count: 2 }, analyses: [{ analysis_id: 'analysis-1' }, { analysis_id: 'analysis-1' }] }, 'report_digest'));
    await expect(loadGitHubReport('run-1')).rejects.toThrow('analysis scope');
  });
  it('does not fetch when cancellation already happened', async () => {
    const fetcher = mock('{}'); const controller = new AbortController(); controller.abort(); await expect(loadGitHubReport('run-1', controller.signal)).rejects.toThrow(); expect(fetcher).not.toHaveBeenCalled();
  });
  it('rejects invalid UTF-8 without replacement characters', async () => {
    vi.stubGlobal('fetch', vi.fn().mockResolvedValue(new Response(new Uint8Array([0xc3, 0x28])))); await expect(loadGitHubReport('run-1')).rejects.toThrow('encoding');
  });
});


describe('analysis revision manifest', () => {
  it.each([undefined, null, { ...reportFixture.analysis_manifest, count: 2 }, { ...reportFixture.analysis_manifest, digest: 'bad' }, { ...reportFixture.analysis_manifest, schema_version: 'old' }, { ...reportFixture.analysis_manifest, extra: true }])('rejects missing or malformed full-report provenance', async analysis_manifest => {
    const value = { ...reportFixture, analysis_manifest };
    if (analysis_manifest === undefined) delete (value as Partial<typeof value>).analysis_manifest;
    mock(await signedFixture(value, 'report_digest')); await expect(loadGitHubReport('run-1')).rejects.toThrow('analysis revision manifest');
  });
});
