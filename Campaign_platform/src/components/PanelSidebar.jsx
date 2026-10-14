"use client"

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
              <span className="sidebar-icon">📊</span> Overview
            </Link>
          </li>
          <li className={`sidebar-item ${isActive("/admin/panel-admin/members") ? "active" : ""}`}>
            <Link to="/admin/panel-admin/members" className="sidebar-link">
              <span className="sidebar-icon">👥</span> Members
            </Link>
          </li>
          <li className={`sidebar-item ${isActive("/admin/panel-admin/recruitment") ? "active" : ""}`}>
            <Link to="/admin/panel-admin/recruitment" className="sidebar-link">
              <span className="sidebar-icon">📣</span> Recruitment
            </Link>
          </li>
          <li className={`sidebar-item ${isActive("/admin/panel-admin/profiling") ? "active" : ""}`}>
            <Link to="/admin/panel-admin/profiling" className="sidebar-link">
              <span className="sidebar-icon">🧭</span> Profiling & Quality
            </Link>
          </li>
          <li className={`sidebar-item ${isActive("/admin/panel-admin/rewards") ? "active" : ""}`}>
            <Link to="/admin/panel-admin/rewards" className="sidebar-link">
              <span className="sidebar-icon">🎁</span> Rewards
            </Link>
          </li>
        </ul>
      </nav>
    </aside>
  )
}

export default PanelSidebar
