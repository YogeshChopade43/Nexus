import { expect, test as setup } from '@playwright/test';

export const OWNER = { name: 'E2E Owner', email: 'owner@example.com', password: 'e2e password 123' };
export const STATE = 'e2e/.auth/owner.json';

// A fresh install: create the owner account through the real sign-up page, and keep its session for every test.
setup('create the owner account', async ({ page }) => {
  await page.goto('/');
  await expect(page.getByRole('heading', { name: 'Welcome to Nexus' })).toBeVisible();
  await page.getByLabel('Email').fill(OWNER.email);
  await page.getByRole('button', { name: 'Continue' }).click();
  await expect(page.getByRole('heading', { name: 'Create your account' })).toBeVisible();
  await page.getByLabel('Name').fill(OWNER.name);
  await page.getByLabel('Password', { exact: true }).fill(OWNER.password);
  await page.getByRole('button', { name: 'Create account' }).click();
  await expect(page.getByRole('button', { name: /account menu/ })).toBeVisible();
  await page.context().storageState({ path: STATE });
});
