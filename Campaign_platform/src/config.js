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
  
  // In production, use the same host with API port 8000
  if (typeof window !== 'undefined') {
    const protocol = window.location.protocol;
    const host = window.location.hostname;
    return `${protocol}//${host}:8000`;
  }
  
  return "http://localhost:8000";
};

export const API_BASE_URL = getApiUrl();