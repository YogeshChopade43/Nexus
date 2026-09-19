import { Button } from '../ui/Button';
import { Tooltip } from '../ui/Tooltip';
import { Badge } from '../ui/Badge';
import { AlertCircle, Check, Loader2, Plug, PlugZap } from 'lucide-react';
import type { App, ConnectionStatus } from '../../types/app';

interface AppCardProps {
  app: App;
  onConnect?: (app: App) => void;
  onDisconnect?: (app: App) => void;
  onConfigure?: (app: App) => void;
  connecting?: string | null;
}

function statusLabel(status: ConnectionStatus): string {
  switch (status) {
    case 'connected':
      return 'Connected';
    case 'connecting':
      return 'Connecting';
    case 'error':
      return 'Connection error';
    case 'disconnected':
      return 'Not connected';
  }
}

export function AppCard({ app, onConnect, onDisconnect, onConfigure, connecting }: AppCardProps) {
  const appKey = app.app_id ?? app.id;
  const isConnecting = connecting === appKey;
  const status = app.connectionStatus ?? (app.connected ? 'connected' : 'disconnected');

  const handleConnect = () => {
    onConnect?.(app);
  };

  const handleDisconnect = () => {
    onDisconnect?.(app);
  };

  return (
    <div className="flex flex-col h-full p-4 bg-nexus-bg-secondary border-nexus-border border rounded-xl group">
      <div className="flex items-start gap-3 mb-3">
        <div className="w-12 h-12 rounded-xl bg-nexus-bg-tertiary flex items-center justify-center flex-shrink-0">
          {app.icon.startsWith('http') || app.icon.startsWith('/') ? (
            <img src={app.icon} alt="" className="w-8 h-8 rounded-lg" />
          ) : (
            <span className="text-2xl">{app.icon}</span>
          )}
        </div>
        <div className="flex-1 min-w-0">
          <div className="flex items-center gap-2">
            <h3 className="font-semibold text-nexus-text truncate">{app.name}</h3>
            <Badge
              variant={status === 'connected' ? 'success' : status === 'error' ? 'danger' : status === 'connecting' ? 'warning' : 'default'}
              size="sm"
              className="ml-auto flex-shrink-0"
            >
              {status === 'connected' && <Check className="w-3 h-3" />}
              {status === 'error' && <AlertCircle className="w-3 h-3" />}
              {statusLabel(status)}
            </Badge>
          </div>
          <p className="text-sm text-nexus-text-secondary mt-1 line-clamp-2">{app.description}</p>
        </div>
      </div>

      <div className="flex flex-wrap gap-1.5 mb-3">
        <span className="px-2 py-0.5 text-xs font-medium bg-nexus-accent-dim text-nexus-accent rounded-full">
          {app.category}
        </span>
        {app.capabilities.slice(0, 3).map((cap, i) => (
          <span key={i} className="px-2 py-0.5 text-xs font-medium bg-nexus-bg-tertiary text-nexus-text-secondary rounded-full">
            {cap}
          </span>
        ))}
        {app.capabilities.length > 3 && (
          <span className="px-2 py-0.5 text-xs font-medium bg-nexus-bg-tertiary text-nexus-text-secondary rounded-full">
            +{app.capabilities.length - 3} more
          </span>
        )}
      </div>

      {app.connectionError && (
        <div className="mb-3 p-2.5 rounded-lg bg-nexus-danger/10 border-nexus-danger/30 border text-xs text-nexus-danger">
          {app.connectionError}
        </div>
      )}

      <div className="mt-auto pt-3 border-t-nexus-border border-t flex items-center gap-2">
        {app.connected || status === 'connecting' ? (
          <>
            <Button
              variant="secondary"
              size="sm"
              className="flex-1 gap-1.5"
              onClick={() => onConfigure?.(app)}
              disabled={isConnecting}
            >
              <PlugZap className="w-4 h-4" />
              <span>{isConnecting ? 'Updating...' : 'Configure'}</span>
            </Button>
            <Tooltip content="Disconnect">
              <Button
                variant="ghost"
                size="sm"
                onClick={handleDisconnect}
                disabled={isConnecting}
                className="text-nexus-text-muted hover:text-nexus-danger"
                aria-label="Disconnect app"
              >
                <Plug className="w-4 h-4" />
              </Button>
            </Tooltip>
          </>
        ) : (
          <Button
            variant="primary"
            size="sm"
            className="flex-1 gap-1.5"
            onClick={handleConnect}
            disabled={isConnecting}
          >
            {isConnecting ? (
              <>
                <Loader2 className="w-4 h-4 animate-spin" />
                <span>Connecting...</span>
              </>
            ) : (
              <>
                <Plug className="w-4 h-4" />
                <span>Connect</span>
              </>
            )}
          </Button>
        )}
      </div>
    </div>
  );
}
