import { useState, type FormEvent } from 'react';
import { EmptyState } from '../ui/PageHeader';
import { cn, getErrorMessage } from '../../lib/utils';
import { Card } from '../ui/Card';
import { Button } from '../ui/Button';
import { Badge } from '../ui/Badge';
import { Modal } from '../ui/Modal';
import { fieldClass } from '../ui/Input';
import { ScrollArea } from '../ui/ScrollArea';
import { ChevronDown, Edit, Folder, FolderInput, FolderMinus, FolderPlus, GitBranch, MoreHorizontal, MoreVertical, Pencil, Play, Plus, Search, Square, Trash2 } from 'lucide-react';
import { Dropdown, DropdownItem } from '../ui/Dropdown';
import { useLocalStorage } from '../../hooks/useUtils';
import type { Workflow } from '../../types/workflow';
import { runState } from './runState';

/** Show the search box once there are this many workflows (or any folders). */
const SEARCH_FROM = 6;

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
  /** File a workflow in a folder ('' takes it out). */
  onMove?: (workflow: Workflow, folder: string) => void;
  /** Folders made on this page, including empty ones (folders in use are added from the workflows). */
  folders?: string[];
  onCreateFolder?: (name: string) => Promise<void> | void;
  onRenameFolder?: (name: string, newName: string) => Promise<void> | void;
  onDeleteFolder?: (name: string) => void;
  loading?: boolean;
}

/** Ask for a folder's name: to make one, or rename one. Shows the server's refusal (a name already taken). */
function FolderNameDialog({ title, initial = '', action, onSave, onClose }: {
  title: string; initial?: string; action: string; onSave: (name: string) => Promise<void> | void; onClose: () => void;
}) {
  const [name, setName] = useState(initial);
  const [error, setError] = useState<string | null>(null);
  const save = async (e: FormEvent) => {
    e.preventDefault();
    try {
      await onSave(name.trim());
      onClose();
    } catch (err) {
      setError(getErrorMessage(err));
    }
  };
  return (
    <Modal open onClose={onClose} title={title} size="sm">
      <form onSubmit={(e) => void save(e)} className="space-y-3">
        <input aria-label="Folder name" placeholder="e.g. Health, Work reports" value={name} maxLength={60} autoFocus
          onChange={(e) => { setName(e.target.value); setError(null); }} className={fieldClass} />
        {error && <p role="alert" className="text-xs text-nexus-danger">{error}</p>}
        <div className="flex justify-end gap-2">
          <Button type="button" variant="ghost" size="sm" onClick={onClose}>Cancel</Button>
          <Button type="submit" size="sm" disabled={!name.trim() || name.trim() === initial}>{action}</Button>
        </div>
      </form>
    </Modal>
  );
}

/** Pick a folder for a workflow: one you have, a new one, or none. */
function MoveDialog({ workflow, folders, onMove, onClose }: {
  workflow: Workflow; folders: string[]; onMove: (folder: string) => void; onClose: () => void;
}) {
  const [name, setName] = useState('');
  const others = folders.filter(f => f !== workflow.folder);
  const submit = (e: FormEvent) => {
    e.preventDefault();
    if (name.trim()) onMove(name.trim());
  };
  return (
    <Modal open onClose={onClose} title={`Move “${workflow.name}”`} size="sm">
      <div className="space-y-4">
        {others.length > 0 && (
          <div className="flex flex-wrap gap-1.5">
            {others.map(folder => (
              <Button key={folder} variant="secondary" size="sm" onClick={() => onMove(folder)}>
                <Folder className="h-3.5 w-3.5" /> {folder}
              </Button>
            ))}
          </div>
        )}
        <form onSubmit={submit} className="flex gap-2">
          <input aria-label="New folder" placeholder="New folder, e.g. Health" value={name} maxLength={60}
            onChange={(e) => setName(e.target.value)} className={cn(fieldClass, 'flex-1')} />
          <Button type="submit" size="sm" disabled={!name.trim()}>Move</Button>
        </form>
        {workflow.folder && (
          <Button variant="ghost" size="sm" onClick={() => onMove('')}>
            <FolderMinus className="h-3.5 w-3.5" /> Take out of “{workflow.folder}”
          </Button>
        )}
      </div>
    </Modal>
  );
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
  onMove,
  folders: saved = [],
  onCreateFolder,
  onRenameFolder,
  onDeleteFolder,
  loading,
}: WorkflowListProps) {
  const [query, setQuery] = useState('');
  const [naming, setNaming] = useState<{ folder?: string } | null>(null);  // the new-folder or rename dialog
  const [dragged, setDragged] = useState<Workflow | null>(null);
  const [dropOn, setDropOn] = useState<string | null>(null);
  const [closed, setClosed] = useLocalStorage<string[]>('nexus-workflow-folders-closed', []);
  const [moving, setMoving] = useState<Workflow | null>(null);

  const folders = [...new Set([...saved, ...workflows.map(w => w.folder || '')].filter(Boolean))].sort((a, b) => a.localeCompare(b));
  const needle = query.trim().toLowerCase();
  const shown = needle
    ? workflows.filter(w => `${w.name} ${w.description} ${w.folder ?? ''}`.toLowerCase().includes(needle))
    : workflows;
  const groups: [string, Workflow[]][] = [
    ...folders.map(folder => [folder, shown.filter(w => w.folder === folder)] as [string, Workflow[]]),
    ['', shown.filter(w => !w.folder)],
  ].filter(([folder, items]) => items.length > 0 || (folder && !needle)) as [string, Workflow[]][];  // empty folders show too
  const toggle = (folder: string) =>
    setClosed(prev => (prev.includes(folder) ? prev.filter(f => f !== folder) : [...prev, folder]));

  const menuItems = (workflow: Workflow): DropdownItem[] => [
    { label: 'Execute', icon: <Play className="w-4 h-4" />, onClick: () => onExecute(workflow) },
    { label: 'Edit', icon: <Edit className="w-4 h-4" />, onClick: () => onEdit(workflow) },
    ...(onMove ? [{ label: 'Move to folder', icon: <FolderInput className="w-4 h-4" />, onClick: () => setMoving(workflow) }] : []),
    ...(runState(workflow).automatic ? [{
      label: workflow.isActive ? 'Stop' : 'Start',
      icon: workflow.isActive ? <Square className="w-4 h-4" /> : <Play className="w-4 h-4" />,
      onClick: () => onToggleActive(workflow),
    }] : []),
    { label: 'Delete', icon: <Trash2 className="w-4 h-4" />, onClick: () => onDelete(workflow.id), danger: true },
  ];

  const row = (workflow: Workflow) => (
    <div key={workflow.id} className="relative">
      <div
        draggable={!!onMove}
        onDragStart={(e) => { e.dataTransfer?.setData('text/plain', String(workflow.id)); setDragged(workflow); }}
        onDragEnd={() => { setDragged(null); setDropOn(null); }}
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
  );

  return (
    <Card padding="none" className="h-full flex flex-col">
      <div className="flex items-center justify-between border-b border-nexus-border px-4 py-3">
        <h3 className="flex items-center gap-2 text-[13px] font-semibold text-nexus-text">
          All workflows
          <Badge size="sm">{workflows.length}</Badge>
        </h3>
        {onCreateFolder && (
          <Button variant="ghost" size="sm" className="h-7 px-2 text-xs" onClick={() => setNaming({})}>
            <FolderPlus className="h-3.5 w-3.5" /> New folder
          </Button>
        )}
      </div>
      {!loading && (workflows.length >= SEARCH_FROM || folders.length > 0) && (
        <div className="relative border-b border-nexus-border px-3 py-2">
          <Search className="pointer-events-none absolute left-5 top-1/2 h-3.5 w-3.5 -translate-y-1/2 text-nexus-text-muted" aria-hidden />
          <input type="search" aria-label="Search workflows" placeholder="Search workflows or folders" value={query}
            onChange={(e) => setQuery(e.target.value)} className={cn(fieldClass, 'h-8 pl-7 text-[13px]')} />
        </div>
      )}

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
            {shown.length === 0 && <p className="px-1 py-6 text-center text-xs text-nexus-text-muted">No workflow matches “{query}”.</p>}
            {folders.length === 0 ? shown.map(row) : groups.map(([folder, items]) => {
              const open = !!needle || !closed.includes(folder);  // searching shows every match
              const drop = {  // drag a workflow here to file it in this folder
                onDragOver: (e: React.DragEvent) => { if (dragged) { e.preventDefault(); setDropOn(folder); } },
                onDragLeave: () => setDropOn(current => (current === folder ? null : current)),
                onDrop: (e: React.DragEvent) => {
                  e.preventDefault();
                  if (dragged && onMove && (dragged.folder || '') !== folder) onMove(dragged, folder);
                  setDragged(null);
                  setDropOn(null);
                },
              };
              return (
                <section key={folder || '(none)'} {...drop}
                  className={cn('space-y-1.5 rounded-lg transition-colors', dropOn === folder && 'bg-nexus-accent/10 ring-1 ring-nexus-accent/40')}>
                  <div className="group/folder flex items-center gap-0.5">
                    <button type="button" aria-expanded={open} onClick={() => toggle(folder)} {...drop}
                      className="flex min-w-0 flex-1 items-center gap-1.5 rounded-md px-1.5 py-1 text-left text-xs font-medium text-nexus-text-secondary hover:bg-nexus-bg-tertiary/60 hover:text-nexus-text">
                      <ChevronDown className={cn('h-3.5 w-3.5 shrink-0 transition-transform', !open && '-rotate-90')} aria-hidden />
                      {folder ? <Folder className="h-3.5 w-3.5 shrink-0" aria-hidden /> : null}
                      <span className="min-w-0 flex-1 truncate">{folder || 'Not in a folder'}</span>
                      <span className="tabular-nums text-nexus-text-muted">{items.length}</span>
                    </button>
                    {folder && (onRenameFolder || onDeleteFolder) && (
                      <Dropdown items={[
                        ...(onRenameFolder ? [{ label: 'Rename', icon: <Pencil className="w-4 h-4" />, onClick: () => setNaming({ folder }) }] : []),
                        ...(onDeleteFolder ? [{ label: 'Delete folder', icon: <Trash2 className="w-4 h-4" />, onClick: () => onDeleteFolder(folder), danger: true }] : []),
                      ]} trigger={
                        <Button variant="ghost" size="sm" className="h-6 w-6 px-0 opacity-60 group-hover/folder:opacity-100 focus-visible:opacity-100"
                          aria-label={`Folder actions for ${folder}`}>
                          <MoreHorizontal className="h-3.5 w-3.5 text-nexus-text-muted" />
                        </Button>} />
                    )}
                  </div>
                  {open && (items.length
                    ? <div className="space-y-1.5 pl-2">{items.map(row)}</div>
                    : <p className="ml-2 rounded-lg border border-dashed border-nexus-border px-3 py-2.5 text-xs text-nexus-text-muted">
                        Drag a workflow here, or use Move to folder in its menu.
                      </p>)}
                </section>
              );
            })}
          </div>
        </ScrollArea>
      )}
      {naming && (naming.folder ? onRenameFolder : onCreateFolder) && (
        <FolderNameDialog title={naming.folder ? `Rename “${naming.folder}”` : 'New folder'} initial={naming.folder}
          action={naming.folder ? 'Rename' : 'Create'} onClose={() => setNaming(null)}
          onSave={(name) => (naming.folder ? onRenameFolder!(naming.folder, name) : onCreateFolder!(name))} />
      )}
      {moving && onMove && (
        <MoveDialog workflow={moving} folders={folders} onClose={() => setMoving(null)}
          onMove={(folder) => { onMove(moving, folder); setMoving(null); }} />
      )}
    </Card>
  );
}
