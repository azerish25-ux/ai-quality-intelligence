import { expect, type APIRequestContext, type Page, type TestInfo } from '@playwright/test';

export async function evaluationJourney(page: Page, request: APIRequestContext, info: TestInfo) {
  const response = await request.get('http://127.0.0.1:8000/api/v1/evaluations/latest');
  expect(response.ok()).toBeTruthy();
  const { metrics } = await response.json();
  expect(metrics.evaluation_scope).toBe('production_component_challenge');
  expect(metrics.source_counts.ledgerguard_executed).toBe(60);
  expect(metrics.family_count).toBe(15);
  expect(metrics.database_dialect).toBe('postgresql');
  expect(metrics.source_worktree_dirty).toBe(false);
  expect(metrics.full_m6_complete).toBe(false);
  await page.goto('/');
  const panel = page.locator('#evaluation');
  await expect(panel.getByText('Executed LedgerGuard components', { exact: true })).toBeVisible();
  await panel.scrollIntoViewIfNeeded();
  await expect(panel.locator('.eval-grid').getByText('60', { exact: true })).toBeVisible();
  await expect(panel.locator('.eval-grid').getByText('Not established', { exact: true })).toBeVisible();
  await expect(panel.locator('.eval-grid').getByText(`${(metrics.product_defect_recall * 100).toFixed(1)}%`, { exact: true })).toBeVisible();
  const dangerous = metrics.dangerous_dismissal;
  await expect(panel.locator('.eval-grid').getByText(`${dangerous.numerator}/${dangerous.denominator}`, { exact: true })).toBeVisible();
  for (const [name, passed] of Object.entries(metrics.quality_targets)) {
    const row = panel.getByRole('row').filter({ has: page.getByRole('cell', { name: name.replaceAll('_', ' '), exact: true }) });
    await expect(row.getByRole('cell', { name: passed ? 'PASS' : 'FAIL', exact: true })).toBeVisible();
  }
  const mechanismSummary = panel.locator('summary').filter({ hasText: 'Results by fault mechanism' });
  await mechanismSummary.focus();
  await page.keyboard.press('Enter');
  // The inner locator must be relative to each details element, not #evaluation.
  const detail = panel.locator('details').filter({ has: page.locator('summary').filter({ hasText: 'Results by fault mechanism' }) });
  await expect(detail).toHaveAttribute('open', '');
  await expect(detail.getByRole('row')).toHaveCount(metrics.family_count + 1);
  const integritySummary = panel.locator('summary').filter({ hasText: 'Execution and evidence-integrity checks' });
  await integritySummary.focus();
  await page.keyboard.press('Enter');
  for (const table of await panel.getByRole('table').all()) {
    await expect(table.locator('caption')).not.toBeEmpty();
    const headers = table.locator('thead th');
    expect(await headers.count()).toBeGreaterThan(0);
    for (const header of await headers.all()) await expect(header).toHaveAttribute('scope', 'col');
  }
  await integritySummary.focus();
  await page.keyboard.press('Enter');
  const width = await page.evaluate(() => [document.documentElement.scrollWidth, document.documentElement.clientWidth]);
  expect(width[0]).toBeLessThanOrEqual(width[1] + 1);
  const scrollRegion = detail.getByRole('region', { name: 'Fault mechanism results; scroll horizontally for all columns' });
  const hasOverflow = await scrollRegion.evaluate((element) => element.scrollWidth > element.clientWidth);
  if (hasOverflow) {
    await scrollRegion.focus();
    await page.keyboard.press('ArrowRight');
    await expect.poll(() => scrollRegion.evaluate((element) => element.scrollLeft)).toBeGreaterThan(0);
    await scrollRegion.evaluate((element) => { element.scrollLeft = 0; });
  }
  await panel.screenshot({ path: info.outputPath('m6-executed-evaluation.png') });
}
