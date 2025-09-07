"use client"

import { Link, useLocation } from "react-router-dom"
import { useState, useEffect } from "react"
import "./RightSidebar.css"

function RightSidebar() {
  const location = useLocation()
  const [campaignDropdownOpen, setCampaignDropdownOpen] = useState(false)

  useEffect(() => {
    if (location.pathname.startsWith("/sales/campaign")) {
      setCampaignDropdownOpen(true)
    } else {
      setCampaignDropdownOpen(false)
    }
  }, [location.pathname])

  const isActive = (path) => {
    return location.pathname === path || location.pathname.startsWith(path)
  }

  const handleCampaignToggle = (e) => {
    e.preventDefault()
    e.stopPropagation()
    setCampaignDropdownOpen(!campaignDropdownOpen)
  }

  return (
    <aside className="right-sidebar">
      <div className="sidebar-section">
        <h3 className="sidebar-title">Sales Navigation</h3>
      </div>

      <nav className="sidebar-nav">
        <ul className="sidebar-nav">
          <li className="sidebar-nav-item">
            <Link
              to="/sales"
              className={`sidebar-nav-link ${isActive("/sales") && !location.pathname.includes("/sales/") ? "active" : ""}`}
            >
              <span className="sidebar-nav-icon">📊</span>
              Sales Dashboard
            </Link>
          </li>

          <li className="sidebar-nav-item">
            <div className={`nav-item dropdown ${campaignDropdownOpen ? "open" : ""}`}>
              <button className="sidebar-nav-link dropdown-toggle" onClick={handleCampaignToggle} type="button">
                <span className="sidebar-nav-icon">🎯</span>
                <span>Campaign</span>
                <span className={`dropdown-arrow ${campaignDropdownOpen ? "rotated" : ""}`}>⏷</span>
              </button>
              <div className="sidebar-submenu">
                <Link
                  to="/sales/campaign/list"
                  className={`sidebar-nav-link ${isActive("/sales/campaign/list") ? "active" : ""}`}
                >
                  <span className="sidebar-nav-icon">📋</span>
                  List
                </Link>
                <Link
                  to="/sales/campaign/templates"
                  className={`sidebar-nav-link ${isActive("/sales/campaign/templates") ? "active" : ""}`}
                >
                  <span className="sidebar-nav-icon">📝</span>
                  Templates
                </Link>
                <Link
                  to="/sales/campaign/workflow"
                  className={`sidebar-nav-link ${isActive("/sales/campaign/workflow") ? "active" : ""}`}
                >
                  <span className="sidebar-nav-icon">🔄</span>
                  Workflow
                </Link>
                <Link
                  to="/sales/campaign/reports"
                  className={`sidebar-nav-link ${isActive("/sales/campaign/reports") ? "active" : ""}`}
                >
                  <span className="sidebar-nav-icon">📊</span>
                  Reports
                </Link>
              </div>
            </div>
          </li>

          <li className="sidebar-nav-item">
            <Link to="/sales/leads" className={`sidebar-nav-link ${isActive("/sales/leads") ? "active" : ""}`}>
              <span className="sidebar-nav-icon">👥</span>
              Leads
            </Link>
          </li>

          <li className="sidebar-nav-item">
            <Link to="/sales/contacts" className={`sidebar-nav-link ${isActive("/sales/contacts") ? "active" : ""}`}>
              <span className="sidebar-nav-icon">📞</span>
              Contacts
            </Link>
          </li>

          <li className="sidebar-nav-item">
            <Link to="/sales/account" className={`sidebar-nav-link ${isActive("/sales/account") ? "active" : ""}`}>
              <span className="sidebar-nav-icon">🏢</span>
              Account
            </Link>
          </li>

          <li className="sidebar-nav-item">
            <Link to="/sales/rfq" className={`sidebar-nav-link ${isActive("/sales/rfq") ? "active" : ""}`}>
              <span className="sidebar-nav-icon">📋</span>
              RFQ
            </Link>
          </li>
        </ul>
      </nav>
    </aside>
  )
}

export default RightSidebar
