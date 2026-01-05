// file: src/components/ui/ConfirmDialog.jsx
// Standardized confirmation dialog for destructive actions

import { forwardRef } from 'react';
import { createPortal } from 'react-dom';
import { clsx } from 'clsx';
import { Button } from './Button';

/**
 * ConfirmDialog variants for different action types
 */
const dialogVariants = {
  danger: {
    iconBg: 'bg-red-100',
    iconColor: 'text-red-600',
    buttonVariant: 'danger',
    icon: (
      <svg className="w-6 h-6" fill="none" viewBox="0 0 24 24" stroke="currentColor">
        <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M12 9v2m0 4h.01m-6.938 4h13.856c1.54 0 2.502-1.667 1.732-3L13.732 4c-.77-1.333-2.694-1.333-3.464 0L3.34 16c-.77 1.333.192 3 1.732 3z" />
      </svg>
    ),
  },
  warning: {
    iconBg: 'bg-yellow-100',
    iconColor: 'text-yellow-600',
    buttonVariant: 'warning',
    icon: (
      <svg className="w-6 h-6" fill="none" viewBox="0 0 24 24" stroke="currentColor">
        <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M12 8v4m0 4h.01M21 12a9 9 0 11-18 0 9 9 0 0118 0z" />
      </svg>
    ),
  },
  info: {
    iconBg: 'bg-blue-100',
    iconColor: 'text-blue-600',
    buttonVariant: 'primary',
    icon: (
      <svg className="w-6 h-6" fill="none" viewBox="0 0 24 24" stroke="currentColor">
        <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M13 16h-1v-4h-1m1-4h.01M21 12a9 9 0 11-18 0 9 9 0 0118 0z" />
      </svg>
    ),
  },
  success: {
    iconBg: 'bg-green-100',
    iconColor: 'text-green-600',
    buttonVariant: 'success',
    icon: (
      <svg className="w-6 h-6" fill="none" viewBox="0 0 24 24" stroke="currentColor">
        <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M9 12l2 2 4-4m6 2a9 9 0 11-18 0 9 9 0 0118 0z" />
      </svg>
    ),
  },
};

/**
 * ConfirmDialog Component
 * Modal dialog for confirming user actions, especially destructive ones
 * 
 * @param {boolean} isOpen - Whether dialog is visible
 * @param {function} onClose - Called when dialog should close
 * @param {function} onConfirm - Called when user confirms action
 * @param {string} title - Dialog title
 * @param {string} message - Dialog message/description
 * @param {string} confirmText - Text for confirm button (default: "Confirm")
 * @param {string} cancelText - Text for cancel button (default: "Cancel")
 * @param {string} variant - Dialog type: 'danger' | 'warning' | 'info' | 'success'
 * @param {boolean} loading - Shows loading state on confirm button
 * @param {React.ReactNode} children - Optional additional content
 */
const ConfirmDialog = forwardRef(({
  isOpen,
  onClose,
  onConfirm,
  title = 'Confirm Action',
  message,
  confirmText = 'Confirm',
  cancelText = 'Cancel',
  variant = 'danger',
  loading = false,
  children,
}, ref) => {
  if (!isOpen) return null;

  const dialogStyle = dialogVariants[variant] || dialogVariants.danger;

  const handleKeyDown = (e) => {
    if (e.key === 'Escape' && !loading) {
      onClose?.();
    }
  };

  const handleOverlayClick = (e) => {
    if (e.target === e.currentTarget && !loading) {
      onClose?.();
    }
  };

  const handleConfirm = async () => {
    if (loading) return;
    await onConfirm?.();
  };

  return createPortal(
    <div
      ref={ref}
      role="alertdialog"
      aria-modal="true"
      aria-labelledby="confirm-dialog-title"
      aria-describedby="confirm-dialog-description"
      className="fixed inset-0 z-50 flex items-center justify-center"
      onKeyDown={handleKeyDown}
    >
      {/* Overlay */}
      <div
        className={clsx(
          'fixed inset-0 bg-black/50 transition-opacity duration-200',
          loading && 'pointer-events-none'
        )}
        onClick={handleOverlayClick}
        aria-hidden="true"
      />

      {/* Dialog */}
      <div
        className={clsx(
          'relative bg-white rounded-lg shadow-xl max-w-md w-full mx-4',
          'transform transition-all duration-200',
          'animate-in fade-in zoom-in-95'
        )}
      >
        <div className="p-6">
          {/* Icon and Content */}
          <div className="flex items-start gap-4">
            {/* Icon */}
            <div className={clsx(
              'flex-shrink-0 w-12 h-12 rounded-full flex items-center justify-center',
              dialogStyle.iconBg,
              dialogStyle.iconColor
            )}>
              {dialogStyle.icon}
            </div>

            {/* Text Content */}
            <div className="flex-1 pt-1">
              <h3
                id="confirm-dialog-title"
                className="text-lg font-semibold text-gray-900"
              >
                {title}
              </h3>
              {message && (
                <p
                  id="confirm-dialog-description"
                  className="mt-2 text-sm text-gray-600"
                >
                  {message}
                </p>
              )}
              {children && (
                <div className="mt-4">
                  {children}
                </div>
              )}
            </div>
          </div>
        </div>

        {/* Actions */}
        <div className="px-6 py-4 bg-gray-50 rounded-b-lg flex justify-end gap-3">
          <Button
            variant="outline"
            onClick={onClose}
            disabled={loading}
          >
            {cancelText}
          </Button>
          <Button
            variant={dialogStyle.buttonVariant}
            onClick={handleConfirm}
            disabled={loading}
          >
            {loading ? (
              <span className="flex items-center gap-2">
                <svg className="animate-spin h-4 w-4" fill="none" viewBox="0 0 24 24">
                  <circle className="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" strokeWidth="4" />
                  <path className="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4zm2 5.291A7.962 7.962 0 014 12H0c0 3.042 1.135 5.824 3 7.938l3-2.647z" />
                </svg>
                Processing...
              </span>
            ) : confirmText}
          </Button>
        </div>
      </div>
    </div>,
    document.body
  );
});

ConfirmDialog.displayName = 'ConfirmDialog';

/**
 * DeleteConfirmDialog - Pre-configured for delete operations
 */
const DeleteConfirmDialog = ({
  isOpen,
  onClose,
  onConfirm,
  itemName = 'this item',
  loading = false,
}) => (
  <ConfirmDialog
    isOpen={isOpen}
    onClose={onClose}
    onConfirm={onConfirm}
    title="Delete Confirmation"
    message={`Are you sure you want to delete ${itemName}? This action cannot be undone.`}
    confirmText="Delete"
    cancelText="Cancel"
    variant="danger"
    loading={loading}
  />
);

/**
 * ArchiveConfirmDialog - Pre-configured for archive operations
 */
const ArchiveConfirmDialog = ({
  isOpen,
  onClose,
  onConfirm,
  itemName = 'this item',
  loading = false,
}) => (
  <ConfirmDialog
    isOpen={isOpen}
    onClose={onClose}
    onConfirm={onConfirm}
    title="Archive Confirmation"
    message={`Are you sure you want to archive ${itemName}? You can restore it later from the archive.`}
    confirmText="Archive"
    cancelText="Cancel"
    variant="warning"
    loading={loading}
  />
);

/**
 * UnsavedChangesDialog - Pre-configured for unsaved changes warning
 */
const UnsavedChangesDialog = ({
  isOpen,
  onClose,
  onConfirm,
  loading = false,
}) => (
  <ConfirmDialog
    isOpen={isOpen}
    onClose={onClose}
    onConfirm={onConfirm}
    title="Unsaved Changes"
    message="You have unsaved changes. Are you sure you want to leave? Your changes will be lost."
    confirmText="Leave Without Saving"
    cancelText="Stay"
    variant="warning"
    loading={loading}
  />
);

export { 
  ConfirmDialog, 
  DeleteConfirmDialog, 
  ArchiveConfirmDialog,
  UnsavedChangesDialog 
};
export default ConfirmDialog;
