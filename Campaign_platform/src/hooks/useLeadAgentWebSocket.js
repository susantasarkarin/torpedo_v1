/**
 * useLeadAgentWebSocket Hook
 * 
 * WebSocket hook for real-time lead generation agent progress updates.
 * 
 * Features:
 * - Auto-reconnect with exponential backoff
 * - Job-specific or global connection
 * - Progress and status updates
 * - Callback support for updates
 */

import { useState, useEffect, useRef, useCallback } from 'react';

// Retry delays in milliseconds
const RETRY_DELAYS = [2000, 5000, 10000, 20000, 30000];
const MAX_RETRIES = 5;

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

  const [isConnected, setIsConnected] = useState(false);
  const [error, setError] = useState(null);
  const [lastUpdate, setLastUpdate] = useState(null);
  const [currentJob, setCurrentJob] = useState(null);

  const wsRef = useRef(null);
  const reconnectTimeoutRef = useRef(null);
  const retryCountRef = useRef(0);
  const isUnmountedRef = useRef(false);

  // Build WebSocket URL
  const getWsUrl = useCallback(() => {
    const apiBase = import.meta.env.VITE_API_URL || 'http://localhost:8000';
    const wsBase = apiBase.replace(/^http/, 'ws');
    
    if (jobId) {
      return `${wsBase}/leads/agents/ws/${jobId}`;
    }
    return `${wsBase}/leads/agents/ws/all`;
  }, [jobId]);

  // Connect to WebSocket
  const connect = useCallback(() => {
    if (isUnmountedRef.current) return;
    if (wsRef.current && wsRef.current.readyState === WebSocket.CONNECTING) return;
    if (wsRef.current && wsRef.current.readyState === WebSocket.OPEN) return;

    if (retryCountRef.current >= MAX_RETRIES) {
      setError('Maximum reconnection attempts exceeded');
      onError?.('Maximum reconnection attempts exceeded');
      return;
    }

    try {
      const wsUrl = getWsUrl();
      console.log('[LeadAgentWS] Connecting to:', wsUrl);
      
      const ws = new WebSocket(wsUrl);
      wsRef.current = ws;

      ws.onopen = () => {
        if (isUnmountedRef.current) return;
        console.log('[LeadAgentWS] Connected');
        setIsConnected(true);
        setError(null);
        retryCountRef.current = 0;
      };

      ws.onmessage = (event) => {
        if (isUnmountedRef.current) return;
        
        try {
          const data = JSON.parse(event.data);
          setLastUpdate(new Date().toISOString());
          
          if (data.type === 'agent_progress') {
            setCurrentJob(data);
            onProgress?.(data);
          } else if (data.type === 'job_completed' || data.status === 'completed') {
            setCurrentJob(data);
            onComplete?.(data);
          } else if (data.type === 'job_failed' || data.status === 'failed') {
            setCurrentJob(data);
            onError?.(data.error || data.message || 'Job failed');
          } else if (data.type === 'connected') {
            console.log('[LeadAgentWS] Connection confirmed');
          } else if (data.type === 'heartbeat') {
            // Send pong
            if (ws.readyState === WebSocket.OPEN) {
              ws.send(JSON.stringify({ type: 'pong' }));
            }
          }
        } catch (e) {
          console.error('[LeadAgentWS] Failed to parse message:', e);
        }
      };

      ws.onclose = () => {
        if (isUnmountedRef.current) return;
        console.log('[LeadAgentWS] Disconnected');
        setIsConnected(false);
        
        // Attempt reconnect with backoff
        const delay = RETRY_DELAYS[Math.min(retryCountRef.current, RETRY_DELAYS.length - 1)];
        retryCountRef.current++;
        
        reconnectTimeoutRef.current = setTimeout(connect, delay);
      };

      ws.onerror = (err) => {
        console.error('[LeadAgentWS] Error:', err);
        setError('WebSocket connection error');
        onError?.('WebSocket connection error');
      };

    } catch (err) {
      console.error('[LeadAgentWS] Connection failed:', err);
      setError(err.message);
      onError?.(err.message);
    }
  }, [getWsUrl, onProgress, onComplete, onError]);

  // Disconnect
  const disconnect = useCallback(() => {
    if (reconnectTimeoutRef.current) {
      clearTimeout(reconnectTimeoutRef.current);
      reconnectTimeoutRef.current = null;
    }
    if (wsRef.current) {
      wsRef.current.close();
      wsRef.current = null;
    }
    setIsConnected(false);
    retryCountRef.current = 0;
  }, []);

  // Auto-connect on mount
  useEffect(() => {
    if (autoConnect) {
      connect();
    }
    
    return () => {
      isUnmountedRef.current = true;
      disconnect();
    };
  }, [autoConnect, connect, disconnect]);

  // Reconnect if jobId changes
  useEffect(() => {
    if (isConnected) {
      disconnect();
      setTimeout(connect, 100);
    }
  }, [jobId]);

  return {
    isConnected,
    error,
    lastUpdate,
    currentJob,
    connect,
    disconnect,
  };
}

export default useLeadAgentWebSocket;
