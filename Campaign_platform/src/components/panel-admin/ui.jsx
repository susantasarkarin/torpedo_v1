import { colors, card } from "./tokens"

/**
 * Shared building blocks for the Panel module (Overview, Members, Recruitment,
 * Profiling & Quality, Rewards), so every section has the same page header,
 * tabs, cards, tiles and tables.
 */

export function PageShell({ title, description, actions, children }) {
  return (
    <div style={{ padding: "1.5rem", width: "100%", maxWidth: "1280px", minWidth: 0, boxSizing: "border-box" }}>
      <div style={{ display: "flex", justifyContent: "space-between", alignItems: "flex-end", flexWrap: "wrap", gap: "1rem", marginBottom: "1.25rem" }}>
        <div>
          <h1 style={{ margin: 0, fontSize: "1.5rem", color: colors.text }}>{title}</h1>
          {description && <p style={{ margin: "0.25rem 0 0", color: colors.muted, fontSize: "0.875rem" }}>{description}</p>}
        </div>
        {actions && <div style={{ display: "flex", gap: "0.5rem", flexWrap: "wrap" }}>{actions}</div>}
      </div>
      {/* wide tables scroll inside the section instead of pushing the page sideways */}
      <div style={{ overflowX: "auto" }}>{children}</div>
    </div>
  )
}

export function Tabs({ tabs, active, onChange }) {
  return (
    <div style={{ display: "flex", gap: "0.25rem", borderBottom: `1px solid ${colors.border}`, marginBottom: "1.25rem", overflowX: "auto" }}>
      {tabs.map((t) => (
        <button
          key={t.key}
          type="button"
          onClick={() => onChange(t.key)}
          style={{
            border: "none",
            background: "none",
            padding: "0.6rem 1rem",
            cursor: "pointer",
            whiteSpace: "nowrap",
            fontSize: "0.9rem",
            fontWeight: active === t.key ? 600 : 400,
            color: active === t.key ? colors.accent : "#5c5c5c",
            borderBottom: `3px solid ${active === t.key ? colors.accent : "transparent"}`,
            marginBottom: "-1px",
          }}
        >
          {t.label}
          {t.badge ? <span style={{ marginLeft: "0.4rem", background: colors.bad, color: "#fff", borderRadius: "999px", padding: "0 0.45rem", fontSize: "0.7rem" }}>{t.badge}</span> : null}
        </button>
      ))}
    </div>
  )
}

export function StatTile({ label, value, sub, color = colors.text, onClick }) {
  return (
    <div
      onClick={onClick}
      role={onClick ? "button" : undefined}
      style={{ ...card, marginBottom: 0, cursor: onClick ? "pointer" : "default" }}
    >
      <p style={{ margin: 0, fontSize: "0.8rem", color: colors.muted }}>{label}</p>
      <p style={{ margin: "0.25rem 0 0", fontSize: "1.6rem", fontWeight: 700, color }}>{value}</p>
      {sub && <p style={{ margin: 0, fontSize: "0.75rem", color: "#8a8a8a" }}>{sub}</p>}
    </div>
  )
}

export function TileRow({ children, min = 190 }) {
  return (
    <div style={{ display: "grid", gridTemplateColumns: `repeat(auto-fit, minmax(${min}px, 1fr))`, gap: "0.75rem", marginBottom: "1.25rem" }}>
      {children}
    </div>
  )
}
