// file: src/components/ui/EmptyState.jsx
import { clsx } from 'clsx';
import Button from './Button';

export function EmptyState({
  icon,
  title,
  description,
  action,
  actionLabel,
  onAction,
  secondaryAction,
  secondaryActionLabel,
  onSecondaryAction,
  className = '',
}) {
  const defaultIcon = (
    <svg className="w-16 h-16 text-slate-300" fill="none" viewBox="0 0 24 24" stroke="currentColor">
      <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={1} d="M20 13V6a2 2 0 00-2-2H6a2 2 0 00-2 2v7m16 0v5a2 2 0 01-2 2H6a2 2 0 01-2-2v-5m16 0h-2.586a1 1 0 00-.707.293l-2.414 2.414a1 1 0 01-.707.293h-3.172a1 1 0 01-.707-.293l-2.414-2.414A1 1 0 006.586 13H4" />
    </svg>
  );

  return (
    <div className={clsx('flex flex-col items-center justify-center py-12 px-4 text-center', className)}>
      <div className="mb-4">
        {icon || defaultIcon}
      </div>
      <h3 className="text-lg font-semibold text-text-primary mb-2">
        {title}
      </h3>
      {description && (
        <p className="text-sm text-text-muted max-w-sm mb-6">
          {description}
        </p>
      )}
      {(action || actionLabel) && (
        <div className="flex items-center gap-3">
          {action || (
            <Button variant="primary" onClick={onAction}>
              {actionLabel}
            </Button>
          )}
          {(secondaryAction || secondaryActionLabel) && (
            secondaryAction || (
              <Button variant="outline" onClick={onSecondaryAction}>
                {secondaryActionLabel}
              </Button>
            )
          )}
        </div>
      )}
    </div>
  );
}

// Specific empty states for common use cases
export function NoResultsState({ searchTerm, onClear }) {
  return (
    <EmptyState
      icon={
        <svg className="w-16 h-16 text-slate-300" fill="none" viewBox="0 0 24 24" stroke="currentColor">
          <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={1} d="M21 21l-6-6m2-5a7 7 0 11-14 0 7 7 0 0114 0z" />
        </svg>
      }
      title={`No results for "${searchTerm}"`}
      description="Try adjusting your search or filter to find what you're looking for."
      actionLabel="Clear search"
      onAction={onClear}
    />
  );
}

export function NoDataState({ entity = 'items', onAdd }) {
  return (
    <EmptyState
      icon={
        <svg className="w-16 h-16 text-slate-300" fill="none" viewBox="0 0 24 24" stroke="currentColor">
          <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={1} d="M12 6v6m0 0v6m0-6h6m-6 0H6" />
        </svg>
      }
      title={`No ${entity} yet`}
      description={`Get started by creating your first ${entity.slice(0, -1)}.`}
      actionLabel={`Add ${entity.slice(0, -1)}`}
      onAction={onAdd}
    />
  );
}

export default EmptyState;
