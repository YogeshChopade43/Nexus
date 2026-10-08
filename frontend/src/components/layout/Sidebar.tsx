import { NavLink, useLocation } from 'react-router-dom';
import { cn } from '../../lib/utils';
import {
  Bot,
  GitBranch,
  Server,
  Activity,
  BarChart3,
  Settings,
  ChevronLeft,
  ChevronRight,
} from 'lucide-react';
import { SidebarItem } from './SidebarItem';

interface SidebarProps {
  collapsed?: boolean;
  onToggleCollapse?: () => void;
}

export function Sidebar({ collapsed = false, onToggleCollapse }: SidebarProps) {
  const location = useLocation();

  const navigation = [
    { path: '/', label: 'Agent', icon: Bot, exact: true },
    { path: '/workflows', label: 'Workflows', icon: GitBranch },
    { path: '/servers', label: 'MCP Servers', icon: Server },
    { path: '/dashboard', label: 'Dashboard', icon: BarChart3 },
    { path: '/activity', label: 'Activity', icon: Activity },
    { path: '/settings', label: 'Settings', icon: Settings },
  ];

  return (
    <aside
      className={cn(
        'fixed left-0 top-0 z-40 h-full bg-nexus-bg-secondary border-r-nexus-border transition-all duration-300 ease-in-out flex flex-col',
        collapsed ? 'w-16' : 'w-64'
      )}
      aria-label="Main navigation"
    >
      <div className="flex items-center justify-between h-16 px-4 border-b-nexus-border border-b">
        {!collapsed && (
          <NavLink to="/" className="flex items-center gap-2" aria-label="Nexus Home">
            <div className="w-8 h-8 rounded-lg bg-nexus-accent flex items-center justify-center">
              <Bot className="w-5 h-5 text-nexus-bg" />
            </div>
            <span className="font-semibold text-lg text-nexus-text">Nexus</span>
          </NavLink>
        )}
        <button
          onClick={onToggleCollapse}
          className={cn(
            'p-1.5 rounded-lg text-nexus-text-secondary hover:text-nexus-text hover:bg-nexus-bg-tertiary transition-colors flex-shrink-0',
            collapsed && 'ml-auto'
          )}
          aria-label={collapsed ? 'Expand sidebar' : 'Collapse sidebar'}
          aria-expanded={!collapsed}
        >
          {collapsed ? <ChevronRight className="w-5 h-5" /> : <ChevronLeft className="w-5 h-5" />}
        </button>
      </div>

      <nav className="flex-1 px-3 py-4 space-y-1 overflow-y-auto" aria-label="Navigation">
        {navigation.map((item) => (
          <SidebarItem
            key={item.path}
            item={item}
            collapsed={collapsed}
            isActive={item.exact ? location.pathname === item.path : location.pathname.startsWith(item.path)}
          />
        ))}
      </nav>

      <div className="p-3 border-t-nexus-border border-t">
        {!collapsed && (
          <div className="text-xs text-nexus-text-muted text-center">
            Nexus v0.1.0
          </div>
        )}
      </div>
    </aside>
  );
}