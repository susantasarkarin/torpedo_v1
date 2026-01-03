/**
 * Skeleton - Loading placeholder components
 * Provides visual feedback while content is loading
 */
import { clsx } from 'clsx';

// Base skeleton pulse animation
const pulseClass = 'animate-pulse bg-gray-200 rounded';

/**
 * Skeleton - Base skeleton component
 */
export function Skeleton({ 
  className = '', 
  width, 
  height,
  rounded = 'md',
}) {
  const roundedClasses = {
    none: 'rounded-none',
    sm: 'rounded-sm',
    md: 'rounded',
    lg: 'rounded-lg',
    xl: 'rounded-xl',
    full: 'rounded-full',
  };

  return (
    <div 
      className={clsx(
        'animate-pulse bg-gray-200',
        roundedClasses[rounded],
        className
      )}
      style={{ 
        width: width || '100%', 
        height: height || '1rem' 
      }}
    />
  );
}

/**
 * SkeletonText - Text line skeleton
 */
export function SkeletonText({ 
  lines = 1, 
  className = '',
  lastLineWidth = '75%',
}) {
  return (
    <div className={clsx('space-y-2', className)}>
      {Array.from({ length: lines }).map((_, i) => (
        <Skeleton 
          key={i} 
          height="0.875rem"
          width={i === lines - 1 && lines > 1 ? lastLineWidth : '100%'}
        />
      ))}
    </div>
  );
}

/**
 * SkeletonCircle - Circular skeleton (avatars, icons)
 */
export function SkeletonCircle({ size = 40, className = '' }) {
  return (
    <Skeleton 
      width={size} 
      height={size} 
      rounded="full" 
      className={className}
    />
  );
}

/**
 * SkeletonCard - Card placeholder
 */
export function SkeletonCard({ className = '' }) {
  return (
    <div className={clsx('bg-white rounded-xl border border-gray-100 p-5', className)}>
      <div className="flex items-start justify-between mb-4">
        <div className="flex-1">
          <Skeleton height="0.75rem" width="40%" className="mb-2" />
          <Skeleton height="2rem" width="60%" />
        </div>
        <SkeletonCircle size={32} />
      </div>
      <Skeleton height="0.75rem" width="50%" />
    </div>
  );
}

/**
 * SkeletonStatsGrid - Stats cards skeleton
 */
export function SkeletonStatsGrid({ count = 5, className = '' }) {
  return (
    <div className={clsx('grid grid-cols-2 sm:grid-cols-3 lg:grid-cols-5 gap-4', className)}>
      {Array.from({ length: count }).map((_, i) => (
        <SkeletonCard key={i} />
      ))}
    </div>
  );
}

/**
 * SkeletonTableRow - Table row skeleton
 */
export function SkeletonTableRow({ columns = 5, hasCheckbox = false, className = '' }) {
  return (
    <tr className={clsx('border-b border-gray-100', className)}>
      {hasCheckbox && (
        <td className="px-4 py-3">
          <Skeleton width={18} height={18} rounded="sm" />
        </td>
      )}
      {Array.from({ length: columns }).map((_, i) => (
        <td key={i} className="px-4 py-3">
          <Skeleton 
            height="0.875rem" 
            width={i === 0 ? '70%' : i === columns - 1 ? '50%' : '60%'} 
          />
        </td>
      ))}
    </tr>
  );
}

/**
 * SkeletonTable - Full table skeleton
 */
export function SkeletonTable({ 
  rows = 5, 
  columns = 5, 
  hasCheckbox = false,
  showHeader = true,
  className = '',
}) {
  return (
    <div className={clsx('bg-white rounded-xl border border-gray-200 overflow-hidden', className)}>
      <table className="min-w-full">
        {showHeader && (
          <thead className="bg-gray-50">
            <tr>
              {hasCheckbox && (
                <th className="px-4 py-3 w-12">
                  <Skeleton width={18} height={18} rounded="sm" />
                </th>
              )}
              {Array.from({ length: columns }).map((_, i) => (
                <th key={i} className="px-4 py-3 text-left">
                  <Skeleton height="0.75rem" width={`${40 + (i * 10) % 30}%`} />
                </th>
              ))}
            </tr>
          </thead>
        )}
        <tbody>
          {Array.from({ length: rows }).map((_, i) => (
            <SkeletonTableRow 
              key={i} 
              columns={columns} 
              hasCheckbox={hasCheckbox}
            />
          ))}
        </tbody>
      </table>
    </div>
  );
}

/**
 * SkeletonTabs - Tab navigation skeleton
 */
export function SkeletonTabs({ count = 4, className = '' }) {
  return (
    <div className={clsx('flex space-x-1 border-b border-gray-200 pb-1', className)}>
      {Array.from({ length: count }).map((_, i) => (
        <Skeleton 
          key={i} 
          width={`${80 + (i * 20) % 40}px`} 
          height="2rem" 
          rounded="lg"
        />
      ))}
    </div>
  );
}

/**
 * SkeletonFilterBar - Filter bar skeleton
 */
export function SkeletonFilterBar({ 
  showSearch = true, 
  filterCount = 2,
  className = '',
}) {
  return (
    <div className={clsx('flex flex-col sm:flex-row gap-3 mb-4', className)}>
      {showSearch && (
        <Skeleton height="2.5rem" className="flex-1 max-w-md" rounded="lg" />
      )}
      <div className="flex gap-2">
        {Array.from({ length: filterCount }).map((_, i) => (
          <Skeleton key={i} width="120px" height="2.5rem" rounded="lg" />
        ))}
      </div>
    </div>
  );
}

/**
 * SkeletonPage - Complete page skeleton
 */
export function SkeletonPage({ 
  showStats = true, 
  showTabs = true,
  showFilters = true,
  tableRows = 5,
  tableColumns = 5,
  className = '',
}) {
  return (
    <div className={clsx('px-4 sm:px-6 lg:px-8 py-6', className)}>
      {/* Header */}
      <div className="flex items-center justify-between mb-6">
        <div className="flex items-center gap-3">
          <SkeletonCircle size={32} />
          <div>
            <Skeleton width="200px" height="1.5rem" className="mb-2" />
            <Skeleton width="300px" height="0.875rem" />
          </div>
        </div>
        <div className="flex gap-2">
          <Skeleton width="100px" height="2.5rem" rounded="lg" />
          <Skeleton width="120px" height="2.5rem" rounded="lg" />
        </div>
      </div>

      {/* Stats */}
      {showStats && (
        <div className="mb-6">
          <SkeletonStatsGrid count={5} />
        </div>
      )}

      {/* Tabs */}
      {showTabs && (
        <div className="mb-4">
          <SkeletonTabs count={4} />
        </div>
      )}

      {/* Filters */}
      {showFilters && (
        <SkeletonFilterBar showSearch filterCount={3} />
      )}

      {/* Table */}
      <SkeletonTable rows={tableRows} columns={tableColumns} hasCheckbox />
    </div>
  );
}

/**
 * SkeletonForm - Form skeleton
 */
export function SkeletonForm({ fields = 6, columns = 2, className = '' }) {
  return (
    <div className={clsx('bg-white rounded-xl border border-gray-200 p-6', className)}>
      <div className={clsx(
        'grid gap-4',
        columns === 1 ? 'grid-cols-1' : 'grid-cols-1 sm:grid-cols-2'
      )}>
        {Array.from({ length: fields }).map((_, i) => (
          <div key={i} className={i === 0 ? 'sm:col-span-2' : ''}>
            <Skeleton height="0.75rem" width="30%" className="mb-2" />
            <Skeleton height="2.5rem" rounded="lg" />
          </div>
        ))}
      </div>
      <div className="flex justify-end gap-3 mt-6 pt-4 border-t border-gray-100">
        <Skeleton width="80px" height="2.5rem" rounded="lg" />
        <Skeleton width="100px" height="2.5rem" rounded="lg" />
      </div>
    </div>
  );
}

/**
 * SkeletonList - List items skeleton
 */
export function SkeletonList({ items = 5, showAvatar = true, className = '' }) {
  return (
    <div className={clsx('space-y-3', className)}>
      {Array.from({ length: items }).map((_, i) => (
        <div key={i} className="flex items-center gap-3 p-3 bg-white rounded-lg border border-gray-100">
          {showAvatar && <SkeletonCircle size={40} />}
          <div className="flex-1">
            <Skeleton height="0.875rem" width="50%" className="mb-2" />
            <Skeleton height="0.75rem" width="70%" />
          </div>
          <Skeleton width="60px" height="1.5rem" rounded="full" />
        </div>
      ))}
    </div>
  );
}

export default {
  Skeleton,
  SkeletonText,
  SkeletonCircle,
  SkeletonCard,
  SkeletonStatsGrid,
  SkeletonTableRow,
  SkeletonTable,
  SkeletonTabs,
  SkeletonFilterBar,
  SkeletonPage,
  SkeletonForm,
  SkeletonList,
};
