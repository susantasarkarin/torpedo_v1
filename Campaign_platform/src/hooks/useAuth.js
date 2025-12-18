import { useState, useEffect, useCallback } from 'react';

/**
 * Custom hook for authentication
 * Retrieves user info and session token from localStorage
 */
export function useAuth() {
  const [user, setUser] = useState(null);
  const [token, setToken] = useState(null);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    // Retrieve user and token from localStorage on mount
    const storedUser = localStorage.getItem('username');
    const storedSessionId = localStorage.getItem('session_id');

    if (storedUser && storedSessionId) {
      setUser(storedUser);
      setToken(storedSessionId);
    }
    setLoading(false);
  }, []);

  const logout = useCallback(() => {
    setUser(null);
    setToken(null);
    localStorage.removeItem('user');
    localStorage.removeItem('username');
    localStorage.removeItem('session_id');
    localStorage.removeItem('auth');
  }, []);

  return { user, token, loading, logout };
}
