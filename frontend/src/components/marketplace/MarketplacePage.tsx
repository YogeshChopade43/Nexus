import { useSearchParams } from 'react-router-dom';
import { BuiltInSection, IntegrationModal } from './BuiltIn';
import { integrationService, type Integration, type IntegrationKind } from '../../services/integrations';
import { EmptyState, PageHeader, SegmentedControl } from '../ui/PageHeader';
import { fieldClass } from '../ui/Input';
import { useCallback, useEffect, useRef, useState } from 'react';
import { AlertCircle, Plus, RefreshCw, Search, Upload, Store } from 'lucide-react';
import { Button } from '../ui/Button';
import { cn, formatRelativeTime, getErrorMessage } from '../../lib/utils';
import { marketplaceService, PAGE_SIZE } from '../../services/marketplace';
import type { MarketCard, MarketKind, MarketSort, SyncStatus } from '../../types/marketplace';
import { ImportModal } from './ImportModal';
import { Logo, PublisherBadge } from './Publisher';
import { ListingPanel } from './ListingPanel';
import { ServerFormModal } from './ServerFormModal';

const KINDS: { id: MarketKind; label: string }[] = [
  { id: 'all', label: 'All' },
  { id: 'installed', label: 'Installed' },
];
const STATUS_DOTS: Record<string, string> = {
  connected: 'bg-green-500', connecting: 'bg-blue-500', needs_auth: 'bg-amber-500', error: 'bg-red-500', stopped: 'bg-gray-400',
};

function StatusLine({ status }: { status: SyncStatus | null }) {
  if (!status) return null;
  if (status.status === 'syncing') return <span>Syncing… {status.count} servers</span>;
  if (status.status === 'error') {
    return <span className="text-nexus-danger flex items-center gap-1"><AlertCircle className="w-3.5 h-3.5" />Couldn't reach the MCP Registry: {status.error}</span>;
  }
  return <span>{status.count} servers{status.last_synced_at ? ` · updated ${formatRelativeTime(status.last_synced_at)}` : ''}</span>;
}

function ServerCard({ card, onOpen }: { card: MarketCard; onOpen: () => void }) {
  return (
    <button type="button" onClick={onOpen}
      className="group flex min-w-0 gap-3 rounded-xl border border-nexus-border bg-nexus-bg-secondary p-4 text-left shadow-surface transition-[border-color,background-color,transform] duration-150 hover:-translate-y-px hover:border-nexus-border-hover hover:bg-nexus-bg-tertiary/40">
      <Logo card={card} className="h-10 w-10" />
      <span className="min-w-0 flex-1">
        <span className="block truncate text-[13px] font-semibold text-nexus-text">{card.title}</span>
        <span className="block truncate text-xs text-nexus-text-muted">{card.publisher}</span>
        <span className="mt-1.5 line-clamp-2 block text-[13px] leading-snug text-nexus-text-secondary">{card.description}</span>
        <span className="mt-2.5 flex flex-wrap gap-1.5 text-xs">
          <PublisherBadge card={card} />
          {card.installed_server_id !== null && (
            <span className="inline-flex items-center gap-1 rounded-md bg-nexus-success/10 px-1.5 py-px text-[11px] font-medium text-green-700 ring-1 ring-inset ring-nexus-success/25 dark:text-green-400">
              {card.status && <span role="img" aria-label={`Status: ${card.status}`} title={card.status} className={cn('w-1.5 h-1.5 rounded-full', STATUS_DOTS[card.status])} />}
              Installed
            </span>
          )}
        </span>
      </span>
    </button>
  );
}

/** Browse and install MCP servers from the official MCP Registry; installed servers are managed here too. */
export function MarketplacePage() {
  const [query, setQuery] = useState('');
  const [searched, setSearched] = useState('');
  const [kind, setKind] = useState<MarketKind>('all');
  const [sort, setSort] = useState<MarketSort>('relevance');
  const [official, setOfficial] = useState(false);
  const [items, setItems] = useState<MarketCard[]>([]);
  const [featured, setFeatured] = useState<MarketCard[]>([]);
  const [more, setMore] = useState(false);
  const [status, setStatus] = useState<SyncStatus | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [selected, setSelected] = useState<MarketCard | null>(null);
  const [adding, setAdding] = useState(false);
  const [importing, setImporting] = useState(false);
  // Built-in integrations (email, calendar feeds, RSS...): listed above the MCP Registry.
  const [kinds, setKinds] = useState<IntegrationKind[]>([]);
  const [integrations, setIntegrations] = useState<Integration[]>([]);
  const [openKind, setOpenKind] = useState<IntegrationKind | null>(null);
  const loadIntegrations = useCallback(() => {
    integrationService.list().then(setIntegrations).catch(() => {});
  }, []);
  const [params, setParams] = useSearchParams();
  useEffect(() => {
    integrationService.kinds().then(found => {
      setKinds(found);
      // A link like /servers?connect=telegram (from the getting-started guide) opens that one straight away.
      const wanted = found.find(k => k.id === params.get('connect'));
      if (wanted) {
        setOpenKind(wanted);
        setParams({}, { replace: true });
      }
    }).catch(() => {});
    loadIntegrations();
  }, [loadIntegrations]);  // once, on arrival

  useEffect(() => {
    const timer = setTimeout(() => setSearched(query.trim()), 300);
    return () => clearTimeout(timer);
  }, [query]);

  const latestRequest = useRef(0);
  const listedCount = useRef<number | null>(null);  // registry size when the list was last loaded

  const load = useCallback(async (offset: number) => {
    const request = ++latestRequest.current;
    setLoading(true);
    try {
      const page = await marketplaceService.list({ q: searched, kind, sort, offset, official });
      if (request !== latestRequest.current) return;  // a newer search or filter has been asked for since
      listedCount.current = page.status.count;
      setItems(current => (offset ? [...current, ...page.items] : page.items));
      setMore(page.items.length === PAGE_SIZE);
      setStatus(page.status);
      setError(null);
    } catch (err) {
      if (request === latestRequest.current) setError(getErrorMessage(err));
    } finally {
      if (request === latestRequest.current) setLoading(false);
    }
  }, [searched, kind, sort, official]);

  useEffect(() => { void load(0); }, [load]);

  const loadFeatured = useCallback(() => {
    marketplaceService.featured().then(r => setFeatured(r.items)).catch(() => setFeatured([]));
  }, []);
  useEffect(loadFeatured, [loadFeatured]);
  // The shelf belongs to the plain front page, not to searches or filtered views.
  const showFeatured = featured.length > 0 && !searched && kind === 'all' && !official && sort === 'relevance';

  // While a sync runs, follow its progress; reload the list as listings arrive and when it ends.
  useEffect(() => {
    if (status?.status !== 'syncing') return;
    const timer = setInterval(() => {
      marketplaceService.status().then(next => {
        setStatus(next);
        if (next.status !== 'syncing' || next.count !== listedCount.current) void load(0);
      }).catch(() => {});
    }, 3000);
    return () => clearInterval(timer);
  }, [status?.status, load]);

  const refreshCard = (changed: MarketCard) => {
    if (!changed.name) { void load(0); return; }  // custom servers: only in the Installed view
    marketplaceService.item(changed.name).then(item => {
      const update = (c: MarketCard) => (c.name === item.name
        ? { ...c, installed_server_id: item.installed_server_id, status: item.status } : c);
      setItems(list => list.map(update));
      setFeatured(list => list.map(update));
    }).catch(() => {});
  };

  const refresh = async () => {
    try {
      await marketplaceService.refresh();
      setStatus(s => ({ ...(s ?? { count: 0, last_synced_at: null, error: null }), status: 'syncing', error: null }));
    } catch (err) {
      setError(getErrorMessage(err));
    }
  };

  return (
    <div className="space-y-5">
      <PageHeader title="Marketplace"
        description="Hosted MCP servers from verified publishers in the official MCP Registry. Installed servers give their tools to the agent and to workflows."
        actions={<>
          <Button variant="secondary" size="sm" onClick={() => setImporting(true)}><Upload className="w-3.5 h-3.5" /> Import config</Button>
          <Button variant="secondary" size="sm" onClick={() => setAdding(true)}><Plus className="w-3.5 h-3.5" /> Add custom server</Button>
        </>} />

      <div className="space-y-3">
        <div className="flex flex-col sm:flex-row gap-2">
          <div className="relative flex-1">
            <Search className="w-4 h-4 absolute left-3 top-1/2 -translate-y-1/2 text-nexus-text-muted" />
            <input value={query} onChange={(e) => setQuery(e.target.value)} aria-label="Search servers" placeholder="Search apps: Notion, GitHub, Stripe…"
              className={cn(fieldClass, 'pl-9')} />
          </div>
          <select value={sort} onChange={(e) => setSort(e.target.value as MarketSort)} aria-label="Sort"
            className={cn(fieldClass, 'sm:w-48')}>
            <option value="relevance">Best match</option>
            <option value="updated">Recently updated</option>
          </select>
        </div>
        <div className="flex flex-wrap items-center gap-2 justify-between">
          <div className="flex flex-wrap items-center gap-3">
            <SegmentedControl label="Show" value={kind} onChange={setKind} options={KINDS.map(k => ({ value: k.id, label: k.label }))} />
            <label className="flex items-center gap-1.5 text-[13px] text-nexus-text-secondary"
              title="From the app maker's own verified domain (matched automatically)">
              <input type="checkbox" checked={official} onChange={(e) => setOfficial(e.target.checked)} />
              Official only
            </label>
          </div>
          <div className="flex items-center gap-2 text-xs text-nexus-text-muted">
            <StatusLine status={status} />
            <Button variant="ghost" size="sm" onClick={() => void refresh()} disabled={status?.status === 'syncing'} className="gap-1">
              <RefreshCw className={cn('w-3.5 h-3.5', status?.status === 'syncing' && 'animate-spin')} /> Refresh
            </Button>
          </div>
        </div>
      </div>

      {error && <p role="alert" className="text-sm text-nexus-danger">{error}</p>}

      {!searched && !official && (
        <BuiltInSection onOpen={setOpenKind} integrations={integrations}
          kinds={kind === 'installed' ? kinds.filter(k => integrations.some(i => i.kind === k.id)) : kinds} />
      )}
      {openKind && (
        <IntegrationModal kind={openKind} integrations={integrations} onClose={() => setOpenKind(null)} onChanged={loadIntegrations} />
      )}

      {showFeatured && (
        <section aria-label="Featured" className="space-y-2">
          <h2 className="text-xs font-medium uppercase tracking-wider text-nexus-text-muted">Featured</h2>
          <div className="grid gap-3 sm:grid-cols-2 xl:grid-cols-3">
            {featured.map(card => <ServerCard key={card.name} card={card} onOpen={() => setSelected(card)} />)}
          </div>
          <h2 className="pt-4 text-xs font-medium uppercase tracking-wider text-nexus-text-muted">All servers</h2>
        </section>
      )}

      {items.length === 0 && !loading ? (
        <EmptyState icon={kind === 'installed' ? Store : Search}
          title={status?.status === 'syncing' && status.count === 0
            ? 'Downloading the MCP Registry for the first time…'
            : kind === 'installed' ? 'No servers installed yet' : 'No servers match'}
          description={kind === 'installed' ? 'Install one from All to give the agent and workflows its tools.' : 'Try another name, or turn off "Official only".'} />
      ) : (
        <div className="grid gap-3 sm:grid-cols-2 xl:grid-cols-3">
          {items.map(card => (
            <ServerCard key={card.name ?? `server-${card.installed_server_id}`} card={card} onOpen={() => setSelected(card)} />
          ))}
        </div>
      )}
      {more && (
        <div className="text-center">
          <Button variant="secondary" size="sm" onClick={() => void load(items.length)} disabled={loading}>Load more</Button>
        </div>
      )}

      {selected && <ListingPanel card={selected} onClose={() => setSelected(null)} onChanged={() => refreshCard(selected)} />}
      <ServerFormModal open={adding} server={null} onClose={() => setAdding(false)}
        onSaved={() => { setAdding(false); setKind('installed'); void load(0); }} />
      <ImportModal open={importing} onClose={() => setImporting(false)} onImported={() => void load(0)} />
    </div>
  );
}
