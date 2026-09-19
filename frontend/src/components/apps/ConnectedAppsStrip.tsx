import { useState } from 'react';
import { Button } from '../ui/Button';
import { Tooltip } from '../ui/Tooltip';
import { Plus } from 'lucide-react';
import { AppsDrawer } from './AppsDrawer';
import type { App } from '../../types/app';

interface ConnectedAppsStripProps {
  connectedApps: App[];
  allApps: App[];
  categories: Array<{ id: string; name: string; count: number }>;
  loading: boolean;
  connecting: string | null;
  onConnect: (app: App) => void;
  onDisconnect: (app: App) => void;
  onConfigure?: (app: App) => void;
  onSearchChange: (search: string) => void;
  onCategoryChange: (category: string) => void;
  search: string;
  selectedCategory: string;
}

export function ConnectedAppsStrip({
  connectedApps,
  allApps,
  categories,
  loading,
  connecting,
  onConnect,
  onDisconnect,
  onConfigure,
  onSearchChange,
  onCategoryChange,
  search,
  selectedCategory,
}: ConnectedAppsStripProps) {
  const [drawerOpen, setDrawerOpen] = useState(false);

  return (
    <div className="flex items-center gap-2 overflow-x-auto pb-2 scrollbar-hide" role="list" aria-label="Connected apps">
      {connectedApps.map(app => (
        <Tooltip key={app.app_id ?? app.id} content={app.name} position="top">
          <Button
            variant="secondary"
            size="sm"
            className="flex-shrink-0 gap-1.5 px-3"
            onClick={() => onConfigure?.(app)}
          >
            {app.icon.startsWith('http') || app.icon.startsWith('/') ? (
              <img src={app.icon} alt="" className="w-5 h-5 rounded" />
            ) : (
              <span className="text-base">{app.icon}</span>
            )}
            <span className="hidden sm:inline-block truncate max-w-[100px] font-medium">{app.name}</span>
            <span className="w-2 h-2 rounded-full bg-green-500" aria-hidden="true" />
          </Button>
        </Tooltip>
      ))}

      <Tooltip content="Browse all apps" position="top">
        <Button
          variant="ghost"
          size="sm"
          className="flex-shrink-0 h-9 w-9 p-0"
          onClick={() => setDrawerOpen(true)}
          aria-label="Browse all apps"
        >
          <Plus className="w-5 h-5 text-nexus-text-secondary" />
        </Button>
      </Tooltip>

      <AppsDrawer
        open={drawerOpen}
        onClose={() => setDrawerOpen(false)}
        apps={allApps}
        categories={categories}
        loading={loading}
        connecting={connecting}
        onConnect={onConnect}
        onDisconnect={onDisconnect}
        onConfigure={onConfigure}
        onSearchChange={onSearchChange}
        onCategoryChange={onCategoryChange}
        search={search}
        selectedCategory={selectedCategory}
      />
    </div>
  );
}
