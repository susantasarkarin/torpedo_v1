import { buildApiUrl } from "../config";
import { clearAuth } from "../utils/api";

/**
 * Log out the current user.
 * Calls the backend /logout/ endpoint, then clears local auth state
 * and redirects to the login page.
 *
 * Always clears local state even if the backend call fails, so the
 * user is never stuck in a broken session.
 */
export const logout = async (navigate) => {
  const sessionId = localStorage.getItem("session_id");
  try {
    await fetch(buildApiUrl(`/logout/`), {
      method: "POST",
      headers: { Authorization: sessionId },
    });
  } catch (err) {
    console.error("Logout request failed:", err);
  } finally {
    clearAuth();
    if (navigate) {
      navigate("/admin/login");
    } else {
      window.location.href = "/admin/login";
    }
  }
};
