import { expect, test } from '@playwright/test';

// One journey through a fresh Nexus: build and run a workflow, use the server catalog.
test('run a workflow and use the server catalog', async ({ page }) => {
  await page.goto('/');
  await expect(page.getByRole('heading', { name: 'How can I help?' })).toBeVisible();

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

  // Marketplace: find a listing from the (fake) MCP Registry and install it.
  await page.getByRole('link', { name: 'Marketplace' }).click();
  await page.getByRole('button', { name: 'Refresh' }).click();
  await page.getByLabel('Search servers').fill('demo');
  await page.getByRole('button', { name: /E2E Demo/ }).click();
  const listing = page.getByRole('dialog', { name: 'E2E Demo' });
  await listing.getByRole('button', { name: 'Install' }).click();
  await expect(listing.getByRole('button', { name: 'Remove server' })).toBeVisible({ timeout: 15_000 });
  await listing.getByRole('button', { name: 'Close modal' }).click();
  await expect(page.getByText('Installed', { exact: true }).last()).toBeVisible();

  // Knowledge: create a library, add a document, wait until it's ready, find a passage.
  await page.getByRole('link', { name: 'Knowledge' }).click();
  await page.getByLabel('New library name').fill('Policies');
  await page.getByRole('button', { name: 'Create library' }).click();
  await expect(page.getByRole('heading', { name: 'Policies' })).toBeVisible();
  await page.locator('input[type=file]').setInputFiles({
    name: 'policy.md', mimeType: 'text/markdown',
    buffer: Buffer.from('# Policy\n\n## Refunds\n\nRefunds are accepted within 30 days.\n\n## Shipping\n\nShipping to Pune takes 5 business days.'),
  });
  await expect(page.getByText('policy.md')).toBeVisible();
  await expect(page.getByText('Ready', { exact: true })).toBeVisible({ timeout: 15_000 });
  await page.getByLabel('Search this library').fill('shipping Pune');
  await page.getByLabel('Search this library').press('Enter');
  await expect(page.getByText(/Shipping to Pune takes 5 business days/)).toBeVisible();
  await page.getByLabel('New memory').fill('Our team is called Atlas');
  await page.getByRole('button', { name: 'Add', exact: true }).click();
  await expect(page.getByText('Our team is called Atlas')).toBeVisible();

  // Chat: per-chat settings and the conversation list open and close.
  await page.getByRole('link', { name: 'Agent' }).click();
  await page.getByRole('button', { name: 'Chat settings' }).click();
  await expect(page.getByText('Apps this chat can use')).toBeVisible();
  await page.getByRole('button', { name: 'Cancel' }).click();
  await page.getByRole('button', { name: 'Conversations' }).click();
  await expect(page.getByLabel('Search conversations')).toBeVisible();
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

  for (const path of ['/', '/workflows', '/servers', '/knowledge', '/dashboard', '/activity', '/settings']) {
    await page.goto(path);
    await page.waitForLoadState('networkidle');
    expect(await problems(), path).toEqual({ overflow: false, unnamed: [] });
  }

  await page.goto('/workflows');
  await page.getByRole('button', { name: 'New Workflow' }).click();
  await page.getByRole('button', { name: 'Add a step' }).click();
  expect(await problems(), 'builder').toEqual({ overflow: false, unnamed: [] });
});

test('chat: Markdown replies, cost, retry, edit, stop and search', async ({ page }) => {
  const api = 'http://localhost:8765';
  const provider = await page.request.post(`${api}/api/llm/`, {
    data: { provider_name: 'openai', model: 'fake-gpt', api_key: 'test', base_url: 'http://127.0.0.1:8766/v1' },
  });
  expect(provider.ok()).toBeTruthy();
  await page.request.patch(`${api}/api/settings/user`, { data: { llmPrices: { 'fake-gpt': { input: 10, output: 30 } } } });

  await page.goto('/');
  const input = page.getByLabel('Message input');
  await input.fill('hello there');
  await input.press('Enter');
  const log = page.getByRole('log', { name: 'Chat messages' });
  await expect(log.getByRole('table')).toContainText('Apples');
  await expect(log.getByText('Answer').first()).toHaveJSProperty('tagName', 'STRONG');
  await expect(log.getByLabel('Copy code')).toBeVisible();
  await expect(log.getByText(/120 tokens · <\$0\.01/)).toBeVisible();

  // Retry asks the same question again; Edit replaces it.
  // Wait for the retried reply to finish streaming before editing (Edit is hidden while a reply runs).
  const retried = page.waitForResponse(r => r.url().includes('/api/agent/run'));
  await log.getByRole('button', { name: 'Retry' }).click();
  await (await retried).finished();
  await expect(log.getByText('Answer to: hello there')).toHaveCount(1);
  await log.getByRole('button', { name: 'Edit message' }).click();
  await log.getByRole('textbox', { name: 'Edit message' }).fill('hello again');
  await log.getByRole('button', { name: 'Send' }).click();
  await expect(log.getByText('Answer to: hello again')).toBeVisible();
  await expect(log.getByText('Answer to: hello there')).toHaveCount(0);

  // Stop: a slow reply is cut off and marked.
  await input.fill('a slow question');
  await input.press('Enter');
  await page.getByRole('button', { name: 'Stop' }).click();
  await expect(log.getByText('(stopped before answering)')).toBeVisible();
  await expect(page.getByRole('button', { name: 'Send message' })).toBeVisible();

  // Documents: answer from the "Policies" library with a cited, clickable source.
  await page.getByRole('button', { name: 'Chat settings' }).click();
  await page.getByLabel('Answer from library').selectOption({ label: 'Policies (1 documents)' });
  await page.getByRole('button', { name: 'Save' }).click();
  await input.fill('How long does shipping to Pune take?');
  await input.press('Enter');
  await expect(log.getByText(/From your documents: Shipping to Pune takes 5 business days/)).toBeVisible();
  await log.getByRole('button', { name: /\[1\] policy\.md/ }).click();
  await expect(log.getByRole('dialog', { name: 'Source' })).toContainText('Shipping to Pune');

  // Question cards: the reply pauses to ask, then continues with the answer.
  await input.fill('Remind me daily to stretch, ask me where');
  await input.press('Enter');
  const card = log.getByRole('group', { name: 'Questions from Nexus' });
  await expect(card).toContainText('Where should the reminder reach you?');
  await card.getByRole('radio', { name: 'Nexus pop-up' }).check();
  await card.getByRole('button', { name: 'Send answers' }).click();
  await expect(log.getByText(/You chose: - Where should the reminder reach you\? → Nexus pop-up/)).toBeVisible();

  // Search past conversations by message text.
  await page.getByRole('button', { name: 'Conversations' }).click();
  await page.getByLabel('Search conversations').fill('hello again');
  await expect(page.getByRole('dialog', { name: 'Conversations' }).getByRole('button').filter({ hasText: 'hello' })).toHaveCount(1);
});

test('workflow canvas: add steps, connect them by dragging, save', async ({ page }) => {
  await page.setViewportSize({ width: 1400, height: 900 });
  await page.goto('/workflows');
  await page.getByRole('button', { name: 'New Workflow' }).click();
  await page.getByLabel('Name', { exact: true }).fill('Canvas E2E');

  // + beside the trigger adds a connected step and opens its settings.
  await page.getByRole('button', { name: 'Add a step after Trigger' }).click();
  await page.getByRole('button', { name: /Delay Wait before continuing/ }).click();
  await expect(page.getByRole('region', { name: 'Step settings' })).toBeVisible();

  // "Add step" adds an unconnected one; drag from Delay's output dot to its input to connect them.
  await page.getByRole('button', { name: 'Add step', exact: true }).click();
  await page.getByRole('button', { name: /Compose Build text/ }).click();
  const output = page.locator('.react-flow__node', { hasText: 'Delay' }).locator('.react-flow__handle.source');
  const input = page.locator('.react-flow__node', { hasText: 'Compose' }).locator('.react-flow__handle.target');
  // The canvas pans to each new step (200 ms); measure the dots once they have held still for 450 ms.
  const settled = async (handle: typeof output) => {
    let [last, still] = ['', 0];
    while (still < 3) {
      await page.waitForTimeout(150);
      const box = JSON.stringify(await handle.boundingBox());
      still = box === last ? still + 1 : 0;
      last = box;
    }
    return JSON.parse(last) as { x: number; y: number; width: number; height: number };
  };
  const [a, b] = [await settled(output), await settled(input)];
  await expect(page.locator('.react-flow__edge')).toHaveCount(1);  // trigger -> delay, still drawn
  await page.mouse.move(a.x + a.width / 2, a.y + a.height / 2);
  await page.mouse.down();
  await page.mouse.move(b.x + b.width / 2, b.y + b.height / 2, { steps: 12 });
  await page.mouse.up();
  await expect(page.locator('.react-flow__edge')).toHaveCount(2);

  await page.getByRole('button', { name: 'Save' }).click();
  await expect(page.getByRole('dialog')).toBeHidden();
  const workflows = await (await page.request.get('http://localhost:8765/api/workflows')).json();
  const saved = workflows.find((w: { name: string }) => w.name === 'Canvas E2E');
  expect(saved.edges.map((e: { source: string; target: string }) => `${e.source}->${e.target}`).sort())
    .toEqual(['delay_1->transform_1', 'trigger_1->delay_1']);
  expect(saved.nodes.every((n: { position?: unknown }) => n.position)).toBe(true);
  await page.request.delete(`http://localhost:8765/api/workflows/${saved.id}`);
});

test('built-in integrations: connect an RSS feed from the Marketplace, then mention it in chat', async ({ page }) => {
  await page.goto('/servers');
  await page.getByRole('button', { name: /RSS \/ Atom feed/ }).click();
  const dialog = page.getByRole('dialog');
  await dialog.getByLabel('Name').fill('Team news');
  await dialog.getByLabel(/Feed address/).fill('http://127.0.0.1:8766/feed.xml');
  await dialog.getByRole('button', { name: 'Connect' }).click();
  await expect(dialog.getByRole('status')).toContainText('Feed "Team news" with 1 item(s)');
  await expect(dialog.getByText('Team news', { exact: true })).toBeVisible();  // listed as connected
  await page.keyboard.press('Escape');
  await expect(page.getByText('1 connected')).toBeVisible();

  await page.goto('/');
  const input = page.getByLabel('Message input');
  await input.click();
  await page.keyboard.type('What is new in @Team');
  await expect(page.getByRole('listbox', { name: 'Mention an app or document' }).getByRole('option', { name: /Team news/ })).toBeVisible();

  const listed = await (await page.request.get('http://localhost:8765/api/integrations')).json();
  await page.request.delete(`http://localhost:8765/api/integrations/${listed[0].id}`);
});

test('run once: make one that waits for you to go quiet, check in, edit its steps, and Run asks first', async ({ page }) => {
  await page.goto('/');
  await page.getByRole('link', { name: 'Run once' }).click();
  await page.getByRole('button', { name: 'New run-once' }).click();
  const dialog = page.getByRole('dialog');
  await dialog.getByLabel('Name').fill('Share documents with family');
  await dialog.getByText('If I go quiet').click();
  await dialog.getByRole('button', { name: '30 days' }).click();
  await expect(dialog.getByRole('button', { name: 'Create' })).toBeDisabled();  // needs something to do
  await dialog.getByRole('button', { name: 'Add a step' }).click();
  await page.getByRole('dialog', { name: 'Choose an operation' }).getByRole('button', { name: /Compose/ }).click();
  await expect(dialog.getByText('Compose').first()).toBeVisible();  // the step, ready to fill in
  await dialog.getByRole('button', { name: 'Create' }).click();
  await expect(page.getByRole('heading', { name: 'Share documents with family' })).toBeVisible();
  await expect(page.getByRole('progressbar', { name: /of 30 quiet days/ })).toBeVisible();

  const before = (await (await page.request.get('http://localhost:8765/api/run-once')).json()).lastCheckIn ?? '';
  await page.waitForTimeout(1100);  // so the new check-in time differs
  await page.getByRole('button', { name: "I'm here" }).click();
  await expect(page.getByRole('status')).toContainText('Checked in');
  const after = (await (await page.request.get('http://localhost:8765/api/run-once')).json()).lastCheckIn;
  expect(after > before, `before=${before} after=${after}`).toBeTruthy();  // the server really recorded it

  await page.getByRole('link', { name: /Edit steps/ }).click();
  await expect(page.getByRole('dialog', { name: 'Edit Workflow' })).toContainText("When it's time");  // only the trigger: you add the steps
  await page.keyboard.press('Escape');
  await expect(page.getByRole('dialog')).toBeHidden();
  let asked = '';
  page.once('dialog', d => { asked = d.message(); void d.dismiss(); });
  await page.getByRole('button', { name: 'Run Share documents with family' }).click();
  await expect.poll(() => asked).toContain('run once');  // and dismissing it ran nothing

  const listed = await (await page.request.get('http://localhost:8765/api/run-once')).json();
  for (const item of listed.items) await page.request.delete(`http://localhost:8765/api/run-once/${item.id}`);
});
