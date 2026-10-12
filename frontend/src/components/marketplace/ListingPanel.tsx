import { useCallback, useEffect, useState } from 'react';
import { ExternalLink } from 'lucide-react';
import { Modal } from '../ui/Modal';
import { getErrorMessage } from '../../lib/utils';
import { marketplaceService } from '../../services/marketplace';
import { mcpService } from '../../services/mcp';
import type { MarketCard, MarketItem } from '../../types/marketplace';
import type { McpServer } from '../../types/mcp';
import { InstalledServer } from './InstalledServer';
import { InstallForm } from './InstallForm';
import { Logo, PublisherBadge } from './Publisher';

/** One listing: what it is, then either its install form or the controls of the installed server.
 *  Cards with no registry name are custom servers: only their controls. */
export function ListingPanel({ card, onClose, onChanged }: { card: MarketCard; onClose: () => void; onChanged: () => void }) {
  const [item, setItem] = useState<MarketItem | null>(null);
  const [custom, setCustom] = useState<McpServer | null>(null);
  const [error, setError] = useState<string | null>(null);

  const load = useCallback(async () => {
    try {
      if (card.name) setItem(await marketplaceService.item(card.name));
      else if (card.installed_server_id !== null) setCustom(await mcpService.get(card.installed_server_id));
      setError(null);
    } catch (err) {
      setError(getErrorMessage(err));
    }
  }, [card]);

  useEffect(() => { void load(); }, [load]);

  const changed = (server: McpServer | null) => {
    onChanged();
    if (server === null && !card.name) onClose();  // a removed custom server has nothing left to show
    else void load();
  };

  const installed = item?.installed ?? custom;
  return (
    <Modal open onClose={onClose} title={card.title} size="lg">
      <div className="space-y-4">
        <div className="space-y-1">
          <div className="flex items-center gap-3">
            <Logo card={card} className="w-12 h-12" />
            <div className="min-w-0 space-y-1">
              <p className="text-xs text-nexus-text-muted">
                {card.publisher}{item?.version ? ` · v${item.version}` : ''}
              </p>
              <div className="text-xs"><PublisherBadge card={card} /></div>
              {card.name && (
                <p className="text-xs text-nexus-text-muted font-mono break-all" title="ID in the official MCP Registry">
                  {card.name}
                </p>
              )}
            </div>
          </div>
          {card.description && <p className="text-sm text-nexus-text-secondary">{card.description}</p>}
          {item && (item.repository_url || item.website_url) && (
            <div className="flex flex-wrap gap-3 text-xs">
              {item.repository_url && <a href={item.repository_url} target="_blank" rel="noreferrer" className="inline-flex items-center gap-1 text-nexus-accent-text hover:underline">Source <ExternalLink className="w-3 h-3" /></a>}
              {item.website_url && <a href={item.website_url} target="_blank" rel="noreferrer" className="inline-flex items-center gap-1 text-nexus-accent-text hover:underline">Website <ExternalLink className="w-3 h-3" /></a>}
            </div>
          )}
        </div>
        {error && <p role="alert" className="text-sm text-nexus-danger">{error}</p>}
        {installed ? (
          <InstalledServer server={installed} onChanged={changed} />
        ) : item ? (
          <InstallForm item={item} onInstalled={(server) => changed(server)} />
        ) : !error && <p className="text-sm text-nexus-text-muted">Loading…</p>}
      </div>
    </Modal>
  );
}
