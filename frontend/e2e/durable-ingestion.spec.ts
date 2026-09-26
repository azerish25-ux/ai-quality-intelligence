import { expect, test } from '@playwright/test';

test('uploads a real JUnit report and opens the automatically analyzed run', async ({ page }) => {
  await page.goto('/');
  await page.getByRole('button', { name: 'Load synthetic demo' }).click();
  await expect(page.getByRole('heading', { name: 'Upload an actual test report' })).toBeVisible();

  await page.getByLabel('External run ID').fill('browser-e2e-1');
  await page.getByLabel('Expected observations').fill('1');
  await page.getByLabel('Report file').setInputFiles({
    name: 'browser-junit.xml',
    mimeType: 'application/xml',
    buffer: Buffer.from(
      '<testsuite name="payments"><testcase classname="Transfer" name="duplicate"><failure type="LedgerInvariantError" message="duplicate committed transfer">ledger unbalanced after double charge</failure></testcase></testsuite>'
    )
  });
  await page.getByRole('button', { name: 'Queue ingestion' }).click();

  const ingestion = page.locator('.ingestion-row', { hasText: 'browser-e2e-1' });
  await expect(ingestion).toBeVisible();
  await expect(ingestion.getByText('Succeeded')).toBeVisible();
  await ingestion.getByRole('button', { name: 'Open run' }).click();

  const failure = page.locator('.failure-row', { hasText: 'Transfer::duplicate' });
  await expect(failure).toBeVisible();
  await failure.click();
  await expect(
    page.locator('.analysis-summary').getByText('Probable product defect', { exact: true })
  ).toBeVisible();
  await expect(page.locator('.analysis-summary').getByText(/validated current-run observations/i)).toBeVisible();
});
