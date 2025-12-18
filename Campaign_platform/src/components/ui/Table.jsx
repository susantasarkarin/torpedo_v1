// file: src/components/ui/Table.jsx
import { clsx } from 'clsx';

export function Table({ children, className = '' }) {
  return (
    <div className="overflow-x-auto rounded-xl border border-slate-200 bg-white">
      <table className={clsx('min-w-full divide-y divide-slate-200', className)}>
        {children}
      </table>
    </div>
  );
}

export function TableHead({ children, className = '' }) {
  return (
    <thead className={clsx('bg-slate-50', className)}>
      {children}
    </thead>
  );
}

export function TableBody({ children, className = '' }) {
  return (
    <tbody className={clsx('divide-y divide-slate-100 bg-white', className)}>
      {children}
    </tbody>
  );
}

export function TableRow({ children, className = '', hover = true, selected = false, onClick }) {
  return (
    <tr
      onClick={onClick}
      className={clsx(
        'transition-colors',
        hover && 'hover:bg-slate-50',
        selected && 'bg-cogentix-orange-50',
        onClick && 'cursor-pointer',
        className
      )}
    >
      {children}
    </tr>
  );
}

export function TableHeaderCell({ 
  children, 
  className = '', 
  sortable = false,
  sortDirection,
  onSort,
  align = 'left',
}) {
  const alignClasses = {
    left: 'text-left',
    center: 'text-center',
    right: 'text-right',
  };

  return (
    <th
      scope="col"
      onClick={sortable ? onSort : undefined}
      className={clsx(
        'px-4 py-3 text-xs font-semibold text-text-secondary uppercase tracking-wider',
        alignClasses[align],
        sortable && 'cursor-pointer hover:text-cogentix-navy select-none',
        className
      )}
    >
      <div className="flex items-center gap-1.5">
        {children}
        {sortable && (
          <span className="inline-flex flex-col">
            <svg 
              className={clsx(
                'w-3 h-3 -mb-1',
                sortDirection === 'asc' ? 'text-cogentix-navy' : 'text-slate-300'
              )} 
              fill="currentColor" 
              viewBox="0 0 20 20"
            >
              <path d="M10 3l-7 7h14l-7-7z" />
            </svg>
            <svg 
              className={clsx(
                'w-3 h-3',
                sortDirection === 'desc' ? 'text-cogentix-navy' : 'text-slate-300'
              )} 
              fill="currentColor" 
              viewBox="0 0 20 20"
            >
              <path d="M10 17l7-7H3l7 7z" />
            </svg>
          </span>
        )}
      </div>
    </th>
  );
}

export function TableCell({ children, className = '', align = 'left' }) {
  const alignClasses = {
    left: 'text-left',
    center: 'text-center',
    right: 'text-right',
  };

  return (
    <td className={clsx('px-4 py-4 text-sm text-text-primary whitespace-nowrap', alignClasses[align], className)}>
      {children}
    </td>
  );
}

// Empty state for tables
export function TableEmptyState({ 
  title = 'No data found',
  description = 'Try adjusting your search or filters.',
  action,
  colSpan = 1,
}) {
  return (
    <tr>
      <td colSpan={colSpan} className="px-4 py-12 text-center">
        <div className="flex flex-col items-center">
          <svg className="w-12 h-12 text-slate-300 mb-4" fill="none" viewBox="0 0 24 24" stroke="currentColor">
            <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={1.5} d="M9.172 16.172a4 4 0 015.656 0M9 10h.01M15 10h.01M21 12a9 9 0 11-18 0 9 9 0 0118 0z" />
          </svg>
          <h3 className="text-sm font-medium text-text-primary">{title}</h3>
          <p className="mt-1 text-sm text-text-muted">{description}</p>
          {action && <div className="mt-4">{action}</div>}
        </div>
      </td>
    </tr>
  );
}

export {
  TableRow as TRow,
  TableCell as TCell,
  TableHeaderCell as THeader,
  TableHead as THead,
  TableBody as TBody,
};

export default Table;
