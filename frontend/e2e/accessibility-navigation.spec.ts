import { expect, test } from '@playwright/test';

test('supports keyboard navigation, named controls, and URL-restored investigation state', async ({ page }) => {
  await page.goto('/');

  await page.keyboard.press('Tab');
  await expect(page.getByRole('link', { name: 'Skip to main content' })).toBeFocused();
  await page.keyboard.press('Enter');
  await expect(page.locator('#main-content')).toBeFocused();

  await page.getByRole('button', { name: 'Load synthetic demo' }).click();
  await expect(page.getByRole('heading', { name: 'Upload an actual test report' })).toBeVisible();

  const issues = await page.evaluate(() => {
    const isVisible = (element: Element): boolean => {
      const node = element as HTMLElement;
      const style = window.getComputedStyle(node);
      const box = node.getBoundingClientRect();
      return style.display !== 'none' && style.visibility !== 'hidden' && box.width > 0 && box.height > 0;
    };
    const controls = Array.from(document.querySelectorAll('input:not([type="hidden"]), select, textarea'))
      .filter(isVisible)
      .filter((control) => {
        const field = control as HTMLInputElement;
        return !(field.labels?.length || field.getAttribute('aria-label') || field.getAttribute('aria-labelledby') || field.title);
      })
      .map((control) => `${control.tagName.toLowerCase()}#${(control as HTMLElement).id || 'unnamed'}`);
    const buttons = Array.from(document.querySelectorAll('button, summary'))
      .filter(isVisible)
      .filter((control) => !(control.textContent?.trim() || control.getAttribute('aria-label') || control.getAttribute('aria-labelledby')))
      .map((control) => control.outerHTML.slice(0, 120));
    const headings = Array.from(document.querySelectorAll('h1, h2, h3, h4, h5, h6'))
      .filter(isVisible)
      .map((heading) => Number(heading.tagName.slice(1)));
    const headingJumps = headings.slice(1).filter((level, index) => level - headings[index] > 1);
    const tables = Array.from(document.querySelectorAll('table'))
      .filter(isVisible)
      .filter((table) => !table.querySelector('caption') || !table.querySelector('th[scope="col"]'))
      .map((table) => table.outerHTML.slice(0, 120));
    const emptyStatuses = Array.from(document.querySelectorAll('.state, .pill'))
      .filter(isVisible)
      .filter((status) => !status.textContent?.trim())
      .map((status) => status.outerHTML.slice(0, 120));
    return { controls, buttons, headingJumps, tables, emptyStatuses };
  });

  expect(issues).toEqual({ controls: [], buttons: [], headingJumps: [], tables: [], emptyStatuses: [] });

  const projectSelect = page.locator('#ingestion').getByLabel('Project');
  const runSelect = page.locator('#runs').getByLabel('Run');
  const projectId = await projectSelect.inputValue();
  const runId = await runSelect.inputValue();
  expect(projectId).not.toBe('');
  expect(runId).not.toBe('');

  await expect.poll(() => new URL(page.url()).searchParams.get('project')).toBe(projectId);
  await expect.poll(() => new URL(page.url()).searchParams.get('run')).toBe(runId);

  const historyBranch = page.locator('#history').getByLabel('Branch');
  await historyBranch.fill('main/accessibility');
  await expect.poll(() => new URL(page.url()).searchParams.get('history_branch')).toBe('main/accessibility');

  await page.reload();
  await expect(page.locator('#ingestion').getByLabel('Project')).toHaveValue(projectId);
  await expect(page.locator('#runs').getByLabel('Run')).toHaveValue(runId);
  await expect(page.locator('#history').getByLabel('Branch')).toHaveValue('main/accessibility');
  const restored = new URL(page.url());
  expect(restored.searchParams.get('project')).toBe(projectId);
  expect(restored.searchParams.get('run')).toBe(runId);
  expect(restored.searchParams.get('history_branch')).toBe('main/accessibility');
});

test('review and audit controls expose useful names and persistent filters', async ({ page }) => {
  await page.goto('/');
  await page.getByRole('button', { name: 'Load synthetic demo' }).click();

  const reviewSection = page.locator('#reviews');
  await expect(reviewSection.getByRole('heading', { name: 'Review queue' })).toBeVisible();
  await reviewSection.getByLabel('Status').selectOption('all');
  await reviewSection.getByLabel('Sort').selectOption('severity');
  await reviewSection.getByLabel('Search').fill('transfer');
  await expect.poll(() => new URL(page.url()).searchParams.get('review_status')).toBe('all');
  await expect.poll(() => new URL(page.url()).searchParams.get('review_sort')).toBe('severity');
  await expect.poll(() => new URL(page.url()).searchParams.get('review_search')).toBe('transfer');

  const auditSection = page.locator('#audit');
  await expect(auditSection.getByRole('heading', { name: 'Project audit events' })).toBeVisible();
  await auditSection.getByLabel('Sort').selectOption('oldest');
  await expect.poll(() => new URL(page.url()).searchParams.get('audit_sort')).toBe('oldest');
  await expect(auditSection.getByRole('button', { name: 'Export filtered CSV' })).toBeVisible();
});
