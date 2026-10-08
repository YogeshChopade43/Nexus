import { cn } from '../../lib/utils';
import { Menu, Sun, Moon, Monitor } from 'lucide-react';
import { Button } from '../ui/Button';
import { Dropdown, DropdownItem } from '../ui/Dropdown';
import { useSettings } from '../../hooks/useSettings';
import { NotificationBell } from './NotificationBell';

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
