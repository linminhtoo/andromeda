import { defineConfig, devices } from '@playwright/test';

export default defineConfig({
  testDir: 'tests/ui',
  timeout: 45_000,
  expect: {
    timeout: 8_000,
  },
  fullyParallel: true,
  retries: process.env.CI ? 1 : 0,
  reporter: 'list',
  use: {
    baseURL: 'http://127.0.0.1:8236',
    headless: true,
    trace: 'off',
    screenshot: 'only-on-failure',
    video: 'off',
  },
  projects: [
    {
      name: 'chromium',
      use: {
        ...devices['Desktop Chrome'],
      },
    },
  ],
  webServer: {
    command:
      "npm run -s build:ts && bash -lc 'source .venv/bin/activate && PYTHONPATH=src uvicorn andromeda.main:app --host 127.0.0.1 --port 8236'",
    url: 'http://127.0.0.1:8236/health',
    timeout: 120_000,
    reuseExistingServer: true,
  },
});
