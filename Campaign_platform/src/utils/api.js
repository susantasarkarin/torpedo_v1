/**
 * CENTRALIZED API CLIENT
 * Handles all API requests with consistent error handling, auth, and retry logic.
 *
 * Usage:
 *   import api from '../utils/api';
 *
 *   // GET request
 *   const data = await api.get('/leads');
 *
 *   // POST request
 *   const result = await api.post('/leads', { name: 'John' });
 *
 *   // With pagination
 *   const leads = await api.get('/leads', { skip: 0, limit: 50 });
 */

import { API_BASE_URL, buildApiUrl } from "../config";

// ============== CONFIGURATION ==============

const DEFAULT_TIMEOUT = 30000; // 30 seconds
const MAX_RETRIES = 3;
const RETRY_DELAY = 1000; // 1 second

// ============== REQUEST CACHE & DEDUPLICATION ==============

// In-memory cache for GET requests (TTL-based)
const responseCache = new Map();
const DEFAULT_CACHE_TTL = 30000; // 30 seconds

// In-flight request deduplication (prevents duplicate concurrent requests)
const inflightRequests = new Map();

/**
 * Get cached response if valid
 */
const getCachedResponse = (cacheKey) => {
  const cached = responseCache.get(cacheKey);
  if (cached && Date.now() < cached.expiresAt) {
    return cached.data;
  }
  if (cached) {
    responseCache.delete(cacheKey);
  }
  return null;
};

/**
 * Cache a response
 */
const setCachedResponse = (cacheKey, data, ttl = DEFAULT_CACHE_TTL) => {
  responseCache.set(cacheKey, {
    data,
    expiresAt: Date.now() + ttl,
  });
};

/**
 * Clear specific cache entries or all cache
 */
export const clearCache = (pattern = null) => {
  if (!pattern) {
    responseCache.clear();
    return;
  }
  for (const key of responseCache.keys()) {
    if (key.includes(pattern)) {
      responseCache.delete(key);
    }
  }
};

// ============== AUTH HELPERS ==============

/**
 * Get the current session token from localStorage
 */
export const getSessionToken = () => {
  return localStorage.getItem("session_id") || null;
};

/**
 * Set the session token in localStorage
 */
export const setSessionToken = (token) => {
  if (token) {
    localStorage.setItem("session_id", token);
  } else {
    localStorage.removeItem("session_id");
  }
};

/**
 * Check if user is authenticated
 */
export const isAuthenticated = () => {
  return !!getSessionToken();
};

/**
 * Clear authentication data
 */
export const clearAuth = () => {
  localStorage.removeItem("session_id");
  localStorage.removeItem("username");
  localStorage.removeItem("role");
};

// ============== ERROR HANDLING ==============

/**
 * Custom API Error class with status code and response data
 */
export class APIError extends Error {
  constructor(message, status, data = null) {
    super(message);
    this.name = "APIError";
    this.status = status;
    this.data = data;
  }
}

/**
 * Handle API errors with consistent messaging
 */
const handleError = (error, response) => {
  if (response) {
    // Handle specific status codes
    switch (response.status) {
      case 401:
        clearAuth();
        window.location.href = "/login";
        throw new APIError("Session expired. Please log in again.", 401);
      case 403:
        throw new APIError(
          "You do not have permission to perform this action.",
          403
        );
      case 404:
        throw new APIError("Resource not found.", 404);
      case 422:
        throw new APIError(
          error.detail || "Validation error",
          422,
          error.errors
        );
      case 429:
        throw new APIError("Too many requests. Please try again later.", 429);
      case 500:
        throw new APIError("Server error. Please try again later.", 500);
      default:
        throw new APIError(
          error.detail || error.message || "An error occurred",
          response.status
        );
    }
  }
  throw new APIError(error.message || "Network error", 0);
};

// ============== REQUEST HELPERS ==============

/**
 * Build URL with query parameters
 */
const buildUrl = (endpoint, params = {}) => {
  // Use buildApiUrl helper for consistent URL construction
  const baseUrl = buildApiUrl(endpoint);
  
  // Create URL object - if baseUrl is relative (starts with /), use window.location.origin as base
  const url = baseUrl.startsWith('/') 
    ? new URL(baseUrl, window.location.origin)
    : new URL(baseUrl);

  Object.entries(params).forEach(([key, value]) => {
    if (value !== undefined && value !== null && value !== "") {
      if (Array.isArray(value)) {
        value.forEach((v) => url.searchParams.append(key, v));
      } else {
        url.searchParams.set(key, value);
      }
    }
  });

  return url.toString();
};

/**
 * Get default headers for API requests
 */
const getHeaders = (customHeaders = {}) => {
  const headers = {
    "Content-Type": "application/json",
    ...customHeaders,
  };

  const token = getSessionToken();
  if (token) {
    headers["Authorization"] = token;
  }

  return headers;
};

/**
 * Sleep helper for retry delays
 */
const sleep = (ms) => new Promise((resolve) => setTimeout(resolve, ms));

// ============== MAIN API CLIENT ==============

/**
 * Make an API request with automatic retry, caching, and deduplication
 */
const request = async (
  method,
  endpoint,
  data = null,
  options = {}
) => {
  const {
    params = {},
    headers = {},
    timeout = DEFAULT_TIMEOUT,
    retries = MAX_RETRIES,
    retryDelay = RETRY_DELAY,
    skipAuth = false,
    cache = false, // Enable caching for GET requests
    cacheTTL = DEFAULT_CACHE_TTL,
  } = options;

  const url = buildUrl(endpoint, params);
  
  // Generate cache key for GET requests
  const cacheKey = method === "GET" ? `${url}` : null;
  
  // Check cache for GET requests
  if (method === "GET" && cache && cacheKey) {
    const cached = getCachedResponse(cacheKey);
    if (cached) {
      return cached;
    }
  }
  
  // Deduplicate in-flight GET requests
  if (method === "GET" && cacheKey && inflightRequests.has(cacheKey)) {
    return inflightRequests.get(cacheKey);
  }
  
  const requestHeaders = skipAuth
    ? { "Content-Type": "application/json", ...headers }
    : getHeaders(headers);

  const config = {
    method,
    headers: requestHeaders,
  };

  if (data && ["POST", "PUT", "PATCH"].includes(method)) {
    config.body = JSON.stringify(data);
  }

  // Add timeout using AbortController
  const controller = new AbortController();
  config.signal = controller.signal;
  const timeoutId = setTimeout(() => controller.abort(), timeout);

  let lastError;
  let attempt = 0;
  
  // Create the request promise for deduplication
  const requestPromise = (async () => {
    while (attempt < retries) {
      try {
        const response = await fetch(url, config);
        clearTimeout(timeoutId);

        // Parse response
        const contentType = response.headers.get("content-type");
        let responseData;

        if (contentType && contentType.includes("application/json")) {
          responseData = await response.json();
        } else {
          responseData = await response.text();
        }

        // Handle non-OK responses
        if (!response.ok) {
          handleError(responseData, response);
        }

        // Cache successful GET responses if caching enabled
        if (method === "GET" && cache && cacheKey) {
          setCachedResponse(cacheKey, responseData, cacheTTL);
        }

        return responseData;
      } catch (error) {
        clearTimeout(timeoutId);
        lastError = error;

        // Don't retry on auth errors or validation errors
        if (error instanceof APIError && [401, 403, 422].includes(error.status)) {
          throw error;
        }

        // Don't retry on abort (timeout)
        if (error.name === "AbortError") {
          throw new APIError("Request timeout", 408);
        }

        attempt++;
        if (attempt < retries) {
          console.warn(`API request failed, retrying (${attempt}/${retries})...`);
          await sleep(retryDelay * attempt); // Exponential backoff
        }
      }
    }

    throw lastError || new APIError("Request failed after retries", 0);
  })();
  
  // Store in-flight GET requests for deduplication
  if (method === "GET" && cacheKey) {
    inflightRequests.set(cacheKey, requestPromise);
    try {
      const result = await requestPromise;
      return result;
    } finally {
      inflightRequests.delete(cacheKey);
    }
  }
  
  return requestPromise;
};

// ============== API METHODS ==============

const api = {
  /**
   * GET request
   * @param {string} endpoint - API endpoint
   * @param {object} params - Query parameters
   * @param {object} options - Additional options
   */
  get: (endpoint, params = {}, options = {}) =>
    request("GET", endpoint, null, { ...options, params }),

  /**
   * POST request
   * @param {string} endpoint - API endpoint
   * @param {object} data - Request body
   * @param {object} options - Additional options
   */
  post: (endpoint, data = {}, options = {}) =>
    request("POST", endpoint, data, options),

  /**
   * PUT request
   * @param {string} endpoint - API endpoint
   * @param {object} data - Request body
   * @param {object} options - Additional options
   */
  put: (endpoint, data = {}, options = {}) =>
    request("PUT", endpoint, data, options),

  /**
   * PATCH request
   * @param {string} endpoint - API endpoint
   * @param {object} data - Request body
   * @param {object} options - Additional options
   */
  patch: (endpoint, data = {}, options = {}) =>
    request("PATCH", endpoint, data, options),

  /**
   * DELETE request
   * @param {string} endpoint - API endpoint
   * @param {object} options - Additional options
   */
  delete: (endpoint, options = {}) =>
    request("DELETE", endpoint, null, options),

  // ============== AUTH METHODS ==============

  /**
   * Login and store session
   */
  login: async (username, password) => {
    const response = await request(
      "POST",
      "/login/",
      { username, password },
      { skipAuth: true }
    );

    if (response.session_id) {
      setSessionToken(response.session_id);
      localStorage.setItem("username", response.username);
      localStorage.setItem("role", response.role);
    }

    return response;
  },

  /**
   * Logout and clear session
   */
  logout: async () => {
    try {
      await request("POST", "/logout/");
    } catch (error) {
      console.warn("Logout request failed:", error);
    } finally {
      clearAuth();
    }
  },

  /**
   * Check if authenticated
   */
  isAuthenticated,

  /**
   * Get current user profile
   */
  getProfile: () => request("GET", "/profile/"),

  // ============== HELPER METHODS ==============

  /**
   * Upload file
   * @param {string} endpoint - API endpoint
   * @param {File} file - File to upload
   * @param {object} additionalData - Additional form data
   */
  uploadFile: async (endpoint, file, additionalData = {}) => {
    const formData = new FormData();
    formData.append("file", file);

    Object.entries(additionalData).forEach(([key, value]) => {
      formData.append(key, value);
    });

    const headers = {};
    const token = getSessionToken();
    if (token) {
      headers["Authorization"] = token;
    }

    // Build full URL using buildApiUrl helper
    const url = buildApiUrl(endpoint);

    const response = await fetch(url, {
      method: "POST",
      headers,
      body: formData,
    });

    if (!response.ok) {
      const error = await response.json().catch(() => ({}));
      handleError(error, response);
    }

    return response.json();
  },

  /**
   * Paginated list request
   * @param {string} endpoint - API endpoint
   * @param {object} params - Query parameters including skip/limit
   */
  list: async (endpoint, params = {}) => {
    const { skip = 0, limit = 50, ...otherParams } = params;
    return request("GET", endpoint, null, {
      params: { skip, limit, ...otherParams },
    });
  },

  /**
   * Get all items (handles pagination automatically)
   * WARNING: Use with caution on large datasets
   */
  getAll: async (endpoint, params = {}, maxItems = 10000) => {
    const allItems = [];
    let skip = 0;
    const limit = 100;

    while (allItems.length < maxItems) {
      const response = await api.list(endpoint, { ...params, skip, limit });
      const items = response.items || response;

      if (!Array.isArray(items) || items.length === 0) break;

      allItems.push(...items);

      if (items.length < limit || (response.has_more === false)) break;

      skip += limit;
    }

    return allItems;
  },
  
  // ============== PERFORMANCE METHODS ==============
  
  /**
   * Execute multiple GET requests in parallel
   * @param {Array} requests - Array of { endpoint, params, options } objects
   * @returns {Array} - Array of responses in same order
   */
  parallel: async (requests) => {
    return Promise.all(
      requests.map(({ endpoint, params = {}, options = {} }) =>
        api.get(endpoint, params, options)
      )
    );
  },
  
  /**
   * Execute multiple requests in parallel (any method)
   * @param {Array} requests - Array of { method, endpoint, data, options } objects
   * @returns {Array} - Array of responses in same order
   */
  batch: async (requests) => {
    return Promise.all(
      requests.map(({ method = "GET", endpoint, data = null, options = {} }) => {
        switch (method.toUpperCase()) {
          case "POST": return api.post(endpoint, data, options);
          case "PUT": return api.put(endpoint, data, options);
          case "PATCH": return api.patch(endpoint, data, options);
          case "DELETE": return api.delete(endpoint, options);
          default: return api.get(endpoint, data || {}, options);
        }
      })
    );
  },
  
  /**
   * Cached GET request (30 second TTL by default)
   * @param {string} endpoint - API endpoint
   * @param {object} params - Query parameters
   * @param {number} ttl - Cache TTL in milliseconds
   */
  getCached: (endpoint, params = {}, ttl = DEFAULT_CACHE_TTL) =>
    request("GET", endpoint, null, { params, cache: true, cacheTTL: ttl }),
    
  /**
   * Clear response cache
   * @param {string} pattern - Optional pattern to match (clears all if null)
   */
  clearCache,
};

export default api;

// ============== NAMED EXPORTS FOR CONVENIENCE ==============

export const { get, post, put, patch, delete: del, login, logout, list, uploadFile, getAll, parallel, batch, getCached } = api;
