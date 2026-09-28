import { readFileSync } from 'node:fs';
import { expect, test, type Page, type TestInfo } from '@playwright/test';

const API = '/api/v1';
type Fixture = { project_id: string; run_id: string; failure_id: string; evidence_id: string };
const fixtureFor = (testInfo: TestInfo): Fixture => {
  const path = process.env.FAILURELENS_OPERATIONS_FIXTURES;
  expect(path, 'Seed the real disposable operational fixtures first').toBeTruthy();
  const fixtures = JSON.parse(readFileSync(path!, 'utf8')) as Record<string, Fixture>;
  const fixture = fixtures[`${testInfo.project.name}:${testInfo.retry}`];
  expect(fixture).toBeTruthy();
  return fixture;
};
const runSelect = (page: Page) => page.locator('#runs').getByLabel('Run', { exact: true });
const projectSelect = (page: Page) => page.locator('#runs').getByLabel('Project', { exact: true });

// All responses come from the actual API. No route is fulfilled with invented
// project, run, failure, retention or authorization data.
test('loading the demo selects its returned run despite newer failure-free runs and other projects', async ({ page }, testInfo) => {
  const fixture = fixtureFor(testInfo);
  const seedResponse = await page.request.post(`${API}/demo/seed`);
  expect(seedResponse.ok()).toBeTruthy();
  const seed = await seedResponse.json() as { project_id: string; run_id: string };
  const newer = await page.request.post(`${API}/projects/${seed.project_id}/ingestions`, { data: {
    external_id: `navigation-control-${testInfo.project.name}-${testInfo.retry}-${Date.now()}`,
    observations: [{ test_identity: 'newer-passing-control', outcome: 'passed' }]
  } });
  expect(newer.status()).toBe(202);
  await page.goto(`/?project=${fixture.project_id}&run=${fixture.run_id}`);
  await expect(runSelect(page)).toHaveValue(fixture.run_id);
  await page.getByRole('button', { name: 'Load synthetic demo' }).click();
  await expect(page.locator('.sr-only[role="status"]')).toHaveText('Synthetic demo data loaded.');
  await expect(projectSelect(page)).toHaveValue(seed.project_id);
  await expect(runSelect(page)).toHaveValue(seed.run_id);
  await expect(page.locator('#history').getByLabel('Branch', { exact: true })).toBeVisible();
  await page.reload();
  await expect(runSelect(page)).toHaveValue(seed.run_id);
  await expect(page.locator('#history').getByLabel('Branch', { exact: true })).toBeVisible();
});

test('Back and Forward restore an old investigation outside the recent-run page', async ({ page }, testInfo) => {
  const fixture = fixtureFor(testInfo);
  const seedResponse = await page.request.post(`${API}/demo/seed`);
  expect(seedResponse.ok()).toBeTruthy();
  const seed = await seedResponse.json() as { project_id: string; run_id: string };
  const recent = await page.request.get(`${API}/projects/${fixture.project_id}/runs`);
  expect(recent.ok()).toBeTruthy();
  expect((await recent.json() as { id: string }[]).some(run => run.id === fixture.run_id)).toBe(false);
  await page.goto(`/?project=${fixture.project_id}&run=${fixture.run_id}&failure=${fixture.failure_id}&history_branch=old-link`);
  await expect(page.locator('#history').getByLabel('Branch', { exact: true })).toHaveValue('old-link');
  await expect(runSelect(page)).toHaveValue(fixture.run_id);
  // Exercise the SPA's real popstate handler with a history entry for another
  // project, then use actual browser Back/Forward (not a page reload).
  await page.evaluate(url => {
    window.history.pushState(null, '', url);
    window.dispatchEvent(new PopStateEvent('popstate'));
  }, `/?project=${seed.project_id}&run=${seed.run_id}`);
  await expect(projectSelect(page)).toHaveValue(seed.project_id);
  await expect(runSelect(page)).toHaveValue(seed.run_id);
  await expect(page.locator('#history').getByLabel('Branch', { exact: true })).toHaveValue('');
  await page.goBack();
  await expect(projectSelect(page)).toHaveValue(fixture.project_id);
  await expect(runSelect(page)).toHaveValue(fixture.run_id);
  await expect(page.locator('#history').getByLabel('Branch', { exact: true })).toHaveValue('old-link');
  await page.goForward();
  await expect(projectSelect(page)).toHaveValue(seed.project_id);
  await expect(runSelect(page)).toHaveValue(seed.run_id);
});

test('missing and cross-project run URLs never fall back to a different investigation', async ({ page }, testInfo) => {
  const fixture = fixtureFor(testInfo);
  const seedResponse = await page.request.post(`${API}/demo/seed`);
  expect(seedResponse.ok()).toBeTruthy();
  const seed = await seedResponse.json() as { project_id: string; run_id: string };
  for (const id of ['not-a-real-run', seed.run_id]) {
    await page.goto(`/?project=${fixture.project_id}&run=${id}`);
    await expect(page.getByRole('alert').filter({ hasText: 'Requested investigation is unavailable in this project.' })).toBeVisible();
    await expect(runSelect(page)).toHaveValue(id);
    await expect(page.locator('#workspace .failure-row')).toHaveCount(0);
    expect(new URL(page.url()).searchParams.get('run')).toBe(id);
  }
});

test('a late project response cannot undo a newer project selection', async ({ page }, testInfo) => {
  const fixture = fixtureFor(testInfo);
  const seedResponse = await page.request.post(`${API}/demo/seed`);
  expect(seedResponse.ok()).toBeTruthy();
  const seed = await seedResponse.json() as { project_id: string; run_id: string };
  let release!: () => void;
  const hold = new Promise<void>(resolve => { release = resolve; });
  let requested!: () => void;
  const seen = new Promise<void>(resolve => { requested = resolve; });
  await page.route(`**/api/v1/projects/${fixture.project_id}/runs`, async route => {
    const response = await route.fetch();
    requested();
    await hold;
    await route.fulfill({ response });
  });
  try {
    await page.goto(`/?project=${fixture.project_id}&run=${fixture.run_id}`);
    await seen;
    await projectSelect(page).selectOption(seed.project_id);
    await expect(projectSelect(page)).toHaveValue(seed.project_id);
    release();
    await expect.poll(async () => (await runSelect(page).inputValue()).length).toBeGreaterThan(0);
    await expect(runSelect(page).locator('option:checked')).not.toHaveText(/Loading requested|unavailable/);
    const id = await runSelect(page).inputValue();
    const detail = await page.request.get(`${API}/runs/${id}`);
    expect(detail.ok()).toBeTruthy();
    expect((await detail.json()).run.project_id).toBe(seed.project_id);
    await expect(projectSelect(page)).toHaveValue(seed.project_id);
  } finally {
    release();
    await page.unrouteAll({ behavior: 'wait' });
  }
});
