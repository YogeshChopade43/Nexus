import { HTMLAttributes, forwardRef } from 'react';
import { cn } from '../../lib/utils';

interface BadgeProps extends HTMLAttributes<HTMLSpanElement> {
  variant?: 'default' | 'accent' | 'danger' | 'warning' | 'info' | 'success';
  size?: 'sm' | 'md';
}

export const Badge = forwardRef<HTMLSpanElement, BadgeProps>(
  ({ className, variant = 'default', size = 'md', children, ...props }, ref) => {
    const variants = {
      default: 'bg-nexus-bg-tertiary text-nexus-text-secondary ring-nexus-border',
      accent: 'bg-nexus-accent/10 text-nexus-accent-text ring-nexus-accent/25',
      danger: 'bg-nexus-danger/10 text-red-600 dark:text-red-400 ring-nexus-danger/25',
      warning: 'bg-nexus-warning/10 text-amber-700 dark:text-amber-400 ring-nexus-warning/25',
      info: 'bg-nexus-info/10 text-blue-700 dark:text-blue-400 ring-nexus-info/25',
      success: 'bg-nexus-success/10 text-green-700 dark:text-green-400 ring-nexus-success/25',
    };

    const sizes = {
      sm: 'px-1.5 py-px text-[11px]',
      md: 'px-2 py-0.5 text-xs',
    };

    return (
      <span
        ref={ref}
        className={cn(
          'inline-flex items-center gap-1 rounded-md font-medium ring-1 ring-inset whitespace-nowrap',
          variants[variant],
          sizes[size],
          className
        )}
        {...props}
      >
        {children}
      </span>
    );
  }
);

Badge.displayName = 'Badge';
