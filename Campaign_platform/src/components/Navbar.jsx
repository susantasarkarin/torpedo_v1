"use client"

import { Link } from "react-router-dom"
import { useState } from "react"

function Navbar({ profileDropdownOpen, setProfileDropdownOpen, selectedSection, setSelectedSection }) {
  const [logoDropdownOpen, setLogoDropdownOpen] = useState(false)

  const handleLogoDropdownToggle = () => {
    setLogoDropdownOpen(!logoDropdownOpen)
  }

  const handleProfileDropdownToggle = () => {
    setProfileDropdownOpen(!profileDropdownOpen)
  }

  const handleSectionSelect = (section) => {
    setSelectedSection(section)
    setLogoDropdownOpen(false)
  }

  const handleNonSalesSection = () => {
    setSelectedSection(null)
    setLogoDropdownOpen(false)
  }

  return (
    <nav className="top-navbar">
      <div className="navbar-left">
        <div className={`logo-dropdown ${logoDropdownOpen ? "open" : ""}`}>
          <button className="logo-dropdown-toggle" onClick={handleLogoDropdownToggle}>
            <div className="logo-section">
              <img src="/Logo.png" alt="Company Logo" className="logo-image" />
            </div>
            <span className="dropdown-arrow">⏷</span>
          </button>
          <div className="logo-dropdown-menu">
            <button className="logo-dropdown-item" onClick={() => handleSectionSelect("sales")}>
              <span className="dropdown-icon">💼</span>
              Sales
            </button>
            <Link to="/marketing" className="logo-dropdown-item" onClick={handleNonSalesSection}>
              <span className="dropdown-icon">📈</span>
              Marketing
            </Link>
            <Link to="/finance" className="logo-dropdown-item" onClick={handleNonSalesSection}>
              <span className="dropdown-icon">💰</span>
              Finance
            </Link>
            <Link to="/operations" className="logo-dropdown-item" onClick={handleNonSalesSection}>
              <span className="dropdown-icon">⚙️</span>
              Operations
            </Link>
            <Link to="/hr" className="logo-dropdown-item" onClick={handleNonSalesSection}>
              <span className="dropdown-icon">👥</span>
              HR
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
            <Link to="/profile" className="profile-menu-item">
              <span className="profile-menu-icon">👤</span>
              My Profile
            </Link>
            <Link to="/settings" className="profile-menu-item">
              <span className="profile-menu-icon">⚙️</span>
              Settings
            </Link>
            <Link to="/notifications" className="profile-menu-item">
              <span className="profile-menu-icon">🔔</span>
              Notifications
            </Link>
            <hr className="profile-menu-divider" />
            <Link to="/login" className="profile-menu-item logout">
              <span className="profile-menu-icon">🚪</span>
              Logout
            </Link>
          </div>
        </div>
      </div>
    </nav>
  )
}

export default Navbar
