// file: src/components/ui/Badge.jsx
import { clsx } from 'clsx';

// status pills from the CRM mockup: tinted fill, no border, coloured dot
const badgeVariants = {
  default: 'bg-text-secondary/10 text-text-secondary border-transparent',
  primary: 'bg-cogentix-orange/12 text-cogentix-orange-700 border-transparent',
  secondary: 'bg-cogentix-orange/12 text-cogentix-orange-700 border-transparent',
  success: 'bg-green-600/10 text-green-700 border-transparent',
  warning: 'bg-amber-600/10 text-amber-700 border-transparent',
  danger: 'bg-red-600/10 text-red-700 border-transparent',
  info: 'bg-blue-600/10 text-blue-700 border-transparent',
};

const badgeSizes = {
  sm: 'px-2 py-0.5 text-sm',
  md: 'px-2.5 py-0.5 text-sm',
  lg: 'px-3 py-1 text-sm',
};

export function Badge({
  children,
  variant = 'default',
  size = 'md',
  dot = false,
  removable = false,
  onRemove,
  className = '',
}) {
  return (
    <span
      className={clsx(
        'inline-flex items-center font-semibold rounded-full border whitespace-nowrap',
        badgeVariants[variant],
        badgeSizes[size],
        className
      )}
    >
      {dot && (
        <span className={clsx(
          'w-1.5 h-1.5 rounded-full mr-1.5',
          variant === 'success' && 'bg-green-600',
          variant === 'warning' && 'bg-amber-600',
          variant === 'danger' && 'bg-red-600',
          variant === 'info' && 'bg-blue-600',
          variant === 'primary' && 'bg-cogentix-orange',
          variant === 'secondary' && 'bg-cogentix-orange',
          variant === 'default' && 'bg-text-secondary',
        )} />
      )}
      {children}
      {removable && onRemove && (
        <button
          onClick={onRemove}
          className="ml-1.5 -mr-0.5 hover:bg-black/10 rounded-full p-0.5"
        >
          <svg className="w-3 h-3" fill="none" viewBox="0 0 24 24" stroke="currentColor">
            <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M6 18L18 6M6 6l12 12" />
          </svg>
        </button>
      )}
    </span>
  );
}

// Status badge with predefined statuses
export function StatusBadge({ status }) {
  const statusConfig = {
    active: { variant: 'success', label: 'Active', dot: true },
    inactive: { variant: 'default', label: 'Inactive', dot: true },
    pending: { variant: 'warning', label: 'Pending', dot: true },
    completed: { variant: 'success', label: 'Completed', dot: true },
    cancelled: { variant: 'danger', label: 'Cancelled', dot: true },
    draft: { variant: 'default', label: 'Draft', dot: true },
    paid: { variant: 'success', label: 'Paid', dot: true },
    unpaid: { variant: 'danger', label: 'Unpaid', dot: true },
    overdue: { variant: 'danger', label: 'Overdue', dot: true },
    processing: { variant: 'info', label: 'Processing', dot: true },
    sent: { variant: 'info', label: 'Sent', dot: true },
    open: { variant: 'warning', label: 'Open', dot: true },
    closed: { variant: 'default', label: 'Closed', dot: true },
  };

  const config = statusConfig[status?.toLowerCase()] || { variant: 'default', label: status || 'Unknown', dot: false };

  return (
    <Badge variant={config.variant} dot={config.dot}>
      {config.label}
    </Badge>
  );
}

export default Badge;
