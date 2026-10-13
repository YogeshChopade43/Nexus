import { listApps } from '../../services/integrations';
import { useEffect, useState } from 'react';
import { humanize } from '../workflow/toolInfo';
import { iconUrl } from '../../services/marketplace';

/** How well-known apps are written; others get their first letter capitalised. */
const BRANDS: Record<string, string> = {
  github: 'GitHub', gitlab: 'GitLab', hubspot: 'HubSpot', paypal: 'PayPal', circleci: 'CircleCI',
  huggingface: 'Hugging Face', mongodb: 'MongoDB', posthog: 'PostHog', youtube: 'YouTube', nexus: 'Nexus',
};

/** "github__search_repositories" -> GitHub / "Search repositories"; "notion_2__notion-search" -> Notion / "Search". */
export function toolParts(name: string): { app: string; action: string } {
  const [rawServer, rawTool] = name.includes('__') ? name.split('__', 2) : ['nexus', name.replace(/^nexus_/, '')];
  const server = rawServer.replace(/_\d+$/, '');  // a second server of the same app ("notion_2")
  const tool = rawTool.replace(new RegExp(`^${server}[-_]`, 'i'), '');  // "notion-search" repeats the app
  const app = BRANDS[server.toLowerCase()] ?? server.charAt(0).toUpperCase() + server.slice(1);
  return { app, action: humanize(tool) };
}

/** Server slug -> its Marketplace listing, for logos (one request, shared by every tool step). */
let listings: Promise<Record<string, string>> | null = null;
function registryNames(): Promise<Record<string, string>> {
  listings ??= listApps()
    .then(servers => Object.fromEntries(servers.filter(s => s.registry_name).map(s => [s.slug, s.registry_name as string])))
    .catch(() => ({}));
  return listings;
}

/** A tool as people read it: the app's logo and name, then what it does. */
export function ToolName({ name }: { name: string }) {
  const { app, action } = toolParts(name);
  const slug = name.includes('__') ? name.split('__')[0] : '';
  const [logo, setLogo] = useState<string | null>(null);

  useEffect(() => {
    let alive = true;
    if (slug) void registryNames().then(names => { if (alive && names[slug]) setLogo(iconUrl(names[slug])); });
    return () => { alive = false; };
  }, [slug]);

  return (
    <span title={name} className="inline-flex items-center gap-1.5 min-w-0">
      {logo && <img src={logo} alt="" className="w-4 h-4 rounded-sm object-contain flex-shrink-0" onError={() => setLogo(null)} />}
      <span className="font-medium text-nexus-text">{app}</span>
      <span className="text-nexus-text-muted">·</span>
      <span className="truncate">{action}</span>
    </span>
  );
}
