import { readFileSync } from 'node:fs';
import { expect, test } from '@playwright/test';

const API = 'http://127.0.0.1:8000/api/v1';
const PASSWORD = 'synthetic-browser-account-password';
const NEW_PASSWORD = 'synthetic-browser-new-password';

test('human password rotation and individual session revocation use real cookies', async ({ page, request }, testInfo) => {
  const username = `m53-${testInfo.project.name}-${Date.now()}-${testInfo.retry}`;
  const created = await request.post(`${API}/users`, { data: {
    username, display_name: 'M5.3 browser user', password: PASSWORD, system_admin: false
  }});
  expect(created.status()).toBe(201);
  const second = await request.post(`${API}/auth/login`, { data: { username, password: PASSWORD } });
  const oldToken = (await second.json()).access_token;
  expect((await page.request.post(`${API}/auth/login`, { data: { username, password: PASSWORD } })).ok()).toBeTruthy();
  await page.goto('/');
  const account = page.locator('#account');
  await expect(account.getByRole('heading', { name: 'Account security' })).toBeVisible();
  await account.getByLabel('Current password', { exact: true }).fill(PASSWORD);
  await account.getByLabel('New password', { exact: true }).fill(NEW_PASSWORD);
  await account.getByRole('button', { name: 'Change password and revoke older sessions' }).click();
  await expect(account.getByRole('status')).toContainText('Password changed.');
  expect((await request.get(`${API}/auth/me`, { headers: { Authorization: `Bearer ${oldToken}` } })).status()).toBe(401);
  expect((await page.request.get(`${API}/auth/me`)).status()).toBe(200);
  await account.getByRole('button', { name: 'Revoke this session' }).click();
  await expect(page.getByRole('heading', { name: 'Sign in', exact: true })).toBeVisible();
  await page.reload();
  // Demo mode can return its explicit synthetic identity after a refresh. The
  // revoked human bearer remains invalid regardless of the demo fallback.
  expect((await request.get(`${API}/auth/me`, { headers: { Authorization: `Bearer ${oldToken}` } })).status()).toBe(401);
});

test('old investigation remains reachable and retention expires its evidence through the real worker', async ({ page, request }, testInfo) => {
  const fixturePath = process.env.FAILURELENS_OPERATIONS_FIXTURES;
  // CI must supply the actual executed fixture, not silently skip this journey.
  expect(fixturePath, 'Run scripts/seed_operations_browser.py against the disposable test database first').toBeTruthy();
  const fixtures = JSON.parse(readFileSync(fixturePath!, 'utf8')) as Record<string, {project_id: string; run_id: string; failure_id: string; evidence_id: string}>;
  const fixture = fixtures[`${testInfo.project.name}:${testInfo.retry}`];
  expect(fixture).toBeTruthy();
  await page.goto(`/?project=${fixture.project_id}&run=${fixture.run_id}&failure=${fixture.failure_id}`);
  await expect(page.locator('#runs').getByLabel('Run')).toHaveValue(fixture.run_id);
  const queue = page.locator('#reviews');
  await queue.getByLabel('Search', { exact: true }).fill('retention-old-payment');
  await expect(queue.getByText('retention-old-payment', { exact: true })).toBeVisible();
  const panel = page.locator('section[aria-labelledby="retention-heading"]');
  await panel.getByLabel('Restricted source retention (days)').fill('7');
  await panel.getByLabel('Safe evidence retention (days)').fill('90');
  await panel.getByLabel('Retention change reason').fill('Disposable browser retention verification');
  await panel.getByRole('button', { name: 'Preview policy change', exact: true }).click();
  await panel.getByLabel('I understand the worker will enforce this policy and expiry cannot be undone.').check();
  await panel.getByRole('button', { name: 'Save retention policy', exact: true }).click();
  await expect(panel).toContainText('Saved policy revision 2');
  await panel.getByRole('button', { name: 'Preview cleanup under saved policy', exact: true }).click();
  await panel.getByRole('button', { name: 'Confirm and queue cleanup', exact: true }).click();
  await expect.poll(async () => (await (await request.get(`${API}/runs/${fixture.run_id}`)).json()).evidence_expired_at, { timeout: 30_000 }).toBeTruthy();
  await expect(page.getByText(/^Evidence expired\. Recorded category:/)).toBeVisible();
  expect((await request.get(`${API}/evidence/${fixture.evidence_id}`)).status()).toBe(410);
  await page.reload();
  await expect(page.locator('#runs').getByLabel('Run')).toHaveValue(fixture.run_id);
  await expect(page.getByText(/^Evidence expired\. Recorded category:/)).toBeVisible();
  await expect(panel).toContainText('run evidence');
});
