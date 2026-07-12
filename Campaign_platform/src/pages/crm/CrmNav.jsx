/**
 * CRM section tab bar + tiny shared form/modal primitives.
 * All CRM pages import this so the section is navigable without touching
 * the app-level sidebars. Plain CSS (crm-ui.css) + inline styles.
 */
import { NavLink } from "react-router-dom";
import {
  LayoutDashboard, KanbanSquare, UserPlus, Building2, CheckSquare, BarChart3,
} from "lucide-react";
import "../../styles/crm-ui.css";

const TABS = [
  { to: "/admin/crm", label: "Dashboard", icon: LayoutDashboard, end: true },
  { to: "/admin/crm/pipeline", label: "Pipeline", icon: KanbanSquare },
  { to: "/admin/crm/leads", label: "Leads", icon: UserPlus },
  { to: "/admin/crm/accounts", label: "Accounts", icon: Building2 },
  { to: "/admin/crm/tasks", label: "Tasks", icon: CheckSquare },
  { to: "/admin/crm/reports", label: "Reports", icon: BarChart3 },
];

export default function CrmNav() {
  return (
    <div style={{
      display: "flex", gap: "0.25rem", marginBottom: "1rem",
      borderBottom: "1px solid #e5e7eb", paddingBottom: "0.5rem", flexWrap: "wrap",
    }}>
      {TABS.map(({ to, label, icon: Icon, end }) => (
        <NavLink key={to} to={to} end={end}
          style={({ isActive }) => ({
            display: "inline-flex", alignItems: "center", gap: "0.35rem",
            padding: "0.4rem 0.75rem", borderRadius: "0.4rem",
            fontSize: "0.85rem", fontWeight: 600, textDecoration: "none",
            color: isActive ? "#1d4ed8" : "#6b7280",
            background: isActive ? "#eff6ff" : "transparent",
          })}>
          <Icon size={15} /> {label}
        </NavLink>
      ))}
    </div>
  );
}

/* ---------- tiny shared primitives (no external deps) ---------- */

export function Modal({ title, onClose, children, width = 440 }) {
  return (
    <div onClick={onClose} style={{
      position: "fixed", inset: 0, background: "rgba(17,24,39,0.45)",
      display: "flex", alignItems: "center", justifyContent: "center", zIndex: 1000,
    }}>
      <div onClick={(e) => e.stopPropagation()} style={{
        background: "#fff", borderRadius: "0.6rem", padding: "1.25rem",
        width, maxWidth: "92vw", maxHeight: "85vh", overflowY: "auto",
        boxShadow: "0 20px 40px rgba(0,0,0,0.2)",
      }}>
        <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", marginBottom: "0.9rem" }}>
          <h3 style={{ margin: 0, fontSize: "1rem", fontWeight: 700, color: "#111827" }}>{title}</h3>
          <button onClick={onClose} className="crm-btn" style={{ padding: "0.2rem 0.55rem" }}>✕</button>
        </div>
        {children}
      </div>
    </div>
  );
}

export function Field({ label, children }) {
  return (
    <label style={{ display: "block", marginBottom: "0.7rem" }}>
      <span style={{ display: "block", fontSize: "0.75rem", fontWeight: 600, color: "#6b7280", marginBottom: "0.25rem" }}>
        {label}
      </span>
      {children}
    </label>
  );
}

export const inputStyle = {
  width: "100%", padding: "0.45rem 0.6rem", border: "1px solid #d1d5db",
  borderRadius: "0.4rem", fontSize: "0.85rem", boxSizing: "border-box",
};
