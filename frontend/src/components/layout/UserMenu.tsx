import { LogOut } from 'lucide-react';
import { Button } from '../ui/Button';
import { Dropdown } from '../ui/Dropdown';
import { useAuth } from '../../hooks/useAuth';

/** Who is signed in, with Sign out. */
export function UserMenu() {
  const { user, logout } = useAuth();
  if (!user) return null;
  const label = user.name || user.email;
  return (
    <Dropdown items={[
      { label: user.email, onClick: () => {}, disabled: true },
      { label: 'Sign out', icon: <LogOut className="h-4 w-4" />, onClick: () => { void logout(); } },
    ]} trigger={
      <Button variant="ghost" size="sm" className="h-8 gap-2 px-1.5" aria-label={`${label}: account menu`}>
        <span aria-hidden className="flex h-6 w-6 items-center justify-center rounded-full bg-nexus-accent/15 text-[11px] font-semibold uppercase text-nexus-accent-text">
          {label.slice(0, 1)}
        </span>
        <span className="hidden max-w-[10rem] truncate text-[13px] text-nexus-text-secondary md:inline">{label}</span>
      </Button>
    } />
  );
}
