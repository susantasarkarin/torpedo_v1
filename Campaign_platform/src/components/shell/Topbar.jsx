import { useEffect, useRef } from "react"
import { useLocation } from "react-router-dom"
import { findActiveItem } from "./navConfig"

function Topbar({ onMenu }) {
  const location = useLocation()
  const barRef = useRef(null)
  const active = findActiveItem(location.pathname)

  // Publish the bar's real height as --cx-nav-h: full-height panels on the
  // pages subtract it (they used to hard-code 60/70/90px).
  useEffect(() => {
    const el = barRef.current
    if (!el) return undefined
    const publish = () =>
      document.documentElement.style.setProperty("--cx-nav-h", `${Math.round(el.getBoundingClientRect().height)}px`)
    publish()
    const ro = typeof ResizeObserver !== "undefined" ? new ResizeObserver(publish) : null
    ro?.observe(el)
    window.addEventListener("resize", publish)
    return () => {
      ro?.disconnect()
      window.removeEventListener("resize", publish)
    }
  }, [])

  return (
    <header className="cx-topbar" ref={barRef}>
      <button type="button" className="cx-icon-btn cx-menu-btn" onClick={onMenu} aria-label="Open menu">
        ☰
      </button>
      <div className="cx-topbar-title">
        {active?.module && <span className="cx-topbar-crumb">{active.module.label}</span>}
        <span className="cx-topbar-page">{active ? active.item.label : "Dashboard"}</span>
      </div>
    </header>
  )
}

export default Topbar
