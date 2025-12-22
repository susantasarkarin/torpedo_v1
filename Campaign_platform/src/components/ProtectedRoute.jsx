import { Navigate } from "react-router-dom";

export default function ProtectedRoute({ children }) {
  const sessionId = localStorage.getItem("session_id");
  if (!sessionId) {
    return <Navigate to="/login" replace />;
  }
  return children;
}
