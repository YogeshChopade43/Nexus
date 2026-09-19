import { NavLink } from 'react-router-dom';
import { cn } from '../../lib/utils';
import type { ComponentType } from 'react';
import { Tooltip } from '../ui/Tooltip';

interface SidebarItemProps {
  item: {
    path: string;
    label: string;
    icon: ComponentType<{ className?: string }>;
    exact?: boolean;
  };
  collapsed: boolean;
  isActive: boolean;
}

export function SidebarItem({ item, collapsed, isActive }: SidebarItemProps) {
  const Icon = item.icon;

  const linkContent = (
    <NavLink
      to={item.path}
      className={cn(
        'flex items-center gap-3 px-3 py-2.5 rounded-lg transition-all duration-150',
        'focus:outline-none focus:ring-2 focus:ring-nexus-accent focus:ring-offset-2 focus:ring-offset-nexus-bg',
        isActive
          ? 'bg-nexus-accent-dim text-nexus-accent'
          : 'text-nexus-text-secondary hover:bg-nexus-bg-tertiary hover:text-nexus-text'
      )}
      aria-current={isActive ? 'page' : undefined}
      title={collapsed ? item.label : undefined}
    >
      <Icon className="w-5 h-5 flex-shrink-0" aria-hidden="true" />
      {!collapsed && <span className="font-medium truncate">{item.label}</span>}
    </NavLink>
  );

  if (collapsed) {
    return (
      <Tooltip content={item.label} position="right">
        {linkContent}
      </Tooltip>
    );
  }

  return linkContent;
}
