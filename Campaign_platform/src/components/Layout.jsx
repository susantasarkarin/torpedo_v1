"use client"

import { Outlet } from "react-router-dom"
import Navbar from "./Navbar"
import RightSidebar from "./RightSidebar"
import OperationsSidebar from "./OperationsSidebar"
import FinanceSidebar from "./FinanceSidebar"
import Footer from "./Footer"
import { useState } from "react"

function Layout() {
  const [profileDropdownOpen, setProfileDropdownOpen] = useState(false)
  const [mainDropdownOpen, setMainDropdownOpen] = useState(false)
  const [selectedSection, setSelectedSection] = useState(null)

  console.log("[v0] Selected section:", selectedSection)

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
        {selectedSection === "operations" && <OperationsSidebar />}

        {/* ✅ Finance sidebar (left) */}
        {selectedSection === "finance" && <FinanceSidebar />}

        {/* ✅ Sales sidebar (right) */}
        {selectedSection === "sales" && <RightSidebar />}

        {/* ✅ Content area shifts depending on sidebar */}
        <div
          className={`content-area ${
            selectedSection === "operations"
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