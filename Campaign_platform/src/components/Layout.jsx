"use client"

import { Outlet } from "react-router-dom"
import Navbar from "./Navbar"
import RightSidebar from "./RightSidebar"
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
        <div className={`content-area ${selectedSection === "sales" ? "with-left-sidebar" : ""}`}>
          <Outlet />
        </div>
        {selectedSection === "sales" && <RightSidebar />}
      </div>

      


      <Footer />
    </div>


  )

  
}

export default Layout
