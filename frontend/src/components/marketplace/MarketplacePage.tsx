import { useCallback, useEffect, useRef, useState } from 'react';
import { AlertCircle, Plus, RefreshCw, Search, Upload } from 'lucide-react';
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
      className="text-left rounded-xl border border-nexus-border bg-nexus-bg-secondary p-4 hover:border-nexus-accent transition-colors flex gap-3 min-w-0">
      <Logo card={card} className="w-10 h-10" />
      <span className="min-w-0 flex-1">
        <span className="block font-medium text-nexus-text truncate">{card.title}</span>
        <span className="block text-xs text-nexus-text-muted truncate">{card.publisher}</span>
        <span className="block text-sm text-nexus-text-secondary mt-1 line-clamp-2">{card.description}</span>
        <span className="flex flex-wrap gap-1.5 mt-2 text-xs">
          <PublisherBadge card={card} />
          {card.installed_server_id !== null && (
            <span className="px-1.5 py-0.5 rounded bg-green-500/15 text-green-500 inline-flex items-center gap-1">
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
      <div className="flex flex-col sm:flex-row sm:items-start justify-between gap-4">
        <div>
          <h1 className="text-2xl font-bold text-nexus-text">Marketplace</h1>
          <p className="text-nexus-text-secondary mt-1">
            Hosted MCP servers from verified publishers in the official MCP Registry. Installed servers give their tools to the agent and to workflows.
          </p>
        </div>
        <div className="flex flex-wrap gap-2">
          <Button variant="secondary" className="gap-1.5" onClick={() => setImporting(true)}><Upload className="w-4 h-4" /> Import config</Button>
          <Button variant="secondary" className="gap-1.5" onClick={() => setAdding(true)}><Plus className="w-4 h-4" /> Add custom server</Button>
        </div>
      </div>

      <div className="space-y-3">
        <div className="flex flex-col sm:flex-row gap-2">
          <div className="relative flex-1">
            <Search className="w-4 h-4 absolute left-3 top-1/2 -translate-y-1/2 text-nexus-text-muted" />
            <input value={query} onChange={(e) => setQuery(e.target.value)} aria-label="Search servers" placeholder="Search servers"
              className="w-full pl-9 pr-3 py-2 rounded-lg bg-nexus-bg-secondary border border-nexus-border text-nexus-text placeholder-nexus-text-muted focus:outline-none focus:ring-2 focus:ring-nexus-accent" />
          </div>
          <select value={sort} onChange={(e) => setSort(e.target.value as MarketSort)} aria-label="Sort"
            className="px-3 py-2 rounded-lg bg-nexus-bg-secondary border border-nexus-border text-nexus-text">
            <option value="relevance">Best match</option>
            <option value="updated">Recently updated</option>
          </select>
        </div>
        <div className="flex flex-wrap items-center gap-2 justify-between">
          <div role="radiogroup" aria-label="Show" className="flex flex-wrap gap-1.5">
            {KINDS.map(k => (
              <button key={k.id} type="button" role="radio" aria-checked={kind === k.id} onClick={() => setKind(k.id)}
                className={cn('px-3 py-1 rounded-full text-sm border', kind === k.id
                  ? 'bg-nexus-accent text-white border-nexus-accent'
                  : 'border-nexus-border text-nexus-text-secondary hover:text-nexus-text')}>
                {k.label}
              </button>
            ))}
            <label className="flex items-center gap-1.5 text-sm text-nexus-text-secondary ml-1"
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

      {showFeatured && (
        <section aria-label="Featured" className="space-y-2">
          <h2 className="text-sm font-semibold text-nexus-text">Featured</h2>
          <div className="grid gap-3 sm:grid-cols-2 xl:grid-cols-3">
            {featured.map(card => <ServerCard key={card.name} card={card} onOpen={() => setSelected(card)} />)}
          </div>
          <h2 className="text-sm font-semibold text-nexus-text pt-3">All servers</h2>
        </section>
      )}

      {items.length === 0 && !loading ? (
        <p className="text-sm text-nexus-text-muted text-center py-10">
          {status?.status === 'syncing' && status.count === 0
            ? 'Downloading the MCP Registry for the first time…'
            : kind === 'installed' ? 'No servers installed yet.' : 'No servers match.'}
        </p>
      ) : (
        <div className="grid gap-3 sm:grid-cols-2 xl:grid-cols-3">
          {items.map(card => (
            <ServerCard key={card.name ?? `server-${card.installed_server_id}`} card={card} onOpen={() => setSelected(card)} />
          ))}
        </div>
      )}
      {more && (
        <div className="text-center">
          <Button variant="secondary" onClick={() => void load(items.length)} disabled={loading}>Load more</Button>
        </div>
      )}

      {selected && <ListingPanel card={selected} onClose={() => setSelected(null)} onChanged={() => refreshCard(selected)} />}
      <ServerFormModal open={adding} server={null} onClose={() => setAdding(false)}
        onSaved={() => { setAdding(false); setKind('installed'); void load(0); }} />
      <ImportModal open={importing} onClose={() => setImporting(false)} onImported={() => void load(0)} />
    </div>
  );
}
