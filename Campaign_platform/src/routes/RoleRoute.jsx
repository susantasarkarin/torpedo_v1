import { Navigate } from "react-router-dom";

export default function RoleRoute({ children, allowed }) {
  const role = localStorage.getItem("role"); // "admin" or "user"

  if (!role) return <Navigate to="/admin/login" replace />;
  if (!allowed.includes(role)) return <Navigate to="/unauthorized" replace />;

  return children;
}
