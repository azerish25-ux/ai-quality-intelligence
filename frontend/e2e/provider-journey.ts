import { readFileSync } from 'node:fs';
import { expect, type APIRequestContext, type Page, type TestInfo } from '@playwright/test';

interface AnalysisFixture { run_id: string; failure_id: string; analysis_id: string }
interface Fixture {
  project_id: string; username: string; password: string; viewer_username: string; viewer_password: string;
  success: AnalysisFixture; outage: AnalysisFixture; cancel: AnalysisFixture; navigation: AnalysisFixture;
}
const API = 'http://127.0.0.1:8000/api/v1';
export async function providerJourney(page: Page, request: APIRequestContext, info: TestInfo) {
  const fixturePath = process.env.FAILURELENS_PROVIDER_FIXTURES;
  expect(fixturePath, 'Start integrations/provider/browser_fixture.py with an explicitly disposable database').toBeTruthy();
  const fixture = (JSON.parse(readFileSync(fixturePath!, 'utf8')) as Record<string, Fixture>)[`${info.project.name}:${info.retry}`];
  expect(fixture).toBeTruthy();
  const failures: string[] = [];
  page.on('pageerror', error => failures.push(error.message));
  page.on('console', message => { if (message.type() === 'error') failures.push(message.text()); });
  const route = (target: AnalysisFixture) => `${API}/projects/${fixture.project_id}/runs/${target.run_id}/analyses/${target.analysis_id}/provider`;
  const url = (target: AnalysisFixture) => `/?project=${fixture.project_id}&run=${target.run_id}&failure=${target.failure_id}#optional-provider`;
  const panel = page.locator('#optional-provider');
  let sessionToken = '';
  const authenticatedGet = (url: string) => page.request.get(url, { headers: { Authorization: `Bearer ${sessionToken}` } });
  const login = async (viewer = false) => {
    const response = await page.request.post(`${API}/auth/login`, { data: { username: viewer ? fixture.viewer_username : fixture.username, password: viewer ? fixture.viewer_password : fixture.password } });
    expect(response.ok()).toBeTruthy();
    const authenticated = await response.json();
    expect(authenticated.principal.demo_mode).toBe(false);
    expect(authenticated.principal.kind).toBe('user');
    sessionToken = authenticated.access_token;
    // Production secure-cookie settings stay enabled. The isolated HTTP fixture
    // uses the API's ordinary authenticated bearer session, never an insecure
    // cookie exception or a frontend authentication switch. Traces remain off.
    await page.context().setExtraHTTPHeaders({ Authorization: `Bearer ${sessionToken}` });
  };
  const submit = async () => {
    const consent = panel.getByRole('checkbox', { name: /I approve sending/ });
    await expect(consent).toBeEnabled();
    await consent.focus(); await page.keyboard.press('Space');
    await page.keyboard.press('Tab');
    const button = panel.getByRole('button', { name: 'Submit reviewed proposal request' });
    await expect(button).toBeFocused();
    await page.keyboard.press('Enter');
    await expect(panel.getByRole('status')).toBeFocused();
  };
  // No unauthenticated demo principal exists in this dedicated production-auth lane.
  expect((await request.get(`${route(fixture.success)}/preview`)).status()).toBe(401);
  const denied = await request.post(`${route(fixture.success)}/invocations`, { data: { analysis_revision: 1, preview_digest: 'a'.repeat(64), configuration_digest: 'b'.repeat(64), idempotency_key: 'unauthenticated-denied' } });
  expect(denied.status()).toBe(401);
  await login();
  expect((await page.request.post(`${API}/demo/seed`, { headers: { Authorization: `Bearer ${sessionToken}` } })).status()).toBe(403);
  const approvedPreview = await (await authenticatedGet(`${route(fixture.success)}/preview`)).json();
  expect(approvedPreview.can_submit).toBe(true);
  await page.goto(url(fixture.success));
  await expect(panel.getByRole('heading', { name: 'Optional model proposal' })).toBeVisible();
  await expect(panel).toContainText('Configured for requests');
  await expect(panel).toContainText('Configuration status does not verify live provider connectivity');
  await expect(panel).toContainText('Unknown cost does not mean zero');
  await expect(panel).toContainText(approvedPreview.preview_digest);
  await expect(panel).toContainText('https://provider-fixture.invalid');
  const deterministic = await page.locator('.analysis-summary').innerText();
  await panel.getByText('Inspect approved evidence scope', { exact: true }).click();
  await expect(panel.locator('.provider-evidence')).toContainText('PROVIDER_BROWSER_SUCCESS');
  await submit();
  await expect(panel.getByRole('heading', { name: 'Unverified proposal available' })).toBeVisible();
  await expect(panel).toContainText('Disagrees with the selected deterministic analysis');
  await expect(panel.locator('.provider-proposal')).toContainText('<img src=x onerror="window.providerInjected=true">');
  await expect(panel.locator('.provider-proposal img,.provider-proposal script')).toHaveCount(0);
  expect(await page.evaluate(() => 'providerInjected' in window)).toBe(false);
  expect(await page.locator('.analysis-summary').innerText()).toBe(deterministic);
  await panel.getByText('Inspect per-attempt accounting (1)', { exact: true }).click();
  await expect(panel.locator('.provider-attempts')).toContainText('100 input / 20 output tokens');
  await expect(panel.locator('.provider-attempts')).toContainText('Unknown cost');
  const jobs = await (await authenticatedGet(`${route(fixture.success)}/invocations`)).json();
  expect(jobs.items).toHaveLength(1); expect(jobs.items[0].attempts).toHaveLength(1);
  const sameJob = jobs.items[0].invocation_id;
  await page.reload(); await expect(panel).toContainText(sameJob);
  expect((await (await authenticatedGet(`${route(fixture.success)}/invocations`)).json()).items).toHaveLength(1);
  await panel.screenshot({ path: info.outputPath('provider-proposal.png') });
  await expect.poll(() => page.evaluate(() => document.documentElement.scrollWidth <= document.documentElement.clientWidth + 1)).toBe(true);
  await login(true); await page.reload();
  await expect(panel).toContainText('Read-only provider access');
  await expect(panel.getByRole('button', { name: 'Submit reviewed proposal request' })).toHaveCount(0);
  await expect(panel).toContainText(sameJob);
  const viewerHeaders = { Authorization: `Bearer ${sessionToken}` };
  expect((await page.request.post(`${route(fixture.success)}/invocations`, { headers: viewerHeaders, data: { analysis_revision: approvedPreview.analysis_revision, preview_digest: approvedPreview.preview_digest, configuration_digest: approvedPreview.configuration_digest, idempotency_key: 'viewer-denied' } })).status()).toBe(403);
  expect((await page.request.post(`${route(fixture.success)}/invocations/${sameJob}/cancel`, { headers: viewerHeaders })).status()).toBe(403);
  await login(); await page.goto(url(fixture.outage)); await submit();
  await expect(panel.getByRole('heading', { name: 'Deterministic fallback' })).toBeVisible();
  await expect(panel).toContainText('Unknown cost');
  await expect(panel).toContainText('No current safe model proposal is available');
  await expect(panel.locator('.provider-proposal')).toHaveCount(0);
  await panel.screenshot({ path: info.outputPath('provider-outage.png') });
  await page.goto(url(fixture.cancel)); await submit();
  const cancelButton = panel.getByRole('button', { name: 'Request cancellation', exact: true });
  await expect(cancelButton).toBeVisible();
  const cancelledResponse = page.waitForResponse(response => response.url().endsWith('/cancel') && response.request().method() === 'POST');
  await cancelButton.click(); expect((await cancelledResponse).ok()).toBeTruthy();
  await expect(panel.getByRole('status')).toBeFocused();
  await expect.poll(async () => (await (await authenticatedGet(`${route(fixture.cancel)}/invocations`)).json()).items[0].invocation_state).toBe('cancelled');
  await page.goto(url(fixture.navigation));
  await expect(panel).toContainText('No provider jobs are recorded for this analysis');
  await expect(panel).not.toContainText(sameJob);
  await page.goBack(); await expect(panel).toContainText('Cancellation requested at');
  await page.getByRole('button', { name: 'Sign out', exact: true }).click();
  await expect(page.getByRole('heading', { name: 'Sign in', exact: true })).toBeVisible();
  await expect(panel).toHaveCount(0);
  expect(failures).toEqual([]);
}
