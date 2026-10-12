import { NavLink } from 'react-router-dom';
import { cn } from '../../lib/utils';
import { Tooltip } from '../ui/Tooltip';
import type { NavItem } from './Sidebar';

interface SidebarItemProps {
  item: NavItem;
  collapsed: boolean;
  isActive: boolean;
}

export function SidebarItem({ item, collapsed, isActive }: SidebarItemProps) {
  const Icon = item.icon;

  const link = (
    <NavLink
      to={item.path}
      className={cn(
        'group flex h-8 items-center gap-2.5 rounded-md px-2.5 text-[13px] font-medium transition-colors hover:no-underline',
        collapsed && 'w-10 justify-center px-0',
        isActive
          ? 'bg-nexus-bg-tertiary text-nexus-text'
          : 'text-nexus-text-secondary hover:bg-nexus-bg-tertiary/60 hover:text-nexus-text',
      )}
      aria-current={isActive ? 'page' : undefined}
      aria-label={collapsed ? item.label : undefined}
    >
      <Icon className={cn('h-4 w-4 shrink-0 transition-colors', isActive ? 'text-nexus-accent-text' : 'text-nexus-text-muted group-hover:text-nexus-text-secondary')} aria-hidden="true" />
      {!collapsed && <span className="truncate">{item.label}</span>}
    </NavLink>
  );

  return collapsed ? <Tooltip content={item.label} position="right">{link}</Tooltip> : link;
}
