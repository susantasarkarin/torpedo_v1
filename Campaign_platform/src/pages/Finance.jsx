"use client"

// Updated Finance.jsx - combines sidebar with your existing dashboard
import { useState, useEffect } from "react"
import { Link, Outlet, useLocation } from "react-router-dom"
import { API_BASE_URL } from "../config"
import "./Finance.css"

function Finance() {
  const location = useLocation()
  const isFinanceHome = location.pathname === "/admin/finance"

  // Your existing dashboard state
  const [kpis, setKpis] = useState(null)
  const [loading, setLoading] = useState(true)
  const [activities, setActivities] = useState([])
  const [topCustomers, setTopCustomers] = useState([])
  const [notifications, setNotifications] = useState([])

  useEffect(() => {
    if (isFinanceHome) {
      fetchDashboardData()
    }
  }, [isFinanceHome])

  const fetchDashboardData = async () => {
    try {
      const token = sessionStorage.getItem("token")

      const response = await fetch(`${API_BASE_URL}/finance/dashboard/summary`, {
        headers: {
          Authorization: token,
          "Content-Type": "application/json",
        },
      })

      if (response.ok) {
        const data = await response.json()
        setKpis(data.kpis)
        setActivities(data.recent_activities || [])
        setTopCustomers(data.top_customers || [])
        setNotifications(data.unread_notifications || [])
      }
    } catch (error) {
      console.error("Error fetching dashboard data:", error)
    } finally {
      setLoading(false)
    }
  }

  const formatCurrency = (amount) => {
    return new Intl.NumberFormat("en-IN", {
      style: "currency",
      currency: "INR",
      maximumFractionDigits: 0,
    }).format(amount || 0)
  }

  const mockKpis = {
    revenue: { total_sales: 2450000, total_invoices: 45 },
    expenses: { total: 1820000 },
    profitability: { net_profit: 630000, profit_margin: 25.7 },
    cash_flow: { net_flow: 450000 },
    receivables: { outstanding: 320000, overdue_count: 3 },
    payables: { outstanding: 180000 },
  }

  const displayKpis = kpis || mockKpis

  return (
    <div className="finance-main-content">
      {isFinanceHome ? (
        <FinanceDashboard
          loading={loading}
          displayKpis={displayKpis}
          formatCurrency={formatCurrency}
          activities={activities}
          topCustomers={topCustomers}
          notifications={notifications}
        />
      ) : (
        <Outlet />
      )}
    </div>
  )
}

// Separate Dashboard Component
function FinanceDashboard({ loading, displayKpis, formatCurrency, activities, topCustomers, notifications }) {
  if (loading) {
    return (
      <div style={styles.loadingContainer}>
        <div style={styles.loadingSpinner}></div>
        <p style={styles.loadingText}>Loading Finance Dashboard...</p>
      </div>
    )
  }

  const kpiCards = [
    {
      title: "Total Sales",
      value: formatCurrency(displayKpis.revenue.total_sales),
      subtitle: `${displayKpis.revenue.total_invoices} invoices`,
      trend: "+12% vs last month",
      trendDirection: "up",
      color: "#0d6efd",
    },
    {
      title: "Total Expenses",
      value: formatCurrency(displayKpis.expenses.total),
      subtitle: "Purchases + Operating",
      color: "#6b7280",
    },
    {
      title: "Net Profit",
      value: formatCurrency(displayKpis.profitability.net_profit),
      subtitle: `${displayKpis.profitability.profit_margin.toFixed(1)}% margin`,
      trend: "+5% improvement",
      trendDirection: "up",
      color: "#10b981",
    },
    {
      title: "Cash Flow",
      value: formatCurrency(displayKpis.cash_flow.net_flow),
      subtitle: displayKpis.cash_flow.net_flow >= 0 ? "Positive" : "Negative",
      trendDirection: displayKpis.cash_flow.net_flow >= 0 ? "up" : "down",
      color: "#8b5cf6",
    },
    {
      title: "Receivables",
      value: formatCurrency(displayKpis.receivables.outstanding),
      subtitle: `${displayKpis.receivables.overdue_count} overdue`,
      color: "#f59e0b",
    },
    {
      title: "Payables",
      value: formatCurrency(displayKpis.payables.outstanding),
      subtitle: "Outstanding bills",
      color: "#ef4444",
    },
  ]

  const quickActions = [
    { href: "/admin/finance/customers", icon: "👥", label: "Customers", color: "#0d6efd" },
    { href: "/admin/finance/vendors", icon: "🏢", label: "Vendors", color: "#8b5cf6" },
    { href: "/admin/finance/estimates", icon: "📝", label: "Estimates", color: "#f59e0b" },
    { href: "/admin/finance/invoices", icon: "📄", label: "Invoices", color: "#10b981" },
    { href: "/admin/finance/bills", icon: "🧾", label: "Bills", color: "#ef4444" },
    { href: "/admin/finance/expenses", icon: "💸", label: "Expenses", color: "#ec4899" },
    { href: "/admin/finance/reports", icon: "📊", label: "Reports", color: "#6366f1" },
    { href: "/admin/finance/settings", icon: "⚙️", label: "Settings", color: "#6b7280" },
  ]

  return (
    <div style={styles.container}>
      <div style={styles.header}>
        <div>
          <h2 style={styles.title}>Finance Dashboard</h2>
          <p style={styles.subtitle}>AI-Augmented Financial Management System</p>
        </div>
        <div style={styles.headerActions}>
          <Link to="/admin/finance/invoices" style={{ textDecoration: "none" }}>
            <button style={styles.btnSecondary}>📄 Create Invoice</button>
          </Link>
          <Link to="/admin/finance/expenses" style={{ textDecoration: "none" }}>
            <button style={styles.btnPrimary}>💳 Record Expense</button>
          </Link>
        </div>
      </div>

      {notifications.length > 0 && (
        <div style={styles.notificationBanner}>
          <div style={styles.notificationIcon}>⚠️</div>
          <div style={styles.notificationContent}>
            <p style={styles.notificationTitle}>
              You have {notifications.length} notification{notifications.length !== 1 ? "s" : ""} pending
            </p>
            <p style={styles.notificationSubtitle}>
              {notifications[0]?.message || "Check your finance activities for updates."}
            </p>
          </div>
          <button style={styles.notificationClose}>×</button>
        </div>
      )}

      <div style={styles.kpiGrid}>
        {kpiCards.map((kpi, index) => (
          <div key={index} style={styles.kpiCard}>
            <div style={styles.kpiHeader}>
              <span style={styles.kpiTitle}>{kpi.title}</span>
              <div style={{ ...styles.kpiIcon, backgroundColor: kpi.color + "20", color: kpi.color }}>
                {kpi.title.includes("Sales")
                  ? "💰"
                  : kpi.title.includes("Expenses")
                    ? "💸"
                    : kpi.title.includes("Profit")
                      ? "📈"
                      : kpi.title.includes("Cash")
                        ? "💵"
                        : kpi.title.includes("Receivables")
                          ? "📥"
                          : "📤"}
              </div>
            </div>
            <div style={styles.kpiValue}>{kpi.value}</div>
            <div style={styles.kpiSubtitle}>{kpi.subtitle}</div>
            {kpi.trend && (
              <div style={{ ...styles.kpiTrend, color: kpi.trendDirection === "up" ? "#10b981" : "#ef4444" }}>
                {kpi.trendDirection === "up" ? "↗" : "↘"} {kpi.trend}
              </div>
            )}
          </div>
        ))}
      </div>

      <div style={styles.contentGrid}>
        <div style={styles.card}>
          <div style={styles.cardHeader}>
            <div>
              <h3 style={styles.cardTitle}>Recent Activities</h3>
              <p style={styles.cardSubtitle}>Latest financial transactions</p>
            </div>
            <Link to="/admin/finance/activities" style={styles.viewAllLink}>
              View All →
            </Link>
          </div>
          <div style={styles.cardContent}>
            {activities.length === 0 ? (
              <div style={styles.emptyState}>
                <div style={styles.emptyIcon}>📋</div>
                <p style={styles.emptyText}>No recent activities</p>
              </div>
            ) : (
              <div style={styles.activityList}>
                {activities.slice(0, 5).map((activity, index) => (
                  <div key={index} style={styles.activityItem}>
                    <div style={styles.activityIcon}>{activity.type === "invoice" ? "📄" : "💰"}</div>
                    <div style={styles.activityDetails}>
                      <p style={styles.activityTitle}>{activity.title}</p>
                      <p style={styles.activityDescription}>{activity.description}</p>
                      <p style={styles.activityTime}>{new Date(activity.timestamp).toLocaleString("en-IN")}</p>
                    </div>
                    <div style={styles.activityAmount}>
                      <p
                        style={{ ...styles.activityValue, color: activity.type === "payment" ? "#10b981" : "#374151" }}
                      >
                        {formatCurrency(activity.amount)}
                      </p>
                      <span
                        style={{
                          ...styles.statusBadge,
                          ...(activity.status === "paid"
                            ? styles.statusPaid
                            : activity.status === "pending"
                              ? styles.statusPending
                              : styles.statusOverdue),
                        }}
                      >
                        {activity.status}
                      </span>
                    </div>
                  </div>
                ))}
              </div>
            )}
          </div>
        </div>

        <div style={styles.card}>
          <div style={styles.cardHeader}>
            <div>
              <h3 style={styles.cardTitle}>Top Customers</h3>
              <p style={styles.cardSubtitle}>By revenue this period</p>
            </div>
            <Link to="/admin/finance/customers" style={styles.viewAllLink}>
              View All →
            </Link>
          </div>
          <div style={styles.cardContent}>
            {topCustomers.length === 0 ? (
              <div style={styles.emptyState}>
                <div style={styles.emptyIcon}>👥</div>
                <p style={styles.emptyText}>No customer data available</p>
              </div>
            ) : (
              <div style={styles.customerList}>
                {topCustomers.slice(0, 5).map((customer, index) => (
                  <div key={index} style={styles.customerItem}>
                    <div style={styles.customerRank}>{index + 1}</div>
                    <div style={styles.customerDetails}>
                      <p style={styles.customerName}>{customer.customer_name}</p>
                      <p style={styles.customerInvoices}>{customer.invoice_count} invoices</p>
                    </div>
                    <div style={styles.customerRevenue}>{formatCurrency(customer.revenue)}</div>
                  </div>
                ))}
              </div>
            )}
          </div>
        </div>
      </div>

      <div style={styles.card}>
        <div style={styles.cardHeader}>
          <div>
            <h3 style={styles.cardTitle}>Quick Actions</h3>
            <p style={styles.cardSubtitle}>Navigate to finance modules</p>
          </div>
        </div>
        <div style={styles.cardContent}>
          <div style={styles.quickActionsGrid}>
            {quickActions.map((action, index) => (
              <Link
                key={index}
                to={action.href}
                style={{ ...styles.quickActionCard, textDecoration: "none" }}
                onMouseEnter={(e) => {
                  e.currentTarget.style.borderColor = action.color
                  e.currentTarget.style.backgroundColor = action.color + "08"
                }}
                onMouseLeave={(e) => {
                  e.currentTarget.style.borderColor = "#e5e7eb"
                  e.currentTarget.style.backgroundColor = "white"
                }}
              >
                <div style={{ ...styles.quickActionIcon, backgroundColor: action.color + "20" }}>{action.icon}</div>
                <span style={styles.quickActionLabel}>{action.label}</span>
              </Link>
            ))}
          </div>
        </div>
      </div>
    </div>
  )
}

const styles = {
  container: {
    maxWidth: "1400px",
    margin: "0 auto",
    padding: "2rem",
    fontFamily: '-apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, "Helvetica Neue", Arial, sans-serif',
    backgroundColor: "#f8f9fa",
    minHeight: "100vh",
  },
  header: {
    display: "flex",
    justifyContent: "space-between",
    alignItems: "flex-start",
    marginBottom: "2rem",
    flexWrap: "wrap",
    gap: "1rem",
  },
  title: {
    fontSize: "2rem",
    fontWeight: "700",
    margin: "0 0 0.5rem 0",
    color: "#1a1a1a",
  },
  subtitle: {
    color: "#6b7280",
    margin: "0",
    fontSize: "0.95rem",
  },
  headerActions: {
    display: "flex",
    gap: "0.75rem",
    flexWrap: "wrap",
  },
  btnPrimary: {
    padding: "0.75rem 1.5rem",
    backgroundColor: "#0d6efd",
    color: "white",
    border: "none",
    borderRadius: "0.5rem",
    fontSize: "0.95rem",
    fontWeight: "500",
    cursor: "pointer",
    transition: "all 0.2s",
  },
  btnSecondary: {
    padding: "0.75rem 1.5rem",
    backgroundColor: "white",
    color: "#374151",
    border: "1px solid #d1d5db",
    borderRadius: "0.5rem",
    fontSize: "0.95rem",
    fontWeight: "500",
    cursor: "pointer",
    transition: "all 0.2s",
  },
  loadingContainer: {
    display: "flex",
    flexDirection: "column",
    alignItems: "center",
    justifyContent: "center",
    height: "400px",
  },
  loadingSpinner: {
    width: "2rem",
    height: "2rem",
    border: "3px solid #e5e7eb",
    borderTop: "3px solid #0d6efd",
    borderRadius: "50%",
    animation: "spin 1s linear infinite",
    marginBottom: "1rem",
  },
  loadingText: {
    color: "#6b7280",
    fontSize: "0.95rem",
  },
  notificationBanner: {
    backgroundColor: "#fef3c7",
    border: "1px solid #fbbf24",
    borderRadius: "0.75rem",
    padding: "1rem",
    display: "flex",
    alignItems: "flex-start",
    gap: "0.75rem",
    marginBottom: "2rem",
  },
  notificationIcon: {
    fontSize: "1.5rem",
    flexShrink: 0,
  },
  notificationContent: {
    flex: 1,
  },
  notificationTitle: {
    fontSize: "0.875rem",
    fontWeight: "600",
    color: "#92400e",
    margin: "0 0 0.25rem 0",
  },
  notificationSubtitle: {
    fontSize: "0.875rem",
    color: "#b45309",
    margin: "0",
  },
  notificationClose: {
    background: "none",
    border: "none",
    fontSize: "1.5rem",
    color: "#b45309",
    cursor: "pointer",
    padding: "0",
    lineHeight: "1",
  },
  kpiGrid: {
    display: "grid",
    gridTemplateColumns: "repeat(auto-fit, minmax(200px, 1fr))",
    gap: "1rem",
    marginBottom: "2rem",
  },
  kpiCard: {
    backgroundColor: "white",
    borderRadius: "0.75rem",
    padding: "1.25rem",
    boxShadow: "0 1px 3px rgba(0,0,0,0.1)",
    transition: "all 0.2s",
  },
  kpiHeader: {
    display: "flex",
    justifyContent: "space-between",
    alignItems: "center",
    marginBottom: "0.75rem",
  },
  kpiTitle: {
    fontSize: "0.75rem",
    fontWeight: "600",
    color: "#6b7280",
    textTransform: "uppercase",
    letterSpacing: "0.05em",
  },
  kpiIcon: {
    width: "2rem",
    height: "2rem",
    borderRadius: "0.5rem",
    display: "flex",
    alignItems: "center",
    justifyContent: "center",
    fontSize: "1rem",
  },
  kpiValue: {
    fontSize: "1.5rem",
    fontWeight: "700",
    color: "#1a1a1a",
    marginBottom: "0.25rem",
  },
  kpiSubtitle: {
    fontSize: "0.875rem",
    color: "#6b7280",
  },
  kpiTrend: {
    fontSize: "0.75rem",
    fontWeight: "600",
    marginTop: "0.5rem",
  },
  contentGrid: {
    display: "grid",
    gridTemplateColumns: "repeat(auto-fit, minmax(400px, 1fr))",
    gap: "1.5rem",
    marginBottom: "2rem",
  },
  card: {
    backgroundColor: "white",
    borderRadius: "0.75rem",
    boxShadow: "0 1px 3px rgba(0,0,0,0.1)",
    overflow: "hidden",
  },
  cardHeader: {
    padding: "1.25rem",
    borderBottom: "1px solid #e5e7eb",
    display: "flex",
    justifyContent: "space-between",
    alignItems: "center",
  },
  cardTitle: {
    fontSize: "1.125rem",
    fontWeight: "600",
    color: "#1a1a1a",
    margin: "0 0 0.25rem 0",
  },
  cardSubtitle: {
    fontSize: "0.875rem",
    color: "#6b7280",
    margin: "0",
  },
  viewAllLink: {
    fontSize: "0.875rem",
    color: "#0d6efd",
    textDecoration: "none",
    fontWeight: "500",
  },
  cardContent: {
    padding: "1.25rem",
  },
  emptyState: {
    textAlign: "center",
    padding: "2rem",
  },
  emptyIcon: {
    fontSize: "3rem",
    marginBottom: "0.75rem",
    opacity: 0.3,
  },
  emptyText: {
    fontSize: "0.875rem",
    color: "#9ca3af",
    margin: "0",
  },
  activityList: {
    display: "flex",
    flexDirection: "column",
    gap: "1rem",
  },
  activityItem: {
    display: "flex",
    alignItems: "flex-start",
    gap: "0.75rem",
    paddingBottom: "1rem",
    borderBottom: "1px solid #e5e7eb",
  },
  activityIcon: {
    width: "2.5rem",
    height: "2.5rem",
    borderRadius: "0.5rem",
    backgroundColor: "#f3f4f6",
    display: "flex",
    alignItems: "center",
    justifyContent: "center",
    fontSize: "1.25rem",
    flexShrink: 0,
  },
  activityDetails: {
    flex: 1,
    minWidth: 0,
  },
  activityTitle: {
    fontSize: "0.875rem",
    fontWeight: "500",
    color: "#1a1a1a",
    margin: "0 0 0.25rem 0",
  },
  activityDescription: {
    fontSize: "0.75rem",
    color: "#6b7280",
    margin: "0 0 0.25rem 0",
  },
  activityTime: {
    fontSize: "0.75rem",
    color: "#9ca3af",
    margin: "0",
  },
  activityAmount: {
    textAlign: "right",
  },
  activityValue: {
    fontSize: "0.875rem",
    fontWeight: "600",
    margin: "0 0 0.25rem 0",
  },
  statusBadge: {
    display: "inline-block",
    padding: "0.25rem 0.5rem",
    borderRadius: "0.25rem",
    fontSize: "0.75rem",
    fontWeight: "600",
    textTransform: "capitalize",
  },
  statusPaid: {
    backgroundColor: "#d1fae5",
    color: "#065f46",
  },
  statusPending: {
    backgroundColor: "#fef3c7",
    color: "#92400e",
  },
  statusOverdue: {
    backgroundColor: "#fee2e2",
    color: "#991b1b",
  },
  customerList: {
    display: "flex",
    flexDirection: "column",
    gap: "0.75rem",
  },
  customerItem: {
    display: "flex",
    alignItems: "center",
    gap: "0.75rem",
    padding: "0.75rem",
    borderRadius: "0.5rem",
    backgroundColor: "#f9fafb",
    transition: "all 0.2s",
  },
  customerRank: {
    width: "2rem",
    height: "2rem",
    borderRadius: "50%",
    backgroundColor: "#0d6efd",
    color: "white",
    display: "flex",
    alignItems: "center",
    justifyContent: "center",
    fontSize: "0.875rem",
    fontWeight: "700",
    flexShrink: 0,
  },
  customerDetails: {
    flex: 1,
    minWidth: 0,
  },
  customerName: {
    fontSize: "0.875rem",
    fontWeight: "500",
    color: "#1a1a1a",
    margin: "0 0 0.25rem 0",
  },
  customerInvoices: {
    fontSize: "0.75rem",
    color: "#6b7280",
    margin: "0",
  },
  customerRevenue: {
    fontSize: "0.875rem",
    fontWeight: "600",
    color: "#10b981",
  },
  quickActionsGrid: {
    display: "grid",
    gridTemplateColumns: "repeat(auto-fill, minmax(120px, 1fr))",
    gap: "0.75rem",
  },
  quickActionCard: {
    display: "flex",
    flexDirection: "column",
    alignItems: "center",
    padding: "1rem",
    borderRadius: "0.75rem",
    border: "1px solid #e5e7eb",
    backgroundColor: "white",
    transition: "all 0.2s",
    cursor: "pointer",
  },
  quickActionIcon: {
    width: "3rem",
    height: "3rem",
    borderRadius: "0.75rem",
    display: "flex",
    alignItems: "center",
    justifyContent: "center",
    fontSize: "1.5rem",
    marginBottom: "0.5rem",
    transition: "all 0.2s",
  },
  quickActionLabel: {
    fontSize: "0.875rem",
    fontWeight: "500",
    color: "#374151",
    textAlign: "center",
    margin: "0",
  },
}

export default Finance
