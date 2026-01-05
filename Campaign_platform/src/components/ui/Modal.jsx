// file: src/components/ui/Modal.jsx
// Standardized modal component for consistent dialogs across the app

import { useEffect, useRef, useCallback } from 'react';
import { createPortal } from 'react-dom';
import { clsx } from 'clsx';

const modalSizes = {
  sm: 'max-w-md',
  md: 'max-w-lg',
  lg: 'max-w-2xl',
  xl: 'max-w-4xl',
  full: 'max-w-[90vw]',
};

/**
 * Modal Component
 * 
 * @param {boolean} isOpen - Whether the modal is open
 * @param {function} onClose - Callback when modal should close
 * @param {string} title - Modal title
 * @param {React.ReactNode} children - Modal content
 * @param {string} size - Modal size: 'sm' | 'md' | 'lg' | 'xl' | 'full'
 * @param {boolean} showCloseButton - Show X button in header
 * @param {boolean} closeOnOverlayClick - Close when clicking overlay
 * @param {boolean} closeOnEscape - Close when pressing Escape
 * @param {React.ReactNode} footer - Footer content (usually buttons)
 * @param {string} className - Additional classes for modal content
 */
const Modal = ({
  isOpen,
  onClose,
  title,
  children,
  size = 'md',
  showCloseButton = true,
  closeOnOverlayClick = true,
  closeOnEscape = true,
  footer,
  className = '',
}) => {
  const modalRef = useRef(null);

  // Handle escape key
  const handleKeyDown = useCallback((e) => {
    if (closeOnEscape && e.key === 'Escape') {
      onClose();
    }
  }, [closeOnEscape, onClose]);

  // Handle overlay click
  const handleOverlayClick = (e) => {
    if (closeOnOverlayClick && e.target === e.currentTarget) {
      onClose();
    }
  };

  // Focus trap and body scroll lock
  useEffect(() => {
    if (isOpen) {
      document.addEventListener('keydown', handleKeyDown);
      document.body.style.overflow = 'hidden';
      
      // Focus the modal
      if (modalRef.current) {
        modalRef.current.focus();
      }
    }

    return () => {
      document.removeEventListener('keydown', handleKeyDown);
      document.body.style.overflow = '';
    };
  }, [isOpen, handleKeyDown]);

  if (!isOpen) return null;

  const modalContent = (
    <div
      className="fixed inset-0 z-50 flex items-center justify-center p-4 bg-black/50 backdrop-blur-sm"
      onClick={handleOverlayClick}
      role="dialog"
      aria-modal="true"
      aria-labelledby="modal-title"
    >
      <div
        ref={modalRef}
        tabIndex={-1}
        className={clsx(
          'relative w-full bg-white rounded-xl shadow-2xl',
          'transform transition-all duration-200',
          'animate-in fade-in zoom-in-95',
          modalSizes[size],
          className
        )}
        onClick={(e) => e.stopPropagation()}
      >
        {/* Header */}
        {(title || showCloseButton) && (
          <div className="flex items-center justify-between px-6 py-4 border-b border-gray-200">
            {title && (
              <h2 id="modal-title" className="text-xl font-semibold text-cogentix-navy">
                {title}
              </h2>
            )}
            {showCloseButton && (
              <button
                onClick={onClose}
                className="p-2 text-gray-400 hover:text-gray-600 hover:bg-gray-100 rounded-lg transition-colors"
                aria-label="Close modal"
              >
                <svg className="w-5 h-5" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                  <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M6 18L18 6M6 6l12 12" />
                </svg>
              </button>
            )}
          </div>
        )}

        {/* Body */}
        <div className="px-6 py-4 max-h-[calc(100vh-200px)] overflow-y-auto">
          {children}
        </div>

        {/* Footer */}
        {footer && (
          <div className="flex items-center justify-end gap-3 px-6 py-4 border-t border-gray-200 bg-gray-50 rounded-b-xl">
            {footer}
          </div>
        )}
      </div>
    </div>
  );

  // Render in portal to avoid z-index issues
  return createPortal(modalContent, document.body);
};

/**
 * Modal Header - For custom headers
 */
const ModalHeader = ({ children, className = '' }) => (
  <div className={clsx('px-6 py-4 border-b border-gray-200', className)}>
    {children}
  </div>
);

/**
 * Modal Body - For custom body wrapper
 */
const ModalBody = ({ children, className = '' }) => (
  <div className={clsx('px-6 py-4', className)}>
    {children}
  </div>
);

/**
 * Modal Footer - For custom footers
 */
const ModalFooter = ({ children, className = '' }) => (
  <div className={clsx('flex items-center justify-end gap-3 px-6 py-4 border-t border-gray-200 bg-gray-50 rounded-b-xl', className)}>
    {children}
  </div>
);

export { Modal, ModalHeader, ModalBody, ModalFooter };
export default Modal;
