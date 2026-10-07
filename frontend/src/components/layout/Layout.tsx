import { useState } from 'react';
import type { ReactNode } from 'react';
import { cn } from '../../lib/utils';
import { Sidebar } from './Sidebar';
import { Header } from './Header';

interface LayoutProps {
  sidebarCollapsed?: boolean;
  onSidebarToggle?: () => void;
  children?: ReactNode;
}

export function Layout({ sidebarCollapsed = false, onSidebarToggle, children }: LayoutProps) {
  const [mobileSidebarOpen, setMobileSidebarOpen] = useState(false);

  return (
    <div className="min-h-screen bg-nexus-bg">
      <Sidebar
        collapsed={sidebarCollapsed || mobileSidebarOpen}
        onToggleCollapse={onSidebarToggle}
      />
      <div
        className={cn(
          'transition-all duration-300 min-h-screen',
          sidebarCollapsed ? 'lg:ml-16' : 'lg:ml-64'
        )}
      >
        <Header
          onMenuClick={() => setMobileSidebarOpen(!mobileSidebarOpen)}
          title={null}
        />
         <main
           className={cn(
             'pt-16 min-h-screen',
           )}
           role="main"
         >
          <div className="p-4 lg:p-6">
            {children}
          </div>
        </main>
      </div>

      {mobileSidebarOpen && (
        <div
          className="fixed inset-0 z-30 bg-black/50 lg:hidden"
          onClick={() => setMobileSidebarOpen(false)}
          aria-hidden="true"
        />
      )}
    </div>
  );
}
