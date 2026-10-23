// file: src/components/ui/StatCard.jsx
// Mockup stat tiles: label, big value, optional change line.
// StatRow lays them out 1 / 2 / 4 across (phone / tablet / desktop).
import { clsx } from 'clsx';

export function StatCard({ label, value, change, trend, className = '', onClick }) {
  return (
    <div
      className={clsx('cx-stat-card', onClick && 'cursor-pointer', className)}
      onClick={onClick}
      role={onClick ? 'button' : undefined}
      tabIndex={onClick ? 0 : undefined}
    >
      <div className="cx-stat-label">{label}</div>
      <div className="cx-stat-value">{value}</div>
      {change != null && change !== '' && (
        <div className={clsx('cx-stat-change', trend === 'up' && 'is-up', trend === 'down' && 'is-down')}>{change}</div>
      )}
    </div>
  );
}

export function StatRow({ children, className = '' }) {
  return <div className={clsx('cx-stats-row', className)}>{children}</div>;
}

export default StatCard;
