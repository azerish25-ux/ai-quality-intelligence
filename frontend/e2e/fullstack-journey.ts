import { expect, test } from '@playwright/test';

test('actual full-stack measurements, persisted diagnoses and bounded evidence are inspectable', async ({ page, request }, info) => {
  const response = await request.get('http://127.0.0.1:8000/api/v1/evaluations/fullstack');
  expect(response.ok()).toBeTruthy();
  const { status, metrics } = await response.json();
  expect(status).toBe('available');
  expect(metrics.evaluation_scope).toBe('http_postgresql_fault_proxy');
  expect(metrics.database_dialect).toBe('postgresql');
  expect(metrics.source_revision).toBe(process.env.GITHUB_SHA);
  expect(metrics.family_count).toBe(1);
  expect(metrics.inspection).toHaveLength(8);
  for (const item of metrics.inspection) {
    const analysisResponse = await request.get(`http://127.0.0.1:8000/api/v1/analyses/${item.analysis_id}`);
    expect(analysisResponse.ok()).toBeTruthy();
    const analysis = await analysisResponse.json();
    expect(analysis.category).toBe(item.category);
    expect(item.committed_effects).toBe(item.role === 'control' ? 1 : 2);
    for (const id of item.evidence_ids) {
      const evidence = await request.get(`http://127.0.0.1:8000/api/v1/evidence/${id}`);
      expect(evidence.ok()).toBeTruthy();
      expect((await evidence.json()).excerpt).toContain('transaction-observations-v1');
    }
  }
  await page.goto('/');
  const panel = page.locator('#fullstack-evaluation');
  await expect(panel.getByRole('heading', { name: 'HTTP and database retry evaluation' })).toBeVisible();
  await expect(panel.getByText('Executed HTTP/PostgreSQL · development only', { exact: true })).toBeVisible();
  await expect(panel.getByText('The injected defect is in the retry proxy', { exact: false })).toBeVisible();
  const summary = panel.locator('summary').filter({ hasText: 'Inspect control and intervention observations' });
  await summary.focus(); await page.keyboard.press('Enter');
  const observations = panel.getByRole('table', { name: 'Actual committed effects and persisted classifications' });
  await expect(observations.getByRole('row')).toHaveCount(9);
  for (const table of await panel.getByRole('table').all()) {
    await expect(table.locator('caption')).not.toBeEmpty();
    for (const header of await table.locator('th').all()) await expect(header).toHaveAttribute('scope', 'col');
  }
  const width = await page.evaluate(() => [document.documentElement.scrollWidth, document.documentElement.clientWidth]);
  expect(width[0]).toBeLessThanOrEqual(width[1] + 1);
  await panel.screenshot({ path: info.outputPath('m62-fullstack-evaluation.png') });
});
