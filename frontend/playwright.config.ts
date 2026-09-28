import { defineConfig, devices } from '@playwright/test';

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
    trace: 'retain-on-failure',
    screenshot: 'only-on-failure'
  },
  projects: [
    {
      name: 'chromium-desktop',
      testIgnore: '**/narrow-layout.spec.ts',
      use: { ...devices['Desktop Chrome'] }
    },
    {
      name: 'firefox-desktop',
      testIgnore: '**/narrow-layout.spec.ts',
      use: { ...devices['Desktop Firefox'] }
    },
    {
      name: 'webkit-desktop',
      testIgnore: '**/narrow-layout.spec.ts',
      use: { ...devices['Desktop Safari'] }
    },
    {
      name: 'chromium-narrow',
      testMatch: '**/narrow-layout.spec.ts',
      use: {
        ...devices['Desktop Chrome'],
        viewport: { width: 390, height: 844 },
        hasTouch: true
      }
    }
  ]
});
