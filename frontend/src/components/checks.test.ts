import { test } from 'vitest';

// The *.check.ts self-checks assert at import time; running them here keeps them in the test suite.
test('workflow tree and MCP config self-checks', async () => {
  await import('./workflow/flowTree.check');
  await import('./servers/catalog.check');
});
