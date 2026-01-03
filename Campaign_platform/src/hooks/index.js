/**
 * Hooks - Centralized exports for all custom hooks
 */

export { 
  useApi, 
  usePaginatedApi, 
  useMutation, 
  useMultiApi, 
  clearCache 
} from './useApi'

// Re-export common React hooks for convenience
export { 
  useState, 
  useEffect, 
  useCallback, 
  useMemo, 
  useRef,
  useContext,
  useReducer,
} from 'react'

export { 
  useNavigate, 
  useLocation, 
  useParams, 
  useSearchParams 
} from 'react-router-dom'
