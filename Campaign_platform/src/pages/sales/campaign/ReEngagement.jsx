"use client"

import { useLocation, useNavigate } from "react-router-dom"
import { useState, useEffect } from "react"
import "./ReEngagement.css"
import { buildApiUrl } from "../../../config"

function ReEngagement() {
  const navigate = useNavigate()
  const location = useLocation()
  const { selectedTemplate } = location.state || {}

  // State management
  const [dormantLeads, setDormantLeads] = useState([])
  const [selectedLeads, setSelectedLeads] = useState(new Set())
  const [selectedStrategy, setSelectedStrategy] = useState("soft_drip")
  const [loading, setLoading] = useState(false)
  const [creating, setCreating] = useState(false)
  const [filters, setFilters] = useState({
    search: "",
    inactiveDays: 30,
    stage: "all",
  })
  const [templatesByPhase, setTemplatesByPhase] = useState({
    phase1: null,
    phase2: null,
    phase3: null,
  })
  const [senderRotation, setSenderRotation] = useState(true)
  const [timelineConfig, setTimelineConfig] = useState({
    week3: 21,
    month2: 60,
    month3: 90,
  })

  // Strategy descriptions
  const strategies = {
    soft_drip: "Gentle re-engagement with spaced emails over 3-4 months",
    trigger_based: "Automated emails triggered by specific user behaviors",
    reset: "Complete reset with fresh intro sequence after 2 weeks",
  }

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
        const res = await fetch(
          buildApiUrl(
            `/leads/dormant?days=${filters.inactiveDays}&stage=${filters.stage}`
          ),
          {
            headers: {
              "Content-Type": "application/json",
              Authorization: sessionId,
            },
          }
        )

        if (res.status === 401) {
          alert("Session expired. Please login again.")
          localStorage.removeItem("session_id")
          navigate("/login")
          return
        }

        if (!res.ok) throw new Error(`HTTP ${res.status}: ${res.statusText}`)
        const data = await res.json()
        setDormantLeads(data.leads || [])
      } catch (err) {
        console.error("❌ Fetch dormant leads failed:", err)
      } finally {
        setLoading(false)
      }
    }

    fetchDormantLeads()
  }, [filters.inactiveDays, filters.stage, navigate])

  // Handle lead selection
  const toggleLeadSelection = (leadId) => {
    const newSelected = new Set(selectedLeads)
    if (newSelected.has(leadId)) {
      newSelected.delete(leadId)
    } else {
      newSelected.add(leadId)
    }
    setSelectedLeads(newSelected)
  }

  const toggleAllLeads = () => {
    if (selectedLeads.size === dormantLeads.length) {
      setSelectedLeads(new Set())
    } else {
      setSelectedLeads(new Set(dormantLeads.map((l) => l._id)))
    }
  }

  // Handle create campaign
  const handleCreateCampaign = async () => {
    if (selectedLeads.size === 0) {
      alert("Please select at least one lead")
      return
    }

    if (!templatesByPhase.phase1) {
      alert("Please assign a template for Phase 1 (Week 3-4)")
      return
    }

    const sessionId = localStorage.getItem("session_id")
    if (!sessionId) {
      navigate("/login")
      return
    }

    try {
      setCreating(true)
      const res = await fetch(buildApiUrl(`/campaigns/reengagement`), {
        method: "POST",
        headers: {
          "Content-Type": "application/json",
          Authorization: sessionId,
        },
        body: JSON.stringify({
          lead_ids: Array.from(selectedLeads),
          strategy: selectedStrategy,
          templates: templatesByPhase,
          sender_rotation: senderRotation,
          timeline: timelineConfig,
        }),
      })

      if (res.status === 401) {
        alert("Session expired. Please login again.")
        localStorage.removeItem("session_id")
        navigate("/login")
        return
      }

      const data = await res.json()
      if (!res.ok) throw new Error(data.detail || "Failed to create campaign")

      alert(`✅ Re-engagement campaign created for ${selectedLeads.size} leads`)
      setSelectedLeads(new Set())
      setTemplatesByPhase({ phase1: null, phase2: null, phase3: null })
    } catch (err) {
      console.error("❌ Create campaign failed:", err)
      alert("Error creating campaign: " + err.message)
    } finally {
      setCreating(false)
    }
  }

  // Filter dormant leads based on search
  const filteredLeads = dormantLeads.filter((lead) => {
    const searchLower = filters.search.toLowerCase()
    return (
      lead.name?.toLowerCase().includes(searchLower) ||
      lead.email?.toLowerCase().includes(searchLower) ||
      lead.company_name?.toLowerCase().includes(searchLower)
    )
  })

  return (
    <div className="re-container">
      <div className="re-header">
        <h1 className="re-title">Re-engagement Campaigns</h1>
        <p className="re-subtitle">
          Reactivate dormant leads with targeted campaigns
        </p>
      </div>

      <div className="re-layout">
        {/* Left Panel: Dormant Leads List */}
        <div className="re-panel re-leads-panel">
          <div className="re-panel-header">
            <h2 className="re-panel-title">Dormant Leads</h2>
            <span className="re-badge">
              {selectedLeads.size} / {filteredLeads.length}
            </span>
          </div>

          {/* Filters */}
          <div className="re-filters">
            <input
              type="text"
              placeholder="Search leads..."
              className="re-input"
              value={filters.search}
              onChange={(e) =>
                setFilters({ ...filters, search: e.target.value })
              }
            />
            <select
              className="re-select"
              value={filters.inactiveDays}
              onChange={(e) =>
                setFilters({ ...filters, inactiveDays: parseInt(e.target.value) })
              }
            >
              <option value={7}>Last 7 days</option>
              <option value={30}>Last 30 days</option>
              <option value={60}>Last 60 days</option>
              <option value={90}>Last 90 days</option>
            </select>
          </div>

          {/* Leads List */}
          <div className="re-leads-list">
            {loading ? (
              <div className="re-loading">Loading dormant leads...</div>
            ) : filteredLeads.length === 0 ? (
              <div className="re-empty">No dormant leads found</div>
            ) : (
              <>
                <div className="re-leads-header">
                  <label className="re-checkbox-label">
                    <input
                      type="checkbox"
                      checked={
                        selectedLeads.size === dormantLeads.length &&
                        dormantLeads.length > 0
                      }
                      onChange={toggleAllLeads}
                    />
                    <span>All ({filteredLeads.length})</span>
                  </label>
                </div>
                {filteredLeads.map((lead) => (
                  <div
                    key={lead._id}
                    className={`re-lead-item ${
                      selectedLeads.has(lead._id) ? "re-selected" : ""
                    }`}
                  >
                    <label className="re-checkbox-label">
                      <input
                        type="checkbox"
                        checked={selectedLeads.has(lead._id)}
                        onChange={() => toggleLeadSelection(lead._id)}
                      />
                      <div className="re-lead-info">
                        <div className="re-lead-name">{lead.name}</div>
                        <div className="re-lead-company">
                          {lead.company_name}
                        </div>
                        <div className="re-lead-email">{lead.email}</div>
                      </div>
                    </label>
                  </div>
                ))}
              </>
            )}
          </div>
        </div>

        {/* Right Panel: Campaign Configuration */}
        <div className="re-panel re-config-panel">
          {/* Strategy Selection */}
          <div className="re-section">
            <h3 className="re-section-title">Re-engagement Strategy</h3>
            <div className="re-strategy-options">
              {Object.entries(strategies).map(([key, description]) => (
                <label key={key} className="re-strategy-option">
                  <input
                    type="radio"
                    name="strategy"
                    value={key}
                    checked={selectedStrategy === key}
                    onChange={(e) => setSelectedStrategy(e.target.value)}
                  />
                  <div className="re-strategy-content">
                    <div className="re-strategy-name">
                      {key.replace(/_/g, " ")}
                    </div>
                    <div className="re-strategy-description">{description}</div>
                  </div>
                </label>
              ))}
            </div>
          </div>

          {/* Timeline Visualization */}
          <div className="re-section">
            <h3 className="re-section-title">Timeline</h3>
            <div className="re-timeline">
              <div className="re-phase">
                <div className="re-phase-label">Phase 1: Week 3-4</div>
                <div className="re-phase-days">{timelineConfig.week3} days</div>
              </div>
              <div className="re-timeline-connector"></div>
              <div className="re-phase">
                <div className="re-phase-label">Phase 2: Month 2</div>
                <div className="re-phase-days">{timelineConfig.month2} days</div>
              </div>
              <div className="re-timeline-connector"></div>
              <div className="re-phase">
                <div className="re-phase-label">Phase 3: Month 3-4</div>
                <div className="re-phase-days">{timelineConfig.month3} days</div>
              </div>
            </div>
          </div>

          {/* Template Assignment */}
          <div className="re-section">
            <h3 className="re-section-title">Template Assignment</h3>
            <div className="re-template-grid">
              <div className="re-template-slot">
                <label className="re-label">Phase 1 Template</label>
                <select
                  className={`re-select ${
                    templatesByPhase.phase1 ? "re-selected" : ""
                  }`}
                  value={templatesByPhase.phase1 || ""}
                  onChange={(e) =>
                    setTemplatesByPhase({ ...templatesByPhase, phase1: e.target.value })
                  }
                >
                  <option value="">Select template...</option>
                  <option value="reeng_gentle">Reengagement Gentle</option>
                  <option value="reeng_value">Reengagement Value</option>
                  <option value="reeng_offer">Reengagement Offer</option>
                </select>
              </div>
              <div className="re-template-slot">
                <label className="re-label">Phase 2 Template</label>
                <select
                  className="re-select"
                  value={templatesByPhase.phase2 || ""}
                  onChange={(e) =>
                    setTemplatesByPhase({ ...templatesByPhase, phase2: e.target.value })
                  }
                >
                  <option value="">Select template...</option>
                  <option value="reeng_value">Reengagement Value</option>
                  <option value="reeng_offer">Reengagement Offer</option>
                  <option value="reeng_case">Reengagement Case Study</option>
                </select>
              </div>
              <div className="re-template-slot">
                <label className="re-label">Phase 3 Template</label>
                <select
                  className="re-select"
                  value={templatesByPhase.phase3 || ""}
                  onChange={(e) =>
                    setTemplatesByPhase({ ...templatesByPhase, phase3: e.target.value })
                  }
                >
                  <option value="">Select template...</option>
                  <option value="reeng_offer">Reengagement Offer</option>
                  <option value="reeng_case">Reengagement Case Study</option>
                  <option value="reeng_demo">Reengagement Demo</option>
                </select>
              </div>
            </div>
          </div>

          {/* Sender Rotation */}
          <div className="re-section">
            <label className="re-toggle-label">
              <input
                type="checkbox"
                checked={senderRotation}
                onChange={(e) => setSenderRotation(e.target.checked)}
              />
              <span>Rotate senders across phases</span>
            </label>
            <p className="re-help-text">
              Vary sender identity to improve deliverability and engagement
            </p>
          </div>

          {/* Create Campaign Button */}
          <button
            className="re-btn re-btn-primary"
            onClick={handleCreateCampaign}
            disabled={
              creating || selectedLeads.size === 0 || !templatesByPhase.phase1
            }
            aria-busy={creating ? "true" : "false"}
          >
            {creating ? "Creating campaign..." : "Create Campaign"}
          </button>
        </div>
      </div>
    </div>
  )
}

export default ReEngagement
