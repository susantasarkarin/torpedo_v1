"use client"

import { useState, useEffect, useCallback } from "react"
import { API_BASE_URL, buildApiUrl } from "../../config"
import {
  TrendingUp,
  Target,
  Clock,
  AlertTriangle,
  CheckCircle,
  XCircle,
  DollarSign,
  ArrowDown,
  RefreshCw,
  Calendar,
  BarChart3
} from "lucide-react"
import { formatDateTime } from "../../utils/format"
import { formatMoney } from "../../utils/currency"
import { authFetch } from "../../utils/api"

// ============== COMPACT STYLES ==============
const styles = {
  page: {
    height: "100vh",
    backgroundColor: "#f8fafc",
    padding: "16px",
    overflow: "hidden",
    display: "flex",
    flexDirection: "column"
  },
  header: {
    display: "flex",
    alignItems: "center",
    justifyContent: "space-between",
    marginBottom: "12px",
    flexShrink: 0
  },
  title: {
    fontSize: "20px",
    fontWeight: "700",
    color: "#1a1a1a",
    margin: 0
  },
  subtitle: {
    fontSize: "14px",
    color: "#4b5563",
    marginTop: "2px"
  },
  controls: {
    display: "flex",
    alignItems: "center",
    gap: "8px"
  },
  dateContainer: {
    display: "flex",
    alignItems: "center",
    gap: "6px",
    backgroundColor: "white",
    borderRadius: "6px",
    border: "1px solid #e2e8f0",
    padding: "6px 10px"
  },
  dateInput: {
    border: "none",
    fontSize: "14px",
    color: "#475569",
    outline: "none",
    backgroundColor: "transparent",
    width: "100px"
  },
  select: {
    padding: "6px 12px",
    backgroundColor: "white",
    border: "1px solid #e2e8f0",
    borderRadius: "6px",
    fontSize: "14px",
    color: "#475569",
    cursor: "pointer",
    outline: "none"
  },
  targetInput: {
    width: "80px",
    padding: "6px 10px",
    backgroundColor: "white",
    border: "1px solid #e2e8f0",
    borderRadius: "6px",
    fontSize: "14px",
    color: "#475569",
    outline: "none"
  },
  refreshBtn: {
    display: "inline-flex",
    alignItems: "center",
    gap: "6px",
    padding: "6px 12px",
    backgroundColor: "#f97316",
    color: "white",
    border: "none",
    borderRadius: "6px",
    fontSize: "14px",
    fontWeight: "500",
    cursor: "pointer"
  },
  mainLayout: {
    display: "grid",
    gridTemplateColumns: "320px 1fr",
    gap: "16px",
    flex: 1,
    minHeight: 0
  },
  leftPanel: {
    display: "flex",
    flexDirection: "column",
    gap: "12px"
  },
  rightPanel: {
    display: "flex",
    flexDirection: "column",
    gap: "12px",
    overflow: "auto"
  },
  card: {
    backgroundColor: "white",
    borderRadius: "10px",
    border: "1px solid #e2e8f0",
    boxShadow: "0 1px 2px rgba(0,0,0,0.04)"
  },
  cardHeader: {
    padding: "10px 14px",
    borderBottom: "1px solid #f1f5f9",
    display: "flex",
    alignItems: "center",
    justifyContent: "space-between"
  },
  cardTitle: {
    display: "flex",
    alignItems: "center",
    gap: "6px",
    fontSize: "14px",
    fontWeight: "600",
    color: "#1a1a1a",
    margin: 0
  },
  cardContent: {
    padding: "12px"
  },
  // Compact KPIs
  kpiRow: {
    display: "grid",
    gridTemplateColumns: "repeat(4, 1fr)",
    gap: "10px"
  },
  kpiCard: {
    backgroundColor: "white",
    borderRadius: "8px",
    border: "1px solid #e2e8f0",
    padding: "12px"
  },
  kpiLabel: {
    fontSize: "14px",
    fontWeight: "500",
    color: "#4b5563",
    margin: 0
  },
  kpiValue: {
    fontSize: "20px",
    fontWeight: "700",
    color: "#1a1a1a",
    marginTop: "4px"
  },
  kpiSubtitle: {
    fontSize: "14px",
    color: "#6b6b6b",
    marginTop: "2px"
  },
  kpiIcon: {
    padding: "8px",
    borderRadius: "6px",
    backgroundColor: "#fff7ed"
  },
  // Compact Funnel
  funnelStage: {
    display: "flex",
    alignItems: "center",
    justifyContent: "space-between",
    padding: "8px 12px",
    borderRadius: "6px",
    color: "white",
    marginBottom: "2px"
  },
  funnelStageName: {
    fontWeight: "600",
    fontSize: "14px"
  },
  funnelStageCount: {
    fontSize: "14px",
    opacity: 0.9
  },
  funnelStageValue: {
    fontSize: "16px",
    fontWeight: "700"
  },
  conversionArrow: {
    display: "flex",
    alignItems: "center",
    justifyContent: "center",
    padding: "2px 0"
  },
  conversionBadge: {
    display: "inline-flex",
    alignItems: "center",
    gap: "4px",
    padding: "2px 8px",
    borderRadius: "999px",
    fontSize: "14px",
    fontWeight: "500"
  },
  // Velocity
  velocityGrid: {
    display: "grid",
    gridTemplateColumns: "repeat(3, 1fr)",
    gap: "8px"
  },
  velocityCard: {
    padding: "10px",
    borderRadius: "6px",
    border: "1px solid #e2e8f0"
  },
  velocityName: {
    fontSize: "14px",
    fontWeight: "500",
    color: "#475569"
  },
  velocityValue: {
    fontSize: "18px",
    fontWeight: "700",
    color: "#1a1a1a",
    marginTop: "2px"
  },
  velocityTarget: {
    fontSize: "14px",
    color: "#6b6b6b"
  },
  badge: {
    padding: "1px 6px",
    borderRadius: "999px",
    fontSize: "14px",
    fontWeight: "600",
    textTransform: "uppercase"
  },
  // Aging
  agingGrid: {
    display: "grid",
    gridTemplateColumns: "repeat(3, 1fr)",
    gap: "8px"
  },
  agingCard: {
    padding: "10px",
    borderRadius: "6px",
    textAlign: "center"
  },
  agingLabel: {
    fontSize: "14px",
    fontWeight: "500"
  },
  agingValue: {
    fontSize: "22px",
    fontWeight: "700",
    marginTop: "2px"
  },
  agingAmount: {
    fontSize: "14px",
    color: "#4b5563"
  },
  // Forecast
  forecastRow: {
    display: "grid",
    gridTemplateColumns: "repeat(4, 1fr)",
    gap: "8px"
  },
  forecastCard: {
    padding: "10px",
    borderRadius: "6px",
    textAlign: "center"
  },
  forecastLabel: {
    fontSize: "14px",
    color: "#4b5563",
    textTransform: "uppercase"
  },
  forecastValue: {
    fontSize: "16px",
    fontWeight: "700",
    marginTop: "2px"
  },
  progressBar: {
    height: "8px",
    backgroundColor: "#f1f5f9",
    borderRadius: "4px",
    overflow: "hidden",
    marginBottom: "10px"
  },
  progressFill: {
    height: "100%",
    borderRadius: "4px"
  },
  loading: {
    display: "flex",
    alignItems: "center",
    justifyContent: "center",
    height: "100%"
  },
  errorCard: {
    maxWidth: "400px",
    margin: "auto",
    padding: "24px",
    textAlign: "center"
  },
  footer: {
    textAlign: "center",
    fontSize: "14px",
    color: "#6b6b6b",
    marginTop: "8px",
    flexShrink: 0
  }
}

// ============== HELPERS ==============
const formatCurrency = (amount) => formatMoney(amount || 0, "USD")

const formatPercent = (value) => `${(value || 0).toFixed(1)}%`

const funnelColors = ["#e8890b", "#e8890b", "#8b5cf6", "#d946ef", "#22c55e"]

// ============== COMPONENTS ==============

function KPICard({ title, value, subtitle, icon: Icon, alert }) {
  const alertBorder = alert === "critical" ? "2px solid #ef4444" : alert === "warning" ? "2px solid #fbbf24" : "1px solid #e2e8f0"
  const iconBg = alert === "critical" ? "#fee2e2" : alert === "warning" ? "#fef3c7" : "#fff7ed"
  const iconColor = alert === "critical" ? "#dc2626" : alert === "warning" ? "#d97706" : "#ea580c"

  return (
    <div style={{ ...styles.kpiCard, border: alertBorder }}>
      <div style={{ display: "flex", justifyContent: "space-between", alignItems: "flex-start" }}>
        <div>
          <p style={styles.kpiLabel}>{title}</p>
          <div style={styles.kpiValue}>{value}</div>
          {subtitle && <div style={styles.kpiSubtitle}>{subtitle}</div>}
        </div>
        {Icon && (
          <div style={{ ...styles.kpiIcon, backgroundColor: iconBg }}>
            <Icon size={16} style={{ color: iconColor }} />
          </div>
        )}
      </div>
    </div>
  )
}

function CompactFunnel({ funnel }) {
  if (!funnel) return null

  return (
    <div style={styles.card}>
      <div style={styles.cardHeader}>
        <h3 style={styles.cardTitle}>
          <Target size={14} style={{ color: "#c2410c" }} />
          Sales Funnel
        </h3>
        <span style={{ fontSize: "14px", color: "#4b5563" }}>
          E2E: <strong style={{ color: funnel.end_to_end_rate > 1 ? "#16a34a" : "#dc2626" }}>
            {formatPercent(funnel.end_to_end_rate)}
          </strong>
        </span>
      </div>
      <div style={styles.cardContent}>
        {funnel.stages.map((stage, idx) => {
          const conversion = funnel.conversions[idx]
          const isWorst = conversion?.is_worst_dropoff
          const widthPercent = 100 - (idx * 10)

          return (
            <div key={stage.name}>
              <div
                style={{
                  ...styles.funnelStage,
                  backgroundColor: funnelColors[idx],
                  width: `${widthPercent}%`,
                  marginLeft: "auto",
                  marginRight: "auto"
                }}
              >
                <div>
                  <div style={styles.funnelStageName}>{stage.name}</div>
                  <div style={styles.funnelStageCount}>{stage.count.toLocaleString()} leads</div>
                </div>
                <div style={styles.funnelStageValue}>{stage.count.toLocaleString()}</div>
              </div>
              {conversion && (
                <div style={styles.conversionArrow}>
                  <div style={{
                    ...styles.conversionBadge,
                    backgroundColor: isWorst ? "#fee2e2" : "#f1f5f9",
                    color: isWorst ? "#dc2626" : "#475569"
                  }}>
                    <ArrowDown size={10} />
                    <span>{formatPercent(conversion.rate)}</span>
                    {isWorst && <AlertTriangle size={10} />}
                  </div>
                </div>
              )}
            </div>
          )
        })}
      </div>
    </div>
  )
}

function VelocitySection({ velocity }) {
  if (!velocity || velocity.length === 0) return null

  return (
    <div style={styles.card}>
      <div style={styles.cardHeader}>
        <h3 style={styles.cardTitle}>
          <Clock size={14} style={{ color: "#c2410c" }} />
          Velocity
        </h3>
      </div>
      <div style={styles.cardContent}>
        <div style={styles.velocityGrid}>
          {velocity.map((v, idx) => {
            const isAlert = v.alert_level !== "normal"
            return (
              <div key={idx} style={{
                ...styles.velocityCard,
                backgroundColor: v.alert_level === "critical" ? "#fee2e2" : v.alert_level === "warning" ? "#fef3c7" : "white"
              }}>
                <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center" }}>
                  <span style={styles.velocityName}>{v.name}</span>
                  {isAlert && (
                    <span style={{
                      ...styles.badge,
                      backgroundColor: v.alert_level === "critical" ? "#dc2626" : "#d97706",
                      color: "white"
                    }}>{v.alert_level}</span>
                  )}
                </div>
                <div style={styles.velocityValue}>
                  {v.value_hours != null ? `${v.value_hours}h` : v.value_days != null ? `${v.value_days}d` : "—"}
                </div>
                <div style={styles.velocityTarget}>
                  Target: {v.threshold_hours ? `<${v.threshold_hours}h` : v.threshold_days ? `<${v.threshold_days}d` : "—"}
                </div>
              </div>
            )
          })}
        </div>
      </div>
    </div>
  )
}

function RFQAgingSection({ aging }) {
  if (!aging || aging.length === 0) return null
  const totalCount = aging.reduce((sum, b) => sum + b.count, 0)

  return (
    <div style={styles.card}>
      <div style={styles.cardHeader}>
        <h3 style={styles.cardTitle}>
          <AlertTriangle size={14} style={{ color: "#c2410c" }} />
          RFQ Aging
        </h3>
        <span style={{ fontSize: "14px", color: "#4b5563" }}>{totalCount} open</span>
      </div>
      <div style={styles.cardContent}>
        <div style={styles.agingGrid}>
          {aging.map((bucket, idx) => {
            const isRisk = bucket.bucket === "60+"
            return (
              <div key={idx} style={{
                ...styles.agingCard,
                backgroundColor: isRisk ? "#fee2e2" : "#f8fafc"
              }}>
                <div style={{ ...styles.agingLabel, color: isRisk ? "#dc2626" : "#475569" }}>
                  {bucket.bucket}d
                </div>
                <div style={{ ...styles.agingValue, color: isRisk ? "#dc2626" : "#1a1a1a" }}>
                  {bucket.count}
                </div>
                <div style={styles.agingAmount}>{formatCurrency(bucket.total_value)}</div>
              </div>
            )
          })}
        </div>
      </div>
    </div>
  )
}

function ForecastSection({ forecast }) {
  if (!forecast) return null
  const progressPercent = Math.min((forecast.actual / forecast.target) * 100, 100)
  const isOnTrack = forecast.total_projected >= forecast.target

  return (
    <div style={styles.card}>
      <div style={styles.cardHeader}>
        <h3 style={styles.cardTitle}>
          <BarChart3 size={14} style={{ color: "#c2410c" }} />
          Forecast vs Actual
        </h3>
        <span style={{
          ...styles.badge,
          backgroundColor: isOnTrack ? "#dcfce7" : "#fee2e2",
          color: isOnTrack ? "#16a34a" : "#dc2626",
          padding: "2px 8px"
        }}>
          {isOnTrack ? "On Track" : "At Risk"}
        </span>
      </div>
      <div style={styles.cardContent}>
        <div style={{ display: "flex", justifyContent: "space-between", marginBottom: "4px", fontSize: "14px" }}>
          <span style={{ color: "#475569" }}>Attainment</span>
          <span style={{ fontWeight: "600", color: "#1a1a1a" }}>{formatPercent(forecast.attainment_percent)}</span>
        </div>
        <div style={styles.progressBar}>
          <div style={{
            ...styles.progressFill,
            width: `${progressPercent}%`,
            backgroundColor: progressPercent >= 100 ? "#22c55e" : progressPercent >= 70 ? "#eab308" : "#ef4444"
          }} />
        </div>
        <div style={styles.forecastRow}>
          <div style={{ ...styles.forecastCard, backgroundColor: "#f8fafc" }}>
            <div style={styles.forecastLabel}>Target</div>
            <div style={{ ...styles.forecastValue, color: "#1a1a1a" }}>{formatCurrency(forecast.target)}</div>
          </div>
          <div style={{ ...styles.forecastCard, backgroundColor: "#dcfce7" }}>
            <div style={styles.forecastLabel}>Actual</div>
            <div style={{ ...styles.forecastValue, color: "#16a34a" }}>{formatCurrency(forecast.actual)}</div>
          </div>
          <div style={{ ...styles.forecastCard, backgroundColor: "#fff7ed" }}>
            <div style={styles.forecastLabel}>Forecast</div>
            <div style={{ ...styles.forecastValue, color: "#a25e07" }}>{formatCurrency(forecast.forecast)}</div>
          </div>
          <div style={{ ...styles.forecastCard, backgroundColor: forecast.gap_to_target > 0 ? "#fee2e2" : "#dcfce7" }}>
            <div style={styles.forecastLabel}>Gap</div>
            <div style={{ ...styles.forecastValue, color: forecast.gap_to_target > 0 ? "#dc2626" : "#16a34a" }}>
              {formatCurrency(Math.abs(forecast.gap_to_target))}
            </div>
          </div>
        </div>
      </div>
    </div>
  )
}

// ============== MAIN COMPONENT ==============
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
      const response = await authFetch(buildApiUrl(`/sales/dashboard?${params}`))
      if (!response.ok) throw new Error(`HTTP ${response.status}`)
      setData(await response.json())
    } catch (err) {
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
      <div style={styles.page}>
        <div style={styles.loading}>
          <RefreshCw size={20} style={{ color: "#c2410c" }} />
          <span style={{ marginLeft: "8px", color: "#4b5563", fontSize: "14px" }}>Loading…</span>
        </div>
      </div>
    )
  }

  if (error) {
    return (
      <div style={styles.page}>
        <div style={{ ...styles.card, ...styles.errorCard }}>
          <XCircle size={40} style={{ color: "#ef4444", marginBottom: "12px" }} />
          <h3 style={{ color: "#1a1a1a", marginBottom: "8px", fontSize: "16px" }}>Failed to load</h3>
          <p style={{ color: "#4b5563", marginBottom: "12px", fontSize: "14px" }}>{error}</p>
          <button style={styles.refreshBtn} onClick={fetchDashboard}>
            <RefreshCw size={14} /> Retry
          </button>
        </div>
      </div>
    )
  }

  const winRate = data?.revenue?.find(r => r.name === "Win Rate")
  const avgDealSize = data?.revenue?.find(r => r.name === "Average Deal Size")
  const wonValue = data?.revenue?.find(r => r.name === "Won Deals Value")
  const pipelineValue = data?.revenue?.find(r => r.name === "Open Pipeline Value")
  const pipelineCoverage = data?.revenue?.find(r => r.name === "Pipeline Coverage Ratio")

  return (
    <div style={styles.page}>
      {/* Header */}
      <div style={styles.header}>
        <div>
          <h1 className="cx-page-title" style={styles.title}>Sales Dashboard</h1>
          <p style={styles.subtitle}>
            {role === "manager" ? "Manager View" : "Rep View"} • Conversion KPIs
          </p>
        </div>
        <div style={styles.controls}>
          <div style={styles.dateContainer}>
            <Calendar size={12} style={{ color: "#6b6b6b" }} />
            <input
              type="date"
              value={dateRange.start_date}
              onChange={(e) => setDateRange(prev => ({ ...prev, start_date: e.target.value }))}
              style={styles.dateInput}
            />
            <span style={{ color: "#6b6b6b", fontSize: "14px" }}>to</span>
            <input
              type="date"
              value={dateRange.end_date}
              onChange={(e) => setDateRange(prev => ({ ...prev, end_date: e.target.value }))}
              style={styles.dateInput}
            />
          </div>
          <select value={role} onChange={(e) => setRole(e.target.value)} style={styles.select}>
            <option value="rep">Rep</option>
            <option value="manager">Manager</option>
          </select>
          {role === "manager" && (
            <input
              type="number"
              value={target}
              onChange={(e) => setTarget(Number(e.target.value))}
              style={styles.targetInput}
            />
          )}
          <button style={styles.refreshBtn} onClick={fetchDashboard}>
            <RefreshCw size={12} /> Refresh
          </button>
        </div>
      </div>

      {/* Main Layout: Funnel Left, Everything Else Right */}
      <div style={styles.mainLayout}>
        {/* Left: Compact Funnel */}
        <div style={styles.leftPanel}>
          <CompactFunnel funnel={data?.funnel} />
        </div>

        {/* Right: KPIs + Velocity + Aging + Forecast */}
        <div style={styles.rightPanel}>
          {/* KPI Row */}
          <div style={styles.kpiRow}>
            <KPICard
              title="Win Rate"
              value={formatPercent(winRate?.value)}
              subtitle={`Target: ${formatPercent(winRate?.target)}`}
              icon={CheckCircle}
              alert={winRate?.value < 20 ? "critical" : winRate?.value < 30 ? "warning" : null}
            />
            <KPICard title="Avg Deal" value={formatCurrency(avgDealSize?.value)} icon={DollarSign} />
            <KPICard title="Won Revenue" value={formatCurrency(wonValue?.value)} icon={TrendingUp} />
            <KPICard
              title="Pipeline"
              value={formatCurrency(pipelineValue?.value)}
              subtitle={role === "manager" && pipelineCoverage ? `${pipelineCoverage.value}x coverage` : null}
              icon={Target}
              alert={pipelineCoverage?.alert_level}
            />
          </div>

          {/* Velocity + Aging Row */}
          <div style={{ display: "grid", gridTemplateColumns: role === "manager" ? "1fr 1fr" : "1fr", gap: "12px" }}>
            <VelocitySection velocity={data?.velocity} />
            {role === "manager" && <RFQAgingSection aging={data?.rfq_aging} />}
          </div>

          {/* Forecast (Manager only) */}
          {role === "manager" && data?.forecast_vs_actual && (
            <ForecastSection forecast={data?.forecast_vs_actual} />
          )}
        </div>
      </div>

      {/* Footer */}
      <div style={styles.footer}>
        Updated: {data?.generated_at ? formatDateTime(data.generated_at) : "—"}
      </div>
    </div>
  )
}
