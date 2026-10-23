// file: src/components/ui/Button.jsx
import { forwardRef } from 'react';
import { clsx } from 'clsx';

// CRM design system: orange primary, white bordered secondary ("ghost" in
// the mockup), plain ghost, outline, danger, success
const buttonVariants = {
  primary: 'bg-cogentix-orange text-white border border-cogentix-orange hover:bg-cogentix-orange-600 hover:border-cogentix-orange-600',
  secondary: 'bg-white text-text-secondary border border-line hover:bg-surface-hover hover:text-text-primary',
  outline: 'bg-transparent text-cogentix-orange-700 border border-cogentix-orange/50 hover:bg-cogentix-orange/10',
  ghost: 'bg-transparent text-text-secondary border border-transparent hover:bg-surface-hover hover:text-text-primary',
  danger: 'bg-red-600 text-white border border-red-600 hover:bg-red-700 hover:border-red-700',
  success: 'bg-cogentix-green text-white border border-cogentix-green hover:bg-cogentix-green-600',
};

const buttonSizes = {
  xs: 'min-h-8 px-2.5 py-1 text-sm rounded-md gap-1',
  sm: 'min-h-9 px-3 py-1.5 text-sm rounded-lg gap-1.5',
  md: 'min-h-10 px-4 py-2 text-sm rounded-lg gap-1.5',
  lg: 'min-h-11 px-5 py-2.5 text-base rounded-lg gap-2',
  xl: 'min-h-12 px-6 py-3 text-base rounded-xl gap-2',
};

const Button = forwardRef(({
  children,
  variant = 'primary',
  size = 'md',
  className = '',
  disabled = false,
  loading = false,
  leftIcon,
  rightIcon,
  fullWidth = false,
  as: Component = 'button',
  ...props
}, ref) => {
  const baseClasses = 'inline-flex items-center justify-center font-semibold whitespace-nowrap transition-colors duration-150 focus:outline-none focus-visible:ring-2 focus-visible:ring-offset-2 focus-visible:ring-cogentix-orange-400 disabled:opacity-50 disabled:cursor-not-allowed';
  
  return (
    <Component
      ref={ref}
      className={clsx(
        baseClasses,
        buttonVariants[variant],
        buttonSizes[size],
        fullWidth && 'w-full',
        className
      )}
      disabled={disabled || loading}
      {...props}
    >
      {loading && (
        <svg className="animate-spin -ml-1 mr-2 h-4 w-4" xmlns="http://www.w3.org/2000/svg" fill="none" viewBox="0 0 24 24">
          <circle className="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" strokeWidth="4"></circle>
          <path className="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4zm2 5.291A7.962 7.962 0 014 12H0c0 3.042 1.135 5.824 3 7.938l3-2.647z"></path>
        </svg>
      )}
      {!loading && leftIcon && <span>{leftIcon}</span>}
      {children}
      {!loading && rightIcon && <span>{rightIcon}</span>}
    </Component>
  );
});

Button.displayName = 'Button';

export { Button };
export default Button;
