import { expect, test } from 'vitest';
import { runState } from './runState';
import type { Workflow } from '../../types/workflow';

const wf = (type: string, isActive: boolean) => ({ isActive, trigger_config: { type } }) as unknown as Workflow;

test('only workflows that run on their own are called active', () => {
  expect(runState(wf('recurrence', true))).toEqual({ label: 'Active', tone: 'success', automatic: true });
  expect(runState(wf('poll', false))).toEqual({ label: 'Stopped', tone: 'danger', automatic: true });
  expect(runState(wf('manual', true))).toEqual({ label: 'Manual', tone: 'default', automatic: false });
  expect(runState(wf('manual', false))).toEqual({ label: 'Disabled', tone: 'default', automatic: false });
  expect(runState({ isActive: true } as Workflow)).toEqual({ label: 'Manual', tone: 'default', automatic: false });  // no trigger saved yet
});
