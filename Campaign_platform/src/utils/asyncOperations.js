/**
 * ASYNC OPERATIONS CLIENT
 * Handles polling for long-running operations with exponential backoff.
 * 
 * Usage:
 *   import { startAsyncOperation, pollOperation } from '../utils/asyncOperations';
 * 
 *   // Start an async operation
 *   const operation = await startAsyncOperation('/gmail/parallel-sync/start', { since_days: 7 });
 *   
 *   // Poll with callbacks
 *   await pollOperation(operation.operation_id, {
 *     onProgress: (status) => setProgress(status.progress),
 *     onComplete: (result) => console.log('Done!', result),
 *     onError: (error) => console.error('Failed:', error)
 *   });
 */

import api from './api';

// ============== CONFIGURATION ==============

const DEFAULT_POLL_INTERVAL = 1000;      // Initial poll interval: 1 second
const MAX_POLL_INTERVAL = 30000;         // Max poll interval: 30 seconds
const BACKOFF_MULTIPLIER = 1.5;          // Exponential backoff multiplier
const MAX_POLL_ATTEMPTS = 300;           // Max attempts before giving up (~10 min with backoff)
const POLL_TIMEOUT = 600000;             // Overall timeout: 10 minutes

// ============== OPERATION STATUS CONSTANTS ==============

export const OperationStatus = {
  PENDING: 'PENDING',
  STARTED: 'started',
  IN_PROGRESS: 'in_progress',
  PROGRESS: 'PROGRESS',
  COMPLETED: 'completed',
  SUCCESS: 'SUCCESS',
  FAILED: 'failed',
  FAILURE: 'FAILURE',
  CANCELLED: 'cancelled',
  NOT_FOUND: 'not_found'
};

/**
 * Check if an operation is still running
 */
export const isOperationRunning = (status) => {
  const runningStatuses = [
    OperationStatus.PENDING,
    OperationStatus.STARTED,
    OperationStatus.IN_PROGRESS,
    OperationStatus.PROGRESS
  ];
  return runningStatuses.includes(status);
};

/**
 * Check if an operation has completed (success or failure)
 */
export const isOperationComplete = (status) => {
  const completeStatuses = [
    OperationStatus.COMPLETED,
    OperationStatus.SUCCESS,
    OperationStatus.FAILED,
    OperationStatus.FAILURE,
    OperationStatus.CANCELLED,
    OperationStatus.NOT_FOUND
  ];
  return completeStatuses.includes(status);
};

/**
 * Check if an operation was successful
 */
export const isOperationSuccessful = (status) => {
  return [OperationStatus.COMPLETED, OperationStatus.SUCCESS].includes(status);
};

// ============== ACTIVE OPERATIONS REGISTRY ==============

// Track active polling operations to prevent duplicates
const activePollers = new Map();

/**
 * Get all active polling operations
 */
export const getActivePollers = () => {
  return Array.from(activePollers.entries()).map(([id, data]) => ({
    operationId: id,
    ...data
  }));
};

/**
 * Check if an operation is being polled
 */
export const isPolling = (operationId) => {
  return activePollers.has(operationId);
};

/**
 * Cancel polling for an operation
 */
export const cancelPolling = (operationId) => {
  const poller = activePollers.get(operationId);
  if (poller) {
    poller.cancelled = true;
    activePollers.delete(operationId);
    return true;
  }
  return false;
};

// ============== MAIN API FUNCTIONS ==============

/**
 * Start a new async operation
 * 
 * @param {string} endpoint - API endpoint that returns an operation ID
 * @param {object} data - Request body data
 * @param {object} options - Additional options
 * @returns {Promise<object>} - Operation details including operation_id
 */
export const startAsyncOperation = async (endpoint, data = {}, options = {}) => {
  try {
    const response = await api.post(endpoint, data, {
      timeout: 30000,  // 30 second timeout for starting operation
      ...options
    });
    
    if (!response.operation_id && !response.task_id) {
      // Endpoint might not return an operation_id - it's a sync endpoint
      return {
        ...response,
        sync: true
      };
    }
    
    return {
      operationId: response.operation_id || response.task_id,
      status: response.status || OperationStatus.STARTED,
      pollUrl: response.poll_url || `/operations/async/${response.operation_id || response.task_id}/status`,
      ...response
    };
  } catch (error) {
    console.error('Failed to start async operation:', error);
    throw error;
  }
};

/**
 * Get status of an operation
 * 
 * @param {string} operationId - Operation ID to check
 * @returns {Promise<object>} - Current operation status
 */
export const getOperationStatus = async (operationId) => {
  try {
    const response = await api.get(`/operations/async/${operationId}/status`, {}, {
      timeout: 10000,  // 10 second timeout for status check
      cache: false     // Never cache status checks
    });
    
    return {
      operationId,
      ...response
    };
  } catch (error) {
    // If 404, the operation doesn't exist
    if (error.status === 404) {
      return {
        operationId,
        status: OperationStatus.NOT_FOUND,
        error: 'Operation not found'
      };
    }
    throw error;
  }
};

/**
 * Poll an operation with exponential backoff
 * 
 * @param {string} operationId - Operation ID to poll
 * @param {object} callbacks - Callback functions
 * @param {function} callbacks.onProgress - Called with status updates
 * @param {function} callbacks.onComplete - Called when operation completes successfully
 * @param {function} callbacks.onError - Called when operation fails
 * @param {object} options - Polling options
 * @returns {Promise<object>} - Final operation result
 */
export const pollOperation = async (operationId, callbacks = {}, options = {}) => {
  const {
    onProgress = () => {},
    onComplete = () => {},
    onError = () => {}
  } = callbacks;
  
  const {
    initialInterval = DEFAULT_POLL_INTERVAL,
    maxInterval = MAX_POLL_INTERVAL,
    backoffMultiplier = BACKOFF_MULTIPLIER,
    maxAttempts = MAX_POLL_ATTEMPTS,
    timeout = POLL_TIMEOUT
  } = options;
  
  // Check if already polling this operation
  if (activePollers.has(operationId)) {
    console.warn(`Already polling operation: ${operationId}`);
    return activePollers.get(operationId).promise;
  }
  
  let currentInterval = initialInterval;
  let attempts = 0;
  const startTime = Date.now();
  
  // Register this poller
  const pollerState = {
    cancelled: false,
    startTime,
    attempts: 0,
    lastStatus: null
  };
  
  const pollPromise = new Promise(async (resolve, reject) => {
    while (!pollerState.cancelled) {
      attempts++;
      pollerState.attempts = attempts;
      
      // Check timeout
      if (Date.now() - startTime > timeout) {
        const error = new Error(`Operation ${operationId} timed out after ${timeout}ms`);
        onError(error);
        activePollers.delete(operationId);
        reject(error);
        return;
      }
      
      // Check max attempts
      if (attempts > maxAttempts) {
        const error = new Error(`Operation ${operationId} exceeded max polling attempts (${maxAttempts})`);
        onError(error);
        activePollers.delete(operationId);
        reject(error);
        return;
      }
      
      try {
        const status = await getOperationStatus(operationId);
        pollerState.lastStatus = status;
        
        // Call progress callback
        onProgress(status);
        
        // Check if complete
        if (isOperationComplete(status.status)) {
          activePollers.delete(operationId);
          
          if (isOperationSuccessful(status.status)) {
            onComplete(status);
            resolve(status);
          } else {
            const error = new Error(status.error || `Operation ${operationId} failed`);
            error.status = status;
            onError(error);
            reject(error);
          }
          return;
        }
        
        // Wait before next poll with exponential backoff
        await new Promise(r => setTimeout(r, currentInterval));
        
        // Increase interval with backoff, but don't exceed max
        currentInterval = Math.min(currentInterval * backoffMultiplier, maxInterval);
        
      } catch (error) {
        console.error(`Error polling operation ${operationId}:`, error);
        
        // On network error, increase backoff but continue polling
        currentInterval = Math.min(currentInterval * 2, maxInterval);
        await new Promise(r => setTimeout(r, currentInterval));
      }
    }
    
    // Polling was cancelled
    activePollers.delete(operationId);
    resolve({ operationId, status: OperationStatus.CANCELLED, cancelled: true });
  });
  
  pollerState.promise = pollPromise;
  activePollers.set(operationId, pollerState);
  
  return pollPromise;
};

/**
 * Start an async operation and poll until completion
 * Combines startAsyncOperation and pollOperation into one call
 * 
 * @param {string} endpoint - API endpoint to call
 * @param {object} data - Request body data
 * @param {object} callbacks - Polling callbacks
 * @param {object} options - Start and poll options
 * @returns {Promise<object>} - Final operation result
 */
export const startAndPoll = async (endpoint, data = {}, callbacks = {}, options = {}) => {
  // Start the operation
  const operation = await startAsyncOperation(endpoint, data, options);
  
  // If it's a sync response, return immediately
  if (operation.sync) {
    if (callbacks.onComplete) {
      callbacks.onComplete(operation);
    }
    return operation;
  }
  
  // Poll until complete
  return pollOperation(operation.operationId, callbacks, options);
};

/**
 * Cancel a running operation on the server
 * 
 * @param {string} operationId - Operation ID to cancel
 * @returns {Promise<object>} - Cancellation result
 */
export const cancelOperation = async (operationId) => {
  try {
    // Cancel local polling first
    cancelPolling(operationId);
    
    // Send cancel request to server
    const response = await api.post(`/operations/async/${operationId}/cancel`);
    
    return {
      operationId,
      cancelled: true,
      ...response
    };
  } catch (error) {
    console.error(`Failed to cancel operation ${operationId}:`, error);
    throw error;
  }
};

/**
 * List all active operations from the server
 * 
 * @param {string} operationType - Optional filter by operation type
 * @returns {Promise<object>} - List of active operations
 */
export const listActiveOperations = async (operationType = null) => {
  try {
    const params = operationType ? { type: operationType } : {};
    const response = await api.get('/operations/async/active', params);
    
    return response;
  } catch (error) {
    console.error('Failed to list active operations:', error);
    return { operations: [], count: 0 };
  }
};

// ============== CONVENIENCE FUNCTIONS FOR SPECIFIC OPERATIONS ==============

/**
 * Start email sync for a specific account or all accounts
 * 
 * @param {string} accountEmail - Email account to sync (null for all)
 * @param {number} sinceDays - Only sync emails from last N days
 * @param {object} callbacks - Progress callbacks
 * @returns {Promise<object>} - Sync result
 */
export const startEmailSync = async (accountEmail = null, sinceDays = 0, callbacks = {}) => {
  const data = { since_days: sinceDays };
  if (accountEmail) {
    data.account_email = accountEmail;
  }
  
  return startAndPoll('/gmail/parallel-sync/start', data, callbacks, {
    maxInterval: 5000,  // Poll more frequently for email sync
    timeout: 1800000    // 30 minute timeout for large syncs
  });
};

/**
 * Start AI processing pipeline
 * 
 * @param {string} accountEmail - Filter by account (optional)
 * @param {number} limit - Max leads to process
 * @param {object} callbacks - Progress callbacks
 * @returns {Promise<object>} - Processing result
 */
export const startAIProcessing = async (accountEmail = null, limit = 100, callbacks = {}) => {
  const data = { limit };
  if (accountEmail) {
    data.account_email = accountEmail;
  }
  
  return startAndPoll('/gmail/ai-agents/pipeline/start', data, callbacks, {
    maxInterval: 10000,  // AI processing can be slower
    timeout: 3600000     // 1 hour timeout for AI processing
  });
};

export default {
  startAsyncOperation,
  getOperationStatus,
  pollOperation,
  startAndPoll,
  cancelOperation,
  cancelPolling,
  listActiveOperations,
  isPolling,
  getActivePollers,
  // Convenience methods
  startEmailSync,
  startAIProcessing,
  // Constants
  OperationStatus,
  isOperationRunning,
  isOperationComplete,
  isOperationSuccessful
};
