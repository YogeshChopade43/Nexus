import { useEffect, useState } from 'react';
import type { ReactNode } from 'react';
import { useLocation } from 'react-router-dom';
import { cn } from '../../lib/utils';
import { Sidebar } from './Sidebar';
import { Header } from './Header';
import { CommandPalette } from './CommandPalette';
import { useChatContext } from '../../hooks/useChatContext';
import { RunOnceBanner } from '../runonce/RunOnce';

const COLLAPSED_KEY = 'nexus-sidebar-collapsed';

function readCollapsed(): boolean {
  try {
    return localStorage.getItem(COLLAPSED_KEY) === '1';
  } catch {
    return false;
  }
}

export function Layout({ children }: { children?: ReactNode }) {
  const [collapsed, setCollapsed] = useState(readCollapsed);
  const [mobileOpen, setMobileOpen] = useState(false);
  const { openSession } = useChatContext();
  const { pathname } = useLocation();

  useEffect(() => setMobileOpen(false), [pathname]);  // a phone's menu closes once you pick a page

  const toggleCollapsed = () => setCollapsed(previous => {
    try {
      localStorage.setItem(COLLAPSED_KEY, previous ? '0' : '1');
    } catch {
      // remembering is a convenience
    }
    return !previous;
  });

  return (
    <div className="min-h-screen bg-nexus-bg">
      <Sidebar collapsed={collapsed} mobileOpen={mobileOpen} onToggleCollapse={toggleCollapsed} />
      <div className={cn('flex min-h-screen flex-col transition-[margin] duration-200 ease-out', collapsed ? 'lg:ml-14' : 'lg:ml-60')}>
        <Header onMenuClick={() => setMobileOpen(open => !open)} />
        <RunOnceBanner />
        <main className="flex-1" role="main">
          <div className="mx-auto w-full max-w-[1400px] p-4 lg:px-8 lg:py-6">
            {children}
          </div>
        </main>
      </div>

      <CommandPalette onOpenChat={(id) => void openSession(id)} />

      {mobileOpen && (
        <div className="fixed inset-0 z-30 bg-black/50 backdrop-blur-[1px] lg:hidden" onClick={() => setMobileOpen(false)} aria-hidden="true" />
      )}
    </div>
  );
}
