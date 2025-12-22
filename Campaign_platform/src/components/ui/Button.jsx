// file: src/components/ui/Button.jsx
import { forwardRef } from 'react';
import { clsx } from 'clsx';

const buttonVariants = {
  primary: 'bg-cogentix-orange text-white hover:bg-cogentix-orange-600 shadow-button hover:shadow-button-hover',
  secondary: 'bg-cogentix-navy text-white hover:bg-cogentix-navy-800 shadow-button hover:shadow-button-hover',
  outline: 'border-2 border-cogentix-navy text-cogentix-navy hover:bg-cogentix-navy hover:text-white bg-transparent',
  ghost: 'text-cogentix-navy hover:bg-cogentix-navy-50 bg-transparent',
  danger: 'bg-red-500 text-white hover:bg-red-600 shadow-button hover:shadow-button-hover',
  success: 'bg-cogentix-green text-white hover:bg-cogentix-green-600 shadow-button hover:shadow-button-hover',
};

const buttonSizes = {
  xs: 'px-4 py-2.5 text-sm rounded-md',
  sm: 'px-5 py-3 text-base rounded-lg',
  md: 'px-6 py-4 text-base rounded-lg',
  lg: 'px-8 py-5 text-lg rounded-xl',
  xl: 'px-9 py-6 text-xl rounded-xl',
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
  const baseClasses = 'inline-flex items-center justify-center font-medium transition-all duration-200 focus:outline-none focus:ring-2 focus:ring-offset-2 focus:ring-cogentix-orange-400 disabled:opacity-50 disabled:cursor-not-allowed';
  
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
      {!loading && leftIcon && <span className="mr-2">{leftIcon}</span>}
      {children}
      {!loading && rightIcon && <span className="ml-2">{rightIcon}</span>}
    </Component>
  );
});

Button.displayName = 'Button';

export { Button };
export default Button;
