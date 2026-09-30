import { expect, test } from '@playwright/test';

test('renders an authorized advisory preview as inert text and downloads the actual report', async ({ page, request }, info) => {
  const seeded = await request.post('http://127.0.0.1:8000/api/v1/demo/seed');
  expect(seeded.ok()).toBeTruthy();
  const { project_id, run_id } = await seeded.json();
  const response = await request.get(`http://127.0.0.1:8000/api/v1/runs/${run_id}/github-report-preview`);
  expect(response.ok()).toBeTruthy();
  const expected = await response.json();
  await page.goto(`/?project=${project_id}&run=${run_id}#github-report`);
  await expect(page).toHaveTitle('Loose Thread · Evidence-grounded triage');
  const panel = page.locator('#github-report');
  await expect(panel.getByText('Report digest:', { exact: false })).toContainText(expected.report_digest);
  await panel.getByText('Inspect sanitized report text', { exact: true }).click();
  const preview = panel.getByLabel('Sanitized GitHub report');
  await expect(preview).toHaveText(expected.markdown);
  await expect(preview.locator('a,img,script')).toHaveCount(0);
  const downloadEvent = page.waitForEvent('download');
  await panel.getByRole('button', { name: 'Download Markdown report' }).click();
  const download = await downloadEvent;
  expect(download.suggestedFilename()).toBe('loose-thread-report.md');
  await panel.getByRole('button', { name: 'Refresh report' }).click();
  await expect(preview).toHaveText(expected.markdown);
  await panel.screenshot({ path: info.outputPath('github-report-preview.png') });
});
