import { useEffect, useRef, useState } from "react"
import { Link, useLocation, useNavigate } from "react-router-dom"
import { logout } from "../../services/authService"
import { MODULES, ACCOUNT_LINKS, isItemActive } from "./navConfig"

function initials(name) {
  const parts = String(name || "").replace(/[@._-]+/g, " ").trim().split(/\s+/).filter(Boolean)
  if (!parts.length) return "?"
  return (parts[0][0] + (parts[1]?.[0] || "")).toUpperCase()
}

function readUser() {
  try {
    return { name: localStorage.getItem("username") || "", role: localStorage.getItem("role") || "" }
  } catch {
    return { name: "", role: "" }
  }
}

function Sidebar({ moduleKey, onModuleChange, open, onClose }) {
  const location = useLocation()
  const navigate = useNavigate()
  const [switcherOpen, setSwitcherOpen] = useState(false)
  const [accountOpen, setAccountOpen] = useState(false)
  const accountRef = useRef(null)
  const user = readUser()
  const current = MODULES.find((m) => m.key === moduleKey) || null

  // menus close when the page changes
  useEffect(() => {
    setSwitcherOpen(false)
    setAccountOpen(false)
  }, [location.pathname])

  useEffect(() => {
    if (!accountOpen) return undefined
    const onDown = (e) => {
      if (accountRef.current && !accountRef.current.contains(e.target)) setAccountOpen(false)
    }
    document.addEventListener("mousedown", onDown)
    return () => document.removeEventListener("mousedown", onDown)
  }, [accountOpen])

  const pickModule = (mod) => {
    onModuleChange(mod.key)
    setSwitcherOpen(false)
    navigate(mod.root)
  }

  const showModuleList = switcherOpen || !current

  return (
    <aside className={`cx-sidebar ${open ? "is-open" : ""}`} aria-label="Main navigation">
      <div className="cx-sidebar-head">
        <Link to="/admin/dashboard" className="cx-logo">
          <span className="cx-logo-mark" aria-hidden="true">C</span>
          <span className="cx-logo-text">
            <strong>COGENTIX</strong>
            <span>Research</span>
          </span>
        </Link>
        <button type="button" className="cx-icon-btn cx-sidebar-close" onClick={onClose} aria-label="Close menu">
          ✕
        </button>
      </div>

      <div className="cx-sidebar-scroll">
        <div className="cx-nav-section">
          <button
            type="button"
            className={`cx-module-switch ${showModuleList ? "is-open" : ""}`}
            onClick={() => setSwitcherOpen((v) => !v)}
            aria-expanded={showModuleList}
          >
            <span className="cx-nav-icon">{current ? current.icon : "▦"}</span>
            <span className="cx-module-switch-label">
              <small>Module</small>
              {current ? current.label : "Choose a module"}
            </span>
            <span className="cx-chevron" aria-hidden="true">▾</span>
          </button>

          {showModuleList && (
            <div className="cx-module-list">
              {MODULES.map((mod) => (
                <button
                  key={mod.key}
                  type="button"
                  className={`cx-nav-item ${mod.key === moduleKey ? "is-active" : ""}`}
                  onClick={() => pickModule(mod)}
                >
                  <span className="cx-nav-icon">{mod.icon}</span>
                  {mod.label}
                </button>
              ))}
            </div>
          )}
        </div>

        {current && !switcherOpen &&
          current.groups.map((group) => (
            <nav key={group.label} className="cx-nav-section" aria-label={group.label}>
              <div className="cx-nav-label">{group.label}</div>
              {group.items.map((item) => (
                <Link
                  key={item.to}
                  to={item.to}
                  className={`cx-nav-item ${isItemActive(item, location.pathname) ? "is-active" : ""}`}
                  aria-current={isItemActive(item, location.pathname) ? "page" : undefined}
                >
                  <span className="cx-nav-icon">{item.icon}</span>
                  <span className="cx-nav-text">{item.label}</span>
                  {item.badge != null && <span className="cx-nav-badge">{item.badge}</span>}
                </Link>
              ))}
            </nav>
          ))}
      </div>

      <div className="cx-sidebar-footer" ref={accountRef}>
        {accountOpen && (
          <div className="cx-account-menu" role="menu">
            {ACCOUNT_LINKS.map((l) => (
              <Link key={l.to} to={l.to} className="cx-nav-item" role="menuitem">
                <span className="cx-nav-icon">{l.icon}</span>
                {l.label}
              </Link>
            ))}
            <hr />
            <button type="button" className="cx-nav-item is-danger" role="menuitem" onClick={() => logout(navigate)}>
              <span className="cx-nav-icon">🚪</span>
              Logout
            </button>
          </div>
        )}
        <button
          type="button"
          className="cx-user-card"
          onClick={() => setAccountOpen((v) => !v)}
          aria-expanded={accountOpen}
          aria-haspopup="menu"
        >
          <span className="cx-avatar">{initials(user.name)}</span>
          <span className="cx-user-info">
            <strong>{user.name || "Account"}</strong>
            {user.role && <span>{user.role}</span>}
          </span>
          <span className="cx-chevron" aria-hidden="true">▴</span>
        </button>
      </div>
    </aside>
  )
}

export default Sidebar
