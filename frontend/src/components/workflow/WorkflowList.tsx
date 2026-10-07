import { cn } from '../../lib/utils';
import { Card } from '../ui/Card';
import { Button } from '../ui/Button';
import { Badge } from '../ui/Badge';
import { ScrollArea } from '../ui/ScrollArea';
import { Plus, Play, Edit, Trash2, GitBranch, MoreVertical } from 'lucide-react';
import { Dropdown, DropdownItem } from '../ui/Dropdown';
import type { Workflow } from '../../types/workflow';

interface WorkflowListProps {
  workflows: Workflow[];
  selectedWorkflow: Workflow | null;
  onSelect: (workflow: Workflow) => void;
  onCreate: () => void;
  onEdit: (workflow: Workflow) => void;
  onDelete: (id: number | string) => void;
  onExecute: (workflow: Workflow) => void;
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
  loading,
}: WorkflowListProps) {
  const menuItems = (workflow: Workflow): DropdownItem[] => [
    { label: 'Execute', icon: <Play className="w-4 h-4" />, onClick: () => onExecute(workflow) },
    { label: 'Edit', icon: <Edit className="w-4 h-4" />, onClick: () => onEdit(workflow) },
    { label: 'Delete', icon: <Trash2 className="w-4 h-4" />, onClick: () => onDelete(workflow.id), danger: true },
  ];

  return (
    <Card className="h-full flex flex-col">
      <div className="p-4 border-b-nexus-border border-b flex items-center justify-between">
        <h3 className="font-semibold text-nexus-text flex items-center gap-2">
          <GitBranch className="w-5 h-5" />
          Workflows
          <Badge variant="accent" size="sm">{workflows.length}</Badge>
        </h3>
        <Button variant="primary" size="sm" onClick={onCreate} className="gap-1.5">
          <Plus className="w-4 h-4" />
          New
        </Button>
      </div>

      {loading ? (
        <div className="flex-1 flex items-center justify-center">
          <div className="w-8 h-8 border-2 border-nexus-accent border-t-transparent rounded-full animate-spin" />
        </div>
      ) : workflows.length === 0 ? (
        <div className="flex-1 flex flex-col items-center justify-center text-nexus-text-muted p-8">
          <GitBranch className="w-16 h-16 text-nexus-text-muted/50 mb-4" />
          <h4 className="text-lg font-medium text-nexus-text mb-1">No workflows yet</h4>
          <p className="text-sm mb-4">Create your first workflow to get started</p>
          <Button variant="primary" size="sm" onClick={onCreate} className="gap-1.5">
            <Plus className="w-4 h-4" />
            Create Workflow
          </Button>
        </div>
      ) : (
        <ScrollArea className="flex-1">
          <div className="p-4 space-y-2">
            {workflows.map(workflow => (
              <div key={workflow.id} className="relative">
                <div
                  onClick={() => onSelect(workflow)}
                  className={cn(
                    'w-full px-3 py-3 rounded-lg text-left transition-all duration-150 cursor-pointer',
                    'focus:outline-none focus:ring-2 focus:ring-nexus-accent focus:ring-offset-2 focus:ring-offset-nexus-bg',
                    selectedWorkflow?.id === workflow.id
                      ? 'bg-nexus-accent-dim border-nexus-accent border'
                      : 'bg-nexus-bg-tertiary/50 hover:bg-nexus-bg-tertiary border-nexus-border border hover:border-nexus-border-hover'
                  )}
                >
                  <div className="flex items-start justify-between gap-3">
                    <div className="flex-1 min-w-0 pr-24">
                      <div className="flex items-center gap-2 mb-1">
                        <span className="font-medium text-nexus-text truncate">{workflow.name}</span>
                        {workflow.isActive && <Badge variant="accent" size="sm">Active</Badge>}
                        {workflow.last_status && (
                          <Badge variant={workflow.last_status === 'completed' ? 'success' : workflow.last_status === 'failed' ? 'danger' : 'warning'} size="sm">
                            {workflow.last_status}
                          </Badge>
                        )}
                      </div>
                      <p className="text-sm text-nexus-text-secondary truncate">{workflow.description}</p>
                      <div className="flex items-center gap-3 mt-2 text-xs text-nexus-text-muted">
                        <span>{workflow.nodes.length} nodes</span>
                        <span>{workflow.edges.length} connections</span>
                        <span>v{workflow.version}</span>
                      </div>
                    </div>
                  </div>
                </div>
                <div className="absolute right-2 top-1/2 -translate-y-1/2 flex items-center gap-1">
                  <Button variant="primary" size="sm" aria-label={`Run ${workflow.name}`} className="gap-1"
                    onClick={(e) => { e.stopPropagation(); onExecute(workflow); }}>
                    <Play className="w-3.5 h-3.5" /> Run
                  </Button>
                  <Dropdown trigger={<MoreVertical className="w-5 h-5 text-nexus-text-muted" />} items={menuItems(workflow)} />
                </div>
              </div>
            ))}
          </div>
        </ScrollArea>
      )}
    </Card>
  );
}
