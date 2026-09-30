import { afterEach, expect, it, vi } from 'vitest';
import { loadGitHubReport } from './github-report';
import { evidenceFixture, reportFixture, reportPair } from './github-report-fixtures';

afterEach(() => vi.unstubAllGlobals());

it('verifies nullable numeric history beside a finite current performance finding', async () => {
  const performance = {
    count: 2,
    stored_status_counts: { WITHIN_TOLERANCE: 1, REGRESSION: 1 },
    items: [
      { comparison_id: 'old-comparison', status: 'NUMERIC_UNAVAILABLE', stored_status: 'WITHIN_TOLERANCE', numeric_state: 'unavailable', numeric_reasons: ['performance_numeric_unavailable'], current_value: 1.2e308, baseline_value: null, allowed_absolute_change: null, relative_change: null, baseline_members: [] },
      { comparison_id: 'new-comparison', status: 'REGRESSION', numeric_state: 'available', current_value: 1.2e308, baseline_value: 1e308, relative_change: 0.2, baseline_members: [] }
    ]
  };
  const { reportRaw } = await reportPair(evidenceFixture, {
    ...reportFixture, performance,
    markdown: 'HOLD_FOR_REVIEW\nNUMERIC_UNAVAILABLE: original record retained\nREGRESSION: current finding',
  });
  vi.stubGlobal('fetch', vi.fn().mockResolvedValue(new Response(reportRaw)));
  const report = await loadGitHubReport('run-1');
  expect(report.raw_json).toBe(reportRaw);
  expect(report.markdown).toContain('NUMERIC_UNAVAILABLE');
  expect(report.markdown).toContain('REGRESSION');
  expect(JSON.parse(report.raw_json!).performance).toEqual(performance);
});
