import { expect, test } from '@playwright/test';

test('keeps every critical workflow reachable without horizontal page overflow', async ({ page }) => {
  await page.goto('/');
  await page.getByRole('button', { name: 'Load synthetic demo' }).click();

  await expect(page.locator('.sidebar')).toBeHidden();
  const compactNavigation = page.locator('.mobile-navigation');
  await expect(compactNavigation.getByText('Navigate', { exact: true })).toBeVisible();
  await compactNavigation.getByText('Navigate', { exact: true }).click();
  await compactNavigation.getByRole('link', { name: 'Review queue' }).click();
  await expect(page.locator('#reviews').getByRole('heading', { name: 'Review queue' })).toBeInViewport();

  await compactNavigation.evaluate((element: Element) => { (element as HTMLDetailsElement).open = true; });
  await compactNavigation.getByRole('link', { name: 'Settings' }).click();
  await expect(page.locator('#settings').getByRole('heading', { name: 'Roles and ingestion credentials' })).toBeInViewport();
  await expect(page.getByRole('button', { name: 'Refresh health' })).toBeVisible();

  const overflow = await page.evaluate(() => ({
    documentWidth: document.documentElement.scrollWidth,
    viewportWidth: document.documentElement.clientWidth,
    bodyWidth: document.body.scrollWidth
  }));
  expect(overflow.documentWidth).toBeLessThanOrEqual(overflow.viewportWidth + 1);
  expect(overflow.bodyWidth).toBeLessThanOrEqual(overflow.viewportWidth + 1);

  await page.reload();
  await page.keyboard.press('Tab');
  await expect(page.getByRole('link', { name: 'Skip to main content' })).toBeFocused();
});
