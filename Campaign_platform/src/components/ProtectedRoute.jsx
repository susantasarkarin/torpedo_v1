import { Navigate } from "react-router-dom";
import { isAuthenticated } from "../utils/api";

export default function ProtectedRoute({ children }) {
  if (!isAuthenticated()) {
    return <Navigate to="/admin/login" replace />;
  }
  return children;
}
