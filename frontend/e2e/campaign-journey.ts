import { expect, test } from '@playwright/test';

// Uses the actual freshly replayed database/report, never favorable UI fixtures.
test('frozen campaign, failures and source-scoped published decisions remain inspectable', async ({ page, request }, info) => {
  const response = await request.get('http://127.0.0.1:8000/api/v1/evaluations/campaign');
  expect(response.ok()).toBeTruthy();
  const { status, metrics } = await response.json();
  expect(status).toBe('available');
  expect(metrics.evaluation_scope).toBe('frozen_mixed_source_campaign');
  expect(metrics.source_revision).toBe(process.env.GITHUB_SHA);
  expect(metrics.source_worktree_dirty).toBe(false);
  expect(metrics.database_dialect).toBe('postgresql');
  expect(metrics.split).toBe('test');
  expect(metrics.case_count).toBe(160);
  expect(metrics.dataset_case_count).toBe(264);
  expect(metrics.source_counts.synthetic).toBe(160);
  expect(metrics.source_counts.ledgerguard_executed).toBe(0);
  expect(metrics.dataset_source_counts.ledgerguard_executed).toBe(60);
  expect(metrics.full_m6_complete).toBe(false);
  expect(Object.keys(metrics.per_category)).toHaveLength(5);
  for (const error of metrics.errors.slice(0, 3)) {
    const result = await request.get(`http://127.0.0.1:8000/api/v1/analyses/${error.analysis_id}`);
    expect(result.ok()).toBeTruthy();
    const analysis = await result.json();
    expect(analysis.category).toBe(error.predicted);
    expect(analysis.run_id).toBe(error.run_id);
    for (const id of analysis.supporting_evidence_ids) {
      const evidence = await request.get(`http://127.0.0.1:8000/api/v1/evidence/${id}`);
      expect(evidence.ok()).toBeTruthy();
      expect((await evidence.json()).excerpt).not.toContain('synthetic-campaign-canary-41729');
    }
  }
  await page.goto('/');
  const panel = page.locator('#campaign-evaluation');
  await expect(panel.getByRole('heading', { name: 'Frozen five-category evaluation' })).toBeVisible();
  await expect(panel.getByText('Frozen five-category campaign · synthetic test split', { exact: true })).toBeVisible();
  await expect(panel.getByText(metrics.source_revision, { exact: true })).toBeVisible();
  const quality = panel.getByRole('table', { name: 'Measured quality targets — failed targets remain visible' });
  for (const [key, value] of Object.entries(metrics.quality_targets)) {
    const row = quality.getByRole('row').filter({ hasText: key.replaceAll('_', ' ') });
    await expect(row.getByRole('cell').last()).toHaveText(value === true ? 'PASS' : value === false ? 'FAIL' : 'NOT RUN');
  }
  const summary = panel.locator('summary').filter({ hasText: 'Five-category results and confusion matrix' });
  await summary.focus(); await page.keyboard.press('Enter');
  const matrix = panel.getByRole('table', { name: 'True category by published category — exact counts' });
  await expect(matrix.getByRole('row')).toHaveCount(6);
  const errorToggle = panel.locator('summary').filter({ hasText: `Inspect test errors (${metrics.errors.length})` });
  await errorToggle.focus(); await page.keyboard.press('Enter');
  const errorTable = panel.getByRole('table', { name: 'All errors remain visible; no cases are removed to improve metrics' });
  await expect(errorTable.getByRole('row')).toHaveCount(metrics.errors.length + 1);
  for (const table of await panel.getByRole('table').all()) {
    await expect(table.locator('caption')).not.toBeEmpty();
    for (const header of await table.locator('th').all()) await expect(header).toHaveAttribute('scope', 'col');
  }
  const widths = await page.evaluate(() => [document.documentElement.scrollWidth, document.documentElement.clientWidth]);
  expect(widths[0]).toBeLessThanOrEqual(widths[1] + 1);
  await errorToggle.click();
  await panel.screenshot({ path: info.outputPath('m63-campaign-evaluation.png') });
});
