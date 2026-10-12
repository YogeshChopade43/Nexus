import { createContext, ReactNode, useContext, useEffect, useId, useRef } from 'react';
import { createPortal } from 'react-dom';
import { cn } from '../../lib/utils';
import { Button } from './Button';
import { X } from 'lucide-react';

interface ModalProps {
  open: boolean;
  onClose: () => void;
  title?: string;
  description?: string;
  children: ReactNode;
  size?: 'sm' | 'md' | 'lg' | 'xl' | 'full' | 'screen';
  showClose?: boolean;
}

/** Open pop-ups with their nesting depth: only the innermost answers Escape, and the page stays locked until
 *  all close. Depth comes from context because React runs a child's effects before its parent's. */
const openModals: { token: symbol; depth: number }[] = [];
const ModalDepth = createContext(0);

function isTop(token: symbol): boolean {
  const deepest = Math.max(...openModals.map(m => m.depth));
  return [...openModals].reverse().find(m => m.depth === deepest)?.token === token;
}

export function Modal({
  open,
  onClose,
  title,
  description,
  children,
  size = 'md',
  showClose = true,
}: ModalProps) {
  const overlayRef = useRef<HTMLDivElement>(null);
  const contentRef = useRef<HTMLDivElement>(null);
  const id = useId();
  const depth = useContext(ModalDepth) + 1;

  useEffect(() => {
    const token = Symbol('modal');
    const handleEscape = (event: KeyboardEvent) => {
      if (event.key === 'Escape' && isTop(token)) onClose();
    };

    const handleOverlayClick = (event: MouseEvent) => {
      if (event.target === overlayRef.current) onClose();
    };

    if (open) {
      openModals.push({ token, depth });
      document.addEventListener('keydown', handleEscape);
      overlayRef.current?.addEventListener('click', handleOverlayClick);
      document.body.style.overflow = 'hidden';
    }

    return () => {
      const index = openModals.findIndex(m => m.token === token);
      if (index >= 0) openModals.splice(index, 1);
      document.removeEventListener('keydown', handleEscape);
      overlayRef.current?.removeEventListener('click', handleOverlayClick);
      if (openModals.length === 0) document.body.style.overflow = '';
    };
  }, [open, onClose, depth]);

  if (!open) return null;

  const sizes = {
    sm: 'max-w-sm',
    md: 'max-w-md',
    lg: 'max-w-lg',
    xl: 'max-w-xl',
    full: 'max-w-4xl',
    screen: 'max-w-7xl',
  };

  const modalContent = (
    <div
      ref={overlayRef}
      className="fixed inset-0 z-50 flex items-center justify-center p-4 bg-black/50 backdrop-blur-[2px] animate-fade-in"
      role="dialog"
      aria-modal="true"
      aria-labelledby={title ? `${id}-title` : undefined}
      aria-describedby={description ? `${id}-description` : undefined}
    >
      <div
        ref={contentRef}
        className={cn(
          // Never taller than the screen: the body scrolls, the title and close button stay reachable.
          'w-full max-h-full flex flex-col bg-nexus-bg-secondary border border-nexus-border rounded-xl shadow-pop animate-slide-up',
          sizes[size]
        )}
      >
        {(title || showClose) && (
          <div className="flex items-start justify-between gap-4 px-5 py-4 border-b border-nexus-border">
            <div>
              {title && (
                <h2 id={`${id}-title`} className="text-[15px] font-semibold text-nexus-text">
                  {title}
                </h2>
              )}
              {description && (
                <p id={`${id}-description`} className="text-[13px] text-nexus-text-secondary mt-0.5">
                  {description}
                </p>
              )}
            </div>
            {showClose && (
              <Button
                variant="ghost"
                size="sm"
                onClick={onClose}
                aria-label="Close modal"
                className="-mr-1.5 -mt-1 w-8 px-0 text-nexus-text-muted hover:text-nexus-text"
              >
                <X className="h-4 w-4" />
              </Button>
            )}
          </div>
        )}
        <div className="px-5 py-4 overflow-y-auto">
          <ModalDepth.Provider value={depth}>{children}</ModalDepth.Provider>
        </div>
      </div>
    </div>
  );

  return createPortal(modalContent, document.body);
}
