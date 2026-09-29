import { expect, test } from '@playwright/test';

test('frozen five-category results retain scope, failures, comparisons and all mismatches', async ({ page, request }, info) => {
  const response = await request.get('http://127.0.0.1:8000/api/v1/evaluations/benchmark');
  expect(response.ok()).toBeTruthy();
  const { status, metrics } = await response.json();
  expect(status).toBe('available');
  expect(metrics.evaluation_scope).toBe('frozen_five_category_benchmark');
  expect(metrics.split).toBe('test');
  expect(metrics.source_revision).toBe(process.env.GITHUB_SHA);
  expect(metrics.corpus.case_count).toBe(260);
  expect(metrics.case_count).toBe(108);
  expect(metrics.corpus.fresh_ledgerguard_executions).toBe(0);
  await page.goto('/');
  const panel = page.locator('#benchmark-evaluation');
  await expect(panel.getByRole('heading', { name: 'Frozen authored benchmark', exact: true })).toBeVisible();
  await expect(panel.getByText('Frozen authored test split · inspect limitations', { exact: true })).toBeVisible();
  await expect(panel.getByText(metrics.source_revision, { exact: true })).toBeVisible();
  const partition = panel.getByRole('table', { name: 'Frozen corpus partitions' });
  await expect(partition.getByRole('row')).toHaveCount(4);
  const summary = panel.locator('summary').filter({ hasText: 'Five-category confusion matrix' });
  await summary.focus(); await page.keyboard.press('Enter');
  const matrix = panel.getByRole('table', { name: 'Test split classifications — rows are truth, columns are predictions' });
  await expect(matrix.getByRole('row')).toHaveCount(6);
  const quality = panel.getByRole('table', { name: 'Measured quality targets — failed targets remain visible' });
  for (const [name, value] of Object.entries(metrics.quality_targets)) {
    const row = quality.getByRole('row').filter({ hasText: name.replaceAll('_', ' ') });
    await expect(row.getByText(value === true ? 'PASS' : value === false ? 'FAIL' : 'NOT RUN', { exact: true })).toBeVisible();
  }
  const errors = panel.locator('summary').filter({ hasText: 'Inspect all test errors' });
  await errors.click();
  if (metrics.error_examples.length) {
    await expect(panel.getByRole('table', { name: 'Every retained test mismatch, including product abstentions' }).getByRole('row')).toHaveCount(metrics.error_examples.length + 1);
  }
  const width = await page.evaluate(() => [document.documentElement.scrollWidth, document.documentElement.clientWidth]);
  expect(width[0]).toBeLessThanOrEqual(width[1] + 1);
  await panel.screenshot({ path: info.outputPath('m63-benchmark.png') });
});
