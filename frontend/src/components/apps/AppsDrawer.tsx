import { useState, useEffect } from 'react';
import { Button } from '../ui/Button';
import { Input } from '../ui/Input';
import { ScrollArea } from '../ui/ScrollArea';
import { Search, X, Loader2, Box } from 'lucide-react';
import { createPortal } from 'react-dom';
import { AppCard } from './AppCard';
import type { App, AppCategory } from '../../types/app';

interface AppsDrawerProps {
  open: boolean;
  onClose: () => void;
  apps: App[];
  categories: AppCategory[];
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

export function AppsDrawer({
  open,
  onClose,
  apps,
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
}: AppsDrawerProps) {
  const [drawerOpen, setDrawerOpen] = useState(open);

  useEffect(() => {
    setDrawerOpen(open);
  }, [open]);

  useEffect(() => {
    if (drawerOpen) {
      document.body.style.overflow = 'hidden';
    } else {
      document.body.style.overflow = '';
    }
    return () => {
      document.body.style.overflow = '';
    };
  }, [drawerOpen]);

  useEffect(() => {
    const handleEscape = (e: KeyboardEvent) => {
      if (e.key === 'Escape') onClose();
    };
    document.addEventListener('keydown', handleEscape);
    return () => document.removeEventListener('keydown', handleEscape);
  }, [onClose]);

  if (!drawerOpen) return null;

  const filteredApps = apps.filter(app => {
    const matchesSearch = app.name.toLowerCase().includes(search.toLowerCase()) ||
      app.description.toLowerCase().includes(search.toLowerCase()) ||
      app.capabilities.some(c => c.toLowerCase().includes(search.toLowerCase()));
    const matchesCategory = !selectedCategory || app.category === selectedCategory;
    return matchesSearch && matchesCategory;
  });

  const drawerContent = (
    <div className="fixed inset-0 z-50 flex lg:hidden" role="dialog" aria-modal="true" aria-label="Apps">
      <div
        className="absolute inset-0 bg-black/50 animate-fade-in"
        onClick={onClose}
        aria-hidden="true"
      />
      <div className="relative flex-1 max-w-md ml-auto bg-nexus-bg-secondary border-l-nexus-border flex flex-col animate-slide-up">
        <div className="flex items-center justify-between p-4 border-b-nexus-border border-b">
          <div className="flex items-center gap-3">
            <Box className="w-8 h-8 rounded-lg bg-nexus-accent flex items-center justify-center text-nexus-bg" />
            <h2 className="text-lg font-semibold text-nexus-text">Apps</h2>
            <span className="px-2 py-0.5 text-xs font-medium bg-nexus-accent-dim text-nexus-accent rounded-full">
              {apps.length} total
            </span>
          </div>
          <Button variant="ghost" size="sm" onClick={onClose} aria-label="Close drawer">
            <X className="w-5 h-5" />
          </Button>
        </div>

        <div className="p-4 space-y-4 flex-1 overflow-hidden">
          <div className="relative">
            <Search className="absolute left-3 top-1/2 -translate-y-1/2 w-5 h-5 text-nexus-text-muted" />
            <Input
              placeholder="Search apps..."
              value={search}
              onChange={(e) => onSearchChange(e.target.value)}
              className="pl-10"
              aria-label="Search apps"
            />
          </div>

          {categories.length > 0 && (
            <div>
              <label className="block text-sm font-medium text-nexus-text-secondary mb-2">Categories</label>
              <ScrollArea className="max-h-32">
                <div className="flex flex-wrap gap-2">
                  <Button
                    variant={!selectedCategory ? 'primary' : 'secondary'}
                    size="sm"
                    onClick={() => onCategoryChange('')}
                  >
                    All <span className="text-nexus-text-muted">({apps.length})</span>
                  </Button>
                  {categories.map(cat => (
                    <Button
                      key={cat.id}
                      variant={selectedCategory === cat.id ? 'primary' : 'secondary'}
                      size="sm"
                      onClick={() => onCategoryChange(cat.id)}
                    >
                      {cat.name} <span className="text-nexus-text-muted">({cat.count})</span>
                    </Button>
                  ))}
                </div>
              </ScrollArea>
            </div>
          )}

          {loading ? (
            <div className="flex items-center justify-center py-8">
              <Loader2 className="w-6 h-6 animate-spin text-nexus-accent" />
            </div>
          ) : filteredApps.length === 0 ? (
            <div className="flex flex-col items-center justify-center py-8 text-nexus-text-muted">
              <Box className="w-12 h-12 text-nexus-text-muted/50 mb-3" />
              <p className="text-sm">No apps found</p>
              <p className="text-xs">Try adjusting your search or filters</p>
            </div>
          ) : (
            <ScrollArea className="flex-1">
              <div className="grid gap-3 sm:grid-cols-2">
                {filteredApps.map(app => (
                  <AppCard
                    key={app.app_id ?? app.id}
                    app={app}
                    onConnect={onConnect}
                    onDisconnect={onDisconnect}
                    onConfigure={onConfigure}
                    connecting={connecting}
                  />
                ))}
              </div>
            </ScrollArea>
          )}
        </div>
      </div>
    </div>
  );

  return createPortal(drawerContent, document.body);
}
