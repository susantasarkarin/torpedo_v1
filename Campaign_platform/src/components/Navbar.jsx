"use client"

import { Link, useNavigate } from "react-router-dom"
import { useState } from "react"
import { logout } from "../services/authService"
import "./Navbar.css"

function Navbar({
  profileDropdownOpen,
  setProfileDropdownOpen,
  setSelectedSection,
}) {
  const [logoDropdownOpen, setLogoDropdownOpen] = useState(false)
  const navigate = useNavigate()

  const handleLogoDropdownToggle = () => {
    setLogoDropdownOpen((prev) => !prev)
    setProfileDropdownOpen(false) // Close profile dropdown when logo dropdown is toggled
  }

  const handleProfileDropdownToggle = () => {
    setProfileDropdownOpen((prev) => !prev)
    setLogoDropdownOpen(false) // Close logo dropdown when profile dropdown is toggled
  }

  const handleSectionSelect = (section) => {
    setSelectedSection(section)
    setLogoDropdownOpen(false)
    navigate("/admin/" + section)
  }

  const handleNonSidebarSection = () => {
    setSelectedSection(null)
    setLogoDropdownOpen(false)
  }

  const handleLogout = () => logout(navigate)

  return (
    <nav className="top-navbar">
      <div className="navbar-left">
        <div className={`logo-dropdown ${logoDropdownOpen ? "open" : ""}`}>
          <button className="logo-dropdown-toggle" onClick={handleLogoDropdownToggle}>
            <div className="logo-section">
              <img src="/newlogo.png" alt="Cogentix Research Logo" className="logo-image" style={{height:32}} />
            </div>
            <span className="dropdown-arrow">⏷</span>
          </button>

          <div className="logo-dropdown-menu">
            <button
              className="logo-dropdown-item"
              onClick={() => handleSectionSelect("sales")}
            >
              <span className="dropdown-icon">💼</span>
              Sales
            </button>

            <Link
              to="/admin/marketing"
              className="logo-dropdown-item"
              onClick={handleNonSidebarSection}
            >
              <span className="dropdown-icon">📈</span>
              Marketing
            </Link>

            <button
              className="logo-dropdown-item"
              onClick={() => handleSectionSelect("finance")}
            >
              <span className="dropdown-icon">💰</span>
              Finance
            </button>

            <button
              className="logo-dropdown-item"
              onClick={() => handleSectionSelect("operations")}
            >
              <span className="dropdown-icon">⚙️</span>
              Operations
            </button>

            <button
              className="logo-dropdown-item"
              onClick={() => handleSectionSelect("vendor")}
            >
              <span className="dropdown-icon">🏢</span>
              Vendors
            </button>

            <Link
              to="/admin/hr"
              className="logo-dropdown-item"
              onClick={handleNonSidebarSection}
            >
              <span className="dropdown-icon">👥</span>
              HR
            </Link>

            <button
              className="logo-dropdown-item"
              onClick={() => handleSectionSelect("panel-admin")}
            >
              <span className="dropdown-icon">📋</span>
              Panel
            </button>

            <Link
              to="/admin/crm"
              className="logo-dropdown-item"
              onClick={handleNonSidebarSection}
            >
              <span className="dropdown-icon">🧭</span>
              CRM
            </Link>

            <Link
              to="/admin/surveys/revenue"
              className="logo-dropdown-item"
              onClick={handleNonSidebarSection}
            >
              <span className="dropdown-icon">📊</span>
              Surveys
            </Link>

            <Link
              to="/admin/ai/approvals"
              className="logo-dropdown-item"
              onClick={handleNonSidebarSection}
            >
              <span className="dropdown-icon">🤖</span>
              AI Approvals
            </Link>
          </div>
        </div>

      </div>

      <div className="profile-section">
        <div className={`profile-dropdown ${profileDropdownOpen ? "open" : ""}`}>
          <button className="profile-button" onClick={handleProfileDropdownToggle}>
            <div className="profile-avatar">JD</div>
            <span className="profile-name">John Doe</span>
            <span className="dropdown-arrow">⏷</span>
          </button>

          <div className="profile-menu">
            <Link to="/admin/profile" className="profile-menu-item">
              <span className="profile-menu-icon">👤</span>
              My Profile
            </Link>
            <Link to="/admin/settings" className="profile-menu-item">
              <span className="profile-menu-icon">⚙️</span>
              Settings
            </Link>
            <Link to="/admin/mail-pool" className="profile-menu-item">
              <span className="profile-menu-icon">📬</span>
              Mail Pool
            </Link>
            <Link to="/admin/gmail-setup" className="profile-menu-item">
              <span className="profile-menu-icon">📧</span>
              Gmail Settings
            </Link>
            <hr className="profile-menu-divider" />
            <button onClick={handleLogout} className="profile-menu-item logout">
              <span className="profile-menu-icon">🚪</span>
              Logout
            </button>
          </div>
        </div>
      </div>
    </nav>
  )
}

export default Navbar
