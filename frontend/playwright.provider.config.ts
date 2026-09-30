import { defineConfig, devices } from '@playwright/test';

// Provider tests require their own empty database and production authentication.
// Ordinary synthetic-demo browser jobs use playwright.config.ts instead.
export default defineConfig({
  testDir: './e2e',
  fullyParallel: false,
  workers: 1,
  timeout: 60_000,
  expect: { timeout: 15_000 },
  forbidOnly: Boolean(process.env.CI),
  retries: process.env.CI ? 1 : 0,
  reporter: [['line']],
  use: {
    baseURL: 'http://127.0.0.1:5173',
    // Bearer sessions and login responses are synthetic but remain private.
    trace: 'off',
    screenshot: 'only-on-failure'
  },
  projects: [
    { name: 'provider-chromium-desktop', testMatch: '**/provider.spec.ts', use: { ...devices['Desktop Chrome'] } },
    { name: 'provider-chromium-narrow', testMatch: '**/provider-narrow.spec.ts', use: { ...devices['Desktop Chrome'], viewport: { width: 390, height: 844 }, hasTouch: true } }
  ]
});
