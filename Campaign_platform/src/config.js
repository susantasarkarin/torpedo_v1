// Determine API URL: use env variable, or derive from current host for production
const getApiUrl = () => {
  // If explicitly set via environment variable, use it
  if (import.meta.env.VITE_API_URL) {
    return import.meta.env.VITE_API_URL;
  }
  
  // In development (localhost), use the local backend
  if (typeof window !== 'undefined' && window.location.hostname === 'localhost') {
    return "http://localhost:8000";
  }
  
  // In production, use relative URL (reverse proxy handles routing to backend)
  // This avoids mixed content issues when site is served over HTTPS
  if (typeof window !== 'undefined') {
    return "";  // Empty string = relative URL, requests go to same origin
  }
  
  return "http://localhost:8000";
};

export const API_BASE_URL = getApiUrl();