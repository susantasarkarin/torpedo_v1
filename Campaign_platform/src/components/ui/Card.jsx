// file: src/components/ui/Card.jsx
import { clsx } from 'clsx';

export function Card({ 
  children, 
  className = '', 
  padding = 'md',
  hover = false,
  ...props 
}) {
  const paddingClasses = {
    none: '',
    sm: 'p-4',
    md: 'p-6',
    lg: 'p-8',
  };

  return (
    <div
      className={clsx(
        'bg-white rounded-xl border border-slate-100 shadow-card',
        paddingClasses[padding],
        hover && 'transition-all duration-200 hover:shadow-card-hover hover:-translate-y-0.5',
        className
      )}
      {...props}
    >
      {children}
    </div>
  );
}

export function CardHeader({ 
  title, 
  subtitle, 
  action,
  className = '' 
}) {
  return (
    <div className={clsx('flex items-start justify-between mb-4', className)}>
      <div>
        {title && (
          <h3 className="text-base font-semibold text-text-primary">
            {title}
          </h3>
        )}
        {subtitle && (
          <p className="text-sm text-text-muted mt-0.5">
            {subtitle}
          </p>
        )}
      </div>
      {action && <div>{action}</div>}
    </div>
  );
}

export function CardContent({ children, className = '' }) {
  return (
    <div className={clsx('', className)}>
      {children}
    </div>
  );
}

export function CardFooter({ children, className = '' }) {
  return (
    <div className={clsx('mt-4 pt-4 border-t border-slate-100', className)}>
      {children}
    </div>
  );
}

// KPI Card variant for dashboard metrics
export function KPICard({
  title,
  value,
  subtitle,
  icon,
  trend,
  trendDirection = 'up',
  className = '',
}) {
  return (
    <Card className={clsx('relative overflow-hidden', className)} hover>
      <div className="flex items-start justify-between">
        <div className="flex-1">
          <p className="text-sm font-medium text-text-muted">{title}</p>
          <p className="mt-2 text-3xl font-bold text-text-primary">{value}</p>
          {subtitle && (
            <p className="mt-1 text-sm text-text-muted">{subtitle}</p>
          )}
          {trend && (
            <div className={clsx(
              'mt-2 inline-flex items-center text-sm font-medium',
              trendDirection === 'up' ? 'text-cogentix-green' : 'text-red-500'
            )}>
              {trendDirection === 'up' ? (
                <svg className="w-4 h-4 mr-1" fill="none" viewBox="0 0 24 24" stroke="currentColor">
                  <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M7 11l5-5m0 0l5 5m-5-5v12" />
                </svg>
              ) : (
                <svg className="w-4 h-4 mr-1" fill="none" viewBox="0 0 24 24" stroke="currentColor">
                  <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M17 13l-5 5m0 0l-5-5m5 5V6" />
                </svg>
              )}
              {trend}
            </div>
          )}
        </div>
        {icon && (
          <div className="flex items-center justify-center w-12 h-12 rounded-xl bg-cogentix-orange-50 text-cogentix-orange">
            {icon}
          </div>
        )}
      </div>
    </Card>
  );
}

export default Card;
