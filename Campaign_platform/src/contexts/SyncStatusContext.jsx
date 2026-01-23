/**
 * SyncStatusContext
 * 
 * Global React Context for tracking email sync status across all components.
 * Persists to localStorage for page refresh survival.
 * 
 * Features:
 * - Track multiple concurrent syncs
 * - Per-mailbox progress with current email details
 * - Automatic SSE connection management
 * - localStorage persistence
 * - Debounced state updates to prevent UI lag during high-frequency updates
 */

import React, { createContext, useContext, useState, useEffect, useCallback, useRef, useMemo } from 'react';
import debounce from 'lodash/debounce';
import { API_BASE_URL } from '../config';

// Storage key for localStorage
const STORAGE_KEY = 'torpedo_sync_status';

// Debounce delay for state updates (ms)
const STATE_UPDATE_DEBOUNCE_MS = 500;

// Initial state
const initialState = {
  activeSyncs: {}, // Map of mailbox_id -> { email_id, subject, progress, status, total, synced }
  isSyncActive: false,
  isConnected: false,
  connectionError: null,
  lastUpdated: null,
};

// Create context
const SyncStatusContext = createContext(null);

/**
 * SyncStatusProvider component
 * Wrap your app with this to enable sync status tracking
 */
export function SyncStatusProvider({ children }) {
  const [state, setState] = useState(() => {
    // Try to restore from localStorage
    try {
      const saved = localStorage.getItem(STORAGE_KEY);
      if (saved) {
        const parsed = JSON.parse(saved);
        // Only restore if syncs were active
        if (Object.keys(parsed.activeSyncs || {}).length > 0) {
          return {
            ...initialState,
            activeSyncs: parsed.activeSyncs,
            isSyncActive: Object.keys(parsed.activeSyncs).length > 0,
          };
        }
      }
    } catch (e) {
      console.warn('Failed to restore sync status from localStorage:', e);
    }
    return initialState;
  });

  const eventSourceRef = useRef(null);
  const reconnectTimeoutRef = useRef(null);
  const retryCountRef = useRef(0);
  
  // Retry delays: 2s, 5s, 10s, 20s, 30s
  const RETRY_DELAYS = [2000, 5000, 10000, 20000, 30000];
  const MAX_RETRIES = 5;

  // Persist to localStorage when activeSyncs changes
  useEffect(() => {
    try {
      localStorage.setItem(STORAGE_KEY, JSON.stringify({
        activeSyncs: state.activeSyncs,
        lastUpdated: new Date().toISOString(),
      }));
    } catch (e) {
      console.warn('Failed to persist sync status to localStorage:', e);
    }
  }, [state.activeSyncs]);

  // Connect to SSE endpoint
  const connectSSE = useCallback(() => {
    // Don't connect if not authenticated
    const isAuthenticated = localStorage.getItem('auth') === 'true' || 
                            localStorage.getItem('session_id');
    if (!isAuthenticated) {
      return;
    }
    
    // Don't reconnect if already connected
    if (eventSourceRef.current && eventSourceRef.current.readyState !== EventSource.CLOSED) {
      return;
    }

    // Check if we've exceeded max retries
    if (retryCountRef.current >= MAX_RETRIES) {
      setState(prev => ({
        ...prev,
        connectionError: 'Max reconnection attempts exceeded',
        isConnected: false,
      }));
      return;
    }

    try {
      const eventSource = new EventSource(`${API_BASE_URL}/gmail/sync/stream`);
      eventSourceRef.current = eventSource;

      eventSource.onopen = () => {
        console.log('SSE connected to sync stream');
        retryCountRef.current = 0;
        setState(prev => ({
          ...prev,
          isConnected: true,
          connectionError: null,
        }));
      };

      // Buffer for accumulating mailbox updates before debounced flush
      const pendingUpdatesRef = { current: {} };
      
      // Debounced function to flush accumulated updates to state
      // This prevents excessive React re-renders during high-frequency sync updates
      const flushUpdates = debounce(() => {
        const updates = pendingUpdatesRef.current;
        if (Object.keys(updates).length === 0) return;
        
        setState(prev => {
          const newActiveSyncs = { ...prev.activeSyncs };
          
          for (const [mailboxId, mailbox] of Object.entries(updates)) {
            if (mailbox.status === 'completed' || mailbox.status === 'error' || mailbox.status === 'cancelled') {
              // Keep completed syncs for a moment then remove
              newActiveSyncs[mailboxId] = {
                ...mailbox,
                completedAt: new Date().toISOString(),
              };
              
              // Schedule removal after 5 seconds
              setTimeout(() => {
                setState(p => {
                  const updated = { ...p.activeSyncs };
                  if (updated[mailboxId]?.status === 'completed' ||
                      updated[mailboxId]?.status === 'error' ||
                      updated[mailboxId]?.status === 'cancelled') {
                    delete updated[mailboxId];
                  }
                  return {
                    ...p,
                    activeSyncs: updated,
                    isSyncActive: Object.values(updated).some(
                      s => !['completed', 'error', 'cancelled'].includes(s.status)
                    ),
                  };
                });
              }, 5000);
            } else {
              newActiveSyncs[mailboxId] = {
                email_id: mailbox.current_email_id,
                subject: mailbox.current_subject,
                progress: mailbox.percentage,
                status: mailbox.status,
                total: mailbox.total_count,
                synced: mailbox.synced_count,
                folder: mailbox.current_folder,
                errors: mailbox.errors,
              };
            }
          }
          
          // Clear pending updates after flush
          pendingUpdatesRef.current = {};
          
          return {
            ...prev,
            activeSyncs: newActiveSyncs,
            isSyncActive: Object.values(newActiveSyncs).some(
              s => !['completed', 'error', 'cancelled'].includes(s.status)
            ),
            lastUpdated: new Date().toISOString(),
          };
        });
      }, STATE_UPDATE_DEBOUNCE_MS);

      eventSource.onmessage = (event) => {
        try {
          const data = JSON.parse(event.data);
          
          if (data.type === 'sync_progress' && data.mailboxes) {
            // Accumulate updates in buffer
            for (const mailbox of data.mailboxes) {
              pendingUpdatesRef.current[mailbox.mailbox_id] = mailbox;
            }
            
            // Check if any mailbox has a terminal status - flush immediately
            const hasTerminalStatus = data.mailboxes.some(
              m => ['completed', 'error', 'cancelled'].includes(m.status)
            );
            
            if (hasTerminalStatus) {
              // Flush immediately for status changes
              flushUpdates.flush();
            } else {
              // Debounced update for progress
              flushUpdates();
            }
          }
          // Heartbeat messages just confirm connection is alive
        } catch (e) {
          console.warn('Failed to parse SSE message:', e);
        }
      };

      eventSource.onerror = (error) => {
        console.warn('SSE connection error:', error);
        eventSource.close();
        eventSourceRef.current = null;
        
        setState(prev => ({
          ...prev,
          isConnected: false,
          connectionError: 'Connection lost',
        }));

        // Schedule reconnection with exponential backoff
        const delay = RETRY_DELAYS[Math.min(retryCountRef.current, RETRY_DELAYS.length - 1)];
        retryCountRef.current++;
        
        console.log(`SSE reconnecting in ${delay}ms (attempt ${retryCountRef.current}/${MAX_RETRIES})`);
        
        reconnectTimeoutRef.current = setTimeout(() => {
          connectSSE();
        }, delay);
      };

    } catch (e) {
      console.error('Failed to create SSE connection:', e);
      setState(prev => ({
        ...prev,
        isConnected: false,
        connectionError: e.message,
      }));
    }
  }, []);

  // Disconnect SSE
  const disconnectSSE = useCallback(() => {
    if (reconnectTimeoutRef.current) {
      clearTimeout(reconnectTimeoutRef.current);
      reconnectTimeoutRef.current = null;
    }
    if (eventSourceRef.current) {
      eventSourceRef.current.close();
      eventSourceRef.current = null;
    }
    retryCountRef.current = 0;
    setState(prev => ({
      ...prev,
      isConnected: false,
    }));
  }, []);

  // Auto-connect when component mounts - only if user is authenticated
  useEffect(() => {
    // Check if user is authenticated before connecting
    const isAuthenticated = localStorage.getItem('auth') === 'true' || 
                            localStorage.getItem('session_id');
    
    if (isAuthenticated) {
      connectSSE();
    }
    
    return () => disconnectSSE();
  }, [connectSSE, disconnectSSE]);

  // Manual methods for components
  const addSync = useCallback((mailboxId, initialData = {}) => {
    setState(prev => ({
      ...prev,
      activeSyncs: {
        ...prev.activeSyncs,
        [mailboxId]: {
          email_id: '',
          subject: '',
          progress: 0,
          status: 'pending',
          total: 0,
          synced: 0,
          ...initialData,
        },
      },
      isSyncActive: true,
    }));
  }, []);

  const updateSync = useCallback((mailboxId, updates) => {
    setState(prev => ({
      ...prev,
      activeSyncs: {
        ...prev.activeSyncs,
        [mailboxId]: {
          ...prev.activeSyncs[mailboxId],
          ...updates,
        },
      },
    }));
  }, []);

  const removeSync = useCallback((mailboxId) => {
    setState(prev => {
      const newSyncs = { ...prev.activeSyncs };
      delete newSyncs[mailboxId];
      return {
        ...prev,
        activeSyncs: newSyncs,
        isSyncActive: Object.keys(newSyncs).length > 0,
      };
    });
  }, []);

  const clearAllSyncs = useCallback(() => {
    setState(prev => ({
      ...prev,
      activeSyncs: {},
      isSyncActive: false,
    }));
    try {
      localStorage.removeItem(STORAGE_KEY);
    } catch (e) {
      console.warn('Failed to clear localStorage:', e);
    }
  }, []);

  // Cancel a sync operation
  const cancelSync = useCallback(async (mailboxId) => {
    try {
      const response = await fetch(`${API_BASE_URL}/gmail/sync/${encodeURIComponent(mailboxId)}/cancel`, {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json',
        },
      });
      
      if (response.ok) {
        updateSync(mailboxId, { status: 'cancelling' });
        return true;
      }
      return false;
    } catch (e) {
      console.error('Failed to cancel sync:', e);
      return false;
    }
  }, [updateSync]);

  const value = {
    ...state,
    addSync,
    updateSync,
    removeSync,
    clearAllSyncs,
    cancelSync,
    connectSSE,
    disconnectSSE,
  };

  return (
    <SyncStatusContext.Provider value={value}>
      {children}
    </SyncStatusContext.Provider>
  );
}

/**
 * Hook to use sync status context
 */
export function useSyncStatus() {
  const context = useContext(SyncStatusContext);
  if (!context) {
    // Return default values instead of throwing - allows use outside provider (e.g., during SSR or lazy loading)
    return {
      activeSyncs: {},
      isSyncActive: false,
      isConnected: false,
      connectionError: null,
      lastUpdated: null,
      addSync: () => {},
      updateSync: () => {},
      removeSync: () => {},
      clearAllSyncs: () => {},
      cancelSync: async () => false,
      connectSSE: () => {},
      disconnectSSE: () => {},
    };
  }
  return context;
}

export default SyncStatusContext;
