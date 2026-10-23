// file: src/components/ui/FilterChip.jsx
// Pill-shaped filter buttons and a list/board style toggle (CRM mockup).
// Styles live in styles/shell.css (.cx-chip, .cx-view-toggle).
import { clsx } from 'clsx';

export function FilterChip({ active = false, children, className = '', ...props }) {
  return (
    <button type="button" aria-pressed={active} className={clsx('cx-chip', active && 'is-active', className)} {...props}>
      {children}
    </button>
  );
}

// options: [{ value, label }]
export function FilterChips({ options = [], value, onChange, className = '' }) {
  return (
    <div className={clsx('cx-toolbar-group', className)} role="group">
      {options.map((o) => (
        <FilterChip key={o.value} active={o.value === value} onClick={() => onChange?.(o.value)}>
          {o.label}
        </FilterChip>
      ))}
    </div>
  );
}

export function ViewToggle({ options = [], value, onChange, className = '' }) {
  return (
    <div className={clsx('cx-view-toggle', className)} role="group">
      {options.map((o) => (
        <button
          key={o.value}
          type="button"
          aria-pressed={o.value === value}
          className={o.value === value ? 'is-active' : undefined}
          onClick={() => onChange?.(o.value)}
        >
          {o.label}
        </button>
      ))}
    </div>
  );
}

export function Toolbar({ left, right, className = '' }) {
  return (
    <div className={clsx('cx-toolbar', className)}>
      <div className="cx-toolbar-group">{left}</div>
      {right && <div className="cx-toolbar-group">{right}</div>}
    </div>
  );
}

export default FilterChip;
