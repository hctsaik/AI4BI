import { chromium, expect, type FullConfig } from '@playwright/test';

// The runner owns this session, so replacement workers inherit it after a
// failed test. Do not write storageState, cookies, or pairing responses to disk.
export default async function setupSession(config: FullConfig) {
  delete process.env.AI4BI_E2E_SESSION_COOKIES;
  const browser = await chromium.launch();
  try {
    const page = await browser.newPage();
    page.setDefaultTimeout(15000);
    await page.goto(config.projects[0].use.baseURL!);
    await page.getByLabel('本次啟動配對碼').fill('local-e2e-pairing-2026');
    await page.getByRole('button', { name: '連接工作區 →' }).click();
    await expect(page.getByRole('button', { name: '新增工作區', exact: true })).toBeVisible();
    process.env.AI4BI_E2E_SESSION_COOKIES = JSON.stringify(await page.context().cookies());
  } finally {
    await browser.close();
  }
  return () => { delete process.env.AI4BI_E2E_SESSION_COOKIES; };
}
