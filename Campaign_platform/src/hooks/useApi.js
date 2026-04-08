/**
 * useApi - Custom hook for API data fetching with caching
 * 
 * Features:
 * - Automatic caching with configurable TTL
 * - Loading and error states
 * - Refetch capability
 * - Optimistic updates
 * - Automatic retry on failure
 * - Debounced search
 */

import { useState, useEffect, useCallback, useRef, useMemo } from "react"
import { useNavigate } from "react-router-dom"
import { API_BASE_URL, buildApiUrl } from "../config"

// Simple in-memory cache
const cache = new Map()
const CACHE_TTL = 10 * 60 * 1000 // 10 minutes default

/**
 * Get cached data if still valid
 */
const getCachedData = (key, ttl = CACHE_TTL) => {
  const cached = cache.get(key)
  if (cached && Date.now() - cached.timestamp < ttl) {
    return cached.data
  }
  return null
}

/**
 * Set cache data
 */
const setCacheData = (key, data) => {
  cache.set(key, { data, timestamp: Date.now() })
}

/**
 * Clear cache for a specific key or pattern
 */
export const clearCache = (pattern = null) => {
  if (!pattern) {
    cache.clear()
  } else {
    for (const key of cache.keys()) {
      if (key.includes(pattern)) {
        cache.delete(key)
      }
    }
  }
}

/**
 * Main API fetching hook
 * @param {string} endpoint - API endpoint (relative to API_BASE_URL)
 * @param {object} options - Configuration options
 */
export function useApi(endpoint, options = {}) {
  const {
    immediate = true,      // Fetch immediately on mount
    cacheTTL = CACHE_TTL,  // Cache time-to-live
    cacheKey = null,       // Custom cache key
    onSuccess = null,      // Success callback
    onError = null,        // Error callback
    transform = null,      // Transform response data
    requireAuth = true,    // Require session_id
    retries = 1,          // Number of retries on failure
    retryDelay = 1000,    // Delay between retries
  } = options

  const navigate = useNavigate()
  const [data, setData] = useState(null)
  const [loading, setLoading] = useState(immediate)
  const [error, setError] = useState(null)
  const abortControllerRef = useRef(null)
  const retryCountRef = useRef(0)

  // Generate cache key
  const effectiveCacheKey = cacheKey || `${endpoint}`

  // Fetch function
  const fetchData = useCallback(async (skipCache = false) => {
    // Check cache first
    if (!skipCache) {
      const cached = getCachedData(effectiveCacheKey, cacheTTL)
      if (cached) {
        setData(cached)
        setLoading(false)
        return cached
      }
    }

    // Cancel any pending request
    if (abortControllerRef.current) {
      abortControllerRef.current.abort()
    }
    abortControllerRef.current = new AbortController()

    setLoading(true)
    setError(null)

    try {
      const headers = {
        "Content-Type": "application/json",
      }

      if (requireAuth) {
        const sessionId = localStorage.getItem("session_id")
        if (!sessionId) {
          navigate("/admin/login")
          return null
        }
        headers.Authorization = sessionId
      }

      const response = await fetch(buildApiUrl(`${endpoint}`), {
        headers,
        signal: abortControllerRef.current.signal,
      })

      if (response.status === 401) {
        localStorage.removeItem("session_id")
        navigate("/admin/login")
        return null
      }

      if (!response.ok) {
        const errorData = await response.json().catch(() => ({}))
        throw new Error(errorData.detail || `HTTP ${response.status}`)
      }

      let result = await response.json()

      // Apply transformation if provided
      if (transform) {
        result = transform(result)
      }

      // Cache the result
      setCacheData(effectiveCacheKey, result)
      
      setData(result)
      retryCountRef.current = 0
      
      if (onSuccess) {
        onSuccess(result)
      }

      return result
    } catch (err) {
      if (err.name === "AbortError") {
        return null
      }

      // Retry logic
      if (retryCountRef.current < retries) {
        retryCountRef.current++
        await new Promise(resolve => setTimeout(resolve, retryDelay))
        return fetchData(true)
      }

      const errorMessage = err.message || "An error occurred"
      setError(errorMessage)
      
      if (onError) {
        onError(err)
      }

      return null
    } finally {
      setLoading(false)
    }
  }, [endpoint, effectiveCacheKey, cacheTTL, requireAuth, transform, navigate, onSuccess, onError, retries, retryDelay])

  // Refetch (bypassing cache)
  const refetch = useCallback(() => {
    return fetchData(true)
  }, [fetchData])

  // Mutate local data optimistically
  const mutate = useCallback((updater) => {
    setData(prev => {
      const newData = typeof updater === "function" ? updater(prev) : updater
      setCacheData(effectiveCacheKey, newData)
      return newData
    })
  }, [effectiveCacheKey])

  // Fetch on mount if immediate
  useEffect(() => {
    if (immediate && endpoint) {
      fetchData()
    }

    return () => {
      if (abortControllerRef.current) {
        abortControllerRef.current.abort()
      }
    }
  }, [immediate, endpoint, fetchData])

  return {
    data,
    loading,
    error,
    refetch,
    mutate,
    setData,
  }
}

/**
 * Hook for paginated data
 */
export function usePaginatedApi(endpoint, options = {}) {
  const {
    initialPage = 1,
    initialPageSize = 10,
    ...apiOptions
  } = options

  const [page, setPage] = useState(initialPage)
  const [pageSize, setPageSize] = useState(initialPageSize)
  const [search, setSearch] = useState("")
  const [debouncedSearch, setDebouncedSearch] = useState("")

  // Debounce search
  useEffect(() => {
    const timer = setTimeout(() => {
      setDebouncedSearch(search)
      setPage(1) // Reset to first page on search
    }, 300)
    return () => clearTimeout(timer)
  }, [search])

  // Build query string
  const queryString = useMemo(() => {
    const params = new URLSearchParams()
    params.set("page", page)
    params.set("limit", pageSize)
    if (debouncedSearch) {
      params.set("search", debouncedSearch)
    }
    return params.toString()
  }, [page, pageSize, debouncedSearch])

  const fullEndpoint = endpoint ? `${endpoint}?${queryString}` : null

  const { data, loading, error, refetch, mutate } = useApi(fullEndpoint, {
    ...apiOptions,
    cacheKey: `${endpoint}?page=${page}&limit=${pageSize}&search=${debouncedSearch}`,
  })

  // Pagination helpers
  const totalPages = data?.total_pages || Math.ceil((data?.total || 0) / pageSize)
  const totalItems = data?.total || (Array.isArray(data) ? data.length : 0)
  const items = data?.items || data?.data || (Array.isArray(data) ? data : [])

  const goToPage = useCallback((newPage) => {
    setPage(Math.max(1, Math.min(newPage, totalPages || 1)))
  }, [totalPages])

  const nextPage = useCallback(() => {
    goToPage(page + 1)
  }, [page, goToPage])

  const prevPage = useCallback(() => {
    goToPage(page - 1)
  }, [page, goToPage])

  const changePageSize = useCallback((size) => {
    setPageSize(size)
    setPage(1)
  }, [])

  return {
    data: items,
    loading,
    error,
    refetch,
    mutate,
    // Pagination state
    page,
    pageSize,
    totalPages,
    totalItems,
    // Pagination actions
    setPage: goToPage,
    nextPage,
    prevPage,
    setPageSize: changePageSize,
    // Search
    search,
    setSearch,
    // Raw response
    rawData: data,
  }
}

/**
 * Hook for mutations (POST, PUT, DELETE)
 */
export function useMutation(options = {}) {
  const {
    onSuccess = null,
    onError = null,
    invalidateCache = null,
    requireAuth = true,
  } = options

  const navigate = useNavigate()
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState(null)

  const mutate = useCallback(async (endpoint, method = "POST", body = null) => {
    setLoading(true)
    setError(null)

    try {
      const headers = {
        "Content-Type": "application/json",
      }

      if (requireAuth) {
        const sessionId = localStorage.getItem("session_id")
        if (!sessionId) {
          navigate("/admin/login")
          return null
        }
        headers.Authorization = sessionId
      }

      const response = await fetch(buildApiUrl(`${endpoint}`), {
        method,
        headers,
        body: body ? JSON.stringify(body) : undefined,
      })

      if (response.status === 401) {
        localStorage.removeItem("session_id")
        navigate("/admin/login")
        return null
      }

      if (!response.ok) {
        const errorData = await response.json().catch(() => ({}))
        throw new Error(errorData.detail || `HTTP ${response.status}`)
      }

      const result = await response.json()

      // Invalidate related cache
      if (invalidateCache) {
        clearCache(invalidateCache)
      }

      if (onSuccess) {
        onSuccess(result)
      }

      return result
    } catch (err) {
      const errorMessage = err.message || "An error occurred"
      setError(errorMessage)
      
      if (onError) {
        onError(err)
      }

      return null
    } finally {
      setLoading(false)
    }
  }, [requireAuth, navigate, onSuccess, onError, invalidateCache])

  const post = useCallback((endpoint, body) => mutate(endpoint, "POST", body), [mutate])
  const put = useCallback((endpoint, body) => mutate(endpoint, "PUT", body), [mutate])
  const patch = useCallback((endpoint, body) => mutate(endpoint, "PATCH", body), [mutate])
  const del = useCallback((endpoint) => mutate(endpoint, "DELETE"), [mutate])

  return {
    mutate,
    post,
    put,
    patch,
    delete: del,
    loading,
    error,
    setError,
  }
}

/**
 * Hook for multiple related API calls
 */
export function useMultiApi(endpoints, options = {}) {
  const [results, setResults] = useState({})
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState(null)
  const navigate = useNavigate()

  const fetchAll = useCallback(async () => {
    setLoading(true)
    setError(null)

    try {
      const sessionId = localStorage.getItem("session_id")
      if (!sessionId && options.requireAuth !== false) {
        navigate("/admin/login")
        return
      }

      const headers = {
        "Content-Type": "application/json",
        ...(sessionId && { Authorization: sessionId }),
      }

      const promises = Object.entries(endpoints).map(async ([key, endpoint]) => {
        const cached = getCachedData(endpoint)
        if (cached) {
          return { key, data: cached }
        }

        const response = await fetch(buildApiUrl(`${endpoint}`), { headers })
        if (!response.ok) {
          throw new Error(`Failed to fetch ${key}`)
        }
        const data = await response.json()
        setCacheData(endpoint, data)
        return { key, data }
      })

      const responses = await Promise.all(promises)
      const newResults = responses.reduce((acc, { key, data }) => {
        acc[key] = data
        return acc
      }, {})

      setResults(newResults)
      return newResults
    } catch (err) {
      setError(err.message)
      return null
    } finally {
      setLoading(false)
    }
  }, [endpoints, navigate, options.requireAuth])

  useEffect(() => {
    fetchAll()
  }, [fetchAll])

  return { data: results, loading, error, refetch: fetchAll }
}

export default useApi
