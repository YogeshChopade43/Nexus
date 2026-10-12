import { EmptyState } from '../ui/PageHeader';
import { cn } from '../../lib/utils';
import { Card } from '../ui/Card';
import { Button } from '../ui/Button';
import { Badge } from '../ui/Badge';
import { ScrollArea } from '../ui/ScrollArea';
import { Plus, Play, Square, Edit, Trash2, GitBranch, MoreVertical } from 'lucide-react';
import { Dropdown, DropdownItem } from '../ui/Dropdown';
import type { Workflow } from '../../types/workflow';
import { runState } from './runState';

interface WorkflowListProps {
  workflows: Workflow[];
  selectedWorkflow: Workflow | null;
  onSelect: (workflow: Workflow) => void;
  onCreate: () => void;
  onEdit: (workflow: Workflow) => void;
  onDelete: (id: number | string) => void;
  onExecute: (workflow: Workflow) => void;
  /** Pause or resume a workflow that runs by itself. */
  onToggleActive: (workflow: Workflow) => void;
  loading?: boolean;
}

export function WorkflowList({
  workflows,
  selectedWorkflow,
  onSelect,
  onCreate,
  onEdit,
  onDelete,
  onExecute,
  onToggleActive,
  loading,
}: WorkflowListProps) {
  const menuItems = (workflow: Workflow): DropdownItem[] => [
    { label: 'Execute', icon: <Play className="w-4 h-4" />, onClick: () => onExecute(workflow) },
    { label: 'Edit', icon: <Edit className="w-4 h-4" />, onClick: () => onEdit(workflow) },
    ...(runState(workflow).automatic ? [{
      label: workflow.isActive ? 'Stop' : 'Start',
      icon: workflow.isActive ? <Square className="w-4 h-4" /> : <Play className="w-4 h-4" />,
      onClick: () => onToggleActive(workflow),
    }] : []),
    { label: 'Delete', icon: <Trash2 className="w-4 h-4" />, onClick: () => onDelete(workflow.id), danger: true },
  ];

  return (
    <Card padding="none" className="h-full flex flex-col">
      <div className="flex items-center justify-between border-b border-nexus-border px-4 py-3">
        <h3 className="flex items-center gap-2 text-[13px] font-semibold text-nexus-text">
          All workflows
          <Badge size="sm">{workflows.length}</Badge>
        </h3>
      </div>

      {loading ? (
        <div className="space-y-2 p-3" aria-busy="true">
          {[0, 1, 2].map(i => <div key={i} className="h-[4.5rem] animate-pulse rounded-lg bg-nexus-bg-tertiary/60" />)}
        </div>
      ) : workflows.length === 0 ? (
        <EmptyState icon={GitBranch} title="No workflows yet" className="flex-1"
          description="Describe one in chat (&ldquo;remind me every day at 9&rdquo;), start from a template, or build it step by step."
          action={<Button variant="primary" size="sm" onClick={onCreate}><Plus className="w-3.5 h-3.5" /> Create workflow</Button>} />
      ) : (
        <ScrollArea className="flex-1">
          <div className="space-y-1.5 p-3">
            {workflows.map(workflow => (
              <div key={workflow.id} className="relative">
                <div
                  onClick={() => onSelect(workflow)}
                  className={cn(
                    'relative w-full cursor-pointer rounded-lg border px-3 py-2.5 text-left transition-colors duration-150',
                    selectedWorkflow?.id === workflow.id
                      ? 'border-nexus-border-hover bg-nexus-bg-tertiary before:absolute before:inset-y-2.5 before:left-0 before:w-0.5 before:rounded-full before:bg-nexus-accent'
                      : 'border-transparent hover:border-nexus-border hover:bg-nexus-bg-tertiary/50'
                  )}
                >
                  <div className="flex items-start justify-between gap-3">
                    <div className="flex-1 min-w-0 pr-24">
                      <p className="mb-0.5 line-clamp-2 break-words text-[13px] font-medium text-nexus-text" title={workflow.name}>{workflow.name}</p>
                      <p className="truncate text-xs text-nexus-text-secondary" title={workflow.description}>{workflow.description}</p>
                      <div className="mt-2 flex flex-wrap items-center gap-x-2.5 gap-y-1 text-[11px] text-nexus-text-muted">
                        {runState(workflow).label !== 'Manual' && (
                          <Badge variant={runState(workflow).tone} size="sm">{runState(workflow).label}</Badge>
                        )}
                        <span>{Math.max(0, workflow.nodes.filter(n => n.type !== 'trigger').length)} step(s)</span>
                        <span>v{workflow.version}</span>
                      </div>
                    </div>
                  </div>
                </div>
                <div className="absolute right-2 top-2 flex items-center gap-0.5">
                  <Button variant="secondary" size="sm" aria-label={`Run ${workflow.name}`} className="h-7 px-2 text-xs"
                    onClick={(e) => { e.stopPropagation(); onExecute(workflow); }}>
                    <Play className="w-3 h-3" /> Run
                  </Button>
                  <Dropdown items={menuItems(workflow)} trigger={
                    <Button variant="ghost" size="sm" className="h-7 w-7 px-0" aria-label={`More actions for ${workflow.name}`}>
                      <MoreVertical className="w-4 h-4 text-nexus-text-muted" />
                    </Button>} />
                </div>
              </div>
            ))}
          </div>
        </ScrollArea>
      )}
    </Card>
  );
}
