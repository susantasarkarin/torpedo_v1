"use client"

import { Link, useLocation } from "react-router-dom"
import "./MarketingSidebar.css"

function MarketingSidebar() {
  const location = useLocation()

  const isActive = (path) => location.pathname.startsWith(path)
  const isExact = (path) => location.pathname === path || location.pathname === `${path}/`

  return (
    <aside className="marketing-sidebar">
      <div className="sidebar-section">
        <h3 className="sidebar-title">Marketing</h3>
      </div>
      <nav className="sidebar-menu">
        <ul>
          <li className={`sidebar-item ${isExact("/admin/marketing") ? "active" : ""}`}>
            <Link to="/admin/marketing" className="sidebar-link">
              <span className="sidebar-icon">🏠</span> Overview
            </Link>
          </li>
          <li className={`sidebar-item ${isActive("/admin/marketing/websites") ? "active" : ""}`}>
            <Link to="/admin/marketing/websites" className="sidebar-link">
              <span className="sidebar-icon">🌐</span> Website CMS
            </Link>
          </li>
          <li className={`sidebar-item ${isActive("/admin/marketing/linkedin") ? "active" : ""}`}>
            <Link to="/admin/marketing/linkedin" className="sidebar-link">
              <span className="sidebar-icon">💼</span> LinkedIn
            </Link>
          </li>
          <li className={`sidebar-item ${isActive("/admin/marketing/media") ? "active" : ""}`}>
            <Link to="/admin/marketing/media" className="sidebar-link">
              <span className="sidebar-icon">🖼️</span> Media Library
            </Link>
          </li>
        </ul>
      </nav>
    </aside>
  )
}

export default MarketingSidebar
