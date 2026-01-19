// Determine API URL: use env variable, or derive from current host for production
const getApiUrl = () => {
  // If explicitly set via environment variable, use it
  if (import.meta.env.VITE_API_URL) {
    return import.meta.env.VITE_API_URL;
  }

  // In development (localhost), use the local backend directly
  if (typeof window !== "undefined" && window.location.hostname === "localhost") {
    return "http://localhost:8000";
  }

  // In production, use the /api prefix through Nginx proxy
  // This avoids CORS issues and works with both HTTP and HTTPS
  if (typeof window !== "undefined") {
    return window.location.origin + "/api";
  }

  return "http://localhost:8000";
};

export const API_BASE_URL = getApiUrl();
