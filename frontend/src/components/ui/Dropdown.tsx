import { ReactNode, useState, useRef, useEffect } from 'react';
import { cn } from '../../lib/utils';

export interface DropdownItem {
  label: string;
  onClick: () => void;
  icon?: ReactNode;
  disabled?: boolean;
  danger?: boolean;
  divider?: boolean;
}

interface DropdownProps {
  trigger?: ReactNode;
  children?: ReactNode;
  items: DropdownItem[];
  align?: 'left' | 'right';
}

export function Dropdown({ trigger, children, items, align = 'right' }: DropdownProps) {
  const [open, setOpen] = useState(false);
  const containerRef = useRef<HTMLDivElement>(null);
  const dropdownRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    const handleClickOutside = (event: MouseEvent) => {
      if (containerRef.current && !containerRef.current.contains(event.target as Node)) {
        setOpen(false);
      }
    };

    if (open) {
      document.addEventListener('mousedown', handleClickOutside);
    }
    return () => document.removeEventListener('mousedown', handleClickOutside);
  }, [open]);

  const handleKeyDown = (event: React.KeyboardEvent) => {
    if (event.key === 'Escape') {
      setOpen(false);
    }
  };

  const dropdownContent = (
    <div
      ref={dropdownRef}
      className={cn(
        'absolute z-50 min-w-[160px] bg-nexus-bg-secondary border-nexus-border rounded-lg shadow-lg py-1 animate-fade-in',
        align === 'right' ? 'right-0' : 'left-0'
      )}
      role="menu"
      onKeyDown={handleKeyDown}
    >
      {items.map((item, index) => {
        if (item.divider) {
          return (
            <div key={index} className="h-px bg-nexus-border my-1" role="separator" />
          );
        }
        return (
          <button
            key={index}
            onClick={(e) => {
              e.stopPropagation();
              item.onClick();
              setOpen(false);
            }}
            disabled={item.disabled}
            className={cn(
              'w-full px-3 py-2 text-left text-sm flex items-center gap-2 transition-colors',
              'hover:bg-nexus-bg-tertiary focus:outline-none focus:bg-nexus-bg-tertiary',
              item.danger ? 'text-nexus-danger' : 'text-nexus-text',
              item.disabled ? 'opacity-50 cursor-not-allowed' : ''
            )}
            role="menuitem"
          >
            {item.icon && <span className="flex-shrink-0">{item.icon}</span>}
            {item.label}
          </button>
        );
      })}
    </div>
  );

  return (
    <div ref={containerRef} className="relative inline-block">
      <div onClick={() => setOpen(o => !o)} className="cursor-pointer inline-block">
        {trigger ?? children}
      </div>
      {open && dropdownContent}
    </div>
  );
}
