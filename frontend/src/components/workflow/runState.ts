import type { Workflow } from '../../types/workflow';

export type RunTone = 'success' | 'danger' | 'default';

/** "Active" (green) only for a switched-on workflow that runs by itself (schedule, app check, webhook, app event);
 *  switched off it is "Stopped" (red). A manual one only runs when started: "Manual", or "Disabled" when switched
 *  off (which blocks runs). */
export function runState(workflow: Pick<Workflow, 'isActive' | 'trigger_config'>): { label: string; tone: RunTone; automatic: boolean } {
  const automatic = Boolean(workflow.trigger_config?.type) && workflow.trigger_config?.type !== 'manual';
  if (automatic) return workflow.isActive ? { label: 'Active', tone: 'success', automatic } : { label: 'Stopped', tone: 'danger', automatic };
  return { label: workflow.isActive ? 'Manual' : 'Disabled', tone: 'default', automatic };
}
