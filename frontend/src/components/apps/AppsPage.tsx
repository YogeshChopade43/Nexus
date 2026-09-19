import { useState, useCallback } from 'react';
import { Card } from '../ui/Card';
import { Button } from '../ui/Button';
import { Input } from '../ui/Input';
import { ScrollArea } from '../ui/ScrollArea';
import { Separator } from '../ui/Separator';
import { Search, Grid, List, Loader2, Box } from 'lucide-react';
import { AppCard } from './AppCard';
import { ConnectedAppsStrip } from './ConnectedAppsStrip';
import { AppsDrawer } from './AppsDrawer';
import { ConnectorConfigModal } from './ConnectorConfigModal';
import { useApps } from '../../hooks/useApps';
import type { App } from '../../types/app';

export function AppsPage() {
  const {
    apps,
    categories,
    total,
    loading,
    error,
    toggleConnection,
    configureConnection,
    refreshing,
    availableTools,
    toolsLoading,
    toolsError,
  } = useApps();

  const [drawerOpen, setDrawerOpen] = useState(false);
  const [configuringApp, setConfiguringApp] = useState<App | null>(null);
  const [configuring, setConfiguring] = useState(false);
  const [viewMode, setViewMode] = useState<'grid' | 'list'>('grid');
  const [search, setSearch] = useState('');
  const [selectedCategory, setSelectedCategory] = useState('');
  const [selectedStatus, setSelectedStatus] = useState<'all' | 'connected' | 'available' | 'error'>('all');

  const connectedApps = apps.filter(app => app.connected);
  const filteredApps = apps.filter(app => {
    const matchesSearch = app.name.toLowerCase().includes(search.toLowerCase()) ||
      app.description.toLowerCase().includes(search.toLowerCase()) ||
      app.capabilities.some(capability => capability.toLowerCase().includes(search.toLowerCase()));
    const matchesCategory = !selectedCategory || app.category === selectedCategory;
    const matchesStatus = selectedStatus === 'all' ||
      (selectedStatus === 'connected' && app.connected) ||
      (selectedStatus === 'available' && !app.connected) ||
      (selectedStatus === 'error' && app.connectionStatus === 'error');
    return matchesSearch && matchesCategory && matchesStatus;
  });

  const handleConnect = useCallback((app: App) => {
    setConfiguringApp(app);
  }, []);

  const handleDisconnect = useCallback((app: App) => {
    void toggleConnection(app, false);
  }, [toggleConnection]);

  const handleConfigure = useCallback((app: App) => {
    setConfiguringApp(app);
  }, []);

  const handleConfigureSubmit = useCallback(async (app: App, config: Record<string, string>) => {
    setConfiguring(true);
    try {
      await configureConnection(app, config);
      setConfiguringApp(null);
    } finally {
      setConfiguring(false);
    }
  }, [configureConnection]);

  return (
    <div className="space-y-6">
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-2xl font-bold text-nexus-text">Apps</h1>
          <p className="text-nexus-text-secondary mt-1">Manage your connected applications and integrations</p>
        </div>
        <ConnectedAppsStrip
          connectedApps={connectedApps}
          allApps={apps}
          categories={categories}
          loading={loading}
          connecting={refreshing}
          onConnect={handleConnect}
          onDisconnect={handleDisconnect}
          onConfigure={handleConfigure}
          onSearchChange={setSearch}
          onCategoryChange={setSelectedCategory}
          search={search}
          selectedCategory={selectedCategory}
        />
      </div>

      <div className="flex flex-col lg:flex-row gap-6">
        <aside className="lg:w-64 flex-shrink-0 hidden lg:block">
          <Card className="h-full">
            <div className="p-4">
              <h3 className="font-semibold text-nexus-text mb-4">Filters</h3>
              <div className="space-y-4">
                <div>
                  <label className="block text-sm font-medium text-nexus-text-secondary mb-2">Search</label>
                  <div className="relative">
                    <Search className="absolute left-3 top-1/2 -translate-y-1/2 w-5 h-5 text-nexus-text-muted" />
                    <Input
                      placeholder="Search apps..."
                      value={search}
                      onChange={(e) => setSearch(e.target.value)}
                      className="pl-10"
                    />
                  </div>
                </div>

                <Separator />

                <div>
                  <label className="block text-sm font-medium text-nexus-text-secondary mb-2">Categories</label>
                  <div className="space-y-1.5 max-h-60 overflow-y-auto">
                    <Button
                      variant={!selectedCategory ? 'primary' : 'secondary'}
                      size="sm"
                      className="w-full justify-between"
                      onClick={() => setSelectedCategory('')}
                    >
                      All <span className="text-nexus-text-muted">({total})</span>
                    </Button>
                    {categories.map(cat => (
                      <Button
                        key={cat.id}
                        variant={selectedCategory === cat.id ? 'primary' : 'secondary'}
                        size="sm"
                        className="w-full justify-between"
                        onClick={() => setSelectedCategory(cat.id)}
                      >
                        {cat.name} <span className="text-nexus-text-muted">({cat.count})</span>
                      </Button>
                    ))}
                  </div>
                </div>

                <Separator />

                <div>
                  <label className="block text-sm font-medium text-nexus-text-secondary mb-2">Status</label>
                  <div className="space-y-1.5">
                    <Button
                      variant={selectedStatus === 'connected' ? 'primary' : 'secondary'}
                      size="sm"
                      className="w-full justify-between"
                      onClick={() => setSelectedStatus('connected')}
                    >
                      Connected <span className="text-nexus-text-muted">({connectedApps.length})</span>
                    </Button>
                    <Button
                      variant={selectedStatus === 'available' ? 'primary' : 'secondary'}
                      size="sm"
                      className="w-full justify-between"
                      onClick={() => setSelectedStatus('available')}
                    >
                      Available <span className="text-nexus-text-muted">({total - connectedApps.length})</span>
                    </Button>
                    <Button
                      variant={selectedStatus === 'error' ? 'primary' : 'secondary'}
                      size="sm"
                      className="w-full justify-between"
                      onClick={() => setSelectedStatus('error')}
                    >
                      Errors <span className="text-nexus-text-muted">({apps.filter(app => app.connectionStatus === 'error').length})</span>
                    </Button>
                  </div>
                </div>
              </div>
            </div>
          </Card>
        </aside>

        <main className="flex-1 min-w-0">
          <div className="flex items-center justify-between mb-4">
            <div className="flex items-center gap-2">
              <Button
                variant={viewMode === 'grid' ? 'primary' : 'secondary'}
                size="sm"
                onClick={() => setViewMode('grid')}
                aria-label="Grid view"
              >
                <Grid className="w-4 h-4" />
              </Button>
              <Button
                variant={viewMode === 'list' ? 'primary' : 'secondary'}
                size="sm"
                onClick={() => setViewMode('list')}
                aria-label="List view"
              >
                <List className="w-4 h-4" />
              </Button>
            </div>
            <div className="text-sm text-nexus-text-muted">
              {toolsLoading
                ? 'Loading available tools...'
                : toolsError
                  ? 'Unable to load available tools'
                  : `${availableTools.length} tools available`}
            </div>
          </div>

          {error && (
            <Card className="mb-4 border-nexus-danger/30 bg-red-500/5">
              <div className="flex items-center gap-2 text-nexus-danger p-4">
                <svg className="w-5 h-5" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
                  <circle cx="12" cy="12" r="10" />
                  <line x1="12" y1="8" x2="12" y2="12" />
                  <line x1="12" y1="16" x2="12.01" y2="16" />
                </svg>
                <span>{error.message || 'Something went wrong'}</span>
              </div>
            </Card>
          )}

          {loading ? (
            <Card className="h-[400px]">
              <div className="flex items-center justify-center h-full">
                <Loader2 className="w-8 h-8 animate-spin text-nexus-accent" />
              </div>
            </Card>
          ) : filteredApps.length === 0 ? (
            <Card className="h-[300px]">
              <div className="flex flex-col items-center justify-center h-full text-nexus-text-muted">
                <Box className="w-16 h-16 text-nexus-text-muted/50 mb-4" />
                <h3 className="text-lg font-medium text-nexus-text mb-1">No apps found</h3>
                <p className="text-sm">Try adjusting your filters or search</p>
              </div>
            </Card>
          ) : (
            <Card>
              <ScrollArea className={viewMode === 'grid' ? 'grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 xl:grid-cols-4 gap-4 p-4' : 'p-4 space-y-3'}>
                {filteredApps.map(app => (
                  <AppCard
                    key={app.app_id ?? app.id}
                    app={app}
                    onConnect={handleConnect}
                    onDisconnect={handleDisconnect}
                    onConfigure={handleConfigure}
                    connecting={refreshing}
                  />
                ))}
              </ScrollArea>
            </Card>
          )}

          <ConnectorConfigModal
            app={configuringApp}
            open={configuringApp !== null}
            onClose={() => setConfiguringApp(null)}
            onSubmit={handleConfigureSubmit}
            submitting={configuring}
          />

          <AppsDrawer
            open={drawerOpen}
            onClose={() => setDrawerOpen(false)}
            apps={apps}
            categories={categories}
            loading={loading}
            connecting={refreshing}
            onConnect={handleConnect}
            onDisconnect={handleDisconnect}
            onConfigure={handleConfigure}
            onSearchChange={setSearch}
            onCategoryChange={setSelectedCategory}
            search={search}
            selectedCategory={selectedCategory}
          />
        </main>
      </div>
    </div>
  );
}
