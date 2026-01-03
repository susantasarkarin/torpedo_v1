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

import { API_BASE_URL } from "../config";

// ============== CONFIGURATION ==============

const DEFAULT_TIMEOUT = 30000; // 30 seconds
const MAX_RETRIES = 3;
const RETRY_DELAY = 1000; // 1 second

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
  const url = new URL(`${API_BASE_URL}${endpoint}`);

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
 * Make an API request with automatic retry and error handling
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
  } = options;

  const url = buildUrl(endpoint, params);
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

    const response = await fetch(`${API_BASE_URL}${endpoint}`, {
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
};

export default api;

// ============== NAMED EXPORTS FOR CONVENIENCE ==============

export const { get, post, put, patch, delete: del, login, logout, list, uploadFile, getAll } = api;
