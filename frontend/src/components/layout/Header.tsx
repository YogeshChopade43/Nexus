import { useLocation } from 'react-router-dom';
import { Menu, Sun, Moon, Monitor, Search } from 'lucide-react';
import { Button } from '../ui/Button';
import { Dropdown, DropdownItem } from '../ui/Dropdown';
import { useSettings } from '../../hooks/useSettings';
import { NotificationBell } from './NotificationBell';
import { OPEN_SEARCH_EVENT } from './CommandPalette';
import { NAV_SECTIONS, SETTINGS_ITEM, isActivePath } from './Sidebar';

interface HeaderProps {
  onMenuClick?: () => void;
}

/** The top bar: where you are, search (Ctrl+K), theme and notifications. */
export function Header({ onMenuClick }: HeaderProps) {
  const { theme, setTheme } = useSettings();
  const { pathname } = useLocation();
  const page = [...NAV_SECTIONS.flatMap(s => s.items), SETTINGS_ITEM].find(item => isActivePath(item, pathname));
  const PageIcon = page?.icon;

  const themeOptions: DropdownItem[] = [
    { label: 'Dark', icon: <Moon className="w-4 h-4" />, onClick: () => setTheme('dark') },
    { label: 'Light', icon: <Sun className="w-4 h-4" />, onClick: () => setTheme('light') },
    { label: 'System', icon: <Monitor className="w-4 h-4" />, onClick: () => setTheme('system') },
  ];
  const ThemeIcon = theme === 'light' ? Sun : theme === 'system' ? Monitor : Moon;

  return (
    <header
      className="sticky top-0 z-30 flex h-14 items-center gap-3 border-b border-nexus-border bg-nexus-bg/80 px-4 backdrop-blur-md supports-[backdrop-filter]:bg-nexus-bg/70 lg:px-6"
      role="banner"
    >
      <Button variant="ghost" size="sm" onClick={onMenuClick} className="w-8 px-0 lg:hidden" aria-label="Open menu">
        <Menu className="h-4 w-4" />
      </Button>
      {page && PageIcon && (
        <div className="flex min-w-0 items-center gap-2 text-[13px]">
          <PageIcon className="h-4 w-4 shrink-0 text-nexus-text-muted" aria-hidden />
          <span className="truncate font-medium text-nexus-text">{page.label}</span>
        </div>
      )}

      <div className="ml-auto flex items-center gap-1">
        <button
          type="button"
          aria-label="Search (Ctrl+K)"
          title="Search (Ctrl+K)"
          onClick={() => window.dispatchEvent(new Event(OPEN_SEARCH_EVENT))}
          className="mr-1 flex h-8 items-center gap-2 rounded-md border border-nexus-border bg-nexus-bg-secondary px-2.5 text-[13px] text-nexus-text-muted shadow-surface transition-colors hover:border-nexus-border-hover hover:text-nexus-text-secondary md:w-60"
        >
          <Search className="h-3.5 w-3.5" />
          <span className="hidden md:inline">Search…</span>
          <kbd className="ml-auto hidden rounded border border-nexus-border bg-nexus-bg-tertiary px-1.5 py-px text-[10px] font-medium text-nexus-text-muted md:inline">Ctrl K</kbd>
        </button>
        <Dropdown
          trigger={
            <Button variant="ghost" size="sm" className="w-8 px-0" aria-label="Theme">
              <ThemeIcon className="h-4 w-4" />
            </Button>
          }
          items={themeOptions}
        />
        <NotificationBell />
      </div>
    </header>
  );
}
