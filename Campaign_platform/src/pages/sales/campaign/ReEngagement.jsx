"use client"

import { useState, useEffect } from "react"
import { useNavigate } from "react-router-dom"
import { Mail, Filter, AlertCircle, TrendingUp, Calendar, Send } from "lucide-react"
import "./ReEngagement.css"
import { API_BASE_URL } from "../../../config"
import { buildApiUrl } from "../../../config"

function ReEngagement() {
  const navigate = useNavigate()
  const [dormantLeads, setDormantLeads] = useState([])
  const [selectedLeads, setSelectedLeads] = useState([])
  const [selectedStrategy, setSelectedStrategy] = useState("soft_drip")
  const [loading, setLoading] = useState(true)
  const [creating, setCreating] = useState(false)
  const [phaseTemplates, setPhaseTemplates] = useState({
    phase1: "",
    phase2: "",
    phase3: ""
  })
  const [senderRotation, setSenderRotation] = useState(true)
  const [showSuccess, setShowSuccess] = useState(false)

  // Filters
  const [filters, setFilters] = useState({
    minEngagementScore: 0,
    maxDaysInactive: 90,
    industry: "all",
    company: "all"
  })

  const [showFilters, setShowFilters] = useState(false)

  // Fetch dormant leads
  useEffect(() => {
    const fetchDormantLeads = async () => {
      const sessionId = localStorage.getItem("session_id")
      if (!sessionId) {
        navigate("/login")
        return
      }

      try {
        setLoading(true)
        const params = new URLSearchParams({
          engagement_score_min: filters.minEngagementScore,
          days_inactive_max: filters.maxDaysInactive,
        })
        if (filters.industry !== "all") params.append("industry", filters.industry)
        if (filters.company !== "all") params.append("company", filters.company)

        const res = await fetch(buildApiUrl(`/leads/dormant?${params}`), {
          headers: {
            "Content-Type": "application/json",
            "Authorization": sessionId,
          },
        })

        if (res.status === 401) {
          alert("Session expired. Please login again.")
          localStorage.removeItem("session_id")
          navigate("/login")
          return
        }

        if (!res.ok) {
          // Fallback to mock data if endpoint not available
          setDormantLeads(generateMockDormantLeads())
        } else {
          const data = await res.json()
          setDormantLeads(data.leads || [])
        }
      } catch (err) {
        console.log("Using mock dormant leads data:", err.message)
        setDormantLeads(generateMockDormantLeads())
      } finally {
        setLoading(false)
      }
    }

    fetchDormantLeads()
  }, [navigate, filters])

  // Generate mock data for demonstration
  const generateMockDormantLeads = () => [
    {
      _id: "1",
      name: "John Smith",
      email: "john@company.com",
      company: "TechCorp Inc",
      engagement_score: 35,
      days_inactive: 62,
      last_contact: "2025-11-20",
      industry: "Technology",
      position: "Sales Manager"
    },
    {
      _id: "2",
      name: "Sarah Johnson",
      email: "sarah@enterprise.com",
      company: "Enterprise Solutions",
      engagement_score: 28,
      days_inactive: 85,
      last_contact: "2025-10-15",
      industry: "Consulting",
      position: "Director"
    },
    {
      _id: "3",
      name: "Michael Chen",
      email: "mchen@finance.com",
      company: "Finance Group",
      engagement_score: 42,
      days_inactive: 45,
      last_contact: "2025-12-05",
      industry: "Finance",
      position: "VP Operations"
    },
    {
      _id: "4",
      name: "Emma Wilson",
      email: "emma@retail.com",
      company: "Retail Plus",
      engagement_score: 31,
      days_inactive: 78,
      last_contact: "2025-10-28",
      industry: "Retail",
      position: "Marketing Lead"
    },
    {
      _id: "5",
      name: "David Lopez",
      email: "david@manufacturing.com",
      company: "Manufacturing Corp",
      engagement_score: 38,
      days_inactive: 55,
      last_contact: "2025-11-30",
      industry: "Manufacturing",
      position: "Procurement Manager"
    }
  ]

  const handleLeadSelection = (leadId) => {
    setSelectedLeads(prev =>
      prev.includes(leadId) ? prev.filter(id => id !== leadId) : [...prev, leadId]
    )
  }

  const handleSelectAll = () => {
    if (selectedLeads.length === dormantLeads.length) {
      setSelectedLeads([])
    } else {
      setSelectedLeads(dormantLeads.map(lead => lead._id))
    }
  }

  const handleCreateCampaign = async () => {
    if (selectedLeads.length === 0) {
      alert("Please select at least one lead")
      return
    }

    if (!phaseTemplates.phase1) {
      alert("Please assign a template for Phase 1")
      return
    }

    const sessionId = localStorage.getItem("session_id")
    if (!sessionId) {
      navigate("/login")
      return
    }

    try {
      setCreating(true)
      const res = await fetch(buildApiUrl("/campaigns/reengagement"), {
        method: "POST",
        headers: {
          "Content-Type": "application/json",
          "Authorization": sessionId,
        },
        body: JSON.stringify({
          leads: selectedLeads,
          strategy: selectedStrategy,
          templates: phaseTemplates,
          senderRotation: senderRotation,
          timeline: getTimeline()
        }),
      })

      if (res.status === 401) {
        alert("Session expired. Please login again.")
        localStorage.removeItem("session_id")
        navigate("/login")
        return
      }

      if (!res.ok) throw new Error("Failed to create campaign")

      const data = await res.json()
      setShowSuccess(true)
      setTimeout(() => {
        navigate("/admin/sales/campaign", { state: { campaignId: data.campaign_id } })
      }, 2000)
    } catch (err) {
      alert("Error creating campaign: " + err.message)
    } finally {
      setCreating(false)
    }
  }

  const getTimeline = () => {
    switch (selectedStrategy) {
      case "soft_drip":
        return { week_3_4: 21, month_2: 60, month_3_4: 90 }
      case "trigger_based":
        return { week_3_4: 14, month_2: 45, month_3_4: 75 }
      case "reset":
        return { week_3_4: 7, month_2: 30, month_3_4: 60 }
      default:
        return { week_3_4: 21, month_2: 60, month_3_4: 90 }
    }
  }

  const strategyDescriptions = {
    soft_drip: "Gentle, value-focused sequence with low-pressure messaging",
    trigger_based: "Event-driven outreach triggered by specific engagement signals",
    reset: "Fresh start approach with completely new messaging and positioning"
  }

  return (
    <div className="reengagement-container">
      {/* Header */}
      <div className="reengagement-header">
        <div>
          <h1>Re-engagement Campaigns</h1>
          <p>Identify and reactivate dormant leads with targeted strategies</p>
        </div>
        <div className="header-stats">
          <div className="stat-card">
            <div className="stat-label">Dormant Leads</div>
            <div className="stat-value">{dormantLeads.length}</div>
          </div>
          <div className="stat-card">
            <div className="stat-label">Selected</div>
            <div className="stat-value">{selectedLeads.length}</div>
          </div>
        </div>
      </div>

      {showSuccess && (
        <div className="success-banner">
          <span>✅ Campaign created successfully! Redirecting...</span>
        </div>
      )}

      {/* Strategy Selection */}
      <div className="strategy-section">
        <h2>1. Select Re-engagement Strategy</h2>
        <div className="strategy-grid">
          {[
            { id: "soft_drip", label: "Soft Drip", icon: "💧" },
            { id: "trigger_based", label: "Trigger-Based", icon: "⚡" },
            { id: "reset", label: "Reset", icon: "🔄" }
          ].map(strategy => (
            <div
              key={strategy.id}
              className={`strategy-card ${selectedStrategy === strategy.id ? "active" : ""}`}
              onClick={() => setSelectedStrategy(strategy.id)}
            >
              <div className="strategy-icon">{strategy.icon}</div>
              <h3>{strategy.label}</h3>
              <p>{strategyDescriptions[strategy.id]}</p>
              <div className="timeline-info">
                {strategy.id === "soft_drip" && "Week 3-4 → Month 2 → Month 3-4"}
                {strategy.id === "trigger_based" && "Week 2-3 → Month 1.5 → Month 2.5"}
                {strategy.id === "reset" && "Week 1-2 → Month 1 → Month 2"}
              </div>
            </div>
          ))}
        </div>
      </div>

      {/* Template Assignment */}
      <div className="templates-section">
        <h2>2. Assign Templates per Phase</h2>
        <div className="template-phases">
          <div className="phase-assignment">
            <label className="phase-label">
              <Calendar size={16} /> Week 3-4: Initial Re-engagement
            </label>
            <input
              type="text"
              placeholder="Select or enter template name"
              value={phaseTemplates.phase1}
              onChange={(e) => setPhaseTemplates({ ...phaseTemplates, phase1: e.target.value })}
              className="phase-input"
            />
          </div>
          <div className="phase-assignment">
            <label className="phase-label">
              <Calendar size={16} /> Month 2: Value Proposition
            </label>
            <input
              type="text"
              placeholder="Select or enter template name"
              value={phaseTemplates.phase2}
              onChange={(e) => setPhaseTemplates({ ...phaseTemplates, phase2: e.target.value })}
              className="phase-input"
            />
          </div>
          <div className="phase-assignment">
            <label className="phase-label">
              <Calendar size={16} /> Month 3-4: Final Call
            </label>
            <input
              type="text"
              placeholder="Select or enter template name"
              value={phaseTemplates.phase3}
              onChange={(e) => setPhaseTemplates({ ...phaseTemplates, phase3: e.target.value })}
              className="phase-input"
            />
          </div>
        </div>
      </div>

      {/* Sender Rotation */}
      <div className="sender-section">
        <h2>3. Configure Sender Rotation</h2>
        <div className="sender-toggle">
          <input
            type="checkbox"
            id="senderRotation"
            checked={senderRotation}
            onChange={(e) => setSenderRotation(e.target.checked)}
            className="toggle-input"
          />
          <label htmlFor="senderRotation">Enable sender rotation across phases</label>
          <p className="sender-help">Rotate between different sender addresses to improve deliverability and avoid spam filters</p>
        </div>
      </div>

      {/* Filters */}
      <div className="filters-section">
        <button className="filter-toggle" onClick={() => setShowFilters(!showFilters)}>
          <Filter size={16} /> Filters {showFilters ? "▼" : "▶"}
        </button>
        {showFilters && (
          <div className="filters-panel">
            <div className="filter-row">
              <label>Min Engagement Score</label>
              <input
                type="range"
                min="0"
                max="100"
                value={filters.minEngagementScore}
                onChange={(e) => setFilters({ ...filters, minEngagementScore: parseInt(e.target.value) })}
                className="range-input"
              />
              <span>{filters.minEngagementScore}</span>
            </div>
            <div className="filter-row">
              <label>Max Days Inactive</label>
              <input
                type="range"
                min="30"
                max="180"
                value={filters.maxDaysInactive}
                onChange={(e) => setFilters({ ...filters, maxDaysInactive: parseInt(e.target.value) })}
                className="range-input"
              />
              <span>{filters.maxDaysInactive} days</span>
            </div>
          </div>
        )}
      </div>

      {/* Dormant Leads Table */}
      <div className="leads-section">
        <h2>4. Select Leads to Re-engage</h2>
        {loading ? (
          <div className="loading-state">Loading dormant leads...</div>
        ) : dormantLeads.length === 0 ? (
          <div className="empty-state">
            <AlertCircle size={24} />
            <p>No dormant leads found matching your criteria</p>
          </div>
        ) : (
          <div className="leads-table-wrapper">
            <div className="leads-table-header">
              <label className="select-all-checkbox">
                <input
                  type="checkbox"
                  checked={selectedLeads.length === dormantLeads.length}
                  onChange={handleSelectAll}
                />
                <span>Select All ({selectedLeads.length}/{dormantLeads.length})</span>
              </label>
            </div>
            <table className="leads-table">
              <thead>
                <tr>
                  <th></th>
                  <th>Name</th>
                  <th>Email</th>
                  <th>Company</th>
                  <th>Position</th>
                  <th className="score-column">
                    <TrendingUp size={14} /> Score
                  </th>
                  <th className="inactive-column">
                    <Calendar size={14} /> Inactive
                  </th>
                  <th>Last Contact</th>
                </tr>
              </thead>
              <tbody>
                {dormantLeads.map(lead => (
                  <tr key={lead._id} className={selectedLeads.includes(lead._id) ? "selected" : ""}>
                    <td>
                      <input
                        type="checkbox"
                        checked={selectedLeads.includes(lead._id)}
                        onChange={() => handleLeadSelection(lead._id)}
                      />
                    </td>
                    <td className="name-cell">{lead.name}</td>
                    <td>{lead.email}</td>
                    <td>{lead.company}</td>
                    <td className="position-cell">{lead.position}</td>
                    <td className="score-cell">
                      <span className={`score-badge score-${Math.floor(lead.engagement_score / 25)}`}>
                        {lead.engagement_score}
                      </span>
                    </td>
                    <td className="inactive-cell">{lead.days_inactive}d</td>
                    <td className="date-cell">{new Date(lead.last_contact).toLocaleDateString()}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </div>

      {/* Create Campaign Button */}
      <div className="action-section">
        <button
          className="btn-create-campaign"
          onClick={handleCreateCampaign}
          disabled={creating || selectedLeads.length === 0}
        >
          {creating ? (
            <>
              <span className="spinner"></span> Creating Campaign...
            </>
          ) : (
            <>
              <Send size={18} /> Create Campaign ({selectedLeads.length} leads)
            </>
          )}
        </button>
        <p className="campaign-info">
          Campaign will be scheduled for {getTimeline().month_3_4} days with {phaseTemplates.phase1 ? "templates assigned" : "templates pending"}
        </p>
      </div>
    </div>
  )
}

export default ReEngagement
