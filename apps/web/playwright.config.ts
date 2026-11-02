import { defineConfig } from '@playwright/test';
import { fileURLToPath } from 'node:url';
import { randomUUID } from 'node:crypto';

const python = process.env.AI4BI_E2E_PYTHON || fileURLToPath(new URL('../../.venv/Scripts/python.exe', import.meta.url));
const server = fileURLToPath(new URL('../../scripts/serve_dev.py', import.meta.url));
// Preserve each run for diagnosis without reopening unrelated prior workspaces.
process.env.AI4BI_E2E_DATA_ROOT ??= fileURLToPath(new URL(`../../.artifacts/e2e-runs/${randomUUID()}/data`, import.meta.url));

export default defineConfig({
  // One workflow includes queries, persistence, export and field editing.
  // Individual query assertions keep their separate 45-second limits.
  testDir: '../../tests/e2e', timeout: 180000, workers: 1,
  globalSetup: fileURLToPath(new URL('../../tests/e2e/session.setup.ts', import.meta.url)),
  outputDir: '../../.artifacts/playwright-results',
  use: {baseURL:'http://127.0.0.1:8766',actionTimeout:15000,trace:'retain-on-failure',screenshot:'only-on-failure'},
  reporter: [['list'],['html',{outputFolder:'../../.artifacts/playwright-report',open:'never'}]],
  webServer: {
    command:`"${python}" "${server}"`,
    url:'http://127.0.0.1:8766/ready',timeout:60000,reuseExistingServer:false,
    env:{AI4BI_PORT:'8766',AI4BI_PAIRING_CODE:'local-e2e-pairing-2026',
      AI4BI_DATA_ROOT:process.env.AI4BI_E2E_DATA_ROOT,LLM_MODE:'mock',PYTHONIOENCODING:'utf-8'},
  },
});
