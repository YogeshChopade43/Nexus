import { describe, expect, test } from 'vitest';
import { cleanDescription, humanize, paramFields, toolKind, toolLabel, toolSummary } from './toolInfo';

// Shapes taken from real servers (Notion's @notionhq/notion-mcp-server, GitHub-style, fixtures).
const notionSearch = {
  remote_name: 'API-post-search', title: 'Post Search', destructive: true,
  description: '[Notion] Notion | Search by title\nError Responses:\n400: Bad request',
};

describe('tool labels', () => {
  test('use the short first line of the description, without prefixes or error tables', () => {
    expect(toolLabel(notionSearch)).toBe('Search by title');
    expect(toolSummary(notionSearch)).toBe('');
    expect(cleanDescription(notionSearch.description)).toBe('Search by title');
  });

  test('long descriptions fall back to the title, then a humanized name', () => {
    const long = 'Get details of a specific pull request in a GitHub repository, including its reviews, comments and merge state.';
    expect(toolLabel({ remote_name: 'get_pull_request', title: 'Get pull request', description: long })).toBe('Get pull request');
    expect(toolLabel({ remote_name: 'get_pull_request', description: long })).toBe('Get pull request');
    expect(toolSummary({ remote_name: 'get_pull_request', description: long })).toBe(long);
  });

  test('the summary is what remains after the label', () => {
    expect(toolSummary({ description: 'Echo text back. Useful for testing connections.' })).toBe('Useful for testing connections.');
  });

  test('humanize', () => {
    expect(humanize('API-get-block-children')).toBe('Get block children');
    expect(humanize('listPullRequests')).toBe('List pull requests');
    expect(humanize('page_id')).toBe('Page ID');
  });

  test('read/write comes from server hints, then the policy', () => {
    expect(toolKind({ read_only: true, policy: 'ask' })).toBe('read');
    expect(toolKind(notionSearch)).toBe('read'); // marked destructive by the server, but it only searches
    expect(toolKind({ description: 'Append block children', destructive: true })).toBe('write');
    expect(toolKind({ policy: 'ask' })).toBe('write');
    expect(toolKind({ policy: 'allow' })).toBe('read');
  });
});

describe('paramFields', () => {
  const schema = {
    type: 'object',
    $defs: { parent: { type: 'object', properties: { page_id: { type: 'string', format: 'uuid' } }, required: ['page_id'] } },
    properties: {
      page_size: { type: 'integer', default: 100, description: 'The number of items. Maximum: `100`' },
      type: { type: 'string', enum: ['replace_content', 'update_content'], description: 'The kind of **edit**.' },
      archived: { type: ['boolean', 'null'] },
      parent: { $ref: '#/$defs/parent' },
      sort: { anyOf: [{ type: 'object', properties: { direction: { type: 'string', enum: ['ascending'] } } }, { type: 'string' }] },
      page_id: { type: 'string', format: 'uuid' },
      old: { type: 'string', description: 'Deprecated. Use type instead.' },
      zzz: { type: 'string' },
    },
    required: ['page_id', 'parent'],
  };

  test('required first, with types, choices, defaults and cleaned help text', () => {
    const fields = paramFields(schema);
    expect(fields.map(f => f.key)).toEqual(['parent', 'page_id', 'page_size', 'type', 'archived', 'sort', 'zzz', 'old']);
    const byKey = Object.fromEntries(fields.map(f => [f.key, f]));
    expect(byKey.page_id).toMatchObject({ label: 'Page ID', required: true, type: 'string' });
    expect(byKey.page_size).toMatchObject({ type: 'integer', defaultValue: 100, description: 'The number of items. Maximum: 100' });
    expect(byKey.type.options).toEqual(['replace_content', 'update_content']);
    expect(byKey.archived.type).toBe('boolean');
    expect(JSON.parse(byKey.parent.example!)).toEqual({ page_id: '<id>' });
    expect(JSON.parse(byKey.sort.example!)).toEqual({ direction: 'ascending' });
  });

  test('no schema, no fields', () => {
    expect(paramFields(undefined)).toEqual([]);
  });
});
