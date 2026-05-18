/**
 * Deliverability Dashboard Page
 * Domain health, Gmail account pool, and reputation metrics
 */
"use client"

import { useState, useEffect } from "react"
import { useNavigate } from "react-router-dom"
import {
  CheckCircle,
  AlertCircle,
  TrendingUp,
  TrendingDown,
  Zap,
  Mail,
  BarChart3,
  RefreshCw,
  Settings,
  Shield,
} from "lucide-react"
import {
  LineChart,
  Line,
  AreaChart,
  Area,
  XAxis,
  YAxis,
  CartesianGrid,
  Tooltip,
  Legend,
  ResponsiveContainer,
} from "recharts"
import { buildApiUrl } from "../../../config"
import "./Deliverability.css"

function Deliverability() {
  const navigate = useNavigate()
  const [loading, setLoading] = useState(true)
  const [domains, setDomains] = useState([])
  const [gmailAccounts, setGmailAccounts] = useState([])
  const [reputationMetrics, setReputationMetrics] = useState([])
  const [domainAlerts, setDomainAlerts] = useState([])
  const [overallScore, setOverallScore] = useState(85)

  // Fetch deliverability data
  useEffect(() => {
    const fetchData = async () => {
      const sessionId = localStorage.getItem("session_id")
      if (!sessionId) {
        navigate("/login")
        return
      }

      try {
        setLoading(true)

        // Fetch all deliverability data
        const [domainsRes, accountsRes, metricsRes] = await Promise.all([
          fetch(buildApiUrl("/deliverability/domains"), {
            headers: { Authorization: sessionId },
          }),
          fetch(buildApiUrl("/deliverability/gmail-accounts"), {
            headers: { Authorization: sessionId },
          }),
          fetch(buildApiUrl("/deliverability/reputation-metrics"), {
            headers: { Authorization: sessionId },
          }),
        ])

        if (domainsRes.ok) {
          const domainsData = await domainsRes.json()
          setDomains(domainsData.domains || MOCK_DOMAINS)
        } else {
          setDomains(MOCK_DOMAINS)
        }

        if (accountsRes.ok) {
          const accountsData = await accountsRes.json()
          setGmailAccounts(accountsData.accounts || MOCK_GMAIL_ACCOUNTS)
        } else {
          setGmailAccounts(MOCK_GMAIL_ACCOUNTS)
        }

        if (metricsRes.ok) {
          const metricsData = await metricsRes.json()
          setReputationMetrics(metricsData.metrics || MOCK_REPUTATION_METRICS)
        } else {
          setReputationMetrics(MOCK_REPUTATION_METRICS)
        }

        // Calculate alerts
        const alerts = MOCK_DOMAINS
          .filter((d) => d.status === "degraded" || d.spf_status === "fail" || d.dkim_status === "fail")
          .map((d) => ({
            domain: d.domain,
            message: `Domain "${d.domain}" has degraded reputation (${d.score}/100)`,
            severity: "warning",
          }))
        setDomainAlerts(alerts)

        // Calculate overall score
        const avgScore =
          MOCK_DOMAINS.reduce((sum, d) => sum + d.score, 0) / Math.max(MOCK_DOMAINS.length, 1)
        setOverallScore(Math.round(avgScore))
      } catch (error) {
        console.error("Failed to fetch deliverability data:", error)
        // Use mock data on error
        setDomains(MOCK_DOMAINS)
        setGmailAccounts(MOCK_GMAIL_ACCOUNTS)
        setReputationMetrics(MOCK_REPUTATION_METRICS)
      } finally {
        setLoading(false)
      }
    }

    fetchData()
  }, [navigate])

  const getHealthGrade = (score) => {
    if (score >= 90) return { grade: "A", label: "Excellent" }
    if (score >= 80) return { grade: "B", label: "Good" }
    if (score >= 70) return { grade: "C", label: "Fair" }
    if (score >= 60) return { grade: "D", label: "Poor" }
    return { grade: "F", label: "Critical" }
  }

  const getGradeColor = (grade) => {
    const colors = {
      A: "#22c55e",
      B: "#3b82f6",
      C: "#eab308",
      D: "#f97316",
      F: "#ef4444",
    }
    return colors[grade] || "#6b7280"
  }

  const handleCheckDomain = (domain) => {
    // In a real app, this would trigger a domain check via API
    alert(`Checking domain: ${domain}`)
  }

  const handleWarmup = (domain) => {
    // In a real app, this would start a warmup campaign
    alert(`Starting warmup for domain: ${domain}`)
  }

  const handleConfigureDNS = (domain) => {
    // In a real app, this would open DNS configuration guide
    navigate(`/admin/settings/dns/${domain}`)
  }

  const healthGrade = getHealthGrade(overallScore)

  if (loading) {
    return (
      <div className="deliverability-page">
        <div className="loading-state">
          <RefreshCw className="spinner" />
          <p>Loading deliverability data...</p>
        </div>
      </div>
    )
  }

  return (
    <div className="deliverability-page">
      {/* Page Header */}
      <div className="page-header">
        <div className="header-left">
          <h1>Email Deliverability Dashboard</h1>
          <p className="subtitle">Monitor domain health, Gmail account pool, and sender reputation</p>
        </div>
        <div className="header-actions">
          <button className="btn btn-outline" onClick={() => window.location.reload()}>
            <RefreshCw size={16} /> Refresh
          </button>
        </div>
      </div>

      {/* Overall Health Score */}
      <div className="health-score-card">
        <div className="score-container">
          <div className="score-circle">
            <svg width="140" height="140" className="score-svg">
              <circle cx="70" cy="70" r="60" className="score-bg" />
              <circle
                cx="70"
                cy="70"
                r="60"
                className="score-progress"
                style={{
                  strokeDashoffset:
                    377 - (overallScore / 100) * 377,
                  stroke: getGradeColor(healthGrade.grade),
                }}
              />
            </svg>
            <div className="score-text">
              <div className="score-value">{overallScore}</div>
              <div className="score-label">Overall Score</div>
            </div>
          </div>

          <div className="grade-display">
            <div
              className="grade-badge"
              style={{ color: getGradeColor(healthGrade.grade) }}
            >
              {healthGrade.grade}
            </div>
            <div className="grade-label">{healthGrade.label}</div>
            <div className="grade-description">Sender reputation is strong</div>
          </div>
        </div>
      </div>

      {/* Alerts */}
      {domainAlerts.length > 0 && (
        <div className="alerts-section">
          {domainAlerts.map((alert, idx) => (
            <div key={idx} className={`alert alert-${alert.severity}`}>
              <AlertCircle size={16} />
              <div className="alert-content">
                <strong>{alert.domain}</strong>
                <p>{alert.message}</p>
              </div>
            </div>
          ))}
        </div>
      )}

      {/* Domain Health Cards */}
      <div className="section">
        <h2>Domain Health</h2>
        <div className="domains-grid">
          {domains.map((domain) => (
            <div key={domain.id} className={`domain-card status-${domain.status}`}>
              <div className="domain-header">
                <h3>{domain.domain}</h3>
                <span className={`domain-status ${domain.status}`}>
                  {domain.status === "healthy" && <CheckCircle size={16} />}
                  {domain.status === "degraded" && <AlertCircle size={16} />}
                  {domain.status === "healthy" ? "Healthy" : "Degraded"}
                </span>
              </div>

              <div className="domain-metrics">
                <div className="metric">
                  <div className="metric-label">SPF</div>
                  <div className={`metric-status ${domain.spf_status}`}>
                    {domain.spf_status === "pass" ? "✓" : "✗"}
                  </div>
                </div>
                <div className="metric">
                  <div className="metric-label">DKIM</div>
                  <div className={`metric-status ${domain.dkim_status}`}>
                    {domain.dkim_status === "pass" ? "✓" : "✗"}
                  </div>
                </div>
                <div className="metric">
                  <div className="metric-label">DMARC</div>
                  <div className={`metric-status ${domain.dmarc_status}`}>
                    {domain.dmarc_status === "pass" ? "✓" : "✗"}
                  </div>
                </div>
                <div className="metric">
                  <div className="metric-label">Score</div>
                  <div className="metric-value">{domain.score}/100</div>
                </div>
              </div>

              <div className="domain-score-bar">
                <div
                  className="score-bar-fill"
                  style={{
                    width: `${domain.score}%`,
                    backgroundColor:
                      domain.score >= 80
                        ? "#22c55e"
                        : domain.score >= 60
                          ? "#eab308"
                          : "#ef4444",
                  }}
                />
              </div>

              <div className="domain-actions">
                <button
                  className="action-btn small"
                  onClick={() => handleCheckDomain(domain.domain)}
                >
                  Check Domain
                </button>
                <button
                  className="action-btn small secondary"
                  onClick={() => handleConfigureDNS(domain.domain)}
                >
                  Configure DNS
                </button>
                <button
                  className="action-btn small secondary"
                  onClick={() => handleWarmup(domain.domain)}
                >
                  Start Warmup
                </button>
              </div>
            </div>
          ))}
        </div>
      </div>

      {/* Gmail Account Pool */}
      <div className="section">
        <h2>Gmail Account Pool</h2>
        <div className="accounts-grid">
          {gmailAccounts.map((account) => {
            const usagePercent = (account.emails_sent / account.daily_limit) * 100;
            const remaining = account.daily_limit - account.emails_sent;

            return (
              <div key={account.id} className="account-card">
                <div className="account-header">
                  <Mail size={16} />
                  <span className="account-email">{account.email}</span>
                  <span className={`account-status ${account.status}`}>
                    {account.status === "healthy" ? "●" : "⚠"}
                  </span>
                </div>

                <div className="account-usage">
                  <div className="usage-numbers">
                    <span className="usage-sent">{account.emails_sent}</span>
                    <span className="usage-slash">/</span>
                    <span className="usage-limit">{account.daily_limit}</span>
                  </div>
                  <span className="usage-label">emails sent today</span>
                </div>

                <div className="progress-bar">
                  <div
                    className="progress-fill"
                    style={{
                      width: `${Math.min(usagePercent, 100)}%`,
                      backgroundColor:
                        usagePercent > 80 ? "#ef4444" : usagePercent > 50 ? "#eab308" : "#22c55e",
                    }}
                  />
                </div>

                <div className="account-info">
                  <div className="info-item">
                    <span className="info-label">Remaining</span>
                    <span className="info-value">{remaining}</span>
                  </div>
                  <div className="info-item">
                    <span className="info-label">Warmup</span>
                    <span className="info-value">{account.warmup_status}</span>
                  </div>
                  <div className="info-item">
                    <span className="info-label">Health</span>
                    <span className={`health-badge ${account.status}`}>
                      {account.status === "healthy" ? "Good" : "At Risk"}
                    </span>
                  </div>
                </div>
              </div>
            );
          })}
        </div>
      </div>

      {/* Reputation Trend Charts */}
      <div className="section">
        <h2>Reputation Trends</h2>
        <div className="charts-grid">
          {/* Bounce Rate Chart */}
          <div className="chart-card">
            <h3>Bounce Rate (%)</h3>
            <ResponsiveContainer width="100%" height={250}>
              <AreaChart data={reputationMetrics}>
                <defs>
                  <linearGradient id="bounceGradient" x1="0" y1="0" x2="0" y2="1">
                    <stop offset="5%" stopColor="#ef4444" stopOpacity={0.3} />
                    <stop offset="95%" stopColor="#ef4444" stopOpacity={0} />
                  </linearGradient>
                </defs>
                <CartesianGrid strokeDasharray="3 3" stroke="#e5e7eb" />
                <XAxis dataKey="date" stroke="#6b7280" />
                <YAxis stroke="#6b7280" />
                <Tooltip
                  contentStyle={{
                    backgroundColor: "#ffffff",
                    border: "1px solid #e5e7eb",
                    borderRadius: "6px",
                  }}
                />
                <Area
                  type="monotone"
                  dataKey="bounce_rate"
                  stroke="#ef4444"
                  fillOpacity={1}
                  fill="url(#bounceGradient)"
                />
              </AreaChart>
            </ResponsiveContainer>
          </div>

          {/* Open Rate Chart */}
          <div className="chart-card">
            <h3>Open Rate (%)</h3>
            <ResponsiveContainer width="100%" height={250}>
              <LineChart data={reputationMetrics}>
                <CartesianGrid strokeDasharray="3 3" stroke="#e5e7eb" />
                <XAxis dataKey="date" stroke="#6b7280" />
                <YAxis stroke="#6b7280" />
                <Tooltip
                  contentStyle={{
                    backgroundColor: "#ffffff",
                    border: "1px solid #e5e7eb",
                    borderRadius: "6px",
                  }}
                />
                <Line
                  type="monotone"
                  dataKey="open_rate"
                  stroke="#3b82f6"
                  strokeWidth={2}
                  dot={false}
                />
              </LineChart>
            </ResponsiveContainer>
          </div>

          {/* Complaint Rate Chart */}
          <div className="chart-card">
            <h3>Complaint Rate (%)</h3>
            <ResponsiveContainer width="100%" height={250}>
              <LineChart data={reputationMetrics}>
                <CartesianGrid strokeDasharray="3 3" stroke="#e5e7eb" />
                <XAxis dataKey="date" stroke="#6b7280" />
                <YAxis stroke="#6b7280" />
                <Tooltip
                  contentStyle={{
                    backgroundColor: "#ffffff",
                    border: "1px solid #e5e7eb",
                    borderRadius: "6px",
                  }}
                />
                <Line
                  type="monotone"
                  dataKey="complaint_rate"
                  stroke="#f97316"
                  strokeWidth={2}
                  dot={false}
                />
              </LineChart>
            </ResponsiveContainer>
          </div>

          {/* Click Rate Chart */}
          <div className="chart-card">
            <h3>Click Rate (%)</h3>
            <ResponsiveContainer width="100%" height={250}>
              <LineChart data={reputationMetrics}>
                <CartesianGrid strokeDasharray="3 3" stroke="#e5e7eb" />
                <XAxis dataKey="date" stroke="#6b7280" />
                <YAxis stroke="#6b7280" />
                <Tooltip
                  contentStyle={{
                    backgroundColor: "#ffffff",
                    border: "1px solid #e5e7eb",
                    borderRadius: "6px",
                  }}
                />
                <Line
                  type="monotone"
                  dataKey="click_rate"
                  stroke="#22c55e"
                  strokeWidth={2}
                  dot={false}
                />
              </LineChart>
            </ResponsiveContainer>
          </div>
        </div>
      </div>
    </div>
  )
}

// Mock data for development
const MOCK_DOMAINS = [
  {
    id: 1,
    domain: "mail.example.com",
    spf_status: "pass",
    dkim_status: "pass",
    dmarc_status: "pass",
    score: 95,
    status: "healthy",
  },
  {
    id: 2,
    domain: "campaigns.example.com",
    spf_status: "pass",
    dkim_status: "pass",
    dmarc_status: "fail",
    score: 72,
    status: "degraded",
  },
  {
    id: 3,
    domain: "newsletter.example.com",
    spf_status: "pass",
    dkim_status: "fail",
    dmarc_status: "pass",
    score: 65,
    status: "degraded",
  },
]

const MOCK_GMAIL_ACCOUNTS = [
  {
    id: 1,
    email: "sales1@gmail.com",
    daily_limit: 2000,
    emails_sent: 1245,
    status: "healthy",
    warmup_status: "Complete",
  },
  {
    id: 2,
    email: "sales2@gmail.com",
    daily_limit: 2000,
    emails_sent: 1680,
    status: "healthy",
    warmup_status: "Complete",
  },
  {
    id: 3,
    email: "sales3@gmail.com",
    daily_limit: 2000,
    emails_sent: 450,
    status: "healthy",
    warmup_status: "In Progress",
  },
  {
    id: 4,
    email: "sales4@gmail.com",
    daily_limit: 2000,
    emails_sent: 1920,
    status: "at_risk",
    warmup_status: "Complete",
  },
]

const MOCK_REPUTATION_METRICS = [
  { date: "Jan 20", bounce_rate: 2.1, open_rate: 28.5, complaint_rate: 0.2, click_rate: 4.2 },
  { date: "Jan 21", bounce_rate: 1.9, open_rate: 29.1, complaint_rate: 0.15, click_rate: 4.5 },
  { date: "Jan 22", bounce_rate: 2.3, open_rate: 27.8, complaint_rate: 0.25, click_rate: 3.9 },
  { date: "Jan 23", bounce_rate: 1.8, open_rate: 30.2, complaint_rate: 0.1, click_rate: 4.8 },
  { date: "Jan 24", bounce_rate: 2.0, open_rate: 31.5, complaint_rate: 0.18, click_rate: 5.1 },
  { date: "Jan 25", bounce_rate: 1.7, open_rate: 32.1, complaint_rate: 0.12, click_rate: 5.3 },
  { date: "Jan 26", bounce_rate: 1.9, open_rate: 33.2, complaint_rate: 0.16, click_rate: 5.6 },
]

export default Deliverability
