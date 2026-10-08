import { expect, test } from '@playwright/test';

// One journey through a fresh Nexus: build and run a workflow, use the server catalog.
test('run a workflow and use the server catalog', async ({ page }) => {
  await page.goto('/');
  await expect(page.getByRole('heading', { name: 'Nexus Agent' })).toBeVisible();

  // Workflows: create one through the API, run it from the list.
  const created = await page.request.post('http://localhost:8765/api/workflows', {
    data: {
      name: 'E2E greeting', isActive: true,
      nodes: [{ id: 'hello', type: 'transform', name: 'Hello', config: { template: 'Hello {{ input.name | default("world") }}' } }],
      edges: [],
    },
  });
  expect(created.ok()).toBeTruthy();
  await page.getByRole('link', { name: 'Workflows' }).click();
  await page.getByRole('button', { name: 'Run E2E greeting' }).click();
  const trace = page.getByRole('dialog');
  await expect(trace.getByText('Completed').first()).toBeVisible({ timeout: 15_000 });
  await trace.getByRole('button', { name: 'Close modal' }).click();

  // Servers: the catalog fills in the add form.
  await page.getByRole('link', { name: 'MCP Servers' }).click();
  await page.getByRole('button', { name: 'Catalog' }).click();
  await page.getByRole('button', { name: /^Time/ }).click();
  await expect(page.getByLabel('Arguments')).toHaveValue('mcp-server-time');
  await page.getByRole('button', { name: 'Cancel' }).click();
});

test('phone-sized screens: no sideways scrolling, every button has a name', async ({ page }) => {
  await page.setViewportSize({ width: 375, height: 740 });

  const problems = async () => page.evaluate(() => {
    const overflow = document.documentElement.scrollWidth > window.innerWidth + 1;
    const unnamed = [...document.querySelectorAll('button, [role=button], a[href]')]
      .filter(el => (el as HTMLElement).offsetParent !== null)
      .filter(el => !(el.getAttribute('aria-label') || el.textContent?.trim() || el.getAttribute('title')))
      .map(el => el.outerHTML.slice(0, 120));
    return { overflow, unnamed };
  });

  for (const path of ['/', '/workflows', '/servers', '/dashboard', '/activity', '/settings']) {
    await page.goto(path);
    await page.waitForLoadState('networkidle');
    expect(await problems(), path).toEqual({ overflow: false, unnamed: [] });
  }

  await page.goto('/workflows');
  await page.getByRole('button', { name: 'New Workflow' }).click();
  await page.getByRole('button', { name: 'Add a step' }).click();
  expect(await problems(), 'builder').toEqual({ overflow: false, unnamed: [] });
});
