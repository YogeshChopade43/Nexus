import { mcpService } from '../../services/mcp';
import { ragService } from '../../services/rag';

export interface MentionTarget {
  label: string;
  kind: 'app' | 'document';
}

/** The "@query" being typed just before the caret, if any (it starts at ``start``). */
export function mentionAt(text: string, caret: number): { start: number; query: string } | null {
  const match = /(^|\s)@([^\s@]*)$/.exec(text.slice(0, caret));
  return match ? { start: caret - match[2].length - 1, query: match[2] } : null;
}

/** Connected apps and ready documents, loaded once when someone first types "@". */
let loaded: Promise<MentionTarget[]> | null = null;
export function mentionTargets(): Promise<MentionTarget[]> {
  loaded ??= Promise.all([
    mcpService.list()
      .then(servers => servers.filter(s => s.enabled && s.status === 'connected').map(s => ({ label: s.name, kind: 'app' as const })))
      .catch(() => []),
    ragService.collections()
      .then(libraries => Promise.all(libraries.filter(l => l.kind === 'library' && l.ready > 0).map(l => ragService.documents(l.id))))
      .then(lists => lists.flat().filter(d => d.status === 'ready').map(d => ({ label: d.name, kind: 'document' as const })))
      .catch(() => []),
  ]).then(([apps, documents]) => [...apps, ...documents]);
  return loaded;
}

/** Targets matching the query, those starting with it first. */
export function matchTargets(targets: MentionTarget[], query: string, limit = 6): MentionTarget[] {
  const q = query.toLowerCase();
  const hits = targets.filter(t => t.label.toLowerCase().includes(q));
  return [...hits.filter(t => t.label.toLowerCase().startsWith(q)), ...hits.filter(t => !t.label.toLowerCase().startsWith(q))]
    .slice(0, limit);
}

/** ``text`` cut into plain parts and "@Name" mentions of ``labels`` (any case, whole names only; longest name wins). */
export function splitMentions(text: string, labels: string[]): Array<{ text: string; mention: boolean }> {
  const names = [...new Set(labels.filter(Boolean))].sort((a, b) => b.length - a.length)
    .map(label => label.replace(/[.*+?^${}()|[\]\\]/g, '\\$&'));
  if (!names.length || !text.includes('@')) return [{ text, mention: false }];
  const parts: Array<{ text: string; mention: boolean }> = [];
  let last = 0;
  for (const match of text.matchAll(new RegExp(`@(?:${names.join('|')})(?![\\w])`, 'gi'))) {
    if (match.index > last) parts.push({ text: text.slice(last, match.index), mention: false });
    parts.push({ text: match[0], mention: true });
    last = match.index + match[0].length;
  }
  if (last < text.length) parts.push({ text: text.slice(last), mention: false });
  return parts;
}
