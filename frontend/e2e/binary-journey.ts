import { execFileSync } from 'node:child_process';
import { createHash } from 'node:crypto';
import { readFileSync } from 'node:fs';
import path from 'node:path';
import { expect, type APIRequestContext, type Page, type TestInfo } from '@playwright/test';
import type { BinaryEvidence } from '../src/binary-api';

const API = 'http://127.0.0.1:8000/api/v1';
export async function binaryEvidenceJourney(page: Page, request: APIRequestContext, info: TestInfo) {
  info.setTimeout(90_000);
  const fixtureDir = process.env.FAILURELENS_PRODUCER_FIXTURES;
  expect(fixtureDir, 'Executed producer fixtures are mandatory; generate or download the exact-revision artifact').toBeTruthy();
  const bundlePath = path.join(fixtureDir!, 'failurelens-bundle.zip');
  const created = await request.post(`${API}/projects`, { data: { slug: `binary-${info.project.name}-${Date.now()}-${info.retry}`, name: 'Binary browser evidence' } });
  expect(created.status()).toBe(201);
  const project = await created.json();
  const queued = await request.post(`${API}/projects/${project.id}/ingestions?external_id=binary-browser-${Date.now()}&filename=producer.zip`, {
    data: readFileSync(bundlePath), headers: { 'Content-Type': 'application/zip' }
  });
  expect(queued.status()).toBe(202);
  const ingestion = await queued.json();
  await expect.poll(async () => (await (await request.get(`${API}/ingestions/${ingestion.id}`)).json()).state, { timeout: 30_000 }).toBe('partial');
  const runId = (await (await request.get(`${API}/ingestions/${ingestion.id}`)).json()).run_id;
  const items: BinaryEvidence[] = (await (await request.get(`${API}/runs/${runId}/binary-evidence?limit=100`)).json()).items;
  const actual = items.find(item => item.kind === 'screenshot' && item.relationship === 'actual')!;
  const expected = items.find(item => item.kind === 'screenshot' && item.relationship === 'expected' && item.execution_id === actual.execution_id)!;
  const trace = items.find(item => item.kind === 'playwright-trace' && item.execution_id === actual.execution_id)!;
  expect(actual && expected && trace).toBeTruthy();
  await page.goto(`/?project=${project.id}&run=${runId}&binary=${actual.input_id}#safe-evidence`);
  const panel = page.locator('#safe-evidence');
  await expect(panel.getByRole('heading', { name: 'Screenshots and trace evidence', exact: true })).toBeVisible();
  const derivativeIds: Record<string, string> = {};
  for (const item of [actual, expected]) {
    await panel.getByLabel('Binary evidence input', { exact: true }).selectOption(item.input_id);
    const bytes = execFileSync('python', ['-c', 'import sys,zipfile; sys.stdout.buffer.write(zipfile.ZipFile(sys.argv[1]).read(sys.argv[2]))', bundlePath, item.path!]);
    await panel.getByLabel('Exact local original PNG or JPEG').setInputFiles({ name: 'original.png', mimeType: 'image/png', buffer: bytes });
    await expect(panel.getByRole('status')).toContainText('Local digest verified.');
    await panel.getByLabel('Mask x', { exact: true }).fill('0');
    await panel.getByLabel('Mask y', { exact: true }).fill('60');
    await panel.getByLabel('Mask width', { exact: true }).fill('640');
    await panel.getByLabel('Mask height', { exact: true }).fill('50');
    await panel.getByRole('button', { name: 'Add opaque mask', exact: true }).click();
    await panel.getByLabel('I reviewed the visible pixels and confirm the masked derivative is safe for project members.').check();
    await panel.getByLabel('Evidence review reason').fill('Reviewed executed fixture and masked the synthetic contact area');
    await panel.getByRole('button', { name: 'Save approved masked derivative', exact: true }).click();
    await expect(panel.getByRole('status')).toContainText('Approved masked derivative saved as review revision 1.');
    await expect(panel.getByRole('img')).toBeVisible();
    const approved = await (await request.get(`${API}/binary-evidence/${item.input_id}`)).json();
    derivativeIds[item.relationship!] = approved.derivative.id;
    const download = await request.get(`${API}/artifact-derivatives/${approved.derivative.id}/content?download=true`);
    expect(download.status()).toBe(200);
    expect(download.headers()['x-content-type-options']).toBe('nosniff');
    expect(createHash('sha256').update(await download.body()).digest('hex')).toBe(approved.derivative.digest);
    expect(approved.source_status).toBe('restricted');
  }
  await panel.locator('.binary-comparison summary').click();
  await panel.getByLabel('Expected approved image', { exact: true }).selectOption(derivativeIds.expected);
  await panel.getByLabel('Actual approved image', { exact: true }).selectOption(derivativeIds.actual);
  await panel.getByRole('button', { name: 'Compare approved images', exact: true }).click();
  await expect(panel.locator('.binary-comparison').getByRole('status')).toContainText('COMPARABLE');
  await expect(panel.locator('.binary-comparison')).toContainText('not root-cause evidence');
  await panel.screenshot({ path: info.outputPath('approved-binary-evidence.png') });
  await panel.getByLabel('Binary evidence input', { exact: true }).selectOption(trace.input_id);
  await expect(panel.getByRole('heading', { name: 'Safe trace event index', exact: true })).toBeVisible();
  await expect(panel.locator('.binary-trace-event').first()).toContainText('line');
  const eventLink = await panel.getByRole('link', { name: 'Link to event 0', exact: true }).getAttribute('href');
  expect(eventLink).toContain(`binary=${trace.input_id}`);
  await page.goto(eventLink!);
  await page.reload();
  await expect(panel.getByLabel('Binary evidence input', { exact: true })).toHaveValue(trace.input_id);
  await expect(panel.locator('.binary-trace-event').first()).toContainText('Event 0:');
  const traceEvents = await (await request.get(`${API}/binary-evidence/${trace.input_id}/trace-events`)).json();
  await panel.getByLabel('Evidence review reason').fill('Revoke synthetic trace evidence to verify access closes');
  await panel.getByRole('button', { name: 'Revoke approved evidence', exact: true }).click();
  await expect(panel.getByRole('status')).toContainText('Evidence revoked.');
  expect((await request.get(`${API}/artifact-derivatives/${traceEvents.derivative_id}/content`)).status()).toBe(403);
  expect((await request.get(`${API}/artifact-derivatives/${traceEvents.events[0].evidence_derivative_id}/content`)).status()).toBe(403);
  await panel.getByLabel('Binary evidence input', { exact: true }).selectOption(actual.input_id);
  await expect(panel.getByRole('img')).toBeVisible();
  // Fixture-only aging: refuse any database other than the explicitly disposable browser DB.
  execFileSync('python', ['-c', `import os,sys
from datetime import timedelta
from failurelens.db import SessionLocal
from failurelens import models as m
assert os.environ.get('FAILURELENS_DATABASE_URL','').endswith('/failurelens_browser'), 'disposable browser DB required'
with SessionLocal() as s:
 r=s.get(m.Run,sys.argv[1]); assert r and r.project_id==sys.argv[2] and r.external_id.startswith('binary-browser-')
 r.created_at=m.utcnow()-timedelta(days=100); s.commit()
`, runId, project.id]);
  const preview = await (await request.get(`${API}/projects/${project.id}/retention/preview`)).json();
  const cleanup = await request.post(`${API}/projects/${project.id}/retention/cleanup`, { data: {
    expected_version: preview.policy_version, as_of: preview.as_of, confirmation_digest: preview.confirmation_digest
  }});
  expect(cleanup.status()).toBe(202);
  await expect.poll(async () => (await request.get(`${API}/artifact-derivatives/${derivativeIds.actual}/content`)).status(), { timeout: 30_000 }).toBe(410);
  await expect(panel.getByRole('img')).toHaveCount(0);
  await expect(panel).toContainText('expired');
  await expect.poll(async () => page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth + 1)).toBe(true);
  await page.reload();
  await expect(panel).toContainText('expired');
  await expect(panel.getByRole('img')).toHaveCount(0);
}
