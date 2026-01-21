"use client"

import { useState, useEffect } from "react"
import { useNavigate } from "react-router-dom"
import { API_BASE_URL as API_URL } from "../../config"
import "../../styles/SalesPages.css"

function VendorDashboard() {
  const navigate = useNavigate()
  const [stats, setStats] = useState({
    totalVendors: 0,
    panelVendors: 0,
    billingVendors: 0,
    totalLeads: 0,
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
        totalLeads: 0,
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
      <div className="sales-page">
        <div className="loading-spinner">Loading...</div>
      </div>
    )
  }

  return (
    <div className="sales-page">
      {/* Page Header */}
      <div className="page-header">
        <div className="header-left">
          <h1>Dashboard</h1>
          <p className="subtitle">Vendor management overview and quick actions</p>
        </div>
        <div className="header-actions">
          <button className="btn btn-outline" onClick={() => navigate('/admin/vendor/all')}>
            📋 View All Vendors
          </button>
          <button className="btn btn-primary" onClick={() => navigate('/admin/vendor/all')}>
            + Add Vendor
          </button>
        </div>
      </div>

      {/* Stats Row */}
      <div className="stats-row">
        <div className="stat-card primary">
          <div className="stat-value">{stats.totalVendors}</div>
          <div className="stat-label">Total Vendors</div>
        </div>
        <div className="stat-card">
          <div className="stat-value">{stats.panelVendors}</div>
          <div className="stat-label">🎯 Panel Vendors</div>
        </div>
        <div className="stat-card warning">
          <div className="stat-value">{stats.billingVendors}</div>
          <div className="stat-label">💰 Billing Vendors</div>
        </div>
      </div>

      {/* Quick Actions */}
      <div className="table-container" style={{ padding: "24px" }}>
        <h2 style={{ marginBottom: "20px", fontSize: "1.25rem", fontWeight: "600" }}>Quick Actions</h2>
        <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fit, minmax(200px, 1fr))", gap: "16px" }}>
          <div 
            onClick={() => navigate('/admin/vendor/leads')}
            style={{ 
              padding: "20px", 
              background: "#f8fafc", 
              borderRadius: "12px", 
              cursor: "pointer",
              border: "1px solid #e5e7eb",
              transition: "all 0.2s"
            }}
            onMouseEnter={e => e.currentTarget.style.borderColor = "#2563eb"}
            onMouseLeave={e => e.currentTarget.style.borderColor = "#e5e7eb"}
          >
            <span style={{ fontSize: "2rem" }}>👥</span>
            <h3 style={{ marginTop: "12px", fontWeight: "600" }}>Vendor Leads</h3>
            <p style={{ color: "#6b7280", fontSize: "0.875rem", marginTop: "4px" }}>Manage vendor leads</p>
          </div>
          
          <div 
            onClick={() => navigate('/admin/vendor/all')}
            style={{ 
              padding: "20px", 
              background: "#f8fafc", 
              borderRadius: "12px", 
              cursor: "pointer",
              border: "1px solid #e5e7eb",
              transition: "all 0.2s"
            }}
            onMouseEnter={e => e.currentTarget.style.borderColor = "#2563eb"}
            onMouseLeave={e => e.currentTarget.style.borderColor = "#e5e7eb"}
          >
            <span style={{ fontSize: "2rem" }}>🏢</span>
            <h3 style={{ marginTop: "12px", fontWeight: "600" }}>Vendors</h3>
            <p style={{ color: "#6b7280", fontSize: "0.875rem", marginTop: "4px" }}>View all vendors</p>
          </div>
          
          <div 
            onClick={() => navigate('/admin/vendor/billing')}
            style={{ 
              padding: "20px", 
              background: "#f8fafc", 
              borderRadius: "12px", 
              cursor: "pointer",
              border: "1px solid #e5e7eb",
              transition: "all 0.2s"
            }}
            onMouseEnter={e => e.currentTarget.style.borderColor = "#2563eb"}
            onMouseLeave={e => e.currentTarget.style.borderColor = "#e5e7eb"}
          >
            <span style={{ fontSize: "2rem" }}>💰</span>
            <h3 style={{ marginTop: "12px", fontWeight: "600" }}>Billing</h3>
            <p style={{ color: "#6b7280", fontSize: "0.875rem", marginTop: "4px" }}>Manage invoices</p>
          </div>
          
          <div 
            onClick={() => navigate('/admin/vendor/payments')}
            style={{ 
              padding: "20px", 
              background: "#f8fafc", 
              borderRadius: "12px", 
              cursor: "pointer",
              border: "1px solid #e5e7eb",
              transition: "all 0.2s"
            }}
            onMouseEnter={e => e.currentTarget.style.borderColor = "#2563eb"}
            onMouseLeave={e => e.currentTarget.style.borderColor = "#e5e7eb"}
          >
            <span style={{ fontSize: "2rem" }}>💳</span>
            <h3 style={{ marginTop: "12px", fontWeight: "600" }}>Payments</h3>
            <p style={{ color: "#6b7280", fontSize: "0.875rem", marginTop: "4px" }}>Process payments</p>
          </div>
        </div>
      </div>
    </div>
  )
}

export default VendorDashboard
