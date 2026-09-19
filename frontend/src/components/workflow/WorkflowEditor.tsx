import { useState, useCallback } from 'react';
import { Card } from '../ui/Card';
import { Button } from '../ui/Button';
import { Input } from '../ui/Input';
import { Textarea } from '../ui/Input';
import { Separator } from '../ui/Separator';
import { Plus, Save, X } from 'lucide-react';
import type { Workflow, WorkflowNode, WorkflowEdge, App } from '../../types';

interface WorkflowEditorProps {
  workflow: Workflow | null;
  onSave: (data: { name: string; description: string; nodes: WorkflowNode[]; edges: WorkflowEdge[]; isActive: boolean }) => void;
  onCancel: () => void;
  availableNodeTypes: Array<{ type: string; name: string; description: string; icon: string }>;
  connectedApps: App[];
}

export function WorkflowEditor({ workflow, onSave, onCancel, availableNodeTypes, connectedApps }: WorkflowEditorProps) {
  const [name, setName] = useState(workflow?.name || '');
  const [description, setDescription] = useState(workflow?.description || '');
  const [nodes, setNodes] = useState<WorkflowNode[]>(workflow?.nodes || []);
  const [edges, setEdges] = useState<WorkflowEdge[]>(workflow?.edges || []);
  const [isActive, setIsActive] = useState(workflow?.isActive ?? false);
  const [showNodeModal, setShowNodeModal] = useState(false);
  const [showConnectionModal, setShowConnectionModal] = useState(false);
  const [connectionSource, setConnectionSource] = useState<string | null>(null);
  const [showAppSelector, setShowAppSelector] = useState(false);
  const [selectedAppId, setSelectedAppId] = useState<string | null>(null);

  const addNode = useCallback((type: string) => {
    const nodeType = availableNodeTypes.find(t => t.type === type);
    const newNode: WorkflowNode = {
      id: `node-${Date.now()}`,
      type: type as WorkflowNode['type'],
      name: nodeType?.name || 'New Node',
      description: nodeType?.description || '',
      position: { x: 100, y: 100 + nodes.length * 80 },
      config: {},
      inputs: [],
      outputs: [],
    };
    setNodes(prev => [...prev, newNode]);
    setShowNodeModal(false);
  }, [availableNodeTypes, nodes.length]);

  const updateNodeName = useCallback((id: string, newName: string) => {
    setNodes(prev => prev.map(n => n.id === id ? { ...n, name: newName } : n));
  }, []);

  const deleteNode = useCallback((id: string) => {
    setNodes(prev => prev.filter(n => n.id !== id));
    setEdges(prev => prev.filter(e => e.source !== id && e.target !== id));
  }, []);

  const addEdge = useCallback((source: string, target: string) => {
    const newEdge: WorkflowEdge = {
      id: `edge-${Date.now()}`,
      source,
      sourceHandle: 'output',
      target,
      targetHandle: 'input',
    };
    setEdges(prev => [...prev, newEdge]);
    setShowConnectionModal(false);
    setConnectionSource(null);
  }, []);

  const deleteEdge = useCallback((id: string) => {
    setEdges(prev => prev.filter(e => e.id !== id));
  }, []);

  const handleSave = () => {
    if (!name.trim()) return;
    onSave({
      name: name.trim(),
      description,
      nodes,
      edges,
      isActive,
    });
  };

  const handleConnectNode = (nodeId: string) => {
    const node = nodes.find(n => n.id === nodeId);
    if (node?.type === 'trigger') {
      setConnectionSource(nodeId);
      setShowConnectionModal(true);
    } else {
      setConnectionSource(nodeId);
      setShowConnectionModal(true);
    }
  };

  const handleRemoveApp = (nodeId: string) => {
    setNodes(prev => prev.map(n =>
      n.id === nodeId ? { ...n, app_id: undefined } : n
    ));
  };

  const handleSelectApp = (app: App) => {
    if (connectionSource) {
      setNodes(prev => prev.map(n =>
        n.id === connectionSource ? { ...n, app_id: app.app_id ?? app.id } : n
      ));
    }
    setShowConnectionModal(false);
    setConnectionSource(null);
  };

  return (
    <Card className="h-full flex flex-col">
      <div className="p-4 border-b-nexus-border border-b flex items-center justify-between">
        <h3 className="font-semibold text-nexus-text">
          {workflow ? 'Edit Workflow' : 'Create Workflow'}
        </h3>
        <div className="flex items-center gap-2">
          <Button variant="ghost" size="sm" onClick={onCancel}>
            <X className="w-4 h-4" />
            Cancel
          </Button>
          <Button variant="primary" size="sm" onClick={handleSave} className="gap-1.5">
            <Save className="w-4 h-4" />
            Save
          </Button>
        </div>
      </div>

      <div className="p-4 space-y-6 flex-1 overflow-y-auto">
        <div className="space-y-4">
          <Input
            label="Name"
            value={name}
            onChange={(e) => setName(e.target.value)}
            placeholder="Workflow name"
            required
          />
          <Textarea
            label="Description"
            value={description}
            onChange={(e) => setDescription(e.target.value)}
            placeholder="Describe what this workflow does"
            rows={3}
          />
          <div className="flex items-center gap-3">
            <label className="flex items-center gap-2 cursor-pointer">
              <input
                type="checkbox"
                checked={isActive}
                onChange={(e) => setIsActive(e.target.checked)}
                className="w-4 h-4 rounded border-nexus-border bg-nexus-bg-tertiary text-nexus-accent focus:ring-nexus-accent"
              />
              <span className="text-sm text-nexus-text">Active</span>
            </label>
          </div>
        </div>

        <Separator />

        <div>
          <div className="flex items-center justify-between mb-4">
            <h4 className="font-medium text-nexus-text">Nodes ({nodes.length})</h4>
            <Button variant="secondary" size="sm" onClick={() => setShowNodeModal(true)} className="gap-1.5">
              <Plus className="w-4 h-4" />
              Add Node
            </Button>
          </div>

          {nodes.length === 0 ? (
            <div className="text-center py-8 text-nexus-text-muted border-nexus-border border rounded-lg">
              <p className="mb-2">No nodes added yet</p>
              <Button variant="secondary" size="sm" onClick={() => setShowNodeModal(true)} className="gap-1.5">
                <Plus className="w-4 h-4" />
                Add First Node
              </Button>
            </div>
          ) : (
            <div className="space-y-3 max-h-96 overflow-y-auto">
              {nodes.map((node) => (
                <div key={node.id} className="bg-nexus-bg-tertiary/50 border-nexus-border border rounded-lg p-3">
                  <div className="flex items-center gap-3 mb-2">
                    <span className="text-xl">{availableNodeTypes.find(t => t.type === node.type)?.icon || '⚙️'}</span>
                    <input
                      type="text"
                      value={node.name}
                      onChange={(e) => updateNodeName(node.id, e.target.value)}
                      className="flex-1 bg-transparent border-none focus:outline-none text-sm font-medium text-nexus-text"
                      placeholder="Node name"
                    />
                    <Button variant="ghost" size="sm" onClick={() => deleteNode(node.id)}>
                      <X className="w-4 h-4" />
                    </Button>
                  </div>
                  <p className="text-xs text-nexus-text-muted">{node.description || 'No description'}</p>
                  {node.type === 'trigger' && (
                    <div className="mt-2">
                      {node.app_id ? (
                        <div className="flex items-center gap-2">
                          {(() => {
                            const app = connectedApps.find(a => (a.app_id ?? a.id) === node.app_id);
                            return app ? (
                              <span className="inline-flex items-center gap-1.5 px-2 py-0.5 text-xs font-medium bg-nexus-accent-dim text-nexus-accent rounded-full">
                                {app.icon.startsWith('http') || app.icon.startsWith('/') ? (
                                  <img src={app.icon} alt="" className="w-4 h-4 rounded" />
                                ) : (
                                  <span>{app.icon}</span>
                                )}
                                {app.name}
                              </span>
                            ) : null;
                          })()}
                          <Button
                            variant="ghost"
                            size="sm"
                            onClick={() => handleRemoveApp(node.id)}
                            className="p-1 h-auto"
                            aria-label="Remove app"
                          >
                            <X className="w-3 h-3" />
                          </Button>
                          <button
                            onClick={() => handleConnectNode(node.id)}
                            className="text-xs text-nexus-accent hover:underline"
                          >
                            Change
                          </button>
                        </div>
                      ) : (
                        <button
                          onClick={() => handleConnectNode(node.id)}
                          className="text-xs text-nexus-accent hover:underline"
                        >
                          Connect to app...
                        </button>
                      )}
                    </div>
                  )}
                  {node.type !== 'trigger' && (
                    <button
                      onClick={() => handleConnectNode(node.id)}
                      className="mt-2 text-xs text-nexus-accent hover:underline"
                    >
                      Connect to...
                    </button>
                  )}
                </div>
              ))}
            </div>
          )}
        </div>

        <Separator />

        <div>
          <h4 className="font-medium text-nexus-text mb-4">Connections ({edges.length})</h4>
          {edges.length === 0 ? (
            <p className="text-sm text-nexus-text-muted">No connections defined</p>
          ) : (
            <div className="space-y-2 max-h-64 overflow-y-auto">
              {edges.map(edge => (
                <div key={edge.id} className="flex items-center gap-2 text-sm text-nexus-text-secondary bg-nexus-bg-tertiary/50 border-nexus-border border rounded p-2">
                  <span className="font-mono">{edge.source.slice(0, 8)}... </span>
                  <span className="text-nexus-text-muted">→</span>
                  <span className="font-mono">{edge.target.slice(0, 8)}...</span>
                  <Button variant="ghost" size="sm" className="ml-auto p-1" onClick={() => deleteEdge(edge.id)}>
                    <X className="w-3.5 h-3.5" />
                  </Button>
                </div>
              ))}
            </div>
          )}
        </div>
      </div>

      {showNodeModal && (
        <div className="fixed inset-0 z-50 bg-black/50 flex items-center justify-center p-4">
          <Card className="w-full max-w-md p-6">
            <h4 className="font-semibold text-nexus-text mb-4">Add Node</h4>
            <div className="space-y-2 max-h-60 overflow-y-auto">
              {availableNodeTypes.map(type => (
                <button
                  key={type.type}
                  onClick={() => addNode(type.type)}
                  className="w-full p-3 text-left rounded-lg bg-nexus-bg-tertiary/50 border-nexus-border border hover:bg-nexus-bg-tertiary transition-colors"
                >
                  <div className="flex items-center gap-3">
                    <span className="text-2xl">{type.icon}</span>
                    <div>
                      <div className="font-medium text-nexus-text">{type.name}</div>
                      <div className="text-sm text-nexus-text-secondary">{type.description}</div>
                    </div>
                  </div>
                </button>
              ))}
            </div>
            <Button variant="ghost" size="sm" className="w-full mt-4" onClick={() => setShowNodeModal(false)}>
              Cancel
            </Button>
          </Card>
        </div>
      )}

      {showConnectionModal && connectionSource && (
        <div className="fixed inset-0 z-50 bg-black/50 flex items-center justify-center p-4">
          <Card className="w-full max-w-md p-6">
            <h4 className="font-semibold text-nexus-text mb-4">Connect To</h4>
                  {connectedApps.length > 0 && (
                    <div className="mb-4">
                      <p className="text-xs text-nexus-text-muted mb-2">Connected Apps</p>
                      <div className="space-y-2">
                        {connectedApps.map(app => (
                          <button
                            key={app.app_id ?? app.id}
                            onClick={() => handleSelectApp(app)}
                            className="w-full p-3 text-left rounded-lg bg-nexus-bg-tertiary/50 border-nexus-border border hover:bg-nexus-bg-tertiary transition-colors flex items-center gap-3"
                          >
                            {app.icon.startsWith('http') || app.icon.startsWith('/') ? (
                              <img src={app.icon} alt="" className="w-5 h-5 rounded" />
                            ) : (
                              <span className="text-xl">{app.icon}</span>
                            )}
                            <div>
                              <div className="font-medium text-nexus-text">{app.name}</div>
                              <p className="text-xs text-nexus-text-secondary">App trigger</p>
                            </div>
                          </button>
                        ))}
                      </div>
                    </div>
                  )}
            <Separator className="my-3" />
            <div className="space-y-2">
              {nodes.filter(n => n.id !== connectionSource && n.type !== 'trigger').map(target => (
                <button
                  key={target.id}
                  onClick={() => addEdge(connectionSource, target.id)}
                  className="w-full p-3 text-left rounded-lg bg-nexus-bg-tertiary/50 border-nexus-border border hover:bg-nexus-bg-tertiary transition-colors"
                >
                  <span className="font-medium text-nexus-text">{target.name}</span>
                  <p className="text-xs text-nexus-text-secondary">{target.type}</p>
                </button>
              ))}
            </div>
            {nodes.filter(n => n.id !== connectionSource && n.type === 'trigger').length > 0 && (
              <p className="text-xs text-nexus-text-muted mt-3">Trigger nodes connect via app selection only</p>
            )}
            <Button variant="ghost" size="sm" className="w-full mt-4" onClick={() => { setShowConnectionModal(false); setConnectionSource(null); }}>
              Cancel
            </Button>
          </Card>
        </div>
      )}
    </Card>
  );
}
