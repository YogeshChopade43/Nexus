import { NavLink, useLocation } from 'react-router-dom';
import { cn } from '../../lib/utils';
import {
  Activity, BarChart3, BookOpen, Bot, GitBranch, PanelLeftClose, Repeat1, PanelLeftOpen, Settings, Store,
} from 'lucide-react';
import type { ComponentType } from 'react';
import { SidebarItem } from './SidebarItem';

export interface NavItem {
  path: string;
  label: string;
  icon: ComponentType<{ className?: string }>;
  exact?: boolean;
}

export const NAV_SECTIONS: Array<{ title: string; items: NavItem[] }> = [
  {
    title: 'Workspace',
    items: [
      { path: '/', label: 'Agent', icon: Bot, exact: true },
      { path: '/workflows', label: 'Workflows', icon: GitBranch },
      { path: '/knowledge', label: 'Knowledge', icon: BookOpen },
      { path: '/servers', label: 'Marketplace', icon: Store },
      { path: '/run-once', label: 'Run once', icon: Repeat1 },
    ],
  },
  {
    title: 'Insights',
    items: [
      { path: '/dashboard', label: 'Dashboard', icon: BarChart3 },
      { path: '/activity', label: 'Activity', icon: Activity },
    ],
  },
];

export const SETTINGS_ITEM: NavItem = { path: '/settings', label: 'Settings', icon: Settings };

export const isActivePath = (item: NavItem, pathname: string) =>
  item.exact ? pathname === item.path : pathname.startsWith(item.path);

/** The Nexus mark: a violet tile with the "connected points" glyph. */
/** The Nexus AI signal mark: strokes in the text colour (light and dark themes), the last node in brand blue. */
export function Logo({ className }: { className?: string }) {
  return (
    <svg viewBox="12 18 96 76" className={cn('shrink-0 text-nexus-text', className)} aria-hidden>
      <g fill="none" stroke="currentColor" strokeWidth="5" strokeLinecap="round" strokeLinejoin="round">
        <path d="M25.33 81.01L42.67 54.99M50.88 53.49L69.12 66.51M76.98 64.79L94.03 34.95" />
        <circle cx="22" cy="86" r="6" />
        <circle cx="46" cy="50" r="6" />
        <circle cx="74" cy="70" r="6" />
        <circle cx="98" cy="28" r="8" fill="#3B5BFF" stroke="#3B5BFF" />
      </g>
    </svg>
  );
}

interface SidebarProps {
  collapsed: boolean;
  mobileOpen: boolean;
  onToggleCollapse: () => void;
}

export function Sidebar({ collapsed, mobileOpen, onToggleCollapse }: SidebarProps) {
  const { pathname } = useLocation();
  // On a phone the sidebar slides in over the page, always full width.
  const narrow = collapsed && !mobileOpen;

  return (
    <aside
      className={cn(
        'fixed inset-y-0 left-0 z-40 flex flex-col border-r border-nexus-border bg-nexus-bg transition-[width,transform] duration-200 ease-out',
        narrow ? 'w-14' : 'w-60',
        mobileOpen ? 'translate-x-0 shadow-pop' : '-translate-x-full lg:translate-x-0',
      )}
      aria-label="Main navigation"
    >
      <div className={cn('flex h-14 shrink-0 items-center gap-2 px-3', narrow && 'justify-center px-0')}>
        <NavLink to="/" className="flex min-w-0 items-center gap-2.5 rounded-md hover:no-underline" aria-label="Nexus Home">
          <Logo className="h-7 w-7 shrink-0" />
          {!narrow && (
            <span className="truncate font-brand text-[16px] tracking-tight text-nexus-text">
              <span className="font-semibold">Nexus</span> <span className="font-light">AI</span>
            </span>
          )}
        </NavLink>
        {!narrow && (
          <button
            onClick={onToggleCollapse}
            className="ml-auto hidden rounded-md p-1.5 text-nexus-text-muted transition-colors hover:bg-nexus-bg-tertiary hover:text-nexus-text lg:inline-flex"
            aria-label="Collapse sidebar"
            aria-expanded
          >
            <PanelLeftClose className="h-4 w-4" />
          </button>
        )}
      </div>

      <nav className="flex-1 space-y-5 overflow-y-auto px-2 pb-4 pt-2" aria-label="Navigation">
        {NAV_SECTIONS.map(section => (
          <div key={section.title} className="space-y-0.5">
            {!narrow && (
              <p className="px-2.5 pb-1 text-[11px] font-medium uppercase tracking-wider text-nexus-text-muted">{section.title}</p>
            )}
            {section.items.map(item => (
              <SidebarItem key={item.path} item={item} collapsed={narrow} isActive={isActivePath(item, pathname)} />
            ))}
          </div>
        ))}
      </nav>

      <div className="space-y-0.5 border-t border-nexus-border p-2">
        <SidebarItem item={SETTINGS_ITEM} collapsed={narrow} isActive={isActivePath(SETTINGS_ITEM, pathname)} />
        {narrow ? (
          <button
            onClick={onToggleCollapse}
            className="hidden w-full items-center justify-center rounded-md py-2 text-nexus-text-muted transition-colors hover:bg-nexus-bg-tertiary hover:text-nexus-text lg:flex"
            aria-label="Expand sidebar"
            aria-expanded={false}
          >
            <PanelLeftOpen className="h-4 w-4" />
          </button>
        ) : (
          <p className="px-2.5 pt-1.5 text-[11px] text-nexus-text-muted">Self-hosted · your data stays here</p>
        )}
      </div>
    </aside>
  );
}
