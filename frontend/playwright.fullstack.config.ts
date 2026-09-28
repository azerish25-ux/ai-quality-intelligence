import { defineConfig, devices } from '@playwright/test';
export default defineConfig({
  testDir: './e2e',
  testMatch: '**/fullstack-journey.ts',
  workers: 1,
  timeout: 60_000,
  expect: { timeout: 15_000 },
  retries: 0,
  forbidOnly: true,
  reporter: [['line']],
  use: { baseURL: 'http://127.0.0.1:5173', trace: 'retain-on-failure', screenshot: 'only-on-failure' },
  projects: [
    { name: 'fullstack-desktop', use: { ...devices['Desktop Chrome'] } },
    { name: 'fullstack-narrow', use: { ...devices['Desktop Chrome'], viewport: { width: 390, height: 844 } } }
  ]
});
