// file: src/components/ui/Input.jsx
import { forwardRef } from 'react';
import { clsx } from 'clsx';

const inputSizes = {
  sm: 'px-3 py-1.5 text-sm',
  md: 'px-3.5 py-2.5 text-sm',
  lg: 'px-4 py-3 text-base',
};

const Input = forwardRef(({
  label,
  error,
  hint,
  leftIcon,
  rightIcon,
  size = 'md',
  className = '',
  containerClassName = '',
  required = false,
  ...props
}, ref) => {
  return (
    <div className={clsx('', containerClassName)}>
      {label && (
        <label className="block text-sm font-medium text-text-primary mb-1.5">
          {label}
          {required && <span className="text-red-500 ml-0.5">*</span>}
        </label>
      )}
      <div className="relative">
        {leftIcon && (
          <div className="absolute inset-y-0 left-0 pl-3 flex items-center pointer-events-none text-text-muted">
            {leftIcon}
          </div>
        )}
        <input
          ref={ref}
          className={clsx(
            'block w-full rounded-lg border bg-white transition-all duration-200',
            'focus:outline-none focus:ring-2 focus:ring-cogentix-orange-400 focus:border-cogentix-orange',
            'placeholder:text-text-light',
            error
              ? 'border-red-300 focus:border-red-500 focus:ring-red-200'
              : 'border-slate-200 hover:border-slate-300',
            inputSizes[size],
            leftIcon && 'pl-10',
            rightIcon && 'pr-10',
            className
          )}
          {...props}
        />
        {rightIcon && (
          <div className="absolute inset-y-0 right-0 pr-3 flex items-center text-text-muted">
            {rightIcon}
          </div>
        )}
      </div>
      {error && (
        <p className="mt-1.5 text-sm text-red-500">{error}</p>
      )}
      {hint && !error && (
        <p className="mt-1.5 text-sm text-text-muted">{hint}</p>
      )}
    </div>
  );
});

Input.displayName = 'Input';

// Textarea variant
export const Textarea = forwardRef(({
  label,
  error,
  hint,
  className = '',
  containerClassName = '',
  required = false,
  rows = 4,
  ...props
}, ref) => {
  return (
    <div className={clsx('', containerClassName)}>
      {label && (
        <label className="block text-sm font-medium text-text-primary mb-1.5">
          {label}
          {required && <span className="text-red-500 ml-0.5">*</span>}
        </label>
      )}
      <textarea
        ref={ref}
        rows={rows}
        className={clsx(
          'block w-full rounded-lg border bg-white transition-all duration-200 px-3.5 py-2.5 text-sm',
          'focus:outline-none focus:ring-2 focus:ring-cogentix-orange-400 focus:border-cogentix-orange',
          'placeholder:text-text-light resize-none',
          error
            ? 'border-red-300 focus:border-red-500 focus:ring-red-200'
            : 'border-slate-200 hover:border-slate-300',
          className
        )}
        {...props}
      />
      {error && (
        <p className="mt-1.5 text-sm text-red-500">{error}</p>
      )}
      {hint && !error && (
        <p className="mt-1.5 text-sm text-text-muted">{hint}</p>
      )}
    </div>
  );
});

Textarea.displayName = 'Textarea';

// Search input variant
export const SearchInput = forwardRef(({
  placeholder = 'Search...',
  className = '',
  ...props
}, ref) => {
  return (
    <Input
      ref={ref}
      type="search"
      placeholder={placeholder}
      leftIcon={
        <svg className="w-5 h-5" fill="none" viewBox="0 0 24 24" stroke="currentColor">
          <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M21 21l-6-6m2-5a7 7 0 11-14 0 7 7 0 0114 0z" />
        </svg>
      }
      className={className}
      {...props}
    />
  );
});

SearchInput.displayName = 'SearchInput';

export { Input };
export default Input;
