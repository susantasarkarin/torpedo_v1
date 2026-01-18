/**
 * Panel Protected Route Component
 * Guards panel routes requiring authentication
 */

import { Navigate, useLocation } from 'react-router-dom';
import { isPanelAuthenticated } from '../services/panelApi';

export default function PanelProtectedRoute({ children }) {
  const location = useLocation();

  if (!isPanelAuthenticated()) {
    // Redirect to panel login, preserving the attempted URL
    return <Navigate to="/panel/login" state={{ from: location }} replace />;
  }

  return children;
}
