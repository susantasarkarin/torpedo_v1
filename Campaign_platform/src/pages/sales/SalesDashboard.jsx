"use client"

import { useState, useEffect, useCallback } from "react"
import { API_BASE_URL } from "../../config"
import {
  TrendingUp,
  TrendingDown,
  Target,
  Clock,
  AlertTriangle,
  CheckCircle,
  XCircle,
  DollarSign,
  Users,
  ArrowRight,
  RefreshCw,
  Calendar,
  Eye,
  EyeOff,
  ChevronDown,
  BarChart3
} from "lucide-react"

// ============== STYLES ==============
const styles = {
  container: {
    minHeight: "100vh",
    backgroundColor: "#0f172a",
    padding: "1.5rem",
    color: "#e2e8f0"
  },
  header: {
    display: "flex",
    justifyContent: "space-between",
    alignItems: "center",
    marginBottom: "1.5rem",
    flexWrap: "wrap",
    gap: "1rem"
  },
  title: {
    fontSize: "1.75rem",
    fontWeight: "700",
    color: "#f8fafc",
    margin: 0
  },
  subtitle: {
    fontSize: "0.875rem",
    color: "#94a3b8",
    margin: "0.25rem 0 0 0"
  },
  controls: {
    display: "flex",
    gap: "0.75rem",
    alignItems: "center",
    flexWrap: "wrap"
  },
  select: {
    padding: "0.5rem 1rem",
    backgroundColor: "#1e293b",
    color: "#e2e8f0",
    border: "1px solid #334155",
    borderRadius: "0.5rem",
    fontSize: "0.875rem",
    cursor: "pointer"
  },
  input: {
    padding: "0.5rem 0.75rem",
    backgroundColor: "#1e293b",
    color: "#e2e8f0",
    border: "1px solid #334155",
    borderRadius: "0.5rem",
    fontSize: "0.875rem"
  },
  button: {
    padding: "0.5rem 1rem",
    backgroundColor: "#3b82f6",
    color: "white",
    border: "none",
    borderRadius: "0.5rem",
    fontSize: "0.875rem",
    fontWeight: "500",
    cursor: "pointer",
    display: "flex",
    alignItems: "center",
    gap: "0.5rem"
  },
  buttonSecondary: {
    padding: "0.5rem 1rem",
    backgroundColor: "#334155",
    color: "#e2e8f0",
    border: "1px solid #475569",
    borderRadius: "0.5rem",
    fontSize: "0.875rem",
    fontWeight: "500",
    cursor: "pointer",
    display: "flex",
    alignItems: "center",
    gap: "0.5rem"
  },
  grid: {
    display: "grid",
    gap: "1rem"
  },
  grid3: {
    gridTemplateColumns: "repeat(auto-fit, minmax(280px, 1fr))"
  },
  card: {
    backgroundColor: "#1e293b",
    borderRadius: "0.75rem",
    overflow: "hidden",
    border: "1px solid #334155"
  },
  cardHeader: {
    padding: "1rem 1.25rem",
    borderBottom: "1px solid #334155",
    display: "flex",
    justifyContent: "space-between",
    alignItems: "center"
  },
  cardTitle: {
    fontSize: "0.875rem",
    fontWeight: "600",
    color: "#f8fafc",
    margin: 0,
    display: "flex",
    alignItems: "center",
    gap: "0.5rem"
  },
  cardContent: {
    padding: "1.25rem"
  },
  section: {
    marginBottom: "1.5rem"
  },
  sectionTitle: {
    fontSize: "0.75rem",
    fontWeight: "600",
    color: "#64748b",
    textTransform: "uppercase",
    letterSpacing: "0.05em",
    marginBottom: "0.75rem"
  },
  badge: {
    padding: "0.25rem 0.5rem",
    borderRadius: "9999px",
    fontSize: "0.7rem",
    fontWeight: "600",
    textTransform: "uppercase"
  },
  badgeNormal: {
    backgroundColor: "rgba(34, 197, 94, 0.2)",
    color: "#4ade80"
  },
  badgeWarning: {
    backgroundColor: "rgba(251, 191, 36, 0.2)",
    color: "#fbbf24"
  },
  badgeCritical: {
    backgroundColor: "rgba(239, 68, 68, 0.2)",
    color: "#f87171"
  },
  loading: {
    display: "flex",
    justifyContent: "center",
    alignItems: "center",
    minHeight: "400px",
    color: "#94a3b8"
  }
}

// ============== HELPER FUNCTIONS ==============
const formatCurrency = (amount, currency = "USD") => {
  return new Intl.NumberFormat("en-US", {
    style: "currency",
    currency: currency,
    maximumFractionDigits: 0
  }).format(amount || 0)
}

const formatPercent = (value) => {
  return `${(value || 0).toFixed(1)}%`
}

const getAlertBadge = (level) => {
  const badgeStyles = {
    normal: styles.badgeNormal,
    warning: styles.badgeWarning,
    critical: styles.badgeCritical
  }
  return { ...styles.badge, ...badgeStyles[level] }
}

// ============== FUNNEL COMPONENT ==============
function FunnelVisualization({ funnel }) {
  if (!funnel) return null

  const maxCount = Math.max(...funnel.stages.map(s => s.count), 1)

  return (
    <div style={styles.card}>
      <div style={styles.cardHeader}>
        <h3 style={styles.cardTitle}>
          <Target size={16} />
          Sales Funnel
        </h3>
        <span style={{ fontSize: "0.75rem", color: "#94a3b8" }}>
          End-to-End: <strong style={{ color: funnel.end_to_end_rate > 1 ? "#4ade80" : "#f87171" }}>
            {formatPercent(funnel.end_to_end_rate)}
          </strong>
        </span>
      </div>
      <div style={{ ...styles.cardContent, padding: "1rem" }}>
        {/* Funnel Stages */}
        <div style={{ display: "flex", flexDirection: "column", gap: "0.5rem" }}>
          {funnel.stages.map((stage, idx) => {
            const width = Math.max((stage.count / maxCount) * 100, 15)
            const conversion = funnel.conversions[idx]
            const isWorstDropoff = conversion?.is_worst_dropoff

            return (
              <div key={stage.name}>
                <div style={{ display: "flex", alignItems: "center", gap: "0.75rem", marginBottom: "0.25rem" }}>
                  <span style={{ fontSize: "1.25rem" }}>{stage.icon}</span>
                  <div style={{ flex: 1 }}>
                    <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", marginBottom: "0.25rem" }}>
                      <span style={{ fontSize: "0.8rem", color: "#cbd5e1" }}>{stage.name}</span>
                      <span style={{ fontSize: "0.9rem", fontWeight: "600", color: "#f8fafc" }}>
                        {stage.count.toLocaleString()}
                      </span>
                    </div>
                    <div style={{
                      height: "24px",
                      backgroundColor: "#0f172a",
                      borderRadius: "4px",
                      overflow: "hidden"
                    }}>
                      <div style={{
                        width: `${width}%`,
                        height: "100%",
                        background: idx === funnel.stages.length - 1
                          ? "linear-gradient(90deg, #22c55e, #16a34a)"
                          : "linear-gradient(90deg, #3b82f6, #1d4ed8)",
                        borderRadius: "4px",
                        transition: "width 0.5s ease"
                      }} />
                    </div>
                  </div>
                </div>
                
                {/* Conversion Arrow */}
                {conversion && (
                  <div style={{
                    display: "flex",
                    alignItems: "center",
                    justifyContent: "center",
                    padding: "0.25rem 0",
                    gap: "0.5rem"
                  }}>
                    <ArrowRight size={14} style={{ color: "#475569" }} />
                    <span style={{
                      fontSize: "0.75rem",
                      fontWeight: "600",
                      color: isWorstDropoff ? "#f87171" : "#94a3b8",
                      backgroundColor: isWorstDropoff ? "rgba(239, 68, 68, 0.15)" : "transparent",
                      padding: isWorstDropoff ? "0.125rem 0.5rem" : 0,
                      borderRadius: "9999px"
                    }}>
                      {formatPercent(conversion.rate)}
                      {isWorstDropoff && " ⚠️ Worst Drop-off"}
                    </span>
                  </div>
                )}
              </div>
            )
          })}
        </div>
      </div>
    </div>
  )
}

// ============== VELOCITY CARD ==============
function VelocityCard({ velocity }) {
  if (!velocity || velocity.length === 0) return null

  return (
    <div style={styles.card}>
      <div style={styles.cardHeader}>
        <h3 style={styles.cardTitle}>
          <Clock size={16} />
          Velocity KPIs
        </h3>
      </div>
      <div style={styles.cardContent}>
        <div style={{ display: "flex", flexDirection: "column", gap: "1rem" }}>
          {velocity.map((v, idx) => (
            <div key={idx} style={{
              display: "flex",
              justifyContent: "space-between",
              alignItems: "center",
              padding: "0.75rem",
              backgroundColor: "#0f172a",
              borderRadius: "0.5rem",
              border: v.alert_level !== "normal" ? `1px solid ${v.alert_level === "critical" ? "#ef4444" : "#eab308"}` : "1px solid transparent"
            }}>
              <div>
                <div style={{ fontSize: "0.8rem", color: "#94a3b8", marginBottom: "0.25rem" }}>
                  {v.name}
                </div>
                <div style={{ fontSize: "1.25rem", fontWeight: "700", color: "#f8fafc" }}>
                  {v.value_hours != null
                    ? `${v.value_hours}h`
                    : v.value_days != null
                      ? `${v.value_days}d`
                      : "—"
                  }
                </div>
                {v.threshold_hours && (
                  <div style={{ fontSize: "0.7rem", color: "#64748b" }}>
                    Target: &lt; {v.threshold_hours}h
                  </div>
                )}
                {v.threshold_days && (
                  <div style={{ fontSize: "0.7rem", color: "#64748b" }}>
                    Target: &lt; {v.threshold_days}d
                  </div>
                )}
              </div>
              <div style={{ display: "flex", flexDirection: "column", alignItems: "flex-end", gap: "0.25rem" }}>
                <span style={getAlertBadge(v.alert_level)}>
                  {v.alert_level}
                </span>
                {v.breach_count > 0 && (
                  <span style={{ fontSize: "0.7rem", color: "#f87171" }}>
                    {v.breach_count} SLA breaches
                  </span>
                )}
              </div>
            </div>
          ))}
        </div>
      </div>
    </div>
  )
}

// ============== REVENUE CARD ==============
function RevenueCard({ revenue, role }) {
  if (!revenue || revenue.length === 0) return null

  // Filter metrics based on role
  const displayMetrics = role === "manager" ? revenue : revenue.filter(r => 
    ["Win Rate", "Average Deal Size", "Won Deals Value"].includes(r.name)
  )

  return (
    <div style={styles.card}>
      <div style={styles.cardHeader}>
        <h3 style={styles.cardTitle}>
          <DollarSign size={16} />
          Revenue Reality
        </h3>
      </div>
      <div style={styles.cardContent}>
        <div style={{ display: "grid", gridTemplateColumns: "repeat(2, 1fr)", gap: "0.75rem" }}>
          {displayMetrics.map((r, idx) => {
            const isPercentage = r.name === "Win Rate" || r.name === "Pipeline Coverage Ratio"
            const displayValue = isPercentage ? formatPercent(r.value) : formatCurrency(r.value, r.currency)

            return (
              <div key={idx} style={{
                padding: "0.75rem",
                backgroundColor: "#0f172a",
                borderRadius: "0.5rem",
                border: r.alert_level && r.alert_level !== "normal"
                  ? `1px solid ${r.alert_level === "critical" ? "#ef4444" : "#eab308"}`
                  : "1px solid transparent"
              }}>
                <div style={{ fontSize: "0.7rem", color: "#64748b", marginBottom: "0.25rem", textTransform: "uppercase" }}>
                  {r.name}
                </div>
                <div style={{
                  fontSize: "1.1rem",
                  fontWeight: "700",
                  color: r.alert_level === "critical" ? "#f87171"
                    : r.alert_level === "warning" ? "#fbbf24"
                    : "#f8fafc"
                }}>
                  {displayValue}
                </div>
                {r.target && (
                  <div style={{ fontSize: "0.65rem", color: "#475569" }}>
                    Target: {isPercentage ? formatPercent(r.target) : formatCurrency(r.target)}
                  </div>
                )}
              </div>
            )
          })}
        </div>
      </div>
    </div>
  )
}

// ============== RFQ AGING (MANAGER ONLY) ==============
function RFQAgingCard({ aging }) {
  if (!aging || aging.length === 0) return null

  const totalValue = aging.reduce((sum, b) => sum + b.total_value, 0)
  const totalCount = aging.reduce((sum, b) => sum + b.count, 0)

  return (
    <div style={styles.card}>
      <div style={styles.cardHeader}>
        <h3 style={styles.cardTitle}>
          <AlertTriangle size={16} />
          RFQ Aging Buckets
        </h3>
        <span style={{ fontSize: "0.75rem", color: "#94a3b8" }}>
          {totalCount} open RFQs
        </span>
      </div>
      <div style={styles.cardContent}>
        <div style={{ display: "flex", gap: "0.5rem" }}>
          {aging.map((bucket, idx) => {
            const isRisk = bucket.bucket === "60+"
            const width = totalValue > 0 ? (bucket.total_value / totalValue) * 100 : 0

            return (
              <div key={idx} style={{
                flex: 1,
                padding: "0.75rem",
                backgroundColor: isRisk ? "rgba(239, 68, 68, 0.1)" : "#0f172a",
                borderRadius: "0.5rem",
                border: isRisk ? "1px solid #ef4444" : "1px solid transparent",
                textAlign: "center"
              }}>
                <div style={{
                  fontSize: "0.7rem",
                  color: isRisk ? "#f87171" : "#64748b",
                  marginBottom: "0.25rem"
                }}>
                  {bucket.bucket} days
                </div>
                <div style={{
                  fontSize: "1.25rem",
                  fontWeight: "700",
                  color: isRisk ? "#f87171" : "#f8fafc"
                }}>
                  {bucket.count}
                </div>
                <div style={{ fontSize: "0.7rem", color: "#94a3b8" }}>
                  {formatCurrency(bucket.total_value)}
                </div>
              </div>
            )
          })}
        </div>
      </div>
    </div>
  )
}

// ============== FORECAST VS ACTUAL (MANAGER ONLY) ==============
function ForecastCard({ forecast }) {
  if (!forecast) return null

  const progressPercent = Math.min((forecast.actual / forecast.target) * 100, 100)
  const isOnTrack = forecast.total_projected >= forecast.target

  return (
    <div style={styles.card}>
      <div style={styles.cardHeader}>
        <h3 style={styles.cardTitle}>
          <BarChart3 size={16} />
          Forecast vs Actual
        </h3>
        <span style={{
          ...styles.badge,
          ...(isOnTrack ? styles.badgeNormal : styles.badgeCritical)
        }}>
          {isOnTrack ? "On Track" : "At Risk"}
        </span>
      </div>
      <div style={styles.cardContent}>
        {/* Progress Bar */}
        <div style={{ marginBottom: "1rem" }}>
          <div style={{ display: "flex", justifyContent: "space-between", marginBottom: "0.5rem" }}>
            <span style={{ fontSize: "0.8rem", color: "#94a3b8" }}>Attainment</span>
            <span style={{ fontSize: "0.8rem", fontWeight: "600", color: "#f8fafc" }}>
              {formatPercent(forecast.attainment_percent)}
            </span>
          </div>
          <div style={{
            height: "8px",
            backgroundColor: "#0f172a",
            borderRadius: "4px",
            overflow: "hidden"
          }}>
            <div style={{
              width: `${progressPercent}%`,
              height: "100%",
              background: progressPercent >= 100 ? "#22c55e" : progressPercent >= 70 ? "#eab308" : "#ef4444",
              borderRadius: "4px",
              transition: "width 0.5s ease"
            }} />
          </div>
        </div>

        {/* Metrics Grid */}
        <div style={{ display: "grid", gridTemplateColumns: "repeat(2, 1fr)", gap: "0.75rem" }}>
          <div style={{ padding: "0.5rem", backgroundColor: "#0f172a", borderRadius: "0.375rem" }}>
            <div style={{ fontSize: "0.65rem", color: "#64748b", textTransform: "uppercase" }}>Target</div>
            <div style={{ fontSize: "1rem", fontWeight: "600", color: "#f8fafc" }}>
              {formatCurrency(forecast.target)}
            </div>
          </div>
          <div style={{ padding: "0.5rem", backgroundColor: "#0f172a", borderRadius: "0.375rem" }}>
            <div style={{ fontSize: "0.65rem", color: "#64748b", textTransform: "uppercase" }}>Actual</div>
            <div style={{ fontSize: "1rem", fontWeight: "600", color: "#22c55e" }}>
              {formatCurrency(forecast.actual)}
            </div>
          </div>
          <div style={{ padding: "0.5rem", backgroundColor: "#0f172a", borderRadius: "0.375rem" }}>
            <div style={{ fontSize: "0.65rem", color: "#64748b", textTransform: "uppercase" }}>Forecast</div>
            <div style={{ fontSize: "1rem", fontWeight: "600", color: "#3b82f6" }}>
              {formatCurrency(forecast.forecast)}
            </div>
          </div>
          <div style={{ padding: "0.5rem", backgroundColor: "#0f172a", borderRadius: "0.375rem" }}>
            <div style={{ fontSize: "0.65rem", color: "#64748b", textTransform: "uppercase" }}>Gap to Target</div>
            <div style={{
              fontSize: "1rem",
              fontWeight: "600",
              color: forecast.gap_to_target > 0 ? "#f87171" : "#22c55e"
            }}>
              {formatCurrency(Math.abs(forecast.gap_to_target))}
              {forecast.gap_to_target <= 0 && " ✓"}
            </div>
          </div>
        </div>
      </div>
    </div>
  )
}

// ============== MAIN DASHBOARD COMPONENT ==============
export default function SalesDashboard() {
  const [data, setData] = useState(null)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState(null)
  const [role, setRole] = useState("rep")
  const [dateRange, setDateRange] = useState({
    start_date: new Date(Date.now() - 30 * 24 * 60 * 60 * 1000).toISOString().split("T")[0],
    end_date: new Date().toISOString().split("T")[0]
  })
  const [target, setTarget] = useState(100000)

  const fetchDashboard = useCallback(async () => {
    setLoading(true)
    setError(null)
    try {
      const params = new URLSearchParams({
        start_date: dateRange.start_date,
        end_date: dateRange.end_date,
        role: role,
        target: target.toString()
      })
      const response = await fetch(`${API_BASE_URL}/sales/dashboard?${params}`)
      if (!response.ok) {
        throw new Error(`HTTP ${response.status}: ${response.statusText}`)
      }
      const result = await response.json()
      setData(result)
    } catch (err) {
      console.error("Error fetching sales dashboard:", err)
      setError(err.message)
    } finally {
      setLoading(false)
    }
  }, [dateRange, role, target])

  useEffect(() => {
    fetchDashboard()
  }, [fetchDashboard])

  if (loading) {
    return (
      <div style={styles.container}>
        <div style={styles.loading}>
          <RefreshCw size={24} className="animate-spin" style={{ marginRight: "0.5rem" }} />
          Loading dashboard...
        </div>
      </div>
    )
  }

  if (error) {
    return (
      <div style={styles.container}>
        <div style={{ ...styles.card, padding: "2rem", textAlign: "center" }}>
          <XCircle size={48} style={{ color: "#ef4444", marginBottom: "1rem" }} />
          <h3 style={{ color: "#f8fafc", marginBottom: "0.5rem" }}>Failed to load dashboard</h3>
          <p style={{ color: "#94a3b8", marginBottom: "1rem" }}>{error}</p>
          <button style={styles.button} onClick={fetchDashboard}>
            <RefreshCw size={16} />
            Retry
          </button>
        </div>
      </div>
    )
  }

  return (
    <div style={styles.container}>
      {/* Header */}
      <div style={styles.header}>
        <div>
          <h1 style={styles.title}>Sales Dashboard</h1>
          <p style={styles.subtitle}>
            Conversion-focused KPIs • {role === "manager" ? "Manager View" : "Rep View"}
          </p>
        </div>
        <div style={styles.controls}>
          <input
            type="date"
            value={dateRange.start_date}
            onChange={(e) => setDateRange(prev => ({ ...prev, start_date: e.target.value }))}
            style={styles.input}
          />
          <span style={{ color: "#64748b" }}>to</span>
          <input
            type="date"
            value={dateRange.end_date}
            onChange={(e) => setDateRange(prev => ({ ...prev, end_date: e.target.value }))}
            style={styles.input}
          />
          <select
            value={role}
            onChange={(e) => setRole(e.target.value)}
            style={styles.select}
          >
            <option value="rep">Rep View</option>
            <option value="manager">Manager View</option>
          </select>
          {role === "manager" && (
            <input
              type="number"
              value={target}
              onChange={(e) => setTarget(Number(e.target.value))}
              placeholder="Target"
              style={{ ...styles.input, width: "100px" }}
            />
          )}
          <button style={styles.button} onClick={fetchDashboard}>
            <RefreshCw size={16} />
            Refresh
          </button>
        </div>
      </div>

      {/* Section 1: Funnel Visualization */}
      <div style={{ ...styles.section }}>
        <div style={styles.sectionTitle}>Funnel & Conversions</div>
        <FunnelVisualization funnel={data?.funnel} />
      </div>

      {/* Section 2: Velocity & Aging */}
      <div style={{ ...styles.section }}>
        <div style={styles.sectionTitle}>Velocity & Aging Indicators</div>
        <div style={{ ...styles.grid, ...styles.grid3 }}>
          <VelocityCard velocity={data?.velocity} />
          {role === "manager" && <RFQAgingCard aging={data?.rfq_aging} />}
        </div>
      </div>

      {/* Section 3: Revenue Reality */}
      <div style={{ ...styles.section }}>
        <div style={styles.sectionTitle}>Revenue Reality</div>
        <div style={{ ...styles.grid, ...styles.grid3 }}>
          <RevenueCard revenue={data?.revenue} role={role} />
          {role === "manager" && <ForecastCard forecast={data?.forecast_vs_actual} />}
        </div>
      </div>

      {/* Footer */}
      <div style={{ textAlign: "center", fontSize: "0.75rem", color: "#475569", marginTop: "1rem" }}>
        Last updated: {data?.generated_at ? new Date(data.generated_at).toLocaleString() : "—"}
      </div>
    </div>
  )
}
