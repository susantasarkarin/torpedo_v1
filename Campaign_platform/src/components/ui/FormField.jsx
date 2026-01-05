// file: src/components/ui/FormField.jsx
// Standardized form field wrapper for consistent labels, validation, and errors

import { forwardRef, useId } from 'react';
import { clsx } from 'clsx';

/**
 * FormField Component
 * Wraps input components with consistent label, error, and hint styling
 * 
 * @param {string} label - Field label
 * @param {string} name - Field name (for htmlFor)
 * @param {boolean} required - Shows required indicator
 * @param {string} error - Error message to display
 * @param {string} hint - Hint text below input
 * @param {React.ReactNode} children - Input element
 * @param {string} className - Additional wrapper classes
 */
const FormField = forwardRef(({
  label,
  name,
  required = false,
  error,
  hint,
  children,
  className = '',
  labelPosition = 'top', // 'top' | 'left' | 'inline'
}, ref) => {
  const generatedId = useId();
  const fieldId = name || generatedId;

  const isHorizontal = labelPosition === 'left';
  const isInline = labelPosition === 'inline';

  return (
    <div 
      ref={ref}
      className={clsx(
        'form-field',
        isHorizontal && 'flex items-start gap-4',
        isInline && 'flex items-center gap-2',
        className
      )}
    >
      {/* Label */}
      {label && (
        <label
          htmlFor={fieldId}
          className={clsx(
            'block text-sm font-medium text-gray-700',
            isHorizontal && 'w-1/3 pt-2',
            isInline && 'whitespace-nowrap',
            !isHorizontal && !isInline && 'mb-1.5'
          )}
        >
          {label}
          {required && (
            <span className="text-red-500 ml-1" aria-label="required">*</span>
          )}
        </label>
      )}

      {/* Input Container */}
      <div className={clsx(isHorizontal && 'flex-1')}>
        {/* Render children with additional props */}
        {typeof children === 'function' 
          ? children({ id: fieldId, name, error: !!error })
          : children
        }

        {/* Hint */}
        {hint && !error && (
          <p className="mt-1.5 text-sm text-gray-500">
            {hint}
          </p>
        )}

        {/* Error */}
        {error && (
          <p className="mt-1.5 text-sm text-red-600 flex items-center gap-1">
            <svg className="w-4 h-4 flex-shrink-0" fill="currentColor" viewBox="0 0 20 20">
              <path fillRule="evenodd" d="M18 10a8 8 0 11-16 0 8 8 0 0116 0zm-7 4a1 1 0 11-2 0 1 1 0 012 0zm-1-9a1 1 0 00-1 1v4a1 1 0 102 0V6a1 1 0 00-1-1z" clipRule="evenodd" />
            </svg>
            {error}
          </p>
        )}
      </div>
    </div>
  );
});

FormField.displayName = 'FormField';

/**
 * FormInput - Styled input that works with FormField
 */
const FormInput = forwardRef(({
  type = 'text',
  error,
  className = '',
  size = 'md',
  leftIcon,
  rightIcon,
  ...props
}, ref) => {
  const sizeClasses = {
    sm: 'px-3 py-2 text-sm',
    md: 'px-4 py-2.5 text-base',
    lg: 'px-4 py-3 text-lg',
  };

  return (
    <div className="relative">
      {leftIcon && (
        <div className="absolute left-3 top-1/2 -translate-y-1/2 text-gray-400">
          {leftIcon}
        </div>
      )}
      <input
        ref={ref}
        type={type}
        className={clsx(
          'w-full rounded-lg border transition-colors duration-200',
          'focus:outline-none focus:ring-2 focus:ring-cogentix-orange-400 focus:border-transparent',
          error
            ? 'border-red-300 bg-red-50 text-red-900 placeholder-red-300'
            : 'border-gray-300 bg-white text-gray-900 placeholder-gray-400',
          sizeClasses[size],
          leftIcon && 'pl-10',
          rightIcon && 'pr-10',
          className
        )}
        {...props}
      />
      {rightIcon && (
        <div className="absolute right-3 top-1/2 -translate-y-1/2 text-gray-400">
          {rightIcon}
        </div>
      )}
    </div>
  );
});

FormInput.displayName = 'FormInput';

/**
 * FormTextarea - Styled textarea that works with FormField
 */
const FormTextarea = forwardRef(({
  error,
  className = '',
  rows = 3,
  ...props
}, ref) => {
  return (
    <textarea
      ref={ref}
      rows={rows}
      className={clsx(
        'w-full px-4 py-2.5 rounded-lg border transition-colors duration-200',
        'focus:outline-none focus:ring-2 focus:ring-cogentix-orange-400 focus:border-transparent',
        'resize-none',
        error
          ? 'border-red-300 bg-red-50 text-red-900 placeholder-red-300'
          : 'border-gray-300 bg-white text-gray-900 placeholder-gray-400',
        className
      )}
      {...props}
    />
  );
});

FormTextarea.displayName = 'FormTextarea';

/**
 * FormSelect - Styled select that works with FormField
 */
const FormSelect = forwardRef(({
  error,
  className = '',
  options = [],
  placeholder = 'Select an option',
  ...props
}, ref) => {
  return (
    <select
      ref={ref}
      className={clsx(
        'w-full px-4 py-2.5 rounded-lg border transition-colors duration-200',
        'focus:outline-none focus:ring-2 focus:ring-cogentix-orange-400 focus:border-transparent',
        'appearance-none bg-no-repeat bg-right',
        error
          ? 'border-red-300 bg-red-50 text-red-900'
          : 'border-gray-300 bg-white text-gray-900',
        className
      )}
      style={{
        backgroundImage: `url("data:image/svg+xml,%3csvg xmlns='http://www.w3.org/2000/svg' fill='none' viewBox='0 0 20 20'%3e%3cpath stroke='%236b7280' stroke-linecap='round' stroke-linejoin='round' stroke-width='1.5' d='M6 8l4 4 4-4'/%3e%3c/svg%3e")`,
        backgroundPosition: 'right 0.5rem center',
        backgroundSize: '1.5em 1.5em',
      }}
      {...props}
    >
      {placeholder && (
        <option value="">{placeholder}</option>
      )}
      {options.map((option) => (
        <option 
          key={option.value} 
          value={option.value}
          disabled={option.disabled}
        >
          {option.label}
        </option>
      ))}
    </select>
  );
});

FormSelect.displayName = 'FormSelect';

/**
 * FormCheckbox - Styled checkbox
 */
const FormCheckbox = forwardRef(({
  label,
  error,
  className = '',
  ...props
}, ref) => {
  return (
    <label className={clsx('flex items-center gap-2 cursor-pointer', className)}>
      <input
        ref={ref}
        type="checkbox"
        className={clsx(
          'w-4 h-4 rounded border-gray-300',
          'text-cogentix-orange focus:ring-cogentix-orange-400',
          error && 'border-red-300'
        )}
        {...props}
      />
      {label && (
        <span className="text-sm text-gray-700">{label}</span>
      )}
    </label>
  );
});

FormCheckbox.displayName = 'FormCheckbox';

/**
 * FormRadioGroup - Radio button group
 */
const FormRadioGroup = ({ name, options = [], value, onChange, error, className = '' }) => {
  return (
    <div className={clsx('flex flex-col gap-2', className)}>
      {options.map((option) => (
        <label 
          key={option.value} 
          className="flex items-center gap-2 cursor-pointer"
        >
          <input
            type="radio"
            name={name}
            value={option.value}
            checked={value === option.value}
            onChange={(e) => onChange?.(e.target.value)}
            className={clsx(
              'w-4 h-4 border-gray-300',
              'text-cogentix-orange focus:ring-cogentix-orange-400',
              error && 'border-red-300'
            )}
          />
          <span className="text-sm text-gray-700">{option.label}</span>
        </label>
      ))}
    </div>
  );
};

export { 
  FormField, 
  FormInput, 
  FormTextarea, 
  FormSelect, 
  FormCheckbox,
  FormRadioGroup 
};
export default FormField;
