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
    md: 'p-5',
    lg: 'p-6',
  };

  return (
    <div
      className={clsx(
        'bg-white rounded-[10px] border border-line shadow-card',
        paddingClasses[padding],
        hover && 'transition-colors duration-200 hover:border-cogentix-orange/35',
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

export function CardTitle({ children, className = '' }) {
  return (
    <h3 className={clsx('text-base font-semibold text-text-primary', className)}>
      {children}
    </h3>
  );
}

export function CardDescription({ children, className = '' }) {
  return (
    <p className={clsx('text-sm text-text-muted mt-0.5', className)}>
      {children}
    </p>
  );
}

export function CardFooter({ children, className = '' }) {
  return (
    <div className={clsx('mt-4 pt-4 border-t border-line', className)}>
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
          <p className="mt-1.5 text-[1.7rem] leading-tight font-extrabold tracking-tight text-text-primary">{value}</p>
          {subtitle && (
            <p className="mt-1 text-sm text-text-muted">{subtitle}</p>
          )}
          {trend && (
            <div className={clsx(
              'mt-1 inline-flex items-center text-sm font-semibold',
              trendDirection === 'up' ? 'text-green-600' : 'text-red-600'
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
          <div className="flex items-center justify-center w-11 h-11 rounded-lg bg-cogentix-orange/10 text-cogentix-orange-700">
            {icon}
          </div>
        )}
      </div>
    </Card>
  );
}

export default Card;
