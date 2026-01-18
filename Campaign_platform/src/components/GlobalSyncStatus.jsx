/**
 * GlobalSyncStatus Component
 * 
 * Floating bottom-right panel showing per-mailbox sync status bars.
 * Displays:
 * - Email address being synced
 * - Current email ID/subject being processed
 * - Progress bar with percentage
 * - Cancel button
 * 
 * Collapsible when multiple syncs are active.
 */

import React, { useState } from 'react';
import { useSyncStatus } from '../contexts/SyncStatusContext';

// Icons (inline SVG to avoid dependencies)
const ChevronDownIcon = () => (
  <svg xmlns="http://www.w3.org/2000/svg" width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
    <polyline points="6 9 12 15 18 9"></polyline>
  </svg>
);

const ChevronUpIcon = () => (
  <svg xmlns="http://www.w3.org/2000/svg" width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
    <polyline points="18 15 12 9 6 15"></polyline>
  </svg>
);

const XIcon = () => (
  <svg xmlns="http://www.w3.org/2000/svg" width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
    <line x1="18" y1="6" x2="6" y2="18"></line>
    <line x1="6" y1="6" x2="18" y2="18"></line>
  </svg>
);

const MailIcon = () => (
  <svg xmlns="http://www.w3.org/2000/svg" width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
    <rect x="2" y="4" width="20" height="16" rx="2"></rect>
    <path d="m22 7-8.97 5.7a1.94 1.94 0 0 1-2.06 0L2 7"></path>
  </svg>
);

const LoaderIcon = () => (
  <svg xmlns="http://www.w3.org/2000/svg" width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" className="animate-spin">
    <path d="M21 12a9 9 0 1 1-6.219-8.56"></path>
  </svg>
);

const CheckIcon = () => (
  <svg xmlns="http://www.w3.org/2000/svg" width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
    <polyline points="20 6 9 17 4 12"></polyline>
  </svg>
);

const AlertIcon = () => (
  <svg xmlns="http://www.w3.org/2000/svg" width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
    <circle cx="12" cy="12" r="10"></circle>
    <line x1="12" y1="8" x2="12" y2="12"></line>
    <line x1="12" y1="16" x2="12.01" y2="16"></line>
  </svg>
);

// Status badge colors
const statusColors = {
  pending: 'bg-gray-500',
  connecting: 'bg-blue-500',
  counting: 'bg-blue-500',
  downloading: 'bg-indigo-500',
  processing: 'bg-purple-500',
  completed: 'bg-green-500',
  error: 'bg-red-500',
  cancelled: 'bg-yellow-500',
  cancelling: 'bg-yellow-500',
};

const statusLabels = {
  pending: 'Starting...',
  connecting: 'Connecting...',
  counting: 'Counting emails...',
  downloading: 'Downloading',
  processing: 'Processing',
  completed: 'Complete',
  error: 'Error',
  cancelled: 'Cancelled',
  cancelling: 'Cancelling...',
};

/**
 * Single sync item in the status panel
 */
function SyncItem({ mailboxId, syncData, onCancel }) {
  const {
    email_id,
    subject,
    progress,
    status,
    total,
    synced,
    folder,
    errors,
  } = syncData;

  const isActive = !['completed', 'error', 'cancelled'].includes(status);
  const progressValue = typeof progress === 'number' ? progress : 0;

  return (
    <div className="bg-gray-800 rounded-lg p-3 mb-2 last:mb-0">
      {/* Header row */}
      <div className="flex items-center justify-between mb-2">
        <div className="flex items-center gap-2 flex-1 min-w-0">
          <MailIcon />
          <span className="text-sm font-medium text-white truncate">
            {mailboxId}
          </span>
        </div>
        
        {isActive && status !== 'cancelling' && (
          <button
            onClick={() => onCancel(mailboxId)}
            className="p-1 hover:bg-gray-700 rounded text-gray-400 hover:text-white transition-colors"
            title="Cancel sync"
          >
            <XIcon />
          </button>
        )}
      </div>

      {/* Status and progress */}
      <div className="space-y-2">
        {/* Status badge and counts */}
        <div className="flex items-center justify-between text-xs">
          <span className={`px-2 py-0.5 rounded ${statusColors[status] || 'bg-gray-500'} text-white`}>
            {statusLabels[status] || status}
          </span>
          <span className="text-gray-400">
            {synced?.toLocaleString() || 0} / {total?.toLocaleString() || 0}
          </span>
        </div>

        {/* Progress bar */}
        <div className="w-full bg-gray-700 rounded-full h-2 overflow-hidden">
          <div
            className={`h-full transition-all duration-300 ${
              status === 'completed' ? 'bg-green-500' :
              status === 'error' ? 'bg-red-500' :
              status === 'cancelled' ? 'bg-yellow-500' :
              'bg-indigo-500'
            }`}
            style={{ width: `${Math.min(progressValue, 100)}%` }}
          />
        </div>

        {/* Current email info (when downloading) */}
        {status === 'downloading' && subject && (
          <div className="text-xs text-gray-400 truncate" title={subject}>
            📧 {subject}
          </div>
        )}

        {/* Folder info */}
        {folder && (
          <div className="text-xs text-gray-500">
            📁 {folder}
          </div>
        )}

        {/* Errors (show first error if any) */}
        {errors && errors.length > 0 && (
          <div className="text-xs text-red-400 flex items-center gap-1">
            <AlertIcon />
            {errors[0]}
          </div>
        )}
      </div>
    </div>
  );
}

/**
 * Main GlobalSyncStatus component
 */
export function GlobalSyncStatus() {
  const { activeSyncs, isSyncActive, isConnected, cancelSync } = useSyncStatus();
  const [isCollapsed, setIsCollapsed] = useState(false);

  const syncEntries = Object.entries(activeSyncs);
  const activeCount = syncEntries.filter(
    ([, data]) => !['completed', 'error', 'cancelled'].includes(data.status)
  ).length;

  // Don't render if no syncs
  if (syncEntries.length === 0) {
    return null;
  }

  return (
    <div 
      className="fixed bottom-4 right-4 z-50 w-80 max-w-[calc(100vw-2rem)]"
      style={{ maxHeight: 'calc(100vh - 2rem)' }}
    >
      <div className="bg-gray-900 rounded-xl shadow-2xl border border-gray-700 overflow-hidden">
        {/* Header */}
        <div 
          className="flex items-center justify-between px-4 py-3 bg-gray-800 cursor-pointer"
          onClick={() => setIsCollapsed(!isCollapsed)}
        >
          <div className="flex items-center gap-2">
            {activeCount > 0 ? <LoaderIcon /> : <CheckIcon />}
            <span className="text-sm font-medium text-white">
              Email Sync {activeCount > 0 ? `(${activeCount} active)` : 'Complete'}
            </span>
          </div>
          
          <div className="flex items-center gap-2">
            {/* Connection indicator */}
            <div 
              className={`w-2 h-2 rounded-full ${isConnected ? 'bg-green-500' : 'bg-red-500'}`}
              title={isConnected ? 'Connected' : 'Disconnected'}
            />
            
            <button className="text-gray-400 hover:text-white">
              {isCollapsed ? <ChevronUpIcon /> : <ChevronDownIcon />}
            </button>
          </div>
        </div>

        {/* Sync items (collapsible) */}
        {!isCollapsed && (
          <div className="p-3 max-h-96 overflow-y-auto">
            {syncEntries.map(([mailboxId, syncData]) => (
              <SyncItem
                key={mailboxId}
                mailboxId={mailboxId}
                syncData={syncData}
                onCancel={cancelSync}
              />
            ))}
          </div>
        )}
      </div>
    </div>
  );
}

export default GlobalSyncStatus;
