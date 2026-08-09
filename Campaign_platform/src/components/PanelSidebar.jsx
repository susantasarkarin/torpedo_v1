"use client"

import { useState } from "react"
import { Link, useLocation } from "react-router-dom"
import "./PanelSidebar.css"

function PanelSidebar() {
  const location = useLocation()

  const isActive = (path) => location.pathname.startsWith(path)
  const isExact = (path) => location.pathname === path || location.pathname === `${path}/`
  const isDashboard = isExact("/admin/panel-admin") || isExact("/admin/panel-admin/dashboard")

  return (
    <aside className="panel-sidebar">
      <div className="sidebar-section">
        <h3 className="sidebar-title">Panel</h3>
      </div>
      <nav className="sidebar-menu">
        <ul>
          <li className={`sidebar-item ${isDashboard ? "active" : ""}`}>
            <Link to="/admin/panel-admin" className="sidebar-link">
              <span className="sidebar-icon">📊</span> Dashboard
            </Link>
          </li>
          <li className={`sidebar-item ${isActive("/admin/panel-admin/panelists") ? "active" : ""}`}>
            <Link to="/admin/panel-admin/panelists" className="sidebar-link">
              <span className="sidebar-icon">👥</span> Panelist Management
            </Link>
          </li>
          <li className={`sidebar-item ${isActive("/admin/panel-admin/suppliers") ? "active" : ""}`}>
            <Link to="/admin/panel-admin/suppliers" className="sidebar-link">
              <span className="sidebar-icon">🔗</span> Traffic Suppliers
            </Link>
          </li>
          <li className={`sidebar-item ${isActive("/admin/panel-admin/rewards") ? "active" : ""}`}>
            <Link to="/admin/panel-admin/rewards" className="sidebar-link">
              <span className="sidebar-icon">🎁</span> Rewards & Points
            </Link>
          </li>
          <li className={`sidebar-item ${isActive("/admin/panel-admin/settings") ? "active" : ""}`}>
            <Link to="/admin/panel-admin/settings" className="sidebar-link">
              <span className="sidebar-icon">⚙️</span> Panel Settings
            </Link>
          </li>
        </ul>
      </nav>
    </aside>
  )
}

export default PanelSidebar
