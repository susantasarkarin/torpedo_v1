// Determine API URL: use relative URLs in production (nginx proxies to backend)
// This avoids mixed content issues when site is served over HTTPS
const getApiUrl = () => {
  // In development (localhost), use the local backend
  if (typeof window !== 'undefined' && window.location.hostname === 'localhost') {
    return "http://localhost:8000";
  }
  
  // In production, ALWAYS use relative URL (reverse proxy handles routing to backend)
  // The nginx config proxies /login, /api, /gmail, etc. to the backend
  if (typeof window !== 'undefined') {
    return "";  // Empty string = relative URL, requests go to same origin
  }
  
  return "http://localhost:8000";
};

// Get WebSocket URL based on current context
const getWsUrl = () => {
  if (typeof window !== 'undefined' && window.location.hostname === 'localhost') {
    return "ws://localhost:8000";
  }
  
  // In production, use the same host with wss (since we're on https)
  if (typeof window !== 'undefined') {
    const protocol = window.location.protocol === 'https:' ? 'wss:' : 'ws:';
    return `${protocol}//${window.location.host}`;
  }
  
  return "ws://localhost:8000";
};

export const API_BASE_URL = getApiUrl();
export const WS_BASE_URL = getWsUrl();

/**
 * Helper function to build full URL from endpoint
 * Handles the case when API_BASE_URL is empty string (production with relative URLs)
 * @param {string} endpoint - The API endpoint (e.g., "/leads", "/projects/")
 * @returns {string} - Full URL or relative URL
 */
export const buildApiUrl = (endpoint) => {
  // If API_BASE_URL is empty or whitespace, return the endpoint as-is (relative URL)
  if (!API_BASE_URL || API_BASE_URL.trim() === "") {
    return endpoint;
  }
  // Otherwise, concatenate base URL with endpoint
  return `${API_BASE_URL}${endpoint}`;
};