import { afterEach, expect, test, vi } from 'vitest';
import { render, screen, waitFor } from '@testing-library/react';
import { ToolName, toolParts } from './ToolName';

afterEach(() => vi.unstubAllGlobals());

test('raw tool names become an app and an action', () => {
  expect(toolParts('github__search_repositories')).toEqual({ app: 'GitHub', action: 'Search repositories' });
  expect(toolParts('notion_2__notion-search')).toEqual({ app: 'Notion', action: 'Search' });  // a second Notion server
  expect(toolParts('nexus__search_documents')).toEqual({ app: 'Nexus', action: 'Search documents' });
  expect(toolParts('linear__list_issues')).toEqual({ app: 'Linear', action: 'List issues' });
  expect(toolParts('nexus_find_tools')).toEqual({ app: 'Nexus', action: 'Find tools' });
});

test('shows the app and action, with the raw name on hover', async () => {
  vi.stubGlobal('fetch', vi.fn(async () => new Response(JSON.stringify([
    { slug: 'github', name: 'GitHub', registry_name: 'io.github.github/github-mcp-server' }]),
    { status: 200, headers: { 'content-type': 'application/json' } })));
  const { container } = render(<ToolName name="github__search_repositories" />);
  const label = screen.getByTitle('github__search_repositories');
  expect(label).toHaveTextContent('GitHub');
  expect(label).toHaveTextContent('Search repositories');
  await waitFor(() => expect(container.querySelector('img')).not.toBeNull());
  expect(container.querySelector('img')!.getAttribute('src')).toContain('/api/marketplace/icon?name=io.github.github');
});
