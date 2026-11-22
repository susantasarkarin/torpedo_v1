import { useState, useRef, useEffect } from "react"
import { colors, card, tones, control } from "./tokens"

/**
 * Shared building blocks for the Panel module (Overview, Members, Recruitment,
 * Profiling & Quality, Rewards), so every section has the same page header,
 * tabs, cards, tiles and tables.
 */

export function PageShell({ title, description, actions, children }) {
  return (
    <div style={{ width: "100%", minWidth: 0, boxSizing: "border-box" }}>
      {(title || description || actions) && (
        <div style={{ display: "flex", justifyContent: "space-between", alignItems: "flex-end", flexWrap: "wrap", gap: "1rem", marginBottom: "1.25rem" }}>
          <div>
            {title && <h1 style={{ margin: 0, fontSize: "1.5rem", color: colors.text }}>{title}</h1>}
            {description && <p style={{ margin: "0.25rem 0 0", color: colors.muted, fontSize: "0.875rem" }}>{description}</p>}
          </div>
          {actions && <div style={{ display: "flex", gap: "0.5rem", flexWrap: "wrap" }}>{actions}</div>}
        </div>
      )}
      {/* wide tables scroll inside the section instead of pushing the page sideways */}
      <div style={{ overflowX: "auto" }}>{children}</div>
    </div>
  )
}

export function Tabs({ tabs, active, onChange }) {
  return (
    <div style={{ display: "flex", gap: "0.25rem", borderBottom: `1px solid ${colors.border}`, marginBottom: "1.25rem", overflowX: "auto", overflowY: "hidden", scrollbarWidth: "none" }}>
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
            borderBottom: `3px solid ${active === t.key ? "#e8910a" : "transparent"}`,
          }}
        >
          {t.label}
          {t.badge ? <span style={{ marginLeft: "0.4rem", background: colors.bad, color: "#fff", borderRadius: "999px", padding: "0 0.45rem", fontSize: "0.7rem" }}>{t.badge}</span> : null}
        </button>
      ))}
    </div>
  )
}

export function StatTile({ label, value, sub, color = colors.text, onClick, action }) {
  return (
    <div
      onClick={onClick}
      role={onClick ? "button" : undefined}
      style={{ ...card, marginBottom: 0, cursor: onClick ? "pointer" : "default" }}
    >
      <p style={{ margin: 0, fontSize: "0.8rem", color: colors.muted }}>{label}</p>
      <p style={{ margin: "0.25rem 0 0", fontSize: "1.6rem", fontWeight: 700, color }}>{value}</p>
      {sub && <p style={{ margin: 0, fontSize: "0.75rem", color: "#8a8a8a" }}>{sub}</p>}
      {action && <div style={{ marginTop: "0.6rem" }}>{action}</div>}
    </div>
  )
}

// Heading row for a list or panel: title + one-line description, actions on the right.
export function SectionHeader({ title, description, actions }) {
  return (
    <div style={{ display: "flex", justifyContent: "space-between", alignItems: "flex-start", gap: "0.75rem 1rem", flexWrap: "wrap", marginBottom: "1.25rem" }}>
      <div style={{ minWidth: 0, flex: "1 1 260px" }}>
        {title && <h2 style={{ margin: 0, fontSize: "1.1rem", fontWeight: 700, color: colors.text }}>{title}</h2>}
        {description && <p style={{ margin: "0.2rem 0 0", fontSize: "0.85rem", color: colors.muted, lineHeight: 1.5 }}>{description}</p>}
      </div>
      {actions && <div style={{ display: "flex", gap: "0.5rem", alignItems: "center", flexWrap: "wrap" }}>{actions}</div>}
    </div>
  )
}

// Small status pill. tone: good | warn | bad | accent | neutral
export function Badge({ tone = "neutral", children, title }) {
  const t = tones[tone] || tones.neutral
  return (
    <span title={title} style={{ display: "inline-block", padding: "0.15rem 0.55rem", borderRadius: "999px", fontSize: "0.78rem", fontWeight: 600, lineHeight: 1.5, whiteSpace: "nowrap", background: t.bg, color: t.fg }}>
      {children}
    </span>
  )
}

// Row of small labelled numbers (import / send results). items: [{ label, value, color }]
export function CountGrid({ items, min = 100 }) {
  return (
    <div style={{ display: "grid", gridTemplateColumns: `repeat(auto-fit, minmax(${min}px, 1fr))`, gap: "0.5rem", margin: "0.75rem 0" }}>
      {items.map((it) => (
        <div key={it.label} style={{ border: `1px solid ${colors.border}`, borderRadius: "8px", padding: "0.6rem 0.75rem" }}>
          <div style={{ fontSize: "0.75rem", color: colors.muted }}>{it.label}</div>
          <div style={{ fontSize: "1.25rem", fontWeight: 700, color: it.color || colors.text }}>
            {it.value == null ? "—" : typeof it.value === "string" ? it.value : Number(it.value).toLocaleString()}
          </div>
        </div>
      ))}
    </div>
  )
}

// Pill switch for views inside a section (deliberately not tab-styled, so it
// never reads as a second row of page tabs). options: [{ key, label }]
export function Segmented({ options, value, onChange, label }) {
  return (
    <div role="group" aria-label={label} style={{ display: "inline-flex", flexWrap: "wrap", gap: "0.25rem", padding: "0.2rem", background: tones.neutral.bg, borderRadius: "999px" }}>
      {options.map((o) => {
        const on = o.key === value
        return (
          <button key={o.key} type="button" aria-pressed={on} onClick={() => onChange(o.key)}
            style={{ border: "none", borderRadius: "999px", padding: "0.3rem 0.85rem", fontSize: "0.8rem", fontWeight: 600, cursor: "pointer", whiteSpace: "nowrap", background: on ? "#fff" : "transparent", color: on ? colors.accent : colors.muted, boxShadow: on ? "0 1px 2px rgba(0,0,0,0.08)" : "none" }}>
            {o.label}
          </button>
        )
      })}
    </div>
  )
}

// Form field: label (+ required mark / hint) above its control.
export function Field({ label, htmlFor, hint, required, children, style }) {
  return (
    <div style={{ marginBottom: "0.9rem", ...style }}>
      <label htmlFor={htmlFor} style={{ display: "block", fontSize: "0.8rem", fontWeight: 600, color: colors.text, marginBottom: "0.3rem" }}>
        {label}
        {required && <span style={{ color: colors.bad }}> *</span>}
        {hint && <span style={{ fontWeight: 400, color: colors.muted }}> {hint}</span>}
      </label>
      {children}
    </div>
  )
}

// Secondary actions behind one "More actions ▾" button, so a page keeps a
// single primary button. items: [{ label, onClick, disabled }]
export function ActionMenu({ label = "More actions", items, buttonStyle }) {
  const [open, setOpen] = useState(false)
  const ref = useRef(null)
  useEffect(() => {
    if (!open) return
    const onDown = (e) => { if (ref.current && !ref.current.contains(e.target)) setOpen(false) }
    const onKey = (e) => { if (e.key === "Escape") setOpen(false) }
    document.addEventListener("mousedown", onDown)
    document.addEventListener("keydown", onKey)
    return () => {
      document.removeEventListener("mousedown", onDown)
      document.removeEventListener("keydown", onKey)
    }
  }, [open])
  return (
    <div ref={ref} style={{ position: "relative" }}>
      <button type="button" className="btn btn-outline" aria-haspopup="menu" aria-expanded={open} onClick={() => setOpen((o) => !o)} style={{ whiteSpace: "nowrap", ...buttonStyle }}>
        {label} ▾
      </button>
      {open && (
        <div role="menu" style={{ position: "absolute", right: 0, top: "calc(100% + 4px)", zIndex: 20, minWidth: "220px", background: "#fff", border: `1px solid ${colors.border}`, borderRadius: "8px", boxShadow: "0 8px 24px rgba(0,0,0,0.08)", padding: "0.25rem 0" }}>
          {items.map((it) => (
            <button
              key={it.label}
              type="button"
              role="menuitem"
              disabled={it.disabled}
              onClick={() => { setOpen(false); it.onClick() }}
              onMouseEnter={(e) => { if (!it.disabled) e.currentTarget.style.background = "#faf9f7" }}
              onMouseLeave={(e) => { e.currentTarget.style.background = "none" }}
              style={{ display: "block", width: "100%", textAlign: "left", border: "none", background: "none", padding: "0.55rem 0.9rem", fontSize: "0.875rem", whiteSpace: "nowrap", color: it.disabled ? colors.muted : colors.text, cursor: it.disabled ? "default" : "pointer" }}
            >
              {it.label}
            </button>
          ))}
        </div>
      )}
    </div>
  )
}

// One row of list filters: search (applied as you type, after `delay` ms),
// optional country picker, rows-per-page. The parent owns the committed values.
export function FilterBar({
  search, onSearch, placeholder = "Search…", delay = 300,
  country, onCountry, countries, countryLabel = (c) => c,
  pageSize, onPageSize, pageSizeOptions = [25, 50, 100, 250, 500],
}) {
  const [text, setText] = useState(search || "")
  const onSearchRef = useRef(onSearch)
  onSearchRef.current = onSearch

  // Follow the parent if it resets the search (but don't strip a trailing space mid-typing).
  useEffect(() => {
    setText((t) => (t.trim() === (search || "") ? t : search || ""))
  }, [search])

  useEffect(() => {
    const next = text.trim()
    if (next === (search || "")) return
    const t = setTimeout(() => onSearchRef.current(next), delay)
    return () => clearTimeout(t)
  }, [text, search, delay])

  return (
    <div style={{ display: "flex", gap: "0.75rem", marginBottom: "1rem", flexWrap: "wrap", alignItems: "center" }}>
      <div style={{ position: "relative", flex: 1, minWidth: "220px" }}>
        <input
          type="search"
          value={text}
          placeholder={placeholder}
          aria-label="Search"
          onChange={(e) => setText(e.target.value)}
          onKeyDown={(e) => { if (e.key === "Enter") onSearchRef.current(text.trim()) }}
          style={{ ...control, width: "100%" }}
        />
      </div>
      {onCountry && (
        <select aria-label="Country" value={country} onChange={(e) => onCountry(e.target.value)} style={{ ...control, minWidth: "170px" }}>
          <option value="">All countries</option>
          {(countries || []).map((c) => <option key={c} value={c}>{countryLabel(c)}</option>)}
        </select>
      )}
      {onPageSize && (
        <label style={{ display: "flex", alignItems: "center", gap: "0.4rem", fontSize: "0.875rem", color: colors.muted }}>
          Rows
          <select value={pageSize} onChange={(e) => onPageSize(parseInt(e.target.value, 10))} style={control}>
            {pageSizeOptions.map((n) => <option key={n} value={n}>{n}</option>)}
          </select>
        </label>
      )}
    </div>
  )
}

// "Showing 1–25 of 3,400" with previous/next. Renders nothing when total is 0.
export function Pager({ page, pageSize, total, onPage, noun }) {
  if (!total) return null
  const pages = Math.max(1, Math.ceil(total / pageSize))
  const from = (page - 1) * pageSize + 1
  const to = Math.min(page * pageSize, total)
  return (
    <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", gap: "0.75rem", flexWrap: "wrap", marginTop: "1rem" }}>
      <span style={{ fontSize: "0.875rem", color: colors.muted }}>
        Showing <strong style={{ color: colors.text }}>{from.toLocaleString()}–{to.toLocaleString()}</strong> of {total.toLocaleString()}{noun ? ` ${noun}` : ""}
        {pages > 1 && <> · page {page.toLocaleString()} of {pages.toLocaleString()}</>}
      </span>
      <div style={{ display: "flex", gap: "0.5rem", alignItems: "center" }}>
        <button type="button" className="btn btn-outline" style={{ whiteSpace: "nowrap" }} disabled={page <= 1} onClick={() => onPage(page - 1)}>‹ Previous</button>
        <button type="button" className="btn btn-outline" style={{ whiteSpace: "nowrap" }} disabled={page >= pages} onClick={() => onPage(page + 1)}>Next ›</button>
      </div>
    </div>
  )
}

// Centered dialog. Esc, the × and a backdrop click close it, except while `busy`.
export function Modal({ open, title, onClose, busy = false, width = 640, children, footer }) {
  useEffect(() => {
    if (!open) return
    const onKey = (e) => { if (e.key === "Escape" && !busy) onClose() }
    document.addEventListener("keydown", onKey)
    return () => document.removeEventListener("keydown", onKey)
  }, [open, busy, onClose])
  if (!open) return null
  return (
    <div
      onClick={() => !busy && onClose()}
      style={{ position: "fixed", inset: 0, background: "rgba(0,0,0,0.45)", display: "flex", alignItems: "center", justifyContent: "center", zIndex: 1000, padding: "1rem" }}
    >
      <div
        role="dialog"
        aria-modal="true"
        aria-label={title}
        onClick={(e) => e.stopPropagation()}
        style={{ background: "#fff", borderRadius: "12px", width: "100%", maxWidth: width, maxHeight: "calc(100vh - 2rem)", display: "flex", flexDirection: "column", boxShadow: "0 20px 60px rgba(0,0,0,0.2)" }}
      >
        <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", padding: "1rem 1.25rem", borderBottom: `1px solid ${colors.border}` }}>
          <h3 style={{ margin: 0, fontSize: "1.1rem", color: colors.text }}>{title}</h3>
          <button type="button" aria-label="Close" disabled={busy} onClick={onClose}
            style={{ border: "none", background: "none", fontSize: "1.4rem", lineHeight: 1, color: colors.muted, cursor: busy ? "default" : "pointer" }}>×</button>
        </div>
        <div style={{ padding: "1.25rem", overflowY: "auto" }}>{children}</div>
        {footer && (
          <div style={{ display: "flex", justifyContent: "flex-end", gap: "0.5rem", flexWrap: "wrap", padding: "0.9rem 1.25rem", borderTop: `1px solid ${colors.border}` }}>
            {footer}
          </div>
        )}
      </div>
    </div>
  )
}

// Inline message box. tone: good | warn | bad | accent | neutral
export function Notice({ tone = "neutral", children, style }) {
  const t = tones[tone] || tones.neutral
  return (
    <div role={tone === "bad" ? "alert" : "status"} style={{ padding: "0.65rem 0.85rem", borderRadius: "8px", fontSize: "0.875rem", lineHeight: 1.5, background: t.bg, color: t.fg, border: `1px solid ${t.border}`, ...style }}>
      {children}
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
