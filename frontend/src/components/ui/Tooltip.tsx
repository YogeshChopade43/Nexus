import { ReactNode, useState, useRef, useEffect } from 'react';
import { createPortal } from 'react-dom';
import { cn } from '../../lib/utils';

interface TooltipProps {
  content: ReactNode;
  children: ReactNode;
  position?: 'top' | 'bottom' | 'left' | 'right';
  delay?: number;
}

export function Tooltip({ content, children, position = 'top', delay = 200 }: TooltipProps) {
  const [visible, setVisible] = useState(false);
  const timeoutRef = useRef<ReturnType<typeof setTimeout>>();

  const show = () => {
    timeoutRef.current = setTimeout(() => setVisible(true), delay);
  };

  const hide = () => {
    clearTimeout(timeoutRef.current);
    setVisible(false);
  };

  useEffect(() => {
    return () => clearTimeout(timeoutRef.current);
  }, []);

  const positions = {
    top: 'bottom-full left-1/2 -translate-x-1/2 mb-2',
    bottom: 'top-full left-1/2 -translate-x-1/2 mt-2',
    left: 'right-full top-1/2 -translate-y-1/2 mr-2',
    right: 'left-full top-1/2 -translate-y-1/2 ml-2',
  };

  const arrows = {
    top: 'top-full left-1/2 -translate-x-1/2 border-t-nexus-bg-tertiary',
    bottom: 'bottom-full left-1/2 -translate-x-1/2 border-b-nexus-bg-tertiary',
    left: 'left-full top-1/2 -translate-y-1/2 border-l-nexus-bg-tertiary',
    right: 'right-full top-1/2 -translate-y-1/2 border-r-nexus-bg-tertiary',
  };

  return (
    <>
      <span
        className="relative inline-block"
        onMouseEnter={show}
        onMouseLeave={hide}
        onFocus={show}
        onBlur={hide}
      >
        {children}
      </span>
      {visible && createPortal(
        <div
          className={cn(
            'fixed z-50 px-3 py-1.5 text-xs font-medium text-nexus-text bg-nexus-bg-tertiary border-nexus-border rounded-lg shadow-lg whitespace-nowrap animate-fade-in',
            positions[position]
          )}
          role="tooltip"
        >
          {content}
          <div
            className={cn(
              'absolute w-0 h-0 border-4 border-transparent',
              arrows[position]
            )}
          />
        </div>,
        document.body
      )}
    </>
  );
}
