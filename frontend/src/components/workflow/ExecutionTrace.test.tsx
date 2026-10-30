import { describe, it, expect, beforeAll } from 'vitest';
import { render, screen } from '@testing-library/react';
import { ExecutionTrace } from './ExecutionTrace';
import type { ExecutionTraceEntry } from '../../types/workflow';

beforeAll(() => {
  Element.prototype.scrollIntoView = () => {};
});

const now = new Date().toISOString();
const read: ExecutionTraceEntry = { id: '1', nodeId: 'read', nodeName: 'Read', type: 'tool_executed', timestamp: now, status: 'success' };
const write: ExecutionTraceEntry = {
  id: '2', nodeId: 'write', nodeName: 'Create issue', type: 'action', timestamp: now, status: 'success',
  practice_skipped: true, would_call: 'linear__create_issue', input: { title: 'Bug' },
};

describe('ExecutionTrace practice runs', () => {
  it('lists what a practice run would have changed', () => {
    render(<ExecutionTrace trace={[read, write]} />);
    expect(screen.getByText('Would have made 1 change')).toBeInTheDocument();
    expect(screen.getAllByText('linear__create_issue').length).toBeGreaterThan(0);
    expect(screen.getByText('Practice')).toBeInTheDocument();
  });

  it('has no summary when nothing was skipped', () => {
    render(<ExecutionTrace trace={[read]} />);
    expect(screen.queryByText(/Would have made/)).not.toBeInTheDocument();
    expect(screen.queryByText('Practice')).not.toBeInTheDocument();
  });

  it('marks a condition that read a skipped step as uncertain', () => {
    render(<ExecutionTrace trace={[{ ...read, nodeId: 'check', type: 'condition', uncertain: true }]} />);
    expect(screen.getByText('Uncertain (practice)')).toBeInTheDocument();
  });
});
