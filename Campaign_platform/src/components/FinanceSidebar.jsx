"use client"

import { NavLink, useLocation } from "react-router-dom"
import { useState } from "react"
import "./FinanceSidebar.css"

function FinanceSidebar() {
  const location = useLocation()

  const [openGroups, setOpenGroups] = useState({
    Sales: true,
    Purchase: false,
    Reports: false,
  })

  const toggleGroup = (title) => setOpenGroups((s) => ({ ...s, [title]: !s[title] }))

  const menuItems = [
    {
      title: "Dashboard",
      icon: "📊",
      path: "/admin/finance",
      exact: true,
    },
    {
      title: "Sales",
      icon: "💼",
      submenu: [
        { title: "Customers", path: "/admin/finance/customers", icon: "👥" },
        { title: "Estimates", path: "/admin/finance/estimates", icon: "📝" },
        { title: "Invoices", path: "/admin/finance/invoices", icon: "📄" },
        { title: "Payments", path: "/admin/finance/payments", icon: "💵" },
      ],
    },
    {
      title: "Purchase",
      icon: "🛒",
      submenu: [
        { title: "Vendors", path: "/admin/finance/vendors", icon: "🏢" },
        { title: "Purchase Orders", path: "/admin/finance/purchase-orders", icon: "📋" },
        { title: "Bills", path: "/admin/finance/bills", icon: "🧾" },
        { title: "Expenses", path: "/admin/finance/expenses", icon: "💳" },
      ],
    },
    {
      title: "Reports",
      icon: "📈",
      submenu: [
        { title: "Profit & Loss", path: "/admin/finance/reports/profit-loss", icon: "📊" },
        { title: "Balance Sheet", path: "/admin/finance/reports/balance-sheet", icon: "⚖️" },
        { title: "Cash Flow", path: "/admin/finance/reports/cash-flow", icon: "💹" },
        { title: "GST Reports", path: "/admin/finance/reports/gst", icon: "🧮" },
        { title: "Aging Reports", path: "/admin/finance/reports/aging", icon: "⏰" },
      ],
    },
    {
      title: "Settings",
      icon: "⚙️",
      path: "/admin/finance/settings",
    },
  ]

  const isActive = (path, exact = false) => {
    if (exact) return location.pathname === path
    return location.pathname.startsWith(path)
  }

  return (
    <aside className="finance-sidebar">
      <div className="sidebar-header">
        <h2>💰 Finance</h2>
      </div>

      <nav className="sidebar-nav">
        {menuItems.map((item, index) => (
          <div key={index} className="nav-section">
            {item.path ? (
              <NavLink
                to={item.path}
                className={`nav-item ${isActive(item.path, item.exact) ? "active" : ""}`}
                end={item.exact}
              >
                <span className="nav-icon">{item.icon}</span>
                <span className="nav-title">{item.title}</span>
              </NavLink>
            ) : (
              <>
                        <div className="nav-group-header" onClick={() => toggleGroup(item.title)} role="button">
                  <span className="nav-icon">{item.icon}</span>
                  <span className="nav-title">{item.title}</span>
                          <span className={`nav-chevron ${openGroups[item.title] ? 'open' : ''}`}>▾</span>
                </div>
                        <div className={`nav-submenu ${openGroups[item.title] ? 'open' : 'closed'}`}>
                  {item.submenu?.map((subItem, subIndex) => (
                    <NavLink
                      key={subIndex}
                      to={subItem.path}
                      className={`nav-subitem ${isActive(subItem.path) ? "active" : ""}`}
                    >
                      <span className="nav-icon">{subItem.icon}</span>
                      <span className="nav-title">{subItem.title}</span>
                    </NavLink>
                  ))}
                </div>
              </>
            )}
          </div>
        ))}
      </nav>
    </aside>
  )
}

export default FinanceSidebar
