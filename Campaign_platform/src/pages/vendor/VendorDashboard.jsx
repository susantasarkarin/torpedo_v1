"use client"

import { useState, useEffect } from "react"
import { API_BASE_URL as API_URL } from "../../config"
import "./VendorDashboard.css"

function VendorDashboard() {
  const [stats, setStats] = useState({
    totalVendors: 0,
    panelVendors: 0,
    billingVendors: 0,
    pendingPayments: 0,
    totalPaid: 0
  })
  const [loading, setLoading] = useState(true)

  useEffect(() => {
    fetchStats()
  }, [])

  const fetchStats = async () => {
    try {
      // Fetch unified vendors from the unified vendors endpoint
      const unifiedRes = await fetch(`${API_URL}/vendors/unified`)
      const unifiedData = unifiedRes.ok ? await unifiedRes.json() : []
      
      // Count by type
      const panelData = (unifiedData || []).filter(v => v.source === 'panel')
      const billingData = (unifiedData || []).filter(v => v.source === 'billing')

      setStats({
        totalVendors: (panelData?.length || 0) + (billingData?.length || 0),
        panelVendors: panelData?.length || 0,
        billingVendors: billingData?.length || 0,
        pendingPayments: 0,
        totalPaid: 0
      })
    } catch (error) {
      console.error("Error fetching vendor stats:", error)
    } finally {
      setLoading(false)
    }
  }

  if (loading) {
    return (
      <div className="vendor-dashboard">
        <div className="loading-spinner">Loading...</div>
      </div>
    )
  }

  return (
    <div className="vendor-dashboard">
      <div className="dashboard-header">
        <h1>🏢 Vendor Dashboard</h1>
        <p className="dashboard-subtitle">Unified vendor management overview</p>
      </div>

      <div className="stats-grid">
        <div className="stat-card total">
          <div className="stat-icon">📊</div>
          <div className="stat-content">
            <h3>Total Vendors</h3>
            <span className="stat-value">{stats.totalVendors}</span>
          </div>
        </div>

        <div className="stat-card panel">
          <div className="stat-icon">🎯</div>
          <div className="stat-content">
            <h3>Panel Vendors</h3>
            <span className="stat-value">{stats.panelVendors}</span>
          </div>
        </div>

        <div className="stat-card billing">
          <div className="stat-icon">💰</div>
          <div className="stat-content">
            <h3>Billing Vendors</h3>
            <span className="stat-value">{stats.billingVendors}</span>
          </div>
        </div>

        <div className="stat-card payments">
          <div className="stat-icon">💳</div>
          <div className="stat-content">
            <h3>Pending Payments</h3>
            <span className="stat-value">{stats.pendingPayments}</span>
          </div>
        </div>
      </div>

      <div className="quick-actions">
        <h2>Quick Actions</h2>
        <div className="actions-grid">
          <a href="/admin/vendor/all" className="action-card">
            <span className="action-icon">📋</span>
            <span className="action-text">View All Vendors</span>
          </a>
          <a href="/admin/vendor/panel" className="action-card">
            <span className="action-icon">🎯</span>
            <span className="action-text">Manage Panel Vendors</span>
          </a>
          <a href="/admin/vendor/billing" className="action-card">
            <span className="action-icon">💰</span>
            <span className="action-text">Manage Billing Vendors</span>
          </a>
          <a href="/admin/vendor/payments" className="action-card">
            <span className="action-icon">💳</span>
            <span className="action-text">Process Payments</span>
          </a>
        </div>
      </div>
    </div>
  )
}

export default VendorDashboard
