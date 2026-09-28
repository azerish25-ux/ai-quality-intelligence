import { test, expect } from '../../frontend/node_modules/@playwright/test/index.mjs';
import { appendFileSync } from 'node:fs';
import path from 'node:path';
const output = path.resolve(process.env.PRODUCER_OUTPUT || 'backend/tests/fixtures/producers');
test.beforeEach(async ({ page }) => {
  page.on('console', entry => appendFileSync(path.join(output, 'console.jsonl'), JSON.stringify({
    level: entry.type(), message: entry.text(), source: 'chromium', timestamp: new Date().toISOString()
  }) + '\n'));
  await page.goto('http://127.0.0.1:8779/');
});
test('paired screenshot and trace evidence', async ({ page }, info) => {
  const expected = info.outputPath('expected.png');
  await page.screenshot({ path: expected });
  await info.attach('expected', { path: expected, contentType: 'image/png' });
  await page.locator('#balance').evaluate(element => { element.textContent = '125'; });
  await page.evaluate(async () => {
    console.error('synthetic fixture contact fixture-person@example.com');
    await fetch('/down?token=synthetic-not-a-secret');
  });
  const actual = info.outputPath('actual.png');
  await page.screenshot({ path: actual });
  await info.attach('actual', { path: actual, contentType: 'image/png' });
  // Independent page oracle: the intervention changed a displayed value from 100 to 125.
  await expect(page.locator('#balance')).toHaveText('100');
});
test('retry recovery control', async ({ page }, info) => {
  await expect(page.locator('#balance')).toHaveText(info.retry === 0 ? 'wrong-controlled-value' : '100', { timeout: 250 });
});
test('passing control', async ({ page }) => { await expect(page.locator('#balance')).toHaveText('100'); });
test.skip('skipped control', async () => {});
