// file: src/components/ui/Badge.jsx
import { clsx } from 'clsx';

const badgeVariants = {
  default: 'bg-slate-100 text-slate-700 border-slate-200',
  primary: 'bg-cogentix-navy-50 text-cogentix-navy border-cogentix-navy-200',
  secondary: 'bg-cogentix-orange-50 text-cogentix-orange border-cogentix-orange-200',
  success: 'bg-cogentix-green-50 text-cogentix-green-700 border-cogentix-green-200',
  warning: 'bg-amber-50 text-amber-700 border-amber-200',
  danger: 'bg-red-50 text-red-700 border-red-200',
  info: 'bg-blue-50 text-blue-700 border-blue-200',
};

const badgeSizes = {
  sm: 'px-2 py-0.5 text-xs',
  md: 'px-2.5 py-1 text-xs',
  lg: 'px-3 py-1.5 text-sm',
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
        'inline-flex items-center font-medium rounded-full border',
        badgeVariants[variant],
        badgeSizes[size],
        className
      )}
    >
      {dot && (
        <span className={clsx(
          'w-1.5 h-1.5 rounded-full mr-1.5',
          variant === 'success' && 'bg-cogentix-green',
          variant === 'warning' && 'bg-amber-500',
          variant === 'danger' && 'bg-red-500',
          variant === 'info' && 'bg-blue-500',
          variant === 'primary' && 'bg-cogentix-navy',
          variant === 'secondary' && 'bg-cogentix-orange',
          variant === 'default' && 'bg-slate-500',
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
