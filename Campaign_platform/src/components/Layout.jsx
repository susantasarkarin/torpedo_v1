import { Outlet, useLocation } from "react-router-dom"
import { useState, useEffect } from "react"
import Sidebar from "./shell/Sidebar"
import Topbar from "./shell/Topbar"
import { moduleKeyFromPath } from "./shell/navConfig"

// App shell: one white sidebar on the left (a drawer on phones), a sticky top
// bar, and the page. Pages outside a module (dashboard, settings, profile)
// keep the module that was open last, as the old section sidebars did.
function Layout() {
  const location = useLocation()
  const [moduleKey, setModuleKey] = useState(() => moduleKeyFromPath(location.pathname))
  const [drawerOpen, setDrawerOpen] = useState(false)

  useEffect(() => {
    const key = moduleKeyFromPath(location.pathname)
    if (key !== null) setModuleKey(key)
    setDrawerOpen(false)
  }, [location.pathname])

  useEffect(() => {
    if (!drawerOpen) return undefined
    const onKey = (e) => e.key === "Escape" && setDrawerOpen(false)
    document.addEventListener("keydown", onKey)
    document.body.classList.add("cx-drawer-lock")
    return () => {
      document.removeEventListener("keydown", onKey)
      document.body.classList.remove("cx-drawer-lock")
    }
  }, [drawerOpen])

  return (
    <div className="cx-shell">
      <Sidebar
        moduleKey={moduleKey}
        onModuleChange={setModuleKey}
        open={drawerOpen}
        onClose={() => setDrawerOpen(false)}
      />
      {drawerOpen && <div className="cx-scrim" onClick={() => setDrawerOpen(false)} aria-hidden="true" />}

      <div className="cx-main">
        <Topbar onMenu={() => setDrawerOpen(true)} />
        <main className="cx-content">
          <Outlet />
        </main>
      </div>
    </div>
  )
}

export default Layout
