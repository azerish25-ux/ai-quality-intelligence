import { expect, type Page, type TestInfo } from '@playwright/test';

/** Real API-backed synthetic data. No invented responses or browser interception. */
export async function workbenchJourney(page: Page, info: TestInfo) {
  const errors: string[] = [];
  page.on('pageerror', error => errors.push(error.message));
  await page.goto('/');
  await page.getByRole('button', { name: 'Load synthetic demo' }).click();
  await expect(page.locator('.sr-only[role="status"]')).toHaveText('Synthetic demo data loaded.');
  await expect(page.getByRole('heading', { name: 'Investigation desk.' })).toBeVisible();
  const overview = page.getByRole('region', { name: 'Overview metrics' });
  await expect(overview.getByRole('link')).toHaveCount(4);
  await expect(overview).toContainText('Historical analysis revisions, not a current release verdict');
  await expect.poll(() => page.locator('.failure-row').count()).toBeGreaterThan(0);
  const order = await page.evaluate(() => {
    const workspace = document.getElementById('workspace')!;
    return ['ingestion', 'impact', 'performance'].every(id => Boolean(workspace.compareDocumentPosition(document.getElementById(id)!) & Node.DOCUMENT_POSITION_FOLLOWING));
  });
  expect(order, 'The core investigation must precede administrative and secondary tools').toBe(true);
  await page.screenshot({ path: info.outputPath('workbench-overview.png') });
  const runId = await page.locator('#runs').getByLabel('Run', { exact: true }).inputValue();
  await overview.getByRole('link', { name: /Failures recorded/ }).click();
  await expect(page.locator('#workspace')).toBeFocused();
  await expect(page.locator('#workspace')).toBeInViewport();
  expect(new URL(page.url()).searchParams.get('run')).toBe(runId);
  const rows = page.locator('.failure-row');
  await rows.last().click();
  await expect(rows.last()).toHaveAttribute('aria-pressed', 'true');
  await expect(page.locator('.failure-row[aria-pressed="true"]')).toHaveCount(1);
  await page.locator('#workspace').screenshot({ path: info.outputPath('workbench-investigation.png') });
  await page.reload();
  await expect(page.locator('#runs').getByLabel('Run', { exact: true })).toHaveValue(runId);
  await expect(page.locator('.failure-row[aria-pressed="true"]')).toHaveCount(1);
  await page.locator('.desk-inventory > summary').click();
  await expect(page.locator('.desk-inventory')).toContainText('Infrastructure events');
  const width = await page.evaluate(() => ({ actual: document.documentElement.scrollWidth, viewport: document.documentElement.clientWidth }));
  expect(width.actual).toBeLessThanOrEqual(width.viewport + 1);
  expect(errors).toEqual([]);
}
