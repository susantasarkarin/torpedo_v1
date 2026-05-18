/**
 * useSurveyWebSocket Hook
 * 
 * Generic WebSocket hook for real-time survey updates.
 * Supports both CINT and CPX survey channels with auto-reconnect.
 * 
 * Features:
 * - Auto-reconnect with exponential backoff
 * - Heartbeat handling
 * - Connection status tracking
 * - Callback for survey updates
 * 
 * Usage:
 * ```jsx
 * const { surveys, isConnected, error } = useSurveyWebSocket('cint');
 * // or
 * const { surveys, isConnected, error } = useSurveyWebSocket('cpx');
 * ```
 */

import { useState, useEffect, useRef, useCallback } from 'react';
import { WS_BASE_URL } from '../config';

// Retry delays in milliseconds: 2s, 5s, 10s, 20s, 30s
const RETRY_DELAYS = [2000, 5000, 10000, 20000, 30000];
const MAX_RETRIES = 5;

/**
 * WebSocket hook for survey updates
 * 
 * @param {string} channel - 'cint' or 'cpx'
 * @param {Object} options - Configuration options
 * @param {boolean} options.autoConnect - Auto-connect on mount (default: true)
 * @param {function} options.onSurveysUpdate - Callback when new surveys arrive
 * @param {function} options.onConnect - Callback on successful connection
 * @param {function} options.onDisconnect - Callback on disconnection
 * @param {function} options.onError - Callback on error
 */
export function useSurveyWebSocket(channel, options = {}) {
  const {
    autoConnect = true,
    onSurveysUpdate,
    onConnect,
    onDisconnect,
    onError,
  } = options;

  const [surveys, setSurveys] = useState([]);
  const [isConnected, setIsConnected] = useState(false);
  const [error, setError] = useState(null);
  const [lastUpdate, setLastUpdate] = useState(null);

  const wsRef = useRef(null);
  const reconnectTimeoutRef = useRef(null);
  const retryCountRef = useRef(0);
  const isUnmountedRef = useRef(false);

  // Build WebSocket URL based on channel
  const getWsUrl = useCallback(() => {
    if (channel === 'cint') {
      return `${WS_BASE_URL}/api/cint/ws/surveys`;
    } else if (channel === 'cpx') {
      return `${WS_BASE_URL}/cpx/ws/surveys`;
    } else {
      throw new Error(`Unknown channel: ${channel}`);
    }
  }, [channel]);

  // Connect to WebSocket
  const connect = useCallback(() => {
    // Don't connect if unmounted or already connecting/connected
    if (isUnmountedRef.current) return;
    if (wsRef.current && wsRef.current.readyState === WebSocket.CONNECTING) return;
    if (wsRef.current && wsRef.current.readyState === WebSocket.OPEN) return;

    // Check max retries
    if (retryCountRef.current >= MAX_RETRIES) {
      setError('Maximum reconnection attempts exceeded');
      onError?.('Maximum reconnection attempts exceeded');
      return;
    }

    try {
      const wsUrl = getWsUrl();
      console.log(`[${channel}] Connecting to WebSocket:`, wsUrl);
      
      const ws = new WebSocket(wsUrl);
      wsRef.current = ws;

      ws.onopen = () => {
        if (isUnmountedRef.current) return;
        
        console.log(`[${channel}] WebSocket connected`);
        console.debug('[ws:connect]', { domain: `survey-${channel}` });
        setIsConnected(true);
        setError(null);
        retryCountRef.current = 0;
        onConnect?.();
      };

      ws.onmessage = (event) => {
        if (isUnmountedRef.current) return;
        
        try {
          const data = JSON.parse(event.data);
          
          if (data.type === 'surveys_update' && data.surveys) {
            console.log(`[${channel}] Received ${data.surveys.length} surveys`);
            setSurveys(data.surveys);
            setLastUpdate(new Date().toISOString());
            onSurveysUpdate?.(data.surveys, data);
          } else if (data.type === 'connected') {
            console.log(`[${channel}] Connection confirmed:`, data.message);
          } else if (data.type === 'heartbeat') {
            // Send pong response
            if (ws.readyState === WebSocket.OPEN) {
              ws.send(JSON.stringify({ type: 'ping' }));
            }
          }
        } catch (e) {
          console.warn(`[${channel}] Failed to parse message:`, e);
        }
      };

      ws.onerror = (event) => {
        console.error(`[${channel}] WebSocket error:`, event);
        setError('WebSocket connection error');
        onError?.('WebSocket connection error');
      };

      ws.onclose = (event) => {
        if (isUnmountedRef.current) return;
        
        console.log(`[${channel}] WebSocket closed:`, event.code, event.reason);
        console.debug('[ws:disconnect]', { domain: `survey-${channel}`, code: event.code });
        setIsConnected(false);
        wsRef.current = null;
        onDisconnect?.();

        // Schedule reconnection if not a normal close
        if (event.code !== 1000 && retryCountRef.current < MAX_RETRIES) {
          const delay = RETRY_DELAYS[Math.min(retryCountRef.current, RETRY_DELAYS.length - 1)];
          retryCountRef.current++;
          
          console.log(`[${channel}] Reconnecting in ${delay}ms (attempt ${retryCountRef.current}/${MAX_RETRIES})`);
          
          reconnectTimeoutRef.current = setTimeout(() => {
            if (!isUnmountedRef.current) {
              connect();
            }
          }, delay);
        }
      };

    } catch (e) {
      console.error(`[${channel}] Failed to create WebSocket:`, e);
      setError(e.message);
      onError?.(e.message);
    }
  }, [channel, getWsUrl, onConnect, onDisconnect, onError, onSurveysUpdate]);

  // Disconnect from WebSocket
  const disconnect = useCallback(() => {
    console.log(`[${channel}] Disconnecting WebSocket`);
    
    if (reconnectTimeoutRef.current) {
      clearTimeout(reconnectTimeoutRef.current);
      reconnectTimeoutRef.current = null;
    }
    
    if (wsRef.current) {
      wsRef.current.close(1000, 'User disconnect');
      wsRef.current = null;
    }
    
    setIsConnected(false);
    retryCountRef.current = 0;
  }, [channel]);

  // Send message through WebSocket
  const sendMessage = useCallback((message) => {
    if (wsRef.current && wsRef.current.readyState === WebSocket.OPEN) {
      wsRef.current.send(typeof message === 'string' ? message : JSON.stringify(message));
      return true;
    }
    return false;
  }, []);

  // Reset and reconnect
  const reconnect = useCallback(() => {
    retryCountRef.current = 0;
    disconnect();
    setTimeout(connect, 100);
  }, [connect, disconnect]);

  // Auto-connect on mount
  useEffect(() => {
    isUnmountedRef.current = false;
    
    if (autoConnect) {
      connect();
    }
    
    return () => {
      isUnmountedRef.current = true;
      disconnect();
    };
  }, [autoConnect, connect, disconnect]);

  return {
    surveys,
    isConnected,
    error,
    lastUpdate,
    connect,
    disconnect,
    reconnect,
    sendMessage,
  };
}

export default useSurveyWebSocket;
