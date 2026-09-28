import { defineConfig } from '../../frontend/node_modules/@playwright/test/index.mjs';
import path from 'node:path';
const output = path.resolve(process.env.PRODUCER_OUTPUT || 'backend/tests/fixtures/producers');
export default defineConfig({
  testDir: '.', testMatch: 'browser.cases.mjs', workers: 1, retries: 1, timeout: 15000,
  outputDir: path.join(output, 'browser-results'),
  reporter: [['json', { outputFile: path.join(output, 'playwright.json') }], ['junit', { outputFile: path.join(output, 'playwright.junit.xml') }]],
  use: { browserName: 'chromium', viewport: { width: 640, height: 480 }, deviceScaleFactor: 1,
    trace: 'on', recordHar: { path: path.join(output, 'network.har'), content: 'omit' } },
  projects: [{ name: 'chromium' }]
});
