"use client"

import { Outlet, useLocation } from "react-router-dom"
import Navbar from "./Navbar"
import RightSidebar from "./RightSidebar"
import OperationsSidebar from "./OperationsSidebar"
import FinanceSidebar from "./FinanceSidebar"
import Footer from "./Footer"
import { useState, useEffect } from "react"

// Helper to determine section from pathname
function getSectionFromPath(pathname) {
  if (pathname.startsWith("/admin/sales")) return "sales"
  if (pathname.startsWith("/admin/finance")) return "finance"
  if (pathname.startsWith("/admin/operations") || pathname === "/admin/logs") return "operations"
  return null
}

function Layout() {
  const [profileDropdownOpen, setProfileDropdownOpen] = useState(false)
  const [mainDropdownOpen, setMainDropdownOpen] = useState(false)
  const location = useLocation()
  
  // Initialize selectedSection based on current URL path
  const [selectedSection, setSelectedSection] = useState(() => getSectionFromPath(location.pathname))

  // Keep selectedSection in sync with route changes
  useEffect(() => {
    const section = getSectionFromPath(location.pathname)
    if (section !== null && section !== selectedSection) {
      setSelectedSection(section)
    }
  }, [location.pathname])

  return (
    <div className="app-container">
      <Navbar
        profileDropdownOpen={profileDropdownOpen}
        setProfileDropdownOpen={setProfileDropdownOpen}
        mainDropdownOpen={mainDropdownOpen}
        setMainDropdownOpen={setMainDropdownOpen}
        selectedSection={selectedSection}
        setSelectedSection={setSelectedSection}
      />

      <div className="main-layout">
        {/* ✅ Operations sidebar (left) */}
        {(selectedSection === "operations" || location.pathname === "/admin/logs") && <OperationsSidebar />}

        {/* ✅ Finance sidebar (left) */}
        {selectedSection === "finance" && <FinanceSidebar />}

        {/* ✅ Sales sidebar (right) */}
        {selectedSection === "sales" && <RightSidebar />}

        {/* ✅ Content area shifts depending on sidebar */}
        <div
          className={`content-area ${
            selectedSection === "operations" || location.pathname === "/admin/logs"
              ? "with-left-sidebar"
              : selectedSection === "sales"
              ? "with-right-sidebar"
              : selectedSection === "finance"
              ? "with-left-sidebar"
              : ""
          }`}
        >
          <Outlet />
        </div>
      </div>

      <Footer />
    </div>
  )
}

export default Layout