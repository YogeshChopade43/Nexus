import { ReactNode, useState, useRef, useEffect, type CSSProperties } from 'react';
import { createPortal } from 'react-dom';

interface TooltipProps {
  content: ReactNode;
  children: ReactNode;
  position?: 'top' | 'bottom' | 'left' | 'right';
  delay?: number;
}

const GAP = 6;  // px between the element and the tooltip

/** A small label shown on hover or keyboard focus, placed beside the element (drawn on <body>, so nothing clips it). */
export function Tooltip({ content, children, position = 'top', delay = 300 }: TooltipProps) {
  const [style, setStyle] = useState<CSSProperties | null>(null);
  const anchorRef = useRef<HTMLSpanElement>(null);
  const timeoutRef = useRef<ReturnType<typeof setTimeout>>();

  const show = () => {
    timeoutRef.current = setTimeout(() => {
      const rect = anchorRef.current?.getBoundingClientRect();
      if (!rect) return;
      const placements: Record<string, CSSProperties> = {
        top: { left: rect.left + rect.width / 2, top: rect.top - GAP, transform: 'translate(-50%, -100%)' },
        bottom: { left: rect.left + rect.width / 2, top: rect.bottom + GAP, transform: 'translateX(-50%)' },
        left: { left: rect.left - GAP, top: rect.top + rect.height / 2, transform: 'translate(-100%, -50%)' },
        right: { left: rect.right + GAP, top: rect.top + rect.height / 2, transform: 'translateY(-50%)' },
      };
      setStyle(placements[position]);
    }, delay);
  };

  const hide = () => {
    clearTimeout(timeoutRef.current);
    setStyle(null);
  };

  useEffect(() => () => clearTimeout(timeoutRef.current), []);

  return (
    <>
      <span ref={anchorRef} className="relative inline-flex" onMouseEnter={show} onMouseLeave={hide} onFocus={show} onBlur={hide}>
        {children}
      </span>
      {style && createPortal(
        <div style={{ position: 'fixed', ...style }} role="tooltip"
          className="z-[90] px-2 py-1 text-xs font-medium text-nexus-text bg-nexus-bg-secondary border border-nexus-border rounded-md shadow-pop whitespace-nowrap pointer-events-none animate-fade-in">
          {content}
        </div>,
        document.body,
      )}
    </>
  );
}
