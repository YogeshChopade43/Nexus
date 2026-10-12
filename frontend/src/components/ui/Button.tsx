import { forwardRef, ButtonHTMLAttributes } from 'react';
import { cn } from '../../lib/utils';

export interface ButtonProps extends ButtonHTMLAttributes<HTMLButtonElement> {
  variant?: 'primary' | 'secondary' | 'ghost' | 'danger';
  size?: 'sm' | 'md' | 'lg';
  loading?: boolean;
}

export const Button = forwardRef<HTMLButtonElement, ButtonProps>(
  ({ className, variant = 'primary', size = 'md', loading, disabled, children, ...props }, ref) => {
    // shadcn/ui recipe: compact, hairline-bordered secondary, quiet ghost, visible keyboard focus.
    const baseStyles = 'inline-flex items-center justify-center gap-1.5 whitespace-nowrap font-medium rounded-md select-none '
      + 'transition-[background-color,border-color,color,box-shadow,transform] duration-150 active:scale-[0.98] '
      + 'focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-nexus-accent/60 focus-visible:ring-offset-1 focus-visible:ring-offset-nexus-bg '
      + 'disabled:opacity-50 disabled:cursor-not-allowed disabled:active:scale-100';

    const variants = {
      primary: 'bg-nexus-accent text-nexus-on-accent shadow-sm hover:bg-nexus-accent-hover',
      secondary: 'border border-nexus-border bg-nexus-bg-secondary text-nexus-text shadow-surface hover:bg-nexus-bg-tertiary hover:border-nexus-border-hover',
      ghost: 'bg-transparent text-nexus-text-secondary hover:bg-nexus-bg-tertiary hover:text-nexus-text',
      danger: 'bg-nexus-danger text-white shadow-sm hover:bg-nexus-danger-hover',
    };

    const sizes = {
      sm: 'h-8 px-2.5 text-[13px]',
      md: 'h-9 px-3.5 text-sm',
      lg: 'h-10 px-5 text-sm',
    };

    return (
      <button
        ref={ref}
        className={cn(baseStyles, variants[variant], sizes[size], className)}
        disabled={disabled || loading}
        {...props}
      >
        {loading && (
          <svg className="animate-spin h-4 w-4" viewBox="0 0 24 24">
            <circle className="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" strokeWidth="3" fill="none" />
            <path className="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4zm2 5.291A7.962 7.962 0 014 12H0c0 3.042 1.135 5.824 3 7.938l3-2.647z" />
          </svg>
        )}
        {children}
      </button>
    );
  }
);

Button.displayName = 'Button';
