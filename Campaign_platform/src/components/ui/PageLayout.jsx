/**
 * PageContainer - Unified container for all page layouts
 * Provides consistent spacing, max-width, and responsive behavior
 */
import { clsx } from 'clsx';

export function PageContainer({ 
  children, 
  className = '',
  fullWidth = false,
  noPadding = false,
}) {
  return (
    <div 
      className={clsx(
        'page-container',
        !fullWidth && 'max-w-7xl mx-auto',
        !noPadding && 'px-4 sm:px-6 lg:px-8 py-6',
        className
      )}
    >
      {children}
    </div>
  );
}

/**
 * PageHeader - Consistent page header with title, subtitle, and actions
 */
export function PageHeader({
  icon,
  title,
  subtitle,
  actions,
  backButton,
  className = '',
}) {
  return (
    <div className={clsx('page-header mb-6', className)}>
      <div className="flex flex-col sm:flex-row sm:items-center sm:justify-between gap-4">
        <div className="flex items-center gap-3">
          {backButton && (
            <button
              onClick={backButton.onClick}
              className="inline-flex items-center gap-1 px-3 py-1.5 text-sm font-medium text-gray-600 bg-white border border-gray-200 rounded-lg hover:bg-gray-50 hover:text-gray-800 transition-colors"
            >
              <svg className="w-4 h-4" fill="none" viewBox="0 0 24 24" stroke="currentColor">
                <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M10 19l-7-7m0 0l7-7m-7 7h18" />
              </svg>
              {backButton.label || 'Back'}
            </button>
          )}
          {icon && (
            <span className="text-2xl">{icon}</span>
          )}
          <div>
            <h1 className="text-xl sm:text-2xl font-bold text-gray-900">{title}</h1>
            {subtitle && (
              <p className="mt-1 text-sm text-gray-500">{subtitle}</p>
            )}
          </div>
        </div>
        {actions && (
          <div className="flex items-center gap-2 sm:gap-3 flex-wrap">
            {actions}
          </div>
        )}
      </div>
    </div>
  );
}

/**
 * PageContent - Main content area with consistent styling
 */
export function PageContent({ 
  children, 
  className = '',
  loading = false,
  error = null,
}) {
  if (loading) {
    return <PageLoading />;
  }

  if (error) {
    return <PageError message={error} />;
  }

  return (
    <div className={clsx('page-content', className)}>
      {children}
    </div>
  );
}

/**
 * PageLoading - Unified loading state
 */
export function PageLoading({ message = 'Loading...' }) {
  return (
    <div className="flex flex-col items-center justify-center py-16">
      <div className="relative">
        <div className="w-12 h-12 border-4 border-orange-200 rounded-full animate-spin border-t-orange-500"></div>
      </div>
      <p className="mt-4 text-sm text-gray-500">{message}</p>
    </div>
  );
}

/**
 * PageError - Unified error state
 */
export function PageError({ 
  message = 'Something went wrong', 
  onRetry,
  className = '' 
}) {
  return (
    <div className={clsx('flex flex-col items-center justify-center py-16', className)}>
      <div className="w-16 h-16 bg-red-100 rounded-full flex items-center justify-center mb-4">
        <svg className="w-8 h-8 text-red-500" fill="none" viewBox="0 0 24 24" stroke="currentColor">
          <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M12 9v2m0 4h.01m-6.938 4h13.856c1.54 0 2.502-1.667 1.732-3L13.732 4c-.77-1.333-2.694-1.333-3.464 0L3.34 16c-.77 1.333.192 3 1.732 3z" />
        </svg>
      </div>
      <p className="text-gray-600 text-center max-w-md">{message}</p>
      {onRetry && (
        <button
          onClick={onRetry}
          className="mt-4 px-4 py-2 text-sm font-medium text-white bg-orange-500 rounded-lg hover:bg-orange-600 transition-colors"
        >
          Try Again
        </button>
      )}
    </div>
  );
}

/**
 * PageEmpty - Empty state component
 */
export function PageEmpty({
  icon,
  title = 'No data found',
  description,
  action,
  className = '',
}) {
  return (
    <div className={clsx('flex flex-col items-center justify-center py-16', className)}>
      {icon ? (
        <span className="text-5xl mb-4">{icon}</span>
      ) : (
        <div className="w-16 h-16 bg-gray-100 rounded-full flex items-center justify-center mb-4">
          <svg className="w-8 h-8 text-gray-400" fill="none" viewBox="0 0 24 24" stroke="currentColor">
            <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={1.5} d="M20 13V6a2 2 0 00-2-2H6a2 2 0 00-2 2v7m16 0v5a2 2 0 01-2 2H6a2 2 0 01-2-2v-5m16 0h-2.586a1 1 0 00-.707.293l-2.414 2.414a1 1 0 01-.707.293h-3.172a1 1 0 01-.707-.293l-2.414-2.414A1 1 0 006.586 13H4" />
          </svg>
        </div>
      )}
      <h3 className="text-lg font-medium text-gray-900">{title}</h3>
      {description && (
        <p className="mt-1 text-sm text-gray-500 text-center max-w-md">{description}</p>
      )}
      {action && (
        <div className="mt-4">{action}</div>
      )}
    </div>
  );
}

/**
 * StatsCard - Consistent stats/metric card
 */
export function StatsCard({
  title,
  value,
  subtitle,
  icon,
  trend,
  trendDirection = 'up',
  color = 'orange',
  className = '',
}) {
  const colorClasses = {
    orange: 'border-orange-200 bg-orange-50',
    green: 'border-green-200 bg-green-50',
    blue: 'border-blue-200 bg-blue-50',
    purple: 'border-purple-200 bg-purple-50',
    red: 'border-red-200 bg-red-50',
    gray: 'border-gray-200 bg-gray-50',
  };

  const valueColorClasses = {
    orange: 'text-orange-600',
    green: 'text-green-600',
    blue: 'text-blue-600',
    purple: 'text-purple-600',
    red: 'text-red-600',
    gray: 'text-gray-600',
  };

  return (
    <div className={clsx(
      'bg-white rounded-xl border p-4 sm:p-5 transition-shadow hover:shadow-md',
      colorClasses[color],
      className
    )}>
      <div className="flex items-start justify-between">
        <div className="flex-1 min-w-0">
          <p className="text-xs sm:text-sm font-medium text-gray-500 uppercase tracking-wide truncate">
            {title}
          </p>
          <p className={clsx('mt-2 text-2xl sm:text-3xl font-bold', valueColorClasses[color])}>
            {value}
          </p>
          {subtitle && (
            <p className="mt-1 text-xs sm:text-sm text-gray-500">{subtitle}</p>
          )}
        </div>
        {icon && (
          <span className="text-2xl sm:text-3xl opacity-80">{icon}</span>
        )}
      </div>
      {trend && (
        <div className={clsx(
          'mt-2 inline-flex items-center text-xs sm:text-sm font-medium',
          trendDirection === 'up' ? 'text-green-600' : 'text-red-600'
        )}>
          {trendDirection === 'up' ? '↑' : '↓'} {trend}
        </div>
      )}
    </div>
  );
}

/**
 * StatsGrid - Grid container for stats cards
 */
export function StatsGrid({ children, columns = 5, className = '' }) {
  const colClasses = {
    2: 'grid-cols-1 sm:grid-cols-2',
    3: 'grid-cols-1 sm:grid-cols-2 lg:grid-cols-3',
    4: 'grid-cols-1 sm:grid-cols-2 lg:grid-cols-4',
    5: 'grid-cols-2 sm:grid-cols-3 lg:grid-cols-5',
    6: 'grid-cols-2 sm:grid-cols-3 lg:grid-cols-6',
  };

  return (
    <div className={clsx('grid gap-4', colClasses[columns] || colClasses[4], className)}>
      {children}
    </div>
  );
}

/**
 * TabsContainer - Consistent tab navigation
 */
export function TabsContainer({ tabs, activeTab, onTabChange, className = '' }) {
  return (
    <div className={clsx('border-b border-gray-200', className)}>
      <nav className="flex space-x-1 overflow-x-auto scrollbar-hide">
        {tabs.map((tab) => (
          <button
            key={tab.id}
            onClick={() => onTabChange(tab.id)}
            className={clsx(
              'px-4 py-2.5 text-sm font-medium whitespace-nowrap transition-colors rounded-t-lg',
              activeTab === tab.id
                ? 'text-orange-600 border-b-2 border-orange-500 bg-orange-50'
                : 'text-gray-500 hover:text-gray-700 hover:bg-gray-50'
            )}
          >
            {tab.label}
            {tab.count !== undefined && (
              <span className={clsx(
                'ml-2 px-2 py-0.5 text-xs rounded-full',
                activeTab === tab.id
                  ? 'bg-orange-100 text-orange-600'
                  : 'bg-gray-100 text-gray-500'
              )}>
                {tab.count}
              </span>
            )}
          </button>
        ))}
      </nav>
    </div>
  );
}

/**
 * FilterBar - Consistent filter/search bar
 */
export function FilterBar({ 
  searchValue,
  onSearchChange,
  searchPlaceholder = 'Search...',
  filters = [],
  actions,
  className = '',
}) {
  return (
    <div className={clsx('flex flex-col sm:flex-row gap-3 mb-4', className)}>
      {/* Search input */}
      <div className="relative flex-1 min-w-0 max-w-md">
        <span className="absolute inset-y-0 left-0 flex items-center pl-3">
          <svg className="w-4 h-4 text-gray-400" fill="none" viewBox="0 0 24 24" stroke="currentColor">
            <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M21 21l-6-6m2-5a7 7 0 11-14 0 7 7 0 0114 0z" />
          </svg>
        </span>
        <input
          type="text"
          value={searchValue}
          onChange={(e) => onSearchChange(e.target.value)}
          placeholder={searchPlaceholder}
          className="w-full pl-10 pr-4 py-2 text-sm border border-gray-200 rounded-lg focus:outline-none focus:ring-2 focus:ring-orange-500 focus:border-transparent"
        />
      </div>

      {/* Filters */}
      {filters.length > 0 && (
        <div className="flex items-center gap-2 flex-wrap">
          {filters.map((filter, index) => (
            <select
              key={index}
              value={filter.value}
              onChange={(e) => filter.onChange(e.target.value)}
              className="px-3 py-2 text-sm border border-gray-200 rounded-lg bg-white focus:outline-none focus:ring-2 focus:ring-orange-500"
            >
              {filter.options.map((option) => (
                <option key={option.value} value={option.value}>
                  {option.label}
                </option>
              ))}
            </select>
          ))}
        </div>
      )}

      {/* Actions */}
      {actions && (
        <div className="flex items-center gap-2 sm:ml-auto">
          {actions}
        </div>
      )}
    </div>
  );
}

/**
 * ActionButton - Consistent action button styles
 */
export function ActionButton({
  children,
  variant = 'primary',
  size = 'md',
  icon,
  onClick,
  disabled = false,
  loading = false,
  className = '',
}) {
  const variants = {
    primary: 'bg-orange-500 text-white hover:bg-orange-600 disabled:bg-orange-300',
    secondary: 'bg-white text-gray-700 border border-gray-200 hover:bg-gray-50 disabled:bg-gray-100',
    success: 'bg-green-500 text-white hover:bg-green-600 disabled:bg-green-300',
    danger: 'bg-red-500 text-white hover:bg-red-600 disabled:bg-red-300',
    ghost: 'text-gray-600 hover:bg-gray-100 disabled:text-gray-400',
  };

  const sizes = {
    sm: 'px-3 py-1.5 text-xs',
    md: 'px-4 py-2 text-sm',
    lg: 'px-5 py-2.5 text-base',
  };

  return (
    <button
      onClick={onClick}
      disabled={disabled || loading}
      className={clsx(
        'inline-flex items-center justify-center gap-2 font-medium rounded-lg transition-colors focus:outline-none focus:ring-2 focus:ring-orange-500 focus:ring-offset-2 disabled:cursor-not-allowed',
        variants[variant],
        sizes[size],
        className
      )}
    >
      {loading ? (
        <svg className="w-4 h-4 animate-spin" fill="none" viewBox="0 0 24 24">
          <circle className="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" strokeWidth="4" />
          <path className="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4zm2 5.291A7.962 7.962 0 014 12H0c0 3.042 1.135 5.824 3 7.938l3-2.647z" />
        </svg>
      ) : icon ? (
        <span className="w-4 h-4">{icon}</span>
      ) : null}
      {children}
    </button>
  );
}

export default {
  PageContainer,
  PageHeader,
  PageContent,
  PageLoading,
  PageError,
  PageEmpty,
  StatsCard,
  StatsGrid,
  TabsContainer,
  FilterBar,
  ActionButton,
};
