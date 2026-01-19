/**
 * LeadAgentContext
 * 
 * Global React Context for lead generation agent operations.
 * Tracks agent jobs, quota, configurations, and WebSocket connection.
 * 
 * Features:
 * - Track active agent jobs and their progress
 * - Manage daily quota status
 * - Load/save agent configurations
 * - WebSocket connection for real-time progress updates
 */

import React, { createContext, useContext, useState, useEffect, useCallback, useRef } from 'react';
import api from '../utils/api';

// Constants
const DAILY_LIMIT = 1000;
const RETRY_DELAYS = [2000, 5000, 10000, 20000, 30000];
const MAX_RETRIES = 5;

// Initial state
const initialState = {
  // Quota
  quota: {
    leads_today: 0,
    limit: DAILY_LIMIT,
    remaining: DAILY_LIMIT,
    is_limit_reached: false,
  },
  // Active jobs
  activeJobs: [],
  // Configurations
  configs: [],
  defaultConfigs: [],
  selectedConfig: null,
  // WebSocket
  isConnected: false,
  connectionError: null,
  // UI state
  isLoading: false,
  error: null,
};

// Create context
const LeadAgentContext = createContext(null);

/**
 * LeadAgentProvider component
 */
export function LeadAgentProvider({ children }) {
  const [state, setState] = useState(initialState);
  
  const wsRef = useRef(null);
  const reconnectTimeoutRef = useRef(null);
  const retryCountRef = useRef(0);
  const isUnmountedRef = useRef(false);

  // ============== API FUNCTIONS ==============

  const fetchQuota = useCallback(async () => {
    try {
      const response = await api.get('/leads/agents/quota');
      setState(prev => ({
        ...prev,
        quota: response.data || response,
      }));
    } catch (err) {
      console.error('Failed to fetch quota:', err);
    }
  }, []);

  const fetchJobs = useCallback(async (status = null) => {
    try {
      const params = status ? { status } : {};
      const response = await api.get('/leads/agents/jobs', params);
      const jobs = response.data?.jobs || response.jobs || [];
      setState(prev => ({
        ...prev,
        activeJobs: jobs,
      }));
      return jobs;
    } catch (err) {
      console.error('Failed to fetch jobs:', err);
      return [];
    }
  }, []);

  const fetchConfigs = useCallback(async () => {
    try {
      const response = await api.get('/leads/agents/configs', { include_defaults: true });
      const configs = response.data?.configs || response.configs || [];
      
      const defaultConfigs = configs.filter(c => c.is_default);
      const userConfigs = configs.filter(c => !c.is_default);
      
      setState(prev => ({
        ...prev,
        configs: userConfigs,
        defaultConfigs: defaultConfigs,
      }));
      return configs;
    } catch (err) {
      console.error('Failed to fetch configs:', err);
      return [];
    }
  }, []);

  const getJobStatus = useCallback(async (jobId) => {
    try {
      const response = await api.get(`/leads/agents/status/${jobId}`);
      return response.data || response;
    } catch (err) {
      console.error('Failed to fetch job status:', err);
      return null;
    }
  }, []);

  const runAgents = useCallback(async (options = {}) => {
    const {
      agents = ['company_discovery', 'contact_finder', 'lead_enricher', 'lead_scorer', 'outreach_composer'],
      companyIds = null,
      configId = null,
      icpCriteria = null,
    } = options;

    setState(prev => ({ ...prev, isLoading: true, error: null }));

    try {
      const response = await api.post('/leads/agents/run', {
        agents,
        company_ids: companyIds,
        config_id: configId,
        icp_criteria: icpCriteria,
      });
      
      const result = response.data || response;
      
      // Refresh jobs list
      await fetchJobs();
      
      setState(prev => ({ ...prev, isLoading: false }));
      return result;
    } catch (err) {
      const errorMsg = err.response?.data?.detail || err.message || 'Failed to start agents';
      setState(prev => ({ ...prev, isLoading: false, error: errorMsg }));
      throw new Error(errorMsg);
    }
  }, [fetchJobs]);

  const uploadCompanies = useCallback(async (file, options = {}) => {
    const { runContactFinder = false, configId = null } = options;
    
    setState(prev => ({ ...prev, isLoading: true, error: null }));
    
    try {
      const formData = new FormData();
      formData.append('file', file);
      formData.append('run_contact_finder', runContactFinder.toString());
      if (configId) {
        formData.append('config_id', configId);
      }
      
      const response = await api.post('/leads/agents/import/companies', formData, {
        headers: { 'Content-Type': 'multipart/form-data' },
      });
      
      const result = response.data || response;
      setState(prev => ({ ...prev, isLoading: false }));
      
      // Refresh quota after upload
      await fetchQuota();
      
      return result;
    } catch (err) {
      const errorMsg = err.response?.data?.detail || err.message || 'Failed to upload companies';
      setState(prev => ({ ...prev, isLoading: false, error: errorMsg }));
      throw new Error(errorMsg);
    }
  }, [fetchQuota]);

  const cancelJob = useCallback(async (jobId) => {
    try {
      await api.post(`/leads/agents/jobs/${jobId}/cancel`);
      await fetchJobs();
      return true;
    } catch (err) {
      console.error('Failed to cancel job:', err);
      return false;
    }
  }, [fetchJobs]);

  const saveConfig = useCallback(async (configData) => {
    try {
      const response = await api.post('/leads/agents/configs', configData);
      await fetchConfigs();
      return response.data || response;
    } catch (err) {
      throw new Error(err.response?.data?.detail || 'Failed to save configuration');
    }
  }, [fetchConfigs]);

  const updateConfig = useCallback(async (configId, updates) => {
    try {
      const response = await api.put(`/leads/agents/configs/${configId}`, updates);
      await fetchConfigs();
      return response.data || response;
    } catch (err) {
      throw new Error(err.response?.data?.detail || 'Failed to update configuration');
    }
  }, [fetchConfigs]);

  const deleteConfig = useCallback(async (configId) => {
    try {
      await api.delete(`/leads/agents/configs/${configId}`);
      await fetchConfigs();
      return true;
    } catch (err) {
      throw new Error(err.response?.data?.detail || 'Failed to delete configuration');
    }
  }, [fetchConfigs]);

  const selectConfig = useCallback((config) => {
    setState(prev => ({ ...prev, selectedConfig: config }));
  }, []);

  // ============== WEBSOCKET CONNECTION ==============

  const connectWebSocket = useCallback((jobId = null) => {
    if (isUnmountedRef.current) return;
    if (wsRef.current && wsRef.current.readyState === WebSocket.OPEN) return;

    if (retryCountRef.current >= MAX_RETRIES) {
      setState(prev => ({
        ...prev,
        connectionError: 'Maximum reconnection attempts exceeded',
        isConnected: false,
      }));
      return;
    }

    try {
      const apiBase = import.meta.env.VITE_API_URL || 'http://localhost:8000';
      const wsBase = apiBase.replace(/^http/, 'ws');
      const wsUrl = jobId 
        ? `${wsBase}/leads/agents/ws/${jobId}`
        : `${wsBase}/leads/agents/ws/all`;
      
      console.log('[LeadAgent] Connecting to WebSocket:', wsUrl);
      
      const ws = new WebSocket(wsUrl);
      wsRef.current = ws;

      ws.onopen = () => {
        if (isUnmountedRef.current) return;
        console.log('[LeadAgent] WebSocket connected');
        setState(prev => ({
          ...prev,
          isConnected: true,
          connectionError: null,
        }));
        retryCountRef.current = 0;
      };

      ws.onmessage = (event) => {
        if (isUnmountedRef.current) return;
        
        try {
          const data = JSON.parse(event.data);
          
          if (data.type === 'agent_progress') {
            // Update job in activeJobs list
            setState(prev => {
              const updatedJobs = prev.activeJobs.map(job => 
                job.job_id === data.job_id
                  ? { ...job, ...data }
                  : job
              );
              return { ...prev, activeJobs: updatedJobs };
            });
          } else if (data.type === 'job_completed' || data.type === 'job_failed') {
            // Refresh jobs and quota
            fetchJobs();
            fetchQuota();
          }
        } catch (e) {
          console.error('[LeadAgent] Failed to parse WebSocket message:', e);
        }
      };

      ws.onclose = () => {
        if (isUnmountedRef.current) return;
        console.log('[LeadAgent] WebSocket disconnected');
        
        setState(prev => ({ ...prev, isConnected: false }));
        
        // Attempt reconnect
        const delay = RETRY_DELAYS[Math.min(retryCountRef.current, RETRY_DELAYS.length - 1)];
        retryCountRef.current++;
        
        reconnectTimeoutRef.current = setTimeout(() => {
          connectWebSocket(jobId);
        }, delay);
      };

      ws.onerror = (error) => {
        console.error('[LeadAgent] WebSocket error:', error);
        setState(prev => ({
          ...prev,
          connectionError: 'WebSocket connection error',
        }));
      };

    } catch (err) {
      console.error('[LeadAgent] Failed to connect WebSocket:', err);
    }
  }, [fetchJobs, fetchQuota]);

  const disconnectWebSocket = useCallback(() => {
    if (reconnectTimeoutRef.current) {
      clearTimeout(reconnectTimeoutRef.current);
    }
    if (wsRef.current) {
      wsRef.current.close();
      wsRef.current = null;
    }
    setState(prev => ({ ...prev, isConnected: false }));
  }, []);

  // ============== EFFECTS ==============

  // Initial data fetch
  useEffect(() => {
    fetchQuota();
    fetchJobs();
    fetchConfigs();
  }, [fetchQuota, fetchJobs, fetchConfigs]);

  // Cleanup on unmount
  useEffect(() => {
    return () => {
      isUnmountedRef.current = true;
      disconnectWebSocket();
    };
  }, [disconnectWebSocket]);

  // ============== CONTEXT VALUE ==============

  const contextValue = {
    // State
    ...state,
    
    // API functions
    fetchQuota,
    fetchJobs,
    fetchConfigs,
    getJobStatus,
    runAgents,
    uploadCompanies,
    cancelJob,
    saveConfig,
    updateConfig,
    deleteConfig,
    selectConfig,
    
    // WebSocket
    connectWebSocket,
    disconnectWebSocket,
    
    // Computed
    isQuotaExhausted: state.quota.is_limit_reached,
    hasActiveJobs: state.activeJobs.some(j => j.status === 'running' || j.status === 'pending'),
  };

  return (
    <LeadAgentContext.Provider value={contextValue}>
      {children}
    </LeadAgentContext.Provider>
  );
}

/**
 * Hook to use lead agent context
 */
export function useLeadAgent() {
  const context = useContext(LeadAgentContext);
  if (!context) {
    throw new Error('useLeadAgent must be used within a LeadAgentProvider');
  }
  return context;
}

export default LeadAgentContext;
