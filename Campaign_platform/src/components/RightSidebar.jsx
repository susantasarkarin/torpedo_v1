"use client"

import { Link, useLocation } from "react-router-dom"
import { useState, useEffect } from "react"
import "./RightSidebar.css"

function RightSidebar() {
  const location = useLocation()
  const [campaignDropdownOpen, setCampaignDropdownOpen] = useState(false)

  useEffect(() => {
    if (location.pathname.startsWith("/admin/sales/campaign")) {
      setCampaignDropdownOpen(true)
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

      <nav className="sidebar-menu">
        <ul>
          <li className={`sidebar-item ${isActive("/admin/sales") && !location.pathname.includes("/sales/") ? "active" : ""}`}>
            <Link to="/admin/sales" className="sidebar-link">
              <span className="sidebar-icon">📊</span>
              Sales Dashboard
            </Link>
          </li>

          <li className="sidebar-item">
            <button 
              className={`sidebar-link campaign-toggle ${campaignDropdownOpen ? "open" : ""}`}
              onClick={handleCampaignToggle}
              type="button"
            >
              <span className="sidebar-icon">🎯</span>
              <span>Campaign</span>
              <span className={`dropdown-arrow ${campaignDropdownOpen ? "rotated" : ""}`}>⏷</span>
            </button>
            
            {campaignDropdownOpen && (
              <ul className="campaign-submenu">
                <li className={`sidebar-item ${isActive("/admin/sales/campaign/ai-leads") ? "active" : ""}`}>
                  <Link to="/admin/sales/campaign/ai-leads" className="sidebar-link submenu-link">
                    <span className="sidebar-icon">🤖</span>
                    AI Database
                  </Link>
                </li>
                <li className={`sidebar-item ${isActive("/admin/sales/campaign/email-patterns") ? "active" : ""}`}>
                  <Link to="/admin/sales/campaign/email-patterns" className="sidebar-link submenu-link">
                    <span className="sidebar-icon">📧</span>
                    Email Patterns
                  </Link>
                </li>
                <li className={`sidebar-item ${isActive("/admin/sales/outreach") ? "active" : ""}`}>
                  <Link to="/admin/sales/outreach" className="sidebar-link submenu-link">
                    <span className="sidebar-icon">📨</span>
                    Cold Outreach
                  </Link>
                </li>
              </ul>
            )}
          </li>

          <li className={`sidebar-item ${isActive("/admin/sales/leads") ? "active" : ""}`}>
            <Link to="/admin/sales/leads" className="sidebar-link">
              <span className="sidebar-icon">👥</span>
              Leads
            </Link>
          </li>

          <li className={`sidebar-item ${isActive("/admin/sales/contacts") ? "active" : ""}`}>
            <Link to="/admin/sales/contacts" className="sidebar-link">
              <span className="sidebar-icon">📞</span>
              Contacts
            </Link>
          </li>

          <li className={`sidebar-item ${isActive("/admin/sales/account") ? "active" : ""}`}>
            <Link to="/admin/sales/account" className="sidebar-link">
              <span className="sidebar-icon">🏢</span>
              Account
            </Link>
          </li>

          <li className={`sidebar-item ${isActive("/admin/sales/rfq") ? "active" : ""}`}>
            <Link to="/admin/sales/rfq" className="sidebar-link">
              <span className="sidebar-icon">📋</span>
              RFQ
            </Link>
          </li>

        </ul>
      </nav>
    </aside>
  )
}

export default RightSidebar