import { forwardRef, InputHTMLAttributes, TextareaHTMLAttributes } from 'react';
import { cn } from '../../lib/utils';

/** The look of every hand-built field (inputs, selects, textareas) so they match <Input>. */
export const fieldClass =
  'w-full min-h-9 rounded-md border border-nexus-border bg-nexus-bg-secondary px-3 py-[7px] text-sm text-nexus-text shadow-surface '
  + 'placeholder:text-nexus-text-muted hover:border-nexus-border-hover focus:outline-none focus:border-nexus-accent focus:ring-2 focus:ring-nexus-accent/25';

export interface InputProps extends InputHTMLAttributes<HTMLInputElement> {
  label?: string;
  error?: string;
  hint?: string;
}

export const Input = forwardRef<HTMLInputElement, InputProps>(
  ({ className, label, error, hint, id, ...props }, ref) => {
    const inputId = id || label?.toLowerCase().replace(/\s+/g, '-');

    return (
      <div className="w-full">
        {label && (
          <label htmlFor={inputId} className="block text-[13px] font-medium text-nexus-text mb-1.5">
            {label}
          </label>
        )}
        <input
          ref={ref}
          id={inputId}
          className={cn(
            'w-full h-9 px-3 rounded-md bg-nexus-bg-secondary border shadow-surface transition-[border-color,box-shadow] duration-150 text-sm',
            'text-nexus-text placeholder-nexus-text-muted',
            'focus:outline-none focus:border-nexus-accent focus:ring-2 focus:ring-nexus-accent/25',
            error ? 'border-nexus-danger focus:border-nexus-danger focus:ring-nexus-danger/25' : 'border-nexus-border hover:border-nexus-border-hover',
            'disabled:opacity-50 disabled:cursor-not-allowed',
            className
          )}
          aria-invalid={error ? 'true' : 'false'}
          aria-describedby={error ? `${inputId}-error` : hint ? `${inputId}-hint` : undefined}
          {...props}
        />
        {error && (
          <p id={`${inputId}-error`} className="mt-1.5 text-xs text-nexus-danger" role="alert">
            {error}
          </p>
        )}
        {hint && !error && (
          <p id={`${inputId}-hint`} className="mt-1.5 text-xs text-nexus-text-muted">
            {hint}
          </p>
        )}
      </div>
    );
  }
);

Input.displayName = 'Input';

export interface TextareaProps extends TextareaHTMLAttributes<HTMLTextAreaElement> {
  label?: string;
  error?: string;
  hint?: string;
}

export const Textarea = forwardRef<HTMLTextAreaElement, TextareaProps>(
  ({ className, label, error, hint, id, ...props }, ref) => {
    const textareaId = id || label?.toLowerCase().replace(/\s+/g, '-');

    return (
      <div className="w-full">
        {label && (
          <label htmlFor={textareaId} className="block text-[13px] font-medium text-nexus-text mb-1.5">
            {label}
          </label>
        )}
        <textarea
          ref={ref}
          id={textareaId}
          className={cn(
            'w-full px-3 py-2 rounded-md bg-nexus-bg-secondary border shadow-surface transition-[border-color,box-shadow] duration-150 resize-y min-h-[80px] text-sm',
            'text-nexus-text placeholder-nexus-text-muted',
            'focus:outline-none focus:border-nexus-accent focus:ring-2 focus:ring-nexus-accent/25',
            error ? 'border-nexus-danger focus:border-nexus-danger focus:ring-nexus-danger/25' : 'border-nexus-border hover:border-nexus-border-hover',
            'disabled:opacity-50 disabled:cursor-not-allowed',
            className
          )}
          aria-invalid={error ? 'true' : 'false'}
          aria-describedby={error ? `${textareaId}-error` : hint ? `${textareaId}-hint` : undefined}
          {...props}
        />
        {error && (
          <p id={`${textareaId}-error`} className="mt-1.5 text-xs text-nexus-danger" role="alert">
            {error}
          </p>
        )}
        {hint && !error && (
          <p id={`${textareaId}-hint`} className="mt-1.5 text-xs text-nexus-text-muted">
            {hint}
          </p>
        )}
      </div>
    );
  }
);

Textarea.displayName = 'Textarea';
