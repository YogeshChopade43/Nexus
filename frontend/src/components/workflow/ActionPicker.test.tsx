import { describe, expect, test, vi } from 'vitest';
import { fireEvent, render, screen, within } from '@testing-library/react';
import { MemoryRouter } from 'react-router-dom';
import { ActionPicker } from './ActionPicker';
import { ParameterForm } from './StepConfig';
import type { McpServer, McpTool } from '../../types/mcp';
import type { ToolDefinition } from '../../types/workflow';

const tool = (remote: string, description: string, extra: Partial<McpTool> = {}): McpTool => ({
  name: `notion__${remote}`, remote_name: remote, description: `[Notion] Notion | ${description}\nError Responses:\n400: Bad request`,
  policy: 'allow', ...extra,
});

const server = (id: number, name: string, tools: McpTool[]): McpServer => ({
  id, slug: name.toLowerCase(), name, transport: 'stdio', command: 'npx', args: [], env: {}, url: '', headers: {}, enabled: true,
  status: 'connected', error: null, tools, blocked_tools: [], tool_policies: {}, signed_in: false, auth_url: null, health: null,
});

const notion = server(1, 'Notion', [
  tool('API-post-search', 'Search by title', { destructive: true }),
  tool('API-post-page', 'Create a page', { destructive: true, required: ['parent', 'properties'] }),
  tool('API-get-users', 'List all users', { read_only: true }),
]);

describe('ActionPicker', () => {
  test('lists readable names grouped into reads and changes, and picks with the friendly name', () => {
    const onPick = vi.fn();
    render(<MemoryRouter><ActionPicker servers={[notion]} onPick={onPick} onClose={() => {}} toolsOnly /></MemoryRouter>);
    expect(screen.queryByText('API-post-search')).not.toBeInTheDocument();
    const reads = screen.getByText('Reads').parentElement!;
    expect(within(reads).getByText('Search by title')).toBeInTheDocument(); // read verb beats the server's destructive flag
    const changes = screen.getByText('Changes data', { selector: 'h6' }).parentElement!;
    expect(within(changes).getByText('Create a page')).toBeInTheDocument();
    expect(screen.getByText('Needs: Parent, Properties')).toBeInTheDocument();
    expect(screen.queryByText(/Error Responses/)).not.toBeInTheDocument();
    fireEvent.click(screen.getByText('Search by title'));
    expect(onPick).toHaveBeenCalledWith({ type: 'action', name: 'Search by title', tool: 'notion__API-post-search' });
  });

  test('several apps start collapsed; search opens the matching ones', () => {
    const github = server(2, 'GitHub', [{ name: 'github__list_issues', remote_name: 'list_issues', description: 'List issues in a repository', policy: 'allow' }]);
    render(<MemoryRouter><ActionPicker servers={[notion, github]} onPick={() => {}} onClose={() => {}} /></MemoryRouter>);
    expect(screen.queryByText('Search by title')).not.toBeInTheDocument();
    fireEvent.change(screen.getByLabelText('Search apps and actions'), { target: { value: 'issues' } });
    expect(screen.getByText('List issues in a repository')).toBeInTheDocument();
    expect(screen.queryByText('Notion')).not.toBeInTheDocument();
  });
});

describe('ParameterForm', () => {
  const definition: ToolDefinition = {
    tool_name: 'notion__API-update-page-markdown', app_id: 'notion', description: '', available: true,
    parameters: {
      type: 'object',
      required: ['page_id', 'type'],
      properties: {
        page_id: { type: 'string', format: 'uuid', description: 'Identifier for a Notion page.' },
        type: { type: 'string', enum: ['replace_content', 'update_content'] },
        replace_content: { anyOf: [{ type: 'object', properties: { new_str: { type: 'string' } }, required: ['new_str'] }, { type: 'string' }] },
        include_transcript: { type: 'boolean', default: false },
      },
    },
  };

  test('required first, choices as dropdowns, optional folded away, JSON example on request', () => {
    const onChange = vi.fn();
    render(<ParameterForm tool={definition} parameters={{}} onChange={onChange} />);
    expect(screen.getByText('Page ID')).toBeInTheDocument();
    expect(screen.getByText('Identifier for a Notion page.')).toBeInTheDocument();
    fireEvent.change(screen.getByLabelText('Type'), { target: { value: 'replace_content' } });
    expect(onChange).toHaveBeenLastCalledWith({ type: 'replace_content' });
    expect(screen.getByText('Optional inputs (2)')).toBeInTheDocument();
    fireEvent.click(screen.getByText('Insert example'));
    expect(onChange).toHaveBeenLastCalledWith({ replace_content: { new_str: '…' } });
    fireEvent.change(screen.getByLabelText('Include transcript'), { target: { value: 'true' } });
    expect(onChange).toHaveBeenLastCalledWith({ include_transcript: true });
  });
});
