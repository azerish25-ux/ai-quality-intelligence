import { describe, expect, it } from 'vitest';
import { renderToStaticMarkup } from 'react-dom/server';
import { GitHubReportView } from './GitHubReport';
import { reportPair } from './github-report-fixtures';
import type { ReportPanelState } from './github-report-session';
const state = async (): Promise<ReportPanelState> => ({ report: (await reportPair()).report, loading: false, downloading: null, error: '', stale: false, notice: '' });
const render = (value: ReportPanelState) => renderToStaticMarkup(<GitHubReportView runId="run-1" state={value} refresh={() => {}} download={() => {}} />);
describe('report export rendering', () => {
  it('discloses evidence subset, omitted fields, approval and publication limits', async () => {
    const html = render(await state());
    for (const label of ['Download JSON report', 'Download approved evidence JSON', 'Reported reference subset', 'Not published', 'Original files, binary bodies', 'Field omissions', 'Unknown sensitive patterns', 'Digests identify bytes', 'Unavailable analyses:', 'Omitted section references:', 'Omitted related runs:']) expect(html).toContain(label);
  });
  it('keeps report content inert and cannot create links or scripts', async () => {
    const value = await state(); value.report!.markdown = '<script>secret()</script><img src=x><a href="https://evil.invalid">go</a>';
    const html = render(value); expect(html).not.toContain('<script>'); expect(html).not.toContain('<img '); expect(html).not.toContain('href="https://evil.invalid"'); expect(html).toContain('&lt;script&gt;');
  });
  it('disables download controls and exposes refresh for a stale report', async () => {
    const html = render({ ...await state(), stale: true, error: 'The report changed.' });
    expect(html).toContain('role="alert"'); expect(html).toContain('The displayed preview is stale');
    expect(html.match(/<button type="button" disabled=""/g)).toHaveLength(3); expect(html).toContain('<button type="button">Refresh report</button>');
  });
  it('shows legacy availability honestly while retaining Markdown', async () => {
    const value = await state(); value.report = { ...value.report!, raw_json: null, evidence_export: undefined }; const html = render(value);
    expect(html).toContain('legacy report preview'); expect(html).toContain('<button type="button">Download Markdown report</button>'); expect(html.match(/<button type="button" disabled=""/g)).toHaveLength(2);
  });
  it('exposes evidence verification progress and keeps refresh available to cancel it', async () => {
    const html = render({ ...await state(), downloading: 'evidence' }); expect(html).toContain('Verifying evidence…'); expect(html).toContain('role="status"'); expect(html).toContain('<button type="button">Refresh report</button>');
  });
});
