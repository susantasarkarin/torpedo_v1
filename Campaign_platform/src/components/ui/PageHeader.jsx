// file: src/components/ui/PageHeader.jsx
import { clsx } from 'clsx';
import Button from './Button';

export function PageHeader({
  title,
  subtitle,
  breadcrumbs = [],
  actions,
  className = '',
}) {
  return (
    <div className={clsx('mb-6', className)}>
      {/* Breadcrumbs */}
      {breadcrumbs.length > 0 && (
        <nav className="flex mb-3" aria-label="Breadcrumb">
          <ol className="flex items-center space-x-2 text-sm">
            {breadcrumbs.map((crumb, index) => (
              <li key={index} className="flex items-center">
                {index > 0 && (
                  <svg className="w-4 h-4 text-text-light mx-2" fill="none" viewBox="0 0 24 24" stroke="currentColor">
                    <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M9 5l7 7-7 7" />
                  </svg>
                )}
                {crumb.href ? (
                  <a 
                    href={crumb.href} 
                    className="text-text-muted hover:text-cogentix-orange transition-colors"
                  >
                    {crumb.label}
                  </a>
                ) : (
                  <span className="text-text-primary font-medium">{crumb.label}</span>
                )}
              </li>
            ))}
          </ol>
        </nav>
      )}

      {/* Header content */}
      <div className="flex flex-col sm:flex-row sm:items-center sm:justify-between gap-4">
        <div>
          <h1 className="text-2xl font-bold text-text-primary">{title}</h1>
          {subtitle && (
            <p className="mt-1 text-sm text-text-muted">{subtitle}</p>
          )}
        </div>
        {actions && (
          <div className="flex items-center gap-3">
            {actions}
          </div>
        )}
      </div>
    </div>
  );
}

// Quick action button for page headers
export function QuickAction({ label, icon, onClick, variant = 'primary' }) {
  return (
    <Button variant={variant} leftIcon={icon} onClick={onClick}>
      {label}
    </Button>
  );
}

export default PageHeader;
