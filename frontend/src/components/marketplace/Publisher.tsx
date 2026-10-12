import { useState } from 'react';
import { BadgeCheck, ShieldCheck } from 'lucide-react';
import { cn } from '../../lib/utils';
import { iconUrl } from '../../services/marketplace';
import type { MarketCard } from '../../types/marketplace';

/** The listing's logo (served and cached by the backend), or its first letter when there is none. */
export function Logo({ card, className }: { card: MarketCard; className?: string }) {
  const [failed, setFailed] = useState(false);
  if (card.name && !failed) {
    return <img src={iconUrl(card.name)} alt="" loading="lazy" onError={() => setFailed(true)}
      className={cn('rounded-lg object-contain flex-shrink-0 bg-white/5', className)} />;
  }
  return (
    <span aria-hidden className={cn('rounded-lg bg-nexus-accent/15 text-nexus-accent-text font-semibold flex items-center justify-center flex-shrink-0', className)}>
      {card.title.charAt(0).toUpperCase()}
    </span>
  );
}

/** "Official": from the app maker's own verified domain. "Verified domain": the publisher owns that domain. */
export function PublisherBadge({ card }: { card: MarketCard }) {
  if (card.official) {
    return (
      <span title={`Published from ${card.publisher}, the maker of this app (matched automatically)`}
        className="px-1.5 py-0.5 rounded bg-blue-500/15 text-blue-500 inline-flex items-center gap-1">
        <BadgeCheck className="w-3 h-3" /> Official
      </span>
    );
  }
  if (card.verified) {
    return (
      <span title={`The publisher proved to the MCP Registry that they own ${card.publisher}`}
        className="px-1.5 py-0.5 rounded bg-nexus-bg-tertiary text-nexus-text-secondary inline-flex items-center gap-1">
        <ShieldCheck className="w-3 h-3" /> Verified domain
      </span>
    );
  }
  return null;
}
