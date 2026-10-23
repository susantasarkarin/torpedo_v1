// file: src/components/ui/Drawer.jsx
// Side panel for detail/edit views: slides in from the right, full width on
// phones. Same contract as Modal (isOpen, onClose, title, footer).
import { useEffect } from 'react';
import { createPortal } from 'react-dom';
import { clsx } from 'clsx';

const widths = { sm: 'sm:max-w-sm', md: 'sm:max-w-lg', lg: 'sm:max-w-2xl', xl: 'sm:max-w-4xl' };

export function Drawer({ isOpen, onClose, title, footer, size = 'md', children, className = '' }) {
  useEffect(() => {
    if (!isOpen) return undefined;
    const onKey = (e) => e.key === 'Escape' && onClose?.();
    document.addEventListener('keydown', onKey);
    const prev = document.body.style.overflow;
    document.body.style.overflow = 'hidden';
    return () => {
      document.removeEventListener('keydown', onKey);
      document.body.style.overflow = prev;
    };
  }, [isOpen, onClose]);

  if (!isOpen) return null;

  return createPortal(
    <div className="fixed inset-0 z-[1000] flex justify-end" role="dialog" aria-modal="true" aria-label={typeof title === 'string' ? title : undefined}>
      <div className="absolute inset-0 bg-black/45" onClick={onClose} aria-hidden="true" />
      <aside className={clsx('relative flex h-full w-full flex-col bg-white shadow-2xl', widths[size], className)}>
        <div className="flex items-center justify-between gap-3 border-b border-line px-5 py-4">
          <h2 className="m-0 truncate text-lg font-bold text-text-primary">{title}</h2>
          <button
            type="button"
            onClick={onClose}
            className="grid h-10 w-10 shrink-0 place-items-center rounded-lg border border-line text-text-secondary hover:bg-surface-hover"
            aria-label="Close"
          >
            ✕
          </button>
        </div>
        <div className="flex-1 overflow-y-auto px-5 py-4">{children}</div>
        {footer && <div className="flex flex-wrap items-center justify-end gap-3 border-t border-line bg-gray-50 px-5 py-3">{footer}</div>}
      </aside>
    </div>,
    document.body
  );
}

export default Drawer;
