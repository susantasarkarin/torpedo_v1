// file: src/components/ui/Avatar.jsx
import { clsx } from 'clsx';

// warm palette from the CRM mockup; a name always gets the same colour
const COLORS = ['#e8910a', '#d97706', '#b45309', '#c27800', '#92400e', '#16a34a'];

const sizes = {
  xs: 'w-6 h-6 text-[0.875rem]',
  sm: 'w-8 h-8 text-sm',
  md: 'w-9 h-9 text-sm',
  lg: 'w-11 h-11 text-base',
};

function initialsOf(name = '') {
  const parts = String(name).replace(/[@._-]+/g, ' ').trim().split(/\s+/).filter(Boolean);
  if (!parts.length) return '?';
  return (parts[0][0] + (parts[1]?.[0] || '')).toUpperCase();
}

function colorFor(name = '') {
  let h = 0;
  for (const ch of String(name)) h = (h * 31 + ch.charCodeAt(0)) >>> 0;
  return COLORS[h % COLORS.length];
}

export function Avatar({ name, src, size = 'sm', color, className = '' }) {
  const cls = clsx('inline-grid place-items-center shrink-0 rounded-full font-bold text-white overflow-hidden', sizes[size], className);
  if (src) return <img src={src} alt={name || ''} className={cls} />;
  return (
    <span className={cls} style={{ background: color || colorFor(name) }} title={name || undefined}>
      {initialsOf(name)}
    </span>
  );
}

// avatar + name + secondary line (the mockup's lead cell)
export function AvatarLabel({ name, subtitle, src, size = 'sm', className = '' }) {
  return (
    <div className={clsx('flex items-center gap-2.5 min-w-0', className)}>
      <Avatar name={name} src={src} size={size} />
      <div className="min-w-0">
        <strong className="block truncate text-sm font-semibold text-text-primary">{name}</strong>
        {subtitle && <span className="block truncate text-sm text-text-muted">{subtitle}</span>}
      </div>
    </div>
  );
}

export default Avatar;
