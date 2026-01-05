// file: src/components/ui/ActivityTimeline.jsx
// Unified Activity Timeline component for tracking entity activities

import { forwardRef } from 'react';
import { clsx } from 'clsx';

/**
 * Activity item types with their icons and colors
 */
const activityTypes = {
  email: {
    icon: (
      <svg className="w-4 h-4" fill="none" viewBox="0 0 24 24" stroke="currentColor">
        <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M3 8l7.89 5.26a2 2 0 002.22 0L21 8M5 19h14a2 2 0 002-2V7a2 2 0 00-2-2H5a2 2 0 00-2 2v10a2 2 0 002 2z" />
      </svg>
    ),
    bgColor: 'bg-blue-100',
    iconColor: 'text-blue-600',
    borderColor: 'border-blue-200',
  },
  call: {
    icon: (
      <svg className="w-4 h-4" fill="none" viewBox="0 0 24 24" stroke="currentColor">
        <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M3 5a2 2 0 012-2h3.28a1 1 0 01.948.684l1.498 4.493a1 1 0 01-.502 1.21l-2.257 1.13a11.042 11.042 0 005.516 5.516l1.13-2.257a1 1 0 011.21-.502l4.493 1.498a1 1 0 01.684.949V19a2 2 0 01-2 2h-1C9.716 21 3 14.284 3 6V5z" />
      </svg>
    ),
    bgColor: 'bg-green-100',
    iconColor: 'text-green-600',
    borderColor: 'border-green-200',
  },
  meeting: {
    icon: (
      <svg className="w-4 h-4" fill="none" viewBox="0 0 24 24" stroke="currentColor">
        <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M8 7V3m8 4V3m-9 8h10M5 21h14a2 2 0 002-2V7a2 2 0 00-2-2H5a2 2 0 00-2 2v12a2 2 0 002 2z" />
      </svg>
    ),
    bgColor: 'bg-purple-100',
    iconColor: 'text-purple-600',
    borderColor: 'border-purple-200',
  },
  note: {
    icon: (
      <svg className="w-4 h-4" fill="none" viewBox="0 0 24 24" stroke="currentColor">
        <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M11 5H6a2 2 0 00-2 2v11a2 2 0 002 2h11a2 2 0 002-2v-5m-1.414-9.414a2 2 0 112.828 2.828L11.828 15H9v-2.828l8.586-8.586z" />
      </svg>
    ),
    bgColor: 'bg-yellow-100',
    iconColor: 'text-yellow-600',
    borderColor: 'border-yellow-200',
  },
  task: {
    icon: (
      <svg className="w-4 h-4" fill="none" viewBox="0 0 24 24" stroke="currentColor">
        <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M9 5H7a2 2 0 00-2 2v12a2 2 0 002 2h10a2 2 0 002-2V7a2 2 0 00-2-2h-2M9 5a2 2 0 002 2h2a2 2 0 002-2M9 5a2 2 0 012-2h2a2 2 0 012 2m-6 9l2 2 4-4" />
      </svg>
    ),
    bgColor: 'bg-orange-100',
    iconColor: 'text-orange-600',
    borderColor: 'border-orange-200',
  },
  status_change: {
    icon: (
      <svg className="w-4 h-4" fill="none" viewBox="0 0 24 24" stroke="currentColor">
        <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M9 12l2 2 4-4m6 2a9 9 0 11-18 0 9 9 0 0118 0z" />
      </svg>
    ),
    bgColor: 'bg-teal-100',
    iconColor: 'text-teal-600',
    borderColor: 'border-teal-200',
  },
  document: {
    icon: (
      <svg className="w-4 h-4" fill="none" viewBox="0 0 24 24" stroke="currentColor">
        <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M9 12h6m-6 4h6m2 5H7a2 2 0 01-2-2V5a2 2 0 012-2h5.586a1 1 0 01.707.293l5.414 5.414a1 1 0 01.293.707V19a2 2 0 01-2 2z" />
      </svg>
    ),
    bgColor: 'bg-gray-100',
    iconColor: 'text-gray-600',
    borderColor: 'border-gray-200',
  },
  payment: {
    icon: (
      <svg className="w-4 h-4" fill="none" viewBox="0 0 24 24" stroke="currentColor">
        <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M12 8c-1.657 0-3 .895-3 2s1.343 2 3 2 3 .895 3 2-1.343 2-3 2m0-8c1.11 0 2.08.402 2.599 1M12 8V7m0 1v8m0 0v1m0-1c-1.11 0-2.08-.402-2.599-1M21 12a9 9 0 11-18 0 9 9 0 0118 0z" />
      </svg>
    ),
    bgColor: 'bg-emerald-100',
    iconColor: 'text-emerald-600',
    borderColor: 'border-emerald-200',
  },
  approval: {
    icon: (
      <svg className="w-4 h-4" fill="none" viewBox="0 0 24 24" stroke="currentColor">
        <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M9 12l2 2 4-4M7.835 4.697a3.42 3.42 0 001.946-.806 3.42 3.42 0 014.438 0 3.42 3.42 0 001.946.806 3.42 3.42 0 013.138 3.138 3.42 3.42 0 00.806 1.946 3.42 3.42 0 010 4.438 3.42 3.42 0 00-.806 1.946 3.42 3.42 0 01-3.138 3.138 3.42 3.42 0 00-1.946.806 3.42 3.42 0 01-4.438 0 3.42 3.42 0 00-1.946-.806 3.42 3.42 0 01-3.138-3.138 3.42 3.42 0 00-.806-1.946 3.42 3.42 0 010-4.438 3.42 3.42 0 00.806-1.946 3.42 3.42 0 013.138-3.138z" />
      </svg>
    ),
    bgColor: 'bg-indigo-100',
    iconColor: 'text-indigo-600',
    borderColor: 'border-indigo-200',
  },
  created: {
    icon: (
      <svg className="w-4 h-4" fill="none" viewBox="0 0 24 24" stroke="currentColor">
        <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M12 6v6m0 0v6m0-6h6m-6 0H6" />
      </svg>
    ),
    bgColor: 'bg-cogentix-orange-100',
    iconColor: 'text-cogentix-orange',
    borderColor: 'border-cogentix-orange-200',
  },
};

/**
 * Format relative time (e.g., "2 hours ago", "Yesterday")
 */
function formatRelativeTime(date) {
  const now = new Date();
  const then = new Date(date);
  const diffMs = now - then;
  const diffMins = Math.floor(diffMs / 60000);
  const diffHours = Math.floor(diffMs / 3600000);
  const diffDays = Math.floor(diffMs / 86400000);

  if (diffMins < 1) return 'Just now';
  if (diffMins < 60) return `${diffMins}m ago`;
  if (diffHours < 24) return `${diffHours}h ago`;
  if (diffDays === 1) return 'Yesterday';
  if (diffDays < 7) return `${diffDays} days ago`;
  
  return then.toLocaleDateString('en-US', {
    month: 'short',
    day: 'numeric',
    year: then.getFullYear() !== now.getFullYear() ? 'numeric' : undefined,
  });
}

/**
 * Format absolute time for tooltip
 */
function formatAbsoluteTime(date) {
  return new Date(date).toLocaleString('en-US', {
    weekday: 'short',
    month: 'short',
    day: 'numeric',
    year: 'numeric',
    hour: 'numeric',
    minute: '2-digit',
  });
}

/**
 * Single Activity Item
 */
const ActivityItem = forwardRef(({
  activity,
  isLast = false,
  showLine = true,
  compact = false,
  onClick,
}, ref) => {
  const typeConfig = activityTypes[activity.type] || activityTypes.note;
  
  return (
    <div 
      ref={ref}
      className={clsx(
        'relative flex gap-3',
        onClick && 'cursor-pointer hover:bg-gray-50 rounded-lg -mx-2 px-2 py-1 transition-colors',
        compact ? 'pb-3' : 'pb-4'
      )}
      onClick={() => onClick?.(activity)}
    >
      {/* Timeline line */}
      {showLine && !isLast && (
        <div 
          className="absolute left-4 top-8 w-0.5 bg-gray-200" 
          style={{ height: 'calc(100% - 8px)' }}
        />
      )}
      
      {/* Icon */}
      <div className={clsx(
        'relative z-10 flex-shrink-0 w-8 h-8 rounded-full flex items-center justify-center',
        typeConfig.bgColor,
        typeConfig.iconColor
      )}>
        {typeConfig.icon}
      </div>
      
      {/* Content */}
      <div className="flex-1 min-w-0">
        <div className="flex items-start justify-between gap-2">
          <div className="flex-1 min-w-0">
            {/* Title */}
            <p className={clsx(
              'text-gray-900 font-medium truncate',
              compact ? 'text-sm' : 'text-base'
            )}>
              {activity.title}
            </p>
            
            {/* Description */}
            {activity.description && !compact && (
              <p className="mt-0.5 text-sm text-gray-600 line-clamp-2">
                {activity.description}
              </p>
            )}
            
            {/* Meta info */}
            <div className={clsx(
              'flex items-center gap-2 text-gray-500',
              compact ? 'mt-0.5 text-xs' : 'mt-1 text-sm'
            )}>
              {activity.user && (
                <>
                  <span className="font-medium">{activity.user}</span>
                  <span>•</span>
                </>
              )}
              <time 
                dateTime={activity.timestamp}
                title={formatAbsoluteTime(activity.timestamp)}
              >
                {formatRelativeTime(activity.timestamp)}
              </time>
            </div>
          </div>
          
          {/* Type badge */}
          {!compact && (
            <span className={clsx(
              'flex-shrink-0 px-2 py-0.5 text-xs font-medium rounded-full capitalize',
              typeConfig.bgColor,
              typeConfig.iconColor
            )}>
              {activity.type.replace('_', ' ')}
            </span>
          )}
        </div>
        
        {/* Attachments */}
        {activity.attachments?.length > 0 && !compact && (
          <div className="mt-2 flex flex-wrap gap-2">
            {activity.attachments.map((attachment, idx) => (
              <a
                key={idx}
                href={attachment.url}
                className="inline-flex items-center gap-1 px-2 py-1 text-xs text-gray-600 bg-gray-100 rounded hover:bg-gray-200 transition-colors"
                target="_blank"
                rel="noopener noreferrer"
              >
                <svg className="w-3 h-3" fill="none" viewBox="0 0 24 24" stroke="currentColor">
                  <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M15.172 7l-6.586 6.586a2 2 0 102.828 2.828l6.414-6.586a4 4 0 00-5.656-5.656l-6.415 6.585a6 6 0 108.486 8.486L20.5 13" />
                </svg>
                {attachment.name}
              </a>
            ))}
          </div>
        )}
      </div>
    </div>
  );
});

ActivityItem.displayName = 'ActivityItem';

/**
 * Activity Timeline Component
 * Displays a chronological list of activities for an entity
 * 
 * @param {Array} activities - Array of activity objects
 * @param {boolean} compact - Use compact display mode
 * @param {boolean} showLine - Show connecting line between items
 * @param {number} maxItems - Maximum items to show initially
 * @param {function} onItemClick - Callback when an item is clicked
 * @param {function} onLoadMore - Callback to load more activities
 * @param {boolean} loading - Loading state
 * @param {string} emptyMessage - Message when no activities
 */
const ActivityTimeline = forwardRef(({
  activities = [],
  compact = false,
  showLine = true,
  maxItems = 10,
  onItemClick,
  onLoadMore,
  hasMore = false,
  loading = false,
  emptyMessage = 'No activities yet',
  className = '',
}, ref) => {
  const displayedActivities = activities.slice(0, maxItems);
  const hasHiddenItems = activities.length > maxItems || hasMore;
  
  if (loading && activities.length === 0) {
    return (
      <div ref={ref} className={clsx('space-y-4', className)}>
        {[1, 2, 3].map((i) => (
          <div key={i} className="flex gap-3 animate-pulse">
            <div className="w-8 h-8 bg-gray-200 rounded-full" />
            <div className="flex-1 space-y-2">
              <div className="h-4 bg-gray-200 rounded w-3/4" />
              <div className="h-3 bg-gray-100 rounded w-1/2" />
            </div>
          </div>
        ))}
      </div>
    );
  }
  
  if (activities.length === 0) {
    return (
      <div 
        ref={ref}
        className={clsx(
          'flex flex-col items-center justify-center py-8 text-center',
          className
        )}
      >
        <div className="w-12 h-12 bg-gray-100 rounded-full flex items-center justify-center mb-3">
          <svg className="w-6 h-6 text-gray-400" fill="none" viewBox="0 0 24 24" stroke="currentColor">
            <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M12 8v4l3 3m6-3a9 9 0 11-18 0 9 9 0 0118 0z" />
          </svg>
        </div>
        <p className="text-gray-500">{emptyMessage}</p>
      </div>
    );
  }
  
  return (
    <div ref={ref} className={className}>
      <div className={clsx(compact ? 'space-y-0' : 'space-y-1')}>
        {displayedActivities.map((activity, index) => (
          <ActivityItem
            key={activity.id || index}
            activity={activity}
            isLast={index === displayedActivities.length - 1 && !hasHiddenItems}
            showLine={showLine}
            compact={compact}
            onClick={onItemClick}
          />
        ))}
      </div>
      
      {/* Load More */}
      {hasHiddenItems && (
        <div className="mt-4 pt-4 border-t border-gray-100">
          <button
            onClick={onLoadMore}
            disabled={loading}
            className={clsx(
              'w-full py-2 text-sm font-medium text-cogentix-orange rounded-lg',
              'hover:bg-cogentix-orange-50 transition-colors',
              'focus:outline-none focus:ring-2 focus:ring-cogentix-orange-400',
              loading && 'opacity-50 cursor-not-allowed'
            )}
          >
            {loading ? (
              <span className="flex items-center justify-center gap-2">
                <svg className="animate-spin h-4 w-4" fill="none" viewBox="0 0 24 24">
                  <circle className="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" strokeWidth="4" />
                  <path className="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4zm2 5.291A7.962 7.962 0 014 12H0c0 3.042 1.135 5.824 3 7.938l3-2.647z" />
                </svg>
                Loading...
              </span>
            ) : (
              `Show more activities`
            )}
          </button>
        </div>
      )}
    </div>
  );
});

ActivityTimeline.displayName = 'ActivityTimeline';

/**
 * ActivityTimelineHeader - Optional header for the timeline section
 */
const ActivityTimelineHeader = ({
  title = 'Activity',
  onAddActivity,
  activityTypeOptions = [],
  className = '',
}) => (
  <div className={clsx('flex items-center justify-between mb-4', className)}>
    <h3 className="text-lg font-semibold text-gray-900">{title}</h3>
    {onAddActivity && (
      <button
        onClick={onAddActivity}
        className={clsx(
          'inline-flex items-center gap-1.5 px-3 py-1.5 text-sm font-medium',
          'text-cogentix-orange border border-cogentix-orange rounded-lg',
          'hover:bg-cogentix-orange-50 transition-colors'
        )}
      >
        <svg className="w-4 h-4" fill="none" viewBox="0 0 24 24" stroke="currentColor">
          <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M12 4v16m8-8H4" />
        </svg>
        Log Activity
      </button>
    )}
  </div>
);

export { ActivityTimeline, ActivityItem, ActivityTimelineHeader, activityTypes };
export default ActivityTimeline;
