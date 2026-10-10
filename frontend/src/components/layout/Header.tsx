import { cn } from '../../lib/utils';
import { Menu, Sun, Moon, Monitor, Search } from 'lucide-react';
import { Button } from '../ui/Button';
import { Dropdown, DropdownItem } from '../ui/Dropdown';
import { useSettings } from '../../hooks/useSettings';
import { NotificationBell } from './NotificationBell';
import { OPEN_SEARCH_EVENT } from './CommandPalette';

interface HeaderProps {
  onMenuClick?: () => void;
  title?: string | null;
}

export function Header({ onMenuClick, title }: HeaderProps) {
  const { theme, setTheme } = useSettings();

  const themeOptions: DropdownItem[] = [
    { label: 'Dark', icon: <Moon className="w-4 h-4" />, onClick: () => setTheme('dark') },
    { label: 'Light', icon: <Sun className="w-4 h-4" />, onClick: () => setTheme('light') },
    { label: 'System', icon: <Monitor className="w-4 h-4" />, onClick: () => setTheme('system') },
  ];

  return (
    <header
      className={cn(
        'fixed top-0 right-0 z-30 h-16 bg-nexus-bg-secondary/80 backdrop-blur-sm border-b-nexus-border',
        'flex items-center justify-between px-4 gap-4',
        'transition-all duration-300'
      )}
      role="banner"
    >
      <div className="flex items-center gap-4">
        <Button
          variant="ghost"
          size="sm"
          onClick={onMenuClick}
          className="lg:hidden"
          aria-label="Open menu"
        >
          <Menu className="w-5 h-5" />
        </Button>
        {title && (
          <h1 className="text-lg font-semibold text-nexus-text hidden sm:block">
            {title}
          </h1>
        )}
      </div>

      <div className="flex items-center gap-2">
        <Button variant="ghost" size="sm" aria-label="Search (Ctrl+K)" title="Search (Ctrl+K)"
          onClick={() => window.dispatchEvent(new Event(OPEN_SEARCH_EVENT))} className="gap-1.5">
          <Search className="w-5 h-5" />
          <kbd className="hidden md:inline text-[10px] text-nexus-text-muted border border-nexus-border rounded px-1">Ctrl K</kbd>
        </Button>
        <Dropdown
          trigger={
            <Button variant="ghost" size="sm" aria-label="Theme">
              {theme === 'dark' && <Moon className="w-5 h-5" />}
              {theme === 'light' && <Sun className="w-5 h-5" />}
              {theme === 'system' && <Monitor className="w-5 h-5" />}
            </Button>
          }
          items={themeOptions}
        />

        <NotificationBell />

      </div>
    </header>
  );
}
