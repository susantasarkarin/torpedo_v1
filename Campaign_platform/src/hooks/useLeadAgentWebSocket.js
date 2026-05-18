/**
 * useLeadAgentWebSocket Hook
 * 
 * Context adapter for lead generation agent real-time updates.
 * 
 * Features:
 * - Uses LeadAgentContext as the single transport/state authority
 * - Exposes a backward-compatible API for existing consumers
 * - Emits callbacks based on context state changes
 */

import { useEffect, useMemo, useRef } from 'react';
import { useLeadAgent } from '../contexts/LeadAgentContext';

/**
 * WebSocket hook for lead agent progress
 * 
 * @param {Object} options - Configuration options
 * @param {string} options.jobId - Specific job ID to track (optional)
 * @param {boolean} options.autoConnect - Auto-connect on mount (default: true)
 * @param {function} options.onProgress - Callback for progress updates
 * @param {function} options.onComplete - Callback when job completes
 * @param {function} options.onError - Callback on error
 */
export function useLeadAgentWebSocket(options = {}) {
  const {
    jobId = null,
    autoConnect = true,
    onProgress,
    onComplete,
    onError,
  } = options;

  const {
    isConnected,
    connectionError,
    jobs,
    connectWebSocket,
    disconnectWebSocket,
  } = useLeadAgent();

  const prevJobRef = useRef(null);
  const prevJobStatusRef = useRef(null);

  const currentJob = useMemo(() => {
    if (!Array.isArray(jobs) || jobs.length === 0) return null;
    if (jobId) {
      return jobs.find((job) => job.job_id === jobId) || null;
    }
    return jobs[0] || null;
  }, [jobs, jobId]);

  const lastUpdate = currentJob?.updated_at || currentJob?.last_update || null;

  const connect = () => connectWebSocket(jobId);
  const disconnect = () => disconnectWebSocket();

  // Optional auto-connect delegates to context transport.
  useEffect(() => {
    if (autoConnect) {
      connect();
    }
    return () => {
      if (autoConnect) {
        disconnect();
      }
    };
  }, [autoConnect, jobId]);

  // Rebind connection when tracking a different job.
  useEffect(() => {
    if (autoConnect && isConnected) {
      disconnect();
      connect();
    }
  }, [jobId]);

  // Emit callbacks from context-driven state transitions.
  useEffect(() => {
    if (!currentJob) return;

    const prevJobId = prevJobRef.current;
    const prevStatus = prevJobStatusRef.current;
    const isSameJob = prevJobId === currentJob.job_id;
    const statusChanged = !isSameJob || prevStatus !== currentJob.status;

    onProgress?.(currentJob);

    if (statusChanged) {
      if (currentJob.status === 'completed') {
        onComplete?.(currentJob);
      } else if (currentJob.status === 'failed') {
        onError?.(currentJob.error || currentJob.message || 'Job failed');
      }
    }

    prevJobRef.current = currentJob.job_id;
    prevJobStatusRef.current = currentJob.status;
  }, [currentJob, onProgress, onComplete, onError]);

  useEffect(() => {
    if (connectionError) {
      onError?.(connectionError);
    }
  }, [connectionError, onError]);

  return {
    isConnected,
    error: connectionError,
    lastUpdate,
    currentJob,
    connect,
    disconnect,
  };
}

export default useLeadAgentWebSocket;
