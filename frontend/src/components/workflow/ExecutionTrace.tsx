import { useRef, useEffect } from 'react';
import { cn, formatRelativeTime } from '../../lib/utils';
import { Card } from '../ui/Card';
import { Badge } from '../ui/Badge';
import { ScrollArea } from '../ui/ScrollArea';
import { ChevronRight, CheckCircle, XCircle, Clock, Wrench } from 'lucide-react';
import type { ExecutionTraceEntry } from '../../types/workflow';

interface ExecutionTraceProps {
  trace: ExecutionTraceEntry[];
  autoScroll?: boolean;
}

function safeStringify(value: unknown): string {
  if (value === undefined || value === null) return 'null';
  if (typeof value === 'string') return value;
  try {
    return JSON.stringify(value, null, 2);
  } catch {
    return String(value);
  }
}

function safeSlice(str: string, len: number): string {
  return str.length <= len ? str : str.slice(0, len) + '...';
}

export function ExecutionTrace({ trace, autoScroll = true }: ExecutionTraceProps) {
  const traceEndRef = useRef<HTMLDivElement>(null);
  const skipped = trace.filter(entry => entry.practice_skipped);

  useEffect(() => {
    if (autoScroll) {
      traceEndRef.current?.scrollIntoView({ behavior: 'smooth' });
    }
  }, [trace, autoScroll]);

  const getStatusIcon = (type: ExecutionTraceEntry['type']) => {
    switch (type) {
      case 'start':
        return <div className="w-4 h-4 rounded-full bg-nexus-info animate-pulse" />;
      case 'complete':
        return <CheckCircle className="w-4 h-4 text-nexus-accent-text" />;
      case 'error':
        return <XCircle className="w-4 h-4 text-nexus-danger" />;
      case 'conditional':
        return <ChevronRight className="w-4 h-4 text-nexus-warning" />;
      case 'tool_executed':
        return <Wrench className="w-4 h-4 text-nexus-accent-text" />;
      default:
        return <Clock className="w-4 h-4 text-nexus-text-muted" />;
    }
  };

  const getStatusBadge = (entry: ExecutionTraceEntry) => {
    const { type, status } = entry;
    if (entry.practice_skipped) return <Badge variant="warning" size="sm">Practice</Badge>;
    if (entry.uncertain) return <Badge variant="warning" size="sm">Uncertain (practice)</Badge>;
    if (status === 'running') return <Badge variant="info" size="sm">Running</Badge>;
    if (status === 'cancelled') return <Badge variant="default" size="sm">Cancelled</Badge>;
    if (status === 'success') return <Badge variant="success" size="sm">Completed</Badge>;
    if (status === 'failed') return <Badge variant="danger" size="sm">Failed</Badge>;
    if (status === 'skipped') return <Badge variant="warning" size="sm">Skipped</Badge>;
    switch (type) {
      case 'start':
        return <Badge variant="info" size="sm">Running</Badge>;
      case 'complete':
        return <Badge variant="success" size="sm">Completed</Badge>;
      case 'error':
        return <Badge variant="danger" size="sm">Failed</Badge>;
      case 'conditional':
        return <Badge variant="warning" size="sm">Conditional</Badge>;
      case 'tool_executed':
        return <Badge variant="success" size="sm">Tool executed</Badge>;
      default:
        return <Badge variant="default" size="sm">Pending</Badge>;
    }
  };

  if (trace.length === 0) {
    return (
      <Card className="h-full">
        <div className="flex flex-col items-center justify-center h-full min-h-[200px] text-nexus-text-muted">
          <Clock className="w-12 h-12 text-nexus-text-muted/50 mb-3" />
          <p className="text-sm">No execution trace available</p>
          <p className="text-xs">Run a workflow to see the trace</p>
        </div>
      </Card>
    );
  }

  return (
    <Card padding="none" className="h-full flex flex-col">
      <div className="p-4 border-b-nexus-border border-b">
        <h3 className="font-semibold text-nexus-text flex items-center gap-2">
          <Clock className="w-5 h-5" />
          Execution Trace
          <Badge variant="accent" size="sm">{trace.length} steps</Badge>
        </h3>
      </div>

      <ScrollArea className="flex-1">
        <div className="p-4 space-y-4">
          {skipped.length > 0 && (
            <div className="rounded-lg border border-nexus-warning/40 bg-nexus-warning/5 p-3">
              <p className="text-sm font-medium text-nexus-text">
                Would have made {skipped.length} {skipped.length === 1 ? 'change' : 'changes'}
              </p>
              <p className="mb-2 text-xs text-nexus-text-muted">Practice run: these steps were skipped, so nothing was changed.</p>
              <ul className="space-y-1.5">
                {skipped.map((entry, index) => (
                  <li key={entry.id || `skipped-${index}`}>
                    <details className="group">
                      <summary className="flex cursor-pointer items-center gap-1.5 text-xs text-nexus-text-secondary">
                        <ChevronRight className="h-3.5 w-3.5 transition-transform group-open:rotate-90" />
                        <span className="text-nexus-text">{entry.nodeName || entry.nodeId}</span>
                        <span className="font-mono">{entry.would_call}</span>
                      </summary>
                      <pre className="mt-1 max-w-full overflow-x-auto rounded bg-nexus-bg p-2 font-mono text-xs text-nexus-text-secondary">
                        {safeSlice(safeStringify(entry.input), 5000)}
                      </pre>
                    </details>
                  </li>
                ))}
              </ul>
            </div>
          )}
          {trace.map((entry, index) => (
            <div
              key={entry.id || `trace-${index}`}
              className={cn(
                'relative pl-8 pb-4', entry.parent && 'ml-6',
                index < trace.length - 1 && 'before:content-[""] before:absolute before:left-3 before:top-8 before:bottom-0 before:w-[1px] before:bg-nexus-border'
              )}
            >
              <div className="absolute left-0 top-0 flex items-center justify-center w-6 h-6 rounded-full bg-nexus-bg-tertiary border-nexus-border border z-10">
                {getStatusIcon(entry.type)}
              </div>

              <div className="bg-nexus-bg-tertiary/50 border-nexus-border border rounded-lg p-3">
                <div className="flex items-start gap-3">
                  <div className="flex-1 min-w-0">
                    <div className="flex items-center gap-2 mb-1">
                      <span className="font-mono text-sm text-nexus-text">{entry.nodeName || entry.nodeId || 'Unknown'}</span>
                      {getStatusBadge(entry)}
                      {entry.reused && <Badge variant="default" size="sm">reused from last run</Badge>}
                      {entry.duration !== undefined && entry.duration !== null && (
                        <span className="text-xs text-nexus-text-muted ml-auto">
                          {entry.duration}ms
                        </span>
                      )}
                    </div>
                    <time className="text-xs text-nexus-text-muted">
                      {formatRelativeTime(entry.timestamp)}
                    </time>
                    {entry.reason && <span className="text-xs text-nexus-text-muted"> · {entry.reason}</span>}
                  </div>
                </div>

                {(entry.tool_name || entry.tool || entry.app_id || entry.connected !== undefined || entry.status || entry.input || entry.parameters || entry.output || entry.data || entry.error) && (
                  <div className="mt-3 space-y-2">
                    {(entry.tool_name || entry.tool || entry.app_id || entry.connected !== undefined || entry.status) && (
                      <div className="flex flex-wrap gap-1.5">
                        {(entry.tool_name || entry.tool) && (
                          <Badge variant="accent" size="sm">{entry.tool_name || entry.tool}</Badge>
                        )}
                        {entry.app_id && (
                          <Badge variant="default" size="sm">{entry.app_id}</Badge>
                        )}
                        {entry.status && (
                          <Badge variant={entry.status === 'success' ? 'success' : entry.status === 'failed' ? 'danger' : 'warning'} size="sm">
                            {entry.status}
                          </Badge>
                        )}
                        {entry.connected !== undefined && (
                          <Badge variant={entry.connected ? 'success' : 'danger'} size="sm">{entry.connected ? 'connected' : 'disconnected'}</Badge>
                        )}
                      </div>
                    )}

                    {(entry.input || entry.parameters) && (
                      <details className="group">
                        <summary className="flex items-center gap-1.5 text-xs text-nexus-text-secondary cursor-pointer">
                          <ChevronRight className="w-3.5 h-3.5 transition-transform group-open:rotate-90" />
                          Input
                        </summary>
                        <pre className="mt-2 p-2 bg-nexus-bg text-nexus-text-secondary text-xs font-mono rounded overflow-x-auto max-w-full">
                          {safeSlice(safeStringify(entry.input ?? entry.parameters), 5000)}
                        </pre>
                      </details>
                    )}

                    {(entry.output || entry.data) && (
                      <details className="group">
                        <summary className="flex items-center gap-1.5 text-xs text-nexus-text-secondary cursor-pointer">
                          <ChevronRight className="w-3.5 h-3.5 transition-transform group-open:rotate-90" />
                          Output
                        </summary>
                        <pre className="mt-2 p-2 bg-nexus-bg text-nexus-text text-xs font-mono rounded overflow-x-auto max-w-full">
                          {safeSlice(safeStringify(entry.output ?? entry.data), 5000)}
                        </pre>
                      </details>
                    )}

                    {entry.error && (
                      <div className="p-2 bg-nexus-danger/10 border-nexus-danger/30 border rounded text-nexus-danger text-xs font-mono">
                        {entry.error}
                      </div>
                    )}
                  </div>
                )}
              </div>
            </div>
          ))}
          <div ref={traceEndRef} />
        </div>
      </ScrollArea>
    </Card>
  );
}
