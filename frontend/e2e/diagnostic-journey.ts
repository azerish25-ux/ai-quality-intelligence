import { readFileSync } from 'node:fs';
import { expect, test, type APIRequestContext } from '@playwright/test';
import type { RunDetail } from '../src/api';

// The detail endpoint wraps the run in { run, failure_types, failure_count }.
// Validate its identity before building a link so a malformed response fails here.
async function projectForRun(request: APIRequestContext, runId: string): Promise<string> {
  const response = await request.get(`http://127.0.0.1:8000/api/v1/runs/${runId}`);
  expect(response.ok()).toBeTruthy();
  const detail: RunDetail = await response.json();
  expect(detail.run.id).toBe(runId);
  expect(detail.run.project_id).toMatch(/^[0-9a-f]{8}-(?:[0-9a-f]{4}-){3}[0-9a-f]{12}$/i);
  return detail.run.project_id;
}

// Read only saved predictions, never labels. The backend is the freshly replayed
// PostgreSQL database for this exact source, not a mocked response service.
const kinds = ['operation_isolation', 'projection_ordering', 'weekly_recurrence',
  'atomic_transfer', 'tenant_isolation', 'status_expectation', 'runner_memory_limit'];
for (const kind of kinds) {
  test(`inspect execution-bound ${kind}`, async ({ page, request }, info) => {
    const path = process.env.FAILURELENS_DIAGNOSTIC_REPLAY;
    if (!path) throw new Error('Exact-source diagnostic replay is required');
    const replay = JSON.parse(readFileSync(path, 'utf8'));
    expect(replay.source_revision).toBe(process.env.GITHUB_SHA);
    expect(replay.source_worktree_dirty).toBe(false);
    expect(replay.database_dialect).toBe('postgresql');
    const row = replay.cases.find((r: { analysis: { claims: { predicate?: { contract?: string } }[] } }) =>
      r.analysis.claims.some(claim => claim.predicate?.contract === kind));
    expect(row).toBeTruthy();
    const projectId = await projectForRun(request, row.run_id);
    await page.goto(`/?project=${projectId}&run=${row.run_id}&failure=${row.analysis.failure_id}#workspace`);
    const diagnostic = page.getByRole('region', { name: 'Diagnostic evidence', exact: true });
    await expect(diagnostic).toBeVisible();
    await expect(diagnostic.getByText(`${kind.replaceAll('_', ' ')} · violated`, { exact: true })).toBeVisible();
    await expect(diagnostic.getByText('A conforming narrow check does not establish that the failure or product is harmless.', { exact: true })).toBeVisible();
    for (const id of row.analysis.supporting_evidence_ids) {
      const evidence = await request.get(`http://127.0.0.1:8000/api/v1/evidence/${id}`);
      expect(evidence.ok()).toBeTruthy();
    }
    expect(await page.evaluate(() => document.documentElement.scrollWidth <= document.documentElement.clientWidth + 1)).toBe(true);
    await diagnostic.screenshot({ path: info.outputPath(`${kind}.png`) });
  });
}

test('missing measurements remain visible as an unresolved diagnosis', async ({ page, request }, info) => {
  const replay = JSON.parse(readFileSync(process.env.FAILURELENS_DIAGNOSTIC_REPLAY!, 'utf8'));
  const row = replay.cases.find((r: { analysis: { validation_results: { diagnostic_gap: string } } }) =>
    r.analysis.validation_results.diagnostic_gap === 'missing_or_invalid_observations');
  expect(row.analysis.category).toBe('insufficient_evidence');
  const projectId = await projectForRun(request, row.run_id);
  await page.goto(`/?project=${projectId}&run=${row.run_id}&failure=${row.analysis.failure_id}#workspace`);
  const diagnostic = page.getByRole('region', { name: 'Diagnostic evidence', exact: true });
  await expect(diagnostic.getByRole('status')).toHaveText('Required observations are missing or invalid.');
  await diagnostic.screenshot({ path: info.outputPath('missing-observations.png') });
});
