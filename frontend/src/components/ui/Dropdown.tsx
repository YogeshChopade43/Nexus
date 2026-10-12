import { ReactNode, useState, useRef, useEffect, useLayoutEffect } from 'react';
import { createPortal } from 'react-dom';
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

const GAP = 4;  // px between the trigger and the menu

/** A menu under its trigger. It is drawn in a portal on <body> with fixed positioning, so neighbouring
 *  cards or scrolling lists can never cover or clip it. */
export function Dropdown({ trigger, children, items, align = 'right' }: DropdownProps) {
  const [open, setOpen] = useState(false);
  const [position, setPosition] = useState<{ top: number; left?: number; right?: number }>({ top: 0 });
  const containerRef = useRef<HTMLDivElement>(null);
  const menuRef = useRef<HTMLDivElement>(null);

  // Place the menu under the trigger (above it if there's no room below); follow scrolling and resizing.
  useLayoutEffect(() => {
    if (!open) return;
    const place = () => {
      const rect = containerRef.current?.getBoundingClientRect();
      if (!rect) return;
      const height = menuRef.current?.offsetHeight ?? 0;
      const below = rect.bottom + GAP;
      const top = below + height > window.innerHeight && rect.top - GAP - height > 0 ? rect.top - GAP - height : below;
      setPosition(align === 'right' ? { top, right: window.innerWidth - rect.right } : { top, left: rect.left });
    };
    place();
    window.addEventListener('scroll', place, true);
    window.addEventListener('resize', place);
    return () => { window.removeEventListener('scroll', place, true); window.removeEventListener('resize', place); };
  }, [open, align]);

  useEffect(() => {
    if (!open) return;
    const handleClickOutside = (event: MouseEvent) => {
      const target = event.target as Node;
      // The menu lives in a portal, outside the trigger's container: presses inside it aren't "outside".
      if (!containerRef.current?.contains(target) && !menuRef.current?.contains(target)) setOpen(false);
    };
    const handleEscape = (event: KeyboardEvent) => { if (event.key === 'Escape') setOpen(false); };
    document.addEventListener('mousedown', handleClickOutside);
    document.addEventListener('keydown', handleEscape);
    return () => {
      document.removeEventListener('mousedown', handleClickOutside);
      document.removeEventListener('keydown', handleEscape);
    };
  }, [open]);

  const dropdownContent = (
    <div
      ref={menuRef}
      style={{ position: 'fixed', top: position.top, left: position.left, right: position.right }}
      className="z-[80] min-w-[180px] bg-nexus-bg-secondary border border-nexus-border rounded-lg shadow-pop p-1 animate-fade-in"
      role="menu"
    >
      {items.map((item, index) => {
        if (item.divider) {
          return (
            <div key={index} className="h-px bg-nexus-border -mx-1 my-1" role="separator" />
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
              'w-full h-8 px-2 rounded-md text-left text-[13px] flex items-center gap-2 transition-colors',
              'hover:bg-nexus-bg-tertiary focus:outline-none focus-visible:ring-0 focus:bg-nexus-bg-tertiary',
              item.danger ? 'text-nexus-danger' : 'text-nexus-text [&_svg]:text-nexus-text-muted',
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
      <div onClick={(e) => { e.stopPropagation(); setOpen(o => !o); }} className="cursor-pointer inline-block">
        {trigger ?? children}
      </div>
      {open && createPortal(dropdownContent, document.body)}
    </div>
  );
}
