import { useState, useEffect, useRef } from "react"
import { buildApiUrl } from "../../config"
import { formatDate } from "../../utils/format"
import { authFetch } from "../../utils/api"
import { useNavigate, useSearchParams } from "react-router-dom"
import { countryName, colors, control, th, td } from "../../components/panel-admin/tokens"
import { ActionMenu, FilterBar, Pager, Modal, Notice, Badge, CountGrid, Field, SectionHeader } from "../../components/panel-admin/ui"
import RecruitmentSummary from "./RecruitmentSummary"
import ImportPanelistsDialog from "./ImportPanelistsDialog"
import { parseApiResponse } from "../../components/panel-admin/apiResponse"
import DeletePanelistDialog from "./DeletePanelistDialog"

const PANEL_ADMIN_API_PREFIX = "/api/panel-admin"


// Country codes → names for the filters (the API sends ISO codes)
const COUNTRY_NAMES = {
  US: "United States", IN: "India", GB: "United Kingdom", UK: "United Kingdom", AU: "Australia",
  CA: "Canada", DE: "Germany", FR: "France", SG: "Singapore", AE: "UAE", ES: "Spain", NG: "Nigeria",
}
// Member-journey stages (Overview → "Stopped at" links to ?stage=<key>).
const STAGE_LABELS = {
  signup: "Signed up", verified: "Email verified", membership: "Membership confirmed",
  quickDone: "Quick start done", clicked: "Clicked a survey", result: "Got a survey result",
  completed: "Completed a survey", repeat: "2+ completes",
}
// Badge tone + label for the Recruitment tables.
const EMAIL_STATUS = {
  sent: { tone: "accent", label: "Sent" },
  clicked: { tone: "warn", label: "Clicked" },
  confirmed: { tone: "good", label: "Confirmed" },
  soft_bounced: { tone: "warn", label: "Soft bounce" },
  bounced: { tone: "bad", label: "Bounced" },
  complained: { tone: "bad", label: "Complained" },
  failed: { tone: "neutral", label: "Failed" },
}
const DELIVERABILITY = {
  bounced: { tone: "bad", label: "⚠ Bounced" },
  soft_bounced: { tone: "warn", label: "⚠ Soft bounce" },
  complained: { tone: "bad", label: "⚠ Complained" },
}
const LEAD_STATUS_TONE = { COMPLETE: "good", INCOMPLETE: "warn" }
const PANELIST_STATUS_TONE = { active: "good", pending: "warn" }
// Heading + one-line explanation for each Recruitment list.
const VIEW_TEXT = {
  "panelist-leads": { title: "Leads", description: "Emails captured on landing pages. They get invitations only after they are merged into the panelist list." },
  "panelist-approved": { title: "Approved panelists", description: "Active panelists in the invite pool, with their latest invitation email status." },
}
const cellStrong = { ...td, fontWeight: 600 }
const emptyText = { color: colors.muted, padding: "1rem 0", margin: 0 }

// mode: "members" = SurveyFieldwork Panel members only (Members section);
// "recruitment" = lead lists, imports and invites (Recruitment section).
// view: set by the Recruitment section's own tabs ("panelist-leads" |
// "panelist-approved"); when given, the inner tab bar is hidden.
function PanelistManagement({ mode = "all", view }) {
  const [tabState, setActiveTab] = useState(mode === "members" ? "sfw-panelists" : "panelist-leads")
  const activeTab = view || tabState

  // SFW Panel state
  const [sfwPanelists, setSfwPanelists] = useState([])
  const [sfwPage, setSfwPage] = useState(1)
  const [sfwTotal, setSfwTotal] = useState(0)
  const [sfwPages, setSfwPages] = useState(1)
  const [sfwLoading, setSfwLoading] = useState(false)
  const [sfwSearch, setSfwSearch] = useState("")
  // ?stage=<key>&country=<ISO> (from the Overview's member journey) pre-filter the list.
  const [searchParams, setSearchParams] = useSearchParams()
  const urlStage = searchParams.get("stage") || ""
  const [sfwCountry, setSfwCountry] = useState(searchParams.get("country") || "")
  const [sfwSortBy, setSfwSortBy] = useState("createdAt")
  const [sfwOrder, setSfwOrder] = useState("desc")
  // Member to delete (confirmation dialog); a row click opens the member page.
  const [deleting, setDeleting] = useState(null)
  const navigate = useNavigate()

  // Panelist leads state
  const [panelLeads, setPanelLeads] = useState([])
  const [leadPage, setLeadPage] = useState(1)
  const [leadTotal, setLeadTotal] = useState(0)
  const [leadLoading, setLeadLoading] = useState(false)
  const [leadSearch, setLeadSearch] = useState("")
  const [leadCountry, setLeadCountry] = useState("")
  const [leadPageSize, setLeadPageSize] = useState(25)
  const [allLeadsTotal, setAllLeadsTotal] = useState(null) // unfiltered, for the summary
  const leadReq = useRef(0)

  // Approved panelists state
  const [panelists, setPanelists] = useState([])
  const [panelistPage, setPanelistPage] = useState(1)
  const [panelistTotal, setPanelistTotal] = useState(0)
  const [panelistLoading, setPanelistLoading] = useState(false)
  const [panelistSearch, setPanelistSearch] = useState("")
  const [panelistCountry, setPanelistCountry] = useState("")
  const [panelistPageSize, setPanelistPageSize] = useState(25)
  const panelistReq = useRef(0)
  const [availableCountries, setAvailableCountries] = useState([])
  const [leadCountries, setLeadCountries] = useState([])

  // Import dialog (CSV file or link): ImportPanelistsDialog owns its own state.
  const [showUpload, setShowUpload] = useState(false)

  // Invitation state
  const [showInviteModal, setShowInviteModal] = useState(false)
  const [inviteLoading, setInviteLoading] = useState(false)
  const [inviteResult, setInviteResult] = useState(null)
  const [inviteCount, setInviteCount] = useState(0)

  // Test email state
  const [showTestEmailModal, setShowTestEmailModal] = useState(false)
  const [testEmailAddress, setTestEmailAddress] = useState("")
  const [testEmailName, setTestEmailName] = useState("")
  const [testEmailLoading, setTestEmailLoading] = useState(false)
  const [testEmailResult, setTestEmailResult] = useState(null)

  // Lead promotion state — parsing-page leads only receive invitations once
  // they have been merged into the `panelists` collection.
  const [promotionStatus, setPromotionStatus] = useState(null)
  const [promoting, setPromoting] = useState(false)
  const [promoteResult, setPromoteResult] = useState(null)

  // Records loaded per request for the members list. The Leads and Approved
  // lists each have their own rows-per-page (leadPageSize / panelistPageSize),
  // kept low by default: fetching 100 rows of a 190K-row collection on every
  // page click was the bulk of the wait.
  const [pageSize] = useState(mode === "members" ? 500 : 25)

  // The country filter on the list in view also scopes Send Invitations.
  const inviteCountry = activeTab === "panelist-approved" ? panelistCountry : leadCountry

  // Each list refetches only on its own filters, so they work independently.
  useEffect(() => {
    if (activeTab === "panelist-leads") fetchPanelLeads()
  }, [activeTab, leadPage, leadSearch, leadCountry, leadPageSize])

  useEffect(() => {
    if (activeTab === "panelist-approved") fetchPanelists()
  }, [activeTab, panelistPage, panelistSearch, panelistCountry, panelistPageSize])

  useEffect(() => {
    if (activeTab === "sfw-panelists") fetchSfwPanelists()
  }, [activeTab, pageSize, urlStage])

  // Fetch distinct countries on mount
  useEffect(() => {
    fetchCountries()
    fetchLeadCountries()
    fetchPromotionStatus()
  }, [])

  const fetchPromotionStatus = async () => {
    const sessionId = localStorage.getItem("session_id")
    try {
      const res = await authFetch(buildApiUrl(`${PANEL_ADMIN_API_PREFIX}/panelist-leads/promotion-status`), {
        headers: { Authorization: sessionId },
      })
      if (res.ok) setPromotionStatus(await res.json())
    } catch (err) {
      console.error("Failed to fetch lead promotion status:", err)
    }
  }

  const handlePromoteLeads = async () => {
    setPromoting(true)
    setPromoteResult(null)
    const sessionId = localStorage.getItem("session_id")
    try {
      const res = await authFetch(buildApiUrl(`${PANEL_ADMIN_API_PREFIX}/panelist-leads/promote`), {
        method: "POST",
        headers: { "Content-Type": "application/json", Authorization: sessionId },
        body: JSON.stringify({}),
      })
      const data = await parseApiResponse(res)
      if (res.ok) {
        setPromoteResult({
          success: true,
          message: `Merged ${data.inserted || 0} new leads into the panelist list (${data.already_present || 0} were already there). They enter the invite rotation on the next run.`,
        })
        fetchPromotionStatus()
        fetchPanelists()
      } else {
        setPromoteResult({ success: false, message: data.detail || "Merge failed" })
      }
    } catch (err) {
      setPromoteResult({ success: false, message: "Network error: " + err.message })
    } finally {
      setPromoting(false)
    }
  }

  const confirmPromoteLeads = () => {
    if (window.confirm("Merge all parsing-page leads into the panelist list now? Merged leads enter the invite rotation on the next run.")) {
      handlePromoteLeads()
    }
  }

  const fetchCountries = async () => {
    const sessionId = localStorage.getItem("session_id")
    try {
      const res = await authFetch(buildApiUrl(`${PANEL_ADMIN_API_PREFIX}/panelists/countries`), {
        headers: { Authorization: sessionId },
      })
      if (res.ok) {
        const data = await res.json()
        setAvailableCountries(data.countries || [])
      }
    } catch (err) {
      console.error("Failed to fetch countries:", err)
    }
  }

  const fetchLeadCountries = async () => {
    const sessionId = localStorage.getItem("session_id")
    try {
      const res = await authFetch(buildApiUrl(`${PANEL_ADMIN_API_PREFIX}/panelist-leads/countries`), {
        headers: { Authorization: sessionId },
      })
      if (res.ok) {
        const data = await res.json()
        setLeadCountries(data.countries || [])
      }
    } catch (err) {
      console.error("Failed to fetch lead countries:", err)
    }
  }

  // Search runs as you type, so responses can arrive out of order: only the
  // latest request (leadReq / panelistReq) is allowed to update the table.
  const fetchPanelLeads = async () => {
    const req = ++leadReq.current
    setLeadLoading(true)
    const sessionId = localStorage.getItem("session_id")
    try {
      const params = new URLSearchParams({
        page: leadPage,
        page_size: leadPageSize,
      })
      if (leadSearch) params.append("search", leadSearch)
      if (leadCountry) params.append("country", leadCountry)

      const res = await authFetch(buildApiUrl(`${PANEL_ADMIN_API_PREFIX}/panelist-leads/?${params}`), {
        headers: { Authorization: sessionId },
      })
      if (res.ok && req === leadReq.current) {
        const data = await res.json()
        setPanelLeads(data.results || [])
        setLeadTotal(data.total || 0)
        if (!leadSearch && !leadCountry) setAllLeadsTotal(data.total || 0)
      }
    } catch (err) {
      console.error("Failed to fetch panelist leads:", err)
    } finally {
      if (req === leadReq.current) setLeadLoading(false)
    }
  }

  const fetchPanelists = async () => {
    const req = ++panelistReq.current
    setPanelistLoading(true)
    const sessionId = localStorage.getItem("session_id")
    try {
      const params = new URLSearchParams({
        page: panelistPage,
        page_size: panelistPageSize,
      })
      if (panelistSearch) params.append("search", panelistSearch)
      if (panelistCountry) params.append("country", panelistCountry)
      params.append("status", "active")

      const res = await authFetch(buildApiUrl(`${PANEL_ADMIN_API_PREFIX}/panelists/with-email-status?${params}`), {
        headers: { Authorization: sessionId },
      })
      if (res.ok && req === panelistReq.current) {
        const data = await res.json()
        setPanelists(data.results || data.panelists || [])
        setPanelistTotal(data.total || 0)
      }
    } catch (err) {
      console.error("Failed to fetch panelists:", err)
    } finally {
      if (req === panelistReq.current) setPanelistLoading(false)
    }
  }

  const emailStatusBadge = (status) =>
    EMAIL_STATUS[status] || { tone: "neutral", label: status || "Not sent" }

  // Test email handler
  const handleSendTestEmail = async () => {
    if (!testEmailAddress || !testEmailAddress.includes("@")) return
    setTestEmailLoading(true)
    setTestEmailResult(null)
    const sessionId = localStorage.getItem("session_id")
    try {
      const res = await authFetch(buildApiUrl(`${PANEL_ADMIN_API_PREFIX}/invitations/test-send`), {
        method: "POST",
        headers: { "Content-Type": "application/json", Authorization: sessionId },
        body: JSON.stringify({ to_email: testEmailAddress, first_name: testEmailName }),
      })
      const data = await res.json()
      if (res.ok) {
        setTestEmailResult({ success: true, message: `Test email sent to ${testEmailAddress}` })
      } else {
        setTestEmailResult({ success: false, message: data.detail || "Failed to send test email" })
      }
    } catch (err) {
      setTestEmailResult({ success: false, message: "Network error: " + err.message })
    } finally {
      setTestEmailLoading(false)
    }
  }

  // Invitation handlers
  const handleSendInvitationsClick = async () => {
    const sessionId = localStorage.getItem("session_id")
    try {
      const params = new URLSearchParams()
      if (inviteCountry) params.append("country", inviteCountry)
      const res = await authFetch(buildApiUrl(`${PANEL_ADMIN_API_PREFIX}/invitations/preview?${params}`), {
        headers: { Authorization: sessionId },
      })
      if (res.ok) {
        const data = await res.json()
        setInviteCount(data.eligible_count || 0)
        setInviteResult(null)
        setShowInviteModal(true)
      }
    } catch (err) {
      console.error("Failed to get invitation preview:", err)
    }
  }

  const handleConfirmSendInvitations = async () => {
    setInviteLoading(true)
    setInviteResult(null)
    const sessionId = localStorage.getItem("session_id")

    try {
      const body = {}
      if (inviteCountry) body.country = inviteCountry

      const res = await authFetch(buildApiUrl(`${PANEL_ADMIN_API_PREFIX}/invitations/send`), {
        method: "POST",
        headers: {
          "Content-Type": "application/json",
          Authorization: sessionId,
        },
        body: JSON.stringify(body),
      })

      const data = await res.json()
      if (res.ok) {
        setInviteResult({ success: true, sent: data.sent || 0, skipped: data.skipped || 0, failed: data.failed || 0 })
      } else {
        setInviteResult({ success: false, message: data.detail || "Failed to send invitations" })
      }
    } catch (err) {
      setInviteResult({ success: false, message: "Network error: " + err.message })
    } finally {
      setInviteLoading(false)
    }
  }

  const tabStyle = (tab) => ({
    padding: "0.75rem 1.5rem",
    border: "none",
    borderBottom: activeTab === tab ? "3px solid #e8910a" : "3px solid transparent",
    background: "none",
    cursor: "pointer",
    fontWeight: activeTab === tab ? "600" : "400",
    color: activeTab === tab ? "#e8910a" : "#5c5c5c",
    fontSize: "0.95rem",
  })


  const fetchSfwPanelists = async (overrides = {}) => {
    setSfwLoading(true)
    const sessionId = localStorage.getItem("session_id")
    const pg = overrides.page ?? sfwPage
    const sb = overrides.sortBy ?? sfwSortBy
    const od = overrides.order ?? sfwOrder
    const ct = overrides.country ?? sfwCountry
    const sr = overrides.search ?? sfwSearch
    const st = overrides.stage ?? urlStage
    try {
      const params = new URLSearchParams({ page: pg, limit: Math.min(pageSize, 500), sort_by: sb, order: od, ...(ct ? { country: ct } : {}), ...(sr ? { search: sr } : {}), ...(st ? { stage: st } : {}) })
      const res = await authFetch(buildApiUrl(`${PANEL_ADMIN_API_PREFIX}/sfwpanel-panelists?${params}`), { headers: { Authorization: sessionId } })
      if (res.ok) {
        const data = await res.json()
        setSfwPanelists(data.panelists || [])
        setSfwTotal(data.total || 0)
        setSfwPages(data.pages || 1)
      }
    } catch (err) { console.error("SFW panelists error:", err) }
    finally { setSfwLoading(false) }
  }

  const sfwSort = (field) => {
    const newOrder = sfwSortBy === field && sfwOrder === "desc" ? "asc" : "desc"
    setSfwSortBy(field); setSfwOrder(newOrder); setSfwPage(1)
    fetchSfwPanelists({ sortBy: field, order: newOrder, page: 1 })
  }

  const clearStage = () => {
    const next = new URLSearchParams(searchParams)
    next.delete("stage")
    setSearchParams(next, { replace: true })
    setSfwPage(1)
    fetchSfwPanelists({ page: 1, stage: "" })
  }

  // Balances are INR paise; members see points (100 points = ₹10 / £1 / $1).
  const points = (p, country) => {
    const perPaise = { GB: 1 / 127.89, UK: 1 / 127.89, US: 1 / 96.73 }[String(country || "").toUpperCase()] || 1 / 10
    return `${Math.floor((p || 0) * perPaise).toLocaleString()} pts`
  }
  const fmtDate = (d) => d ? new Date(d).toLocaleDateString("en-IN", { day: "numeric", month: "short", year: "numeric" }) : "—"
  const cname = (cc) => (cc ? countryName(cc) : "—")

  return (
    <div>
      <div className="card">
        {mode !== "members" && (
          <SectionHeader
            title={view ? VIEW_TEXT[activeTab]?.title : "Panelist Management"}
            description={view ? VIEW_TEXT[activeTab]?.description : "Manage parsing-page leads, approved panelists, and bulk uploads."}
            actions={<>
              {/* One primary action; everything occasional sits in the menu. */}
              <ActionMenu
                items={[
                  { label: "Send test email", onClick: () => { setTestEmailResult(null); setShowTestEmailModal(true) } },
                  { label: "Import panelists (CSV or link)…", onClick: () => setShowUpload(true) },
                  { label: promoting ? "Merging leads…" : "Merge leads into panelists now", onClick: confirmPromoteLeads, disabled: promoting },
                ]}
              />
              <button type="button" className="btn btn-primary" onClick={handleSendInvitationsClick}>
                Send Invitations
              </button>
            </>}
          />
        )}

        {promoteResult && (
          <Notice tone={promoteResult.success ? "good" : "bad"} style={{ marginBottom: "1rem" }}>
            {promoteResult.message}
          </Notice>
        )}

        {/* Pending merge card carries "Merge now" (unmerged leads get no invitations). */}
        {view && (
          <RecruitmentSummary totalLeads={allLeadsTotal} promotionStatus={promotionStatus} onMerge={confirmPromoteLeads} merging={promoting} />
        )}

        {/* Tabs (the Members section has a single list, and the Recruitment
            section picks the list with its own page tabs, so no bar there) */}
        {mode !== "members" && !view && <div style={{ borderBottom: "1px solid #e8e4dc", marginBottom: "1.5rem", display: "flex", justifyContent: "space-between", alignItems: "center", flexWrap: "wrap", gap: "0.5rem" }}>
          <div>
            {mode !== "members" && (
              <>
                <button style={tabStyle("panelist-leads")} onClick={() => setActiveTab("panelist-leads")}>
                  Panelist Lead
                </button>
                <button style={tabStyle("panelist-approved")} onClick={() => setActiveTab("panelist-approved")}>
                  Panelist Approved
                </button>
              </>
            )}
            {mode !== "recruitment" && (
              <button style={tabStyle("sfw-panelists")} onClick={() => setActiveTab("sfw-panelists")}>
                {mode === "members" ? "Panel members" : "SFW Panelists"}
              </button>
            )}
          </div>
        </div>}

        {/* Panelist Lead Tab */}
        {activeTab === "panelist-leads" && (
          <div>
            <FilterBar
              search={leadSearch}
              onSearch={(v) => { setLeadSearch(v); setLeadPage(1) }}
              placeholder="Search by mail ID, respondent ID, vendor, country…"
              country={leadCountry}
              onCountry={(c) => { setLeadCountry(c); setLeadPage(1) }}
              countries={leadCountries}
              countryLabel={(c) => COUNTRY_NAMES[c] || c}
              pageSize={leadPageSize}
              onPageSize={(n) => { setLeadPageSize(n); setLeadPage(1) }}
            />

            {/* Keep the current rows (dimmed) while a new search loads, so the
                table doesn't flash on every keystroke. */}
            {leadLoading && panelLeads.length === 0 ? (
              <p style={emptyText}>Loading panelist leads…</p>
            ) : panelLeads.length === 0 ? (
              <p style={emptyText}>No parsing-page mail IDs found.</p>
            ) : (
              <>
                <div style={{ overflowX: "auto", opacity: leadLoading ? 0.5 : 1, transition: "opacity 0.15s" }}>
                  <table style={{ width: "100%", borderCollapse: "collapse" }}>
                    <thead>
                      <tr>
                        <th style={{ ...th, minWidth: "220px" }}>Email</th>
                        <th style={th}>Country</th>
                        <th style={th}>Respondent ID</th>
                        <th style={th}>Vendor ID</th>
                        <th style={th}>Status</th>
                        <th style={th}>Collected</th>
                      </tr>
                    </thead>
                    <tbody>
                      {panelLeads.map((lead, index) => (
                        <tr key={lead._id || lead.id || index}>
                          <td style={cellStrong}>{lead.email || "—"}</td>
                          <td style={td}>
                            {lead.countryCode ? <Badge tone="accent" title={countryName(lead.countryCode)}>{lead.countryCode}</Badge> : "—"}
                          </td>
                          <td style={td}>{lead.respondentId || "—"}</td>
                          <td style={td}>{lead.vendorId || "—"}</td>
                          <td style={td}>
                            {lead.status ? <Badge tone={LEAD_STATUS_TONE[lead.status] || "neutral"}>{lead.status}</Badge> : "—"}
                          </td>
                          <td style={{ ...td, whiteSpace: "nowrap" }}>{lead.createdAt ? formatDate(lead.createdAt) : "—"}</td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>

                <Pager page={leadPage} pageSize={leadPageSize} total={leadTotal} onPage={setLeadPage} noun="unique mail IDs" />
              </>
            )}
          </div>
        )}

        {/* Panelist Approved Tab */}
        {activeTab === "panelist-approved" && (
          <div>
            <FilterBar
              search={panelistSearch}
              onSearch={(v) => { setPanelistSearch(v); setPanelistPage(1) }}
              placeholder="Search approved panelists by email, name, country…"
              country={panelistCountry}
              onCountry={(c) => { setPanelistCountry(c); setPanelistPage(1) }}
              countries={availableCountries}
              countryLabel={(c) => COUNTRY_NAMES[c] || c}
              pageSize={panelistPageSize}
              onPageSize={(n) => { setPanelistPageSize(n); setPanelistPage(1) }}
            />

            {panelistLoading && panelists.length === 0 ? (
              <p style={emptyText}>Loading approved panelists…</p>
            ) : panelists.length === 0 ? (
              <p style={emptyText}>No approved panelists found.</p>
            ) : (
              <>
                <div style={{ overflowX: "auto", opacity: panelistLoading ? 0.5 : 1, transition: "opacity 0.15s" }}>
                  <table style={{ width: "100%", borderCollapse: "collapse" }}>
                    <thead>
                      <tr>
                        <th style={{ ...th, minWidth: "220px" }}>Email</th>
                        <th style={th}>Country</th>
                        <th style={th}>Name</th>
                        <th style={th}>Status</th>
                        <th style={th}>Verified</th>
                        <th style={th}>Deliverability</th>
                        <th style={th}>Joined</th>
                        <th style={th}>Email sent</th>
                        <th style={th}>Email status</th>
                      </tr>
                    </thead>
                    <tbody>
                      {panelists.map((panelist, index) => {
                        const mail = emailStatusBadge(panelist.email_status)
                        const deliver = DELIVERABILITY[panelist.email_status] || { tone: "good", label: "✓ OK" }
                        return (
                          <tr key={panelist._id || panelist.id || index}>
                            <td style={cellStrong}>{panelist.email || "—"}</td>
                            <td style={td}>
                              {panelist.country ? <Badge tone="accent" title={countryName(panelist.country)}>{panelist.country}</Badge> : "—"}
                            </td>
                            <td style={td}>{[panelist.first_name, panelist.last_name].filter(Boolean).join(" ") || "—"}</td>
                            <td style={td}>
                              <Badge tone={PANELIST_STATUS_TONE[panelist.status || "active"] || "bad"}>{panelist.status || "active"}</Badge>
                            </td>
                            <td style={td}>
                              <Badge tone={panelist.email_verified ? "good" : "neutral"}>{panelist.email_verified ? "Verified" : "Unverified"}</Badge>
                            </td>
                            <td style={td}><Badge tone={deliver.tone}>{deliver.label}</Badge></td>
                            <td style={{ ...td, whiteSpace: "nowrap" }}>{panelist.created_at ? formatDate(panelist.created_at) : "—"}</td>
                            <td style={{ ...td, whiteSpace: "nowrap" }}>{panelist.email_sent_date ? formatDate(panelist.email_sent_date) : "—"}</td>
                            <td style={td}><Badge tone={mail.tone}>{mail.label}</Badge></td>
                          </tr>
                        )
                      })}
                    </tbody>
                  </table>
                </div>

                <Pager page={panelistPage} pageSize={panelistPageSize} total={panelistTotal} onPage={setPanelistPage} noun="approved panelists" />
              </>
            )}
          </div>
        )}
        {/* SFW Panelists Tab */}
        {activeTab === "sfw-panelists" && (
          <div>
            {/* Filters */}
            <div style={{ display: "flex", gap: "0.75rem", marginBottom: "1rem", flexWrap: "wrap", alignItems: "center" }}>
              <input type="text" placeholder="Search name, email, panelist ID…" value={sfwSearch}
                onChange={(e) => setSfwSearch(e.target.value)}
                onKeyDown={(e) => { if (e.key === "Enter") { setSfwPage(1); fetchSfwPanelists({ page: 1, search: e.target.value }) } }}
                style={{ flex: 1, minWidth: "220px", padding: "0.5rem 0.75rem", border: "1px solid #d4cec3", borderRadius: "6px", fontSize: "0.875rem" }} />
              <select value={sfwCountry} onChange={(e) => { setSfwCountry(e.target.value); setSfwPage(1); fetchSfwPanelists({ page: 1, country: e.target.value }) }}
                style={{ padding: "0.5rem 0.75rem", border: "1px solid #d4cec3", borderRadius: "6px", fontSize: "0.875rem" }}>
                <option value="">All Countries</option>
                {["US","IN","GB","AU","CA","DE","SG","AE", ...(sfwCountry && !["US","IN","GB","AU","CA","DE","SG","AE"].includes(sfwCountry) ? [sfwCountry] : [])].map(c => <option key={c} value={c}>{COUNTRY_NAMES[c] || countryName(c)}</option>)}
              </select>
              <button onClick={() => { setSfwPage(1); fetchSfwPanelists({ page: 1 }) }}
                style={{ padding: "0.5rem 1rem", background: "#f97316", color: "#fff", border: "none", borderRadius: "6px", cursor: "pointer", fontSize: "0.875rem", fontWeight: "600" }}>
                ↻ Refresh
              </button>
            </div>

            {urlStage && (
              <div style={{ marginBottom: "0.75rem" }}>
                <span style={{ display: "inline-flex", alignItems: "center", gap: "0.4rem", background: "#fdf4e7", border: "1px solid #f3d9ad", color: "#a15f06", borderRadius: "999px", padding: "0.25rem 0.4rem 0.25rem 0.75rem", fontSize: "0.8rem", fontWeight: 600 }}>
                  Stopped at: {STAGE_LABELS[urlStage] || urlStage}
                  <button type="button" onClick={clearStage} aria-label="Remove stage filter"
                    style={{ border: "none", background: "none", cursor: "pointer", color: "#a15f06", fontSize: "0.95rem", lineHeight: 1, padding: "0 0.2rem" }}>×</button>
                </span>
              </div>
            )}

            <p style={{ fontSize: "0.875rem", color: "#6f6f6f", marginBottom: "0.75rem" }}>{sfwTotal} panelists {sfwSearch || sfwCountry || urlStage ? "(filtered)" : ""}</p>

            {/* Table */}
            {sfwLoading ? (
              <p style={{ color: "#5c5c5c", padding: "2rem 0", textAlign: "center" }}>Loading…</p>
            ) : sfwPanelists.length === 0 ? (
              <p style={{ color: "#5c5c5c", padding: "2rem 0", textAlign: "center" }}>No panelists found</p>
            ) : (
              <div style={{ overflowX: "auto" }}>
                <table style={{ width: "100%", borderCollapse: "collapse", fontSize: "0.875rem" }}>
                  <thead>
                    <tr style={{ background: "#faf9f7", borderBottom: "2px solid #e8e4dc" }}>
                      {[
                        { label: "Email", field: null },
                        { label: "Country", field: null },
                        { label: "Joined ↕", field: "createdAt" },
                        { label: "Attempts", field: null },
                        { label: "Completes", field: null },
                        { label: "Points accrued ↕", field: "totalEarnedPaise" },
                        { label: "Source", field: null },
                        { label: "Level", field: null },
                        { label: "", field: null },
                      ].map(({ label, field }) => (
                        <th key={label || "actions"} onClick={field ? () => sfwSort(field) : undefined}
                          style={{ ...thStyle, cursor: field ? "pointer" : "default", whiteSpace: "nowrap", userSelect: "none",
                            color: sfwSortBy === field ? "#f97316" : "#5c5c5c" }}>
                          {label}
                        </th>
                      ))}
                    </tr>
                  </thead>
                  <tbody>
                    {sfwPanelists.map((p) => {
                      const sv = p.surveys || {}
                      return (
                        <tr key={p._id} onClick={() => navigate(`/admin/panel-admin/members/${p._id}`)}
                          style={{ borderBottom: "1px solid #f5f3ef", cursor: "pointer" }}
                          onMouseEnter={(e) => e.currentTarget.style.background = "#fdf4e7"}
                          onMouseLeave={(e) => e.currentTarget.style.background = ""}>
                          <td style={{ ...tdStyle, color: "#1a1a1a", fontWeight: "600" }}>{p.email || "—"}</td>
                          <td style={tdStyle}>{cname(p.country)}</td>
                          <td style={{ ...tdStyle, whiteSpace: "nowrap", color: "#5c5c5c" }}>{fmtDate(p.createdAt)}</td>
                          <td style={{ ...tdStyle, textAlign: "center" }}>{p.attempts || 0}</td>
                          <td style={{ ...tdStyle, textAlign: "center", color: "#15803d", fontWeight: "600" }}>{sv.complete || 0}</td>
                          <td style={{ ...tdStyle, textAlign: "right", color: "#1a1a1a", whiteSpace: "nowrap" }}>{points(p.totalEarnedPaise, p.country)}</td>
                          <td style={{ ...tdStyle, whiteSpace: "nowrap" }}>{p.source || "Direct"}</td>
                          <td style={tdStyle}>{p.level ? p.level.charAt(0).toUpperCase() + p.level.slice(1) : "—"}</td>
                          <td style={{ ...tdStyle, textAlign: "right" }}>
                            <button type="button" title="Delete member" aria-label={`Delete ${p.email}`}
                              onClick={(e) => { e.stopPropagation(); setDeleting(p) }}
                              style={{ padding: "0.3rem 0.6rem", border: "1px solid #fecaca", background: "#fff", color: "#dc2626", borderRadius: "6px", cursor: "pointer", fontSize: "0.8rem" }}>
                              Delete
                            </button>
                          </td>
                        </tr>
                      )
                    })}
                  </tbody>
                </table>
              </div>
            )}

            {deleting && (
              <DeletePanelistDialog panelist={deleting} onClose={() => setDeleting(null)}
                onDeleted={() => { setDeleting(null); fetchSfwPanelists() }} />
            )}

            {/* Pagination */}
            {(sfwPages > 1 || mode === "members") && (
              <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", marginTop: "1rem", fontSize: "0.875rem", color: "#5c5c5c" }}>
                <span>Page {sfwPage} of {sfwPages} · {sfwTotal} panelists</span>
                <div style={{ display: "flex", gap: "0.5rem" }}>
                  <button disabled={sfwPage <= 1} onClick={() => { const p = sfwPage - 1; setSfwPage(p); fetchSfwPanelists({ page: p }) }}
                    style={{ padding: "0.4rem 0.8rem", border: "1px solid #d4cec3", borderRadius: "6px", cursor: sfwPage <= 1 ? "default" : "pointer", opacity: sfwPage <= 1 ? 0.4 : 1 }}>
                    ← Prev
                  </button>
                  <button disabled={sfwPage >= sfwPages} onClick={() => { const p = sfwPage + 1; setSfwPage(p); fetchSfwPanelists({ page: p }) }}
                    style={{ padding: "0.4rem 0.8rem", border: "1px solid #d4cec3", borderRadius: "6px", cursor: sfwPage >= sfwPages ? "default" : "pointer", opacity: sfwPage >= sfwPages ? 0.4 : 1 }}>
                    Next →
                  </button>
                </div>
              </div>
            )}

          </div>
        )}

      </div>

      <Modal
        open={showTestEmailModal}
        title="Send a test invitation email"
        width={460}
        busy={testEmailLoading}
        onClose={() => setShowTestEmailModal(false)}
        footer={<>
          <button type="button" className="btn btn-outline" onClick={() => setShowTestEmailModal(false)} disabled={testEmailLoading}>Close</button>
          <button type="button" className="btn btn-primary" onClick={handleSendTestEmail} disabled={testEmailLoading || !testEmailAddress.includes("@")}>
            {testEmailLoading ? "Sending…" : "Send test email"}
          </button>
        </>}
      >
        <p style={{ margin: "0 0 1rem", fontSize: "0.875rem", color: colors.muted, lineHeight: 1.5 }}>
          Preview the invite email by sending it to any address. Sent from <strong>panel@surveyfieldwork.com</strong> via SES.
        </p>
        <Field label="Recipient email" htmlFor="test-email" required>
          <input id="test-email" type="email" value={testEmailAddress} onChange={(e) => setTestEmailAddress(e.target.value)} placeholder="you@example.com" style={{ ...control, width: "100%" }} />
        </Field>
        <Field label="First name" hint="(optional)" htmlFor="test-name">
          <input id="test-name" type="text" value={testEmailName} onChange={(e) => setTestEmailName(e.target.value)} placeholder="e.g. Alex" style={{ ...control, width: "100%" }} />
        </Field>
        {testEmailResult && <Notice tone={testEmailResult.success ? "good" : "bad"}>{testEmailResult.message}</Notice>}
      </Modal>

      <ImportPanelistsDialog open={showUpload} onClose={() => setShowUpload(false)} onImported={fetchPanelists} />

      <Modal
        open={showInviteModal}
        title="Send invitation emails"
        width={480}
        busy={inviteLoading}
        onClose={() => setShowInviteModal(false)}
        footer={inviteResult ? (
          <button type="button" className="btn btn-primary" onClick={() => setShowInviteModal(false)}>Close</button>
        ) : (<>
          <button type="button" className="btn btn-outline" onClick={() => setShowInviteModal(false)} disabled={inviteLoading}>Cancel</button>
          <button type="button" className="btn btn-primary" onClick={handleConfirmSendInvitations} disabled={inviteLoading || inviteCount === 0}>
            {inviteLoading ? "Sending…" : `Send to ${inviteCount.toLocaleString()} panelists`}
          </button>
        </>)}
      >
        {!inviteResult ? (
          <>
            <p style={{ margin: "0 0 0.75rem", fontSize: "0.9rem", color: colors.text, lineHeight: 1.5 }}>
              Send invitation emails to <strong>{inviteCount.toLocaleString()}</strong> eligible panelists{" "}
              {inviteCountry ? <>in <strong>{countryName(inviteCountry)}</strong></> : "across all countries"}.
            </p>
            <p style={{ margin: 0, fontSize: "0.85rem", color: colors.muted }}>
              Suppressed (bounced/complained) and already-invited panelists will be skipped automatically.
            </p>
          </>
        ) : inviteResult.success ? (
          <>
            <Notice tone="good">Invitations sent.</Notice>
            <CountGrid items={[
              { label: "Sent", value: inviteResult.sent, color: colors.good },
              { label: "Skipped", value: inviteResult.skipped },
              { label: "Failed", value: inviteResult.failed, color: inviteResult.failed ? colors.bad : colors.text },
            ]} />
            <p style={{ margin: 0, fontSize: "0.8rem", color: colors.muted }}>Skipped = suppressed or already invited.</p>
          </>
        ) : (
          <Notice tone="bad">{inviteResult.message}</Notice>
        )}
      </Modal>
    </div>
  )
}

const thStyle = { textAlign: "left", padding: "0.75rem", fontSize: "0.875rem", color: "#5c5c5c" }
const tdStyle = { padding: "0.75rem", fontSize: "0.875rem" }

export default PanelistManagement
