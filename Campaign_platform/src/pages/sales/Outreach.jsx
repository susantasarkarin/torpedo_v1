/**
 * Cold Outreach Dashboard
 * /admin/sales/outreach
 *
 * Manage 4-step cold email campaigns for 3 businesses:
 *   A — Survey Fieldwork   (indira@surveyfieldwork.com)
 *   B — Cogentix Research  (meera@cogentixresearch.com)
 *   C — BIMwave            (susanta@bimwaveconsultants.com)
 *   D — Dual Fit           (all 3 in score order, 21-day gap)
 */
import { useState, useEffect, useCallback } from "react"
import {
  fetchCampaigns, fetchMailboxes, fetchSuppressionStats,
  fetchSuppression as fetchSuppressionApi,
  createCampaign as createCampaignApi,
  launchCampaign as launchCampaignApi,
  pauseCampaign as pauseCampaignApi,
  resumeCampaign as resumeCampaignApi,
  saveStep as saveStepApi,
  sendTestEmail as sendTestEmailApi,
  generateStep,
  saveContext as saveContextApi,
  fetchCampaignStats,
  fetchLeadsByStatus as fetchLeadsByStatusApi,
  enrollDualFit as enrollDualFitApi,
  addMailbox as addMailboxApi,
  removeMailbox as removeMailboxApi,
  addSuppression as addSuppressionApi,
  removeSuppression as removeSuppressionApi,
} from "../../services/outreachService"
import "./campaign/AILeads.css"

const spinKeyframes = `@keyframes spin { to { transform: rotate(360deg); } }`
if (typeof document !== "undefined" && !document.getElementById("spin-kf")) {
  const s = document.createElement("style"); s.id = "spin-kf"; s.textContent = spinKeyframes; document.head.appendChild(s)
}

const BUSINESSES = [
  { key: "sfw",      label: "Survey Fieldwork",  basket: "A", color: "#065f46", bg: "#d1fae5", border: "#6ee7b7", icon: "📊" },
  { key: "cogentix", label: "Cogentix Research",  basket: "B", color: "#5b21b6", bg: "#ede9fe", border: "#c4b5fd", icon: "🔍" },
  { key: "bimwave",  label: "BIMwave",            basket: "C", color: "#1e40af", bg: "#dbeafe", border: "#93c5fd", icon: "🏗️" },
  { key: "dual_fit", label: "Dual Fit",           basket: "D", color: "#0e7490", bg: "#cffafe", border: "#67e8f9", icon: "⚡" },
]

const STEP_DAYS = [1, 4, 7, 12]

// ─────────────────────────────────────────────────────────────────────────────

function Outreach() {
  const [campaigns, setCampaigns] = useState([])
  const [mailboxes, setMailboxes] = useState([])
  const [suppStats, setSuppStats] = useState({ total_suppressed: 0 })
  const [basketCounts, setBasketCounts] = useState({})  // { A: 123, B: 456, ... }
  const [totalLeads, setTotalLeads] = useState(0)
  const [loading, setLoading] = useState(true)
  const [selectedBiz, setSelectedBiz] = useState(null)   // "sfw" | "cogentix" | "bimwave" | "dual_fit"
  const [activeTab, setActiveTab] = useState("templates") // "templates" | "stats" | "mailboxes" | "suppression"
  const [actionMsg, setActionMsg] = useState("")

  // Template editing state per campaign
  const [editSteps, setEditSteps] = useState({})  // { campaign_id: { 1: {subject, body_html}, ... } }
  const [savingStep, setSavingStep] = useState(null)

  // Test email state per step
  const [testRecipient, setTestRecipient] = useState({})   // { "cid-step": email }
  const [sendingTest, setSendingTest] = useState(null)     // "cid-step" while sending
  const [showTestInput, setShowTestInput] = useState({})   // { "cid-step": bool }
  const [generatingStep, setGeneratingStep] = useState(null) // "cid-step" while AI generating

  // Business context per campaign
  const [contextDraft, setContextDraft] = useState({})    // { campaign_id: { description, ... } }
  const [savingContext, setSavingContext] = useState(false)

  // Mailbox add form
  const [showAddMailbox, setShowAddMailbox] = useState(false)
  const [mailboxForm, setMailboxForm] = useState({
    business: "sfw", email: "", display_name: "",
    provider: "smtp",
    // SES fields
    aws_region: "us-east-1", aws_access_key_id: "", aws_secret_access_key: "",
    // SMTP fields
    smtp_host: "smtp.gmail.com", smtp_port: 587, smtp_username: "", smtp_password: "", use_tls: true,
    daily_limit: 400,
  })
  const [addingMailbox, setAddingMailbox] = useState(false)

  // Suppression
  const [suppSearch, setSuppSearch] = useState("")
  const [suppList, setSuppList] = useState([])
  const [suppTotal, setSuppTotal] = useState(0)
  const [manualEmail, setManualEmail] = useState("")

  const flash = (msg) => { setActionMsg(msg); setTimeout(() => setActionMsg(""), 5000) }

  // ── Fetch ──────────────────────────────────────────────────────────────────
  const fetchAll = useCallback(async () => {
    setLoading(true)
    try {
      const [cRes, mRes, sRes] = await Promise.all([
        fetchCampaigns(),
        fetchMailboxes(),
        fetchSuppressionStats(),
      ])
      if (cRes.ok) { const d = await cRes.json(); setCampaigns(d.campaigns || []); setBasketCounts(d.basket_counts || {}); setTotalLeads(d.total_leads || 0) }
      if (mRes.ok) { const d = await mRes.json(); setMailboxes(d.mailboxes || []) }
      if (sRes.ok) { const d = await sRes.json(); setSuppStats(d) }
    } catch (e) {
      console.error("Fetch error", e)
    } finally {
      setLoading(false)
    }
  }, [])

  const fetchSuppression = useCallback(async () => {
    const res = await fetchSuppressionApi(suppSearch)
    if (res.ok) { const d = await res.json(); setSuppList(d.suppressed || []); setSuppTotal(d.total || 0) }
  }, [suppSearch])

  useEffect(() => { fetchAll() }, [fetchAll])
  useEffect(() => {
    if (activeTab === "suppression") fetchSuppression()
  }, [activeTab, suppSearch, fetchSuppression])

  // ── Helpers ────────────────────────────────────────────────────────────────
  const getCampaignForBiz = (bizKey) =>
    campaigns.find(c => c.business === bizKey) || null

  const getStepEdit = (campaignId, stepNum) => {
    const campaign = campaigns.find(c => c.campaign_id === campaignId)
    const stored = campaign?.steps?.find(s => s.step_number === stepNum)
    return editSteps[campaignId]?.[stepNum] ?? {
      subject: stored?.subject || "",
      body_html: stored?.body_html || "",
    }
  }

  const setStepEdit = (campaignId, stepNum, field, value) => {
    setEditSteps(prev => ({
      ...prev,
      [campaignId]: {
        ...(prev[campaignId] || {}),
        [stepNum]: {
          ...getStepEdit(campaignId, stepNum),
          [field]: value,
        },
      },
    }))
  }

  // ── Actions ────────────────────────────────────────────────────────────────
  const createCampaign = async (bizKey) => {
    const res = await createCampaignApi(bizKey)
    if (res.ok) { flash(`Campaign created for ${bizKey}`); fetchAll() }
    else { const d = await res.json(); flash(`Error: ${d.detail}`) }
  }

  const launchCampaign = async (campaignId) => {
    const res = await launchCampaignApi(campaignId)
    if (res.ok) { flash("Campaign launched. Enrollment running…"); fetchAll() }
    else flash("Launch failed")
  }

  const pauseCampaign = async (campaignId) => {
    await pauseCampaignApi(campaignId)
    flash("Campaign paused"); fetchAll()
  }

  const resumeCampaign = async (campaignId) => {
    await resumeCampaignApi(campaignId)
    flash("Campaign resumed"); fetchAll()
  }

  const saveStep = async (campaignId, stepNum) => {
    const data = getStepEdit(campaignId, stepNum)
    if (!data.subject.trim() && !data.body_html.trim()) {
      flash("Add subject and body before saving"); return
    }
    setSavingStep(`${campaignId}-${stepNum}`)
    const res = await saveStepApi(campaignId, stepNum, data.subject, data.body_html)
    setSavingStep(null)
    if (res.ok) { flash(`Step ${stepNum} saved`); fetchAll() }
    else flash("Save failed")
  }

  const sendTestEmail = async (campaignId, stepNum) => {
    const stepKey = `${campaignId}-${stepNum}`
    const recipient = testRecipient[stepKey] || ""
    if (!recipient.trim()) { flash("Enter a recipient email first"); return }
    setSendingTest(stepKey)
    try {
      const res = await sendTestEmailApi(campaignId, stepNum, recipient)
      if (res.ok) {
        const d = await res.json()
        flash(`✓ Test sent to ${d.sent_to} from ${d.from}`)
        setShowTestInput(prev => ({ ...prev, [stepKey]: false }))
      } else {
        const d = await res.json().catch(() => ({}))
        flash(`Send failed: ${d.detail || d.error || "unknown error"}`)
      }
    } catch (err) {
      flash(`Send failed: ${err.message || "network error"}`)
    } finally {
      setSendingTest(null)
    }
  }

  const generateStepWithAI = async (campaignId, stepNum) => {
    const stepKey = `${campaignId}-${stepNum}`
    setGeneratingStep(stepKey)
    const res = await generateStep(campaignId, stepNum)
    setGeneratingStep(null)
    if (res.ok) {
      const d = await res.json()
      setEditSteps(prev => ({
        ...prev,
        [campaignId]: {
          ...(prev[campaignId] || {}),
          [stepNum]: { subject: d.subject, body_html: d.body_html },
        },
      }))
      flash(`✨ Step ${stepNum} generated (${d.tokens_used} tokens) — review and save`)
    } else {
      const d = await res.json().catch(() => ({}))
      flash(`AI generation failed: ${d.detail || "unknown error"}`)
    }
  }

  const getContextDraft = (campaignId) => {
    if (contextDraft[campaignId]) return contextDraft[campaignId]
    const campaign = campaigns.find(c => c.campaign_id === campaignId)
    return campaign?.business_context || { description: "", value_proposition: "", target_customer: "", tone: "professional", sender_name: "", sender_title: "" }
  }

  const setContextField = (campaignId, field, value) => {
    setContextDraft(prev => ({
      ...prev,
      [campaignId]: { ...getContextDraft(campaignId), [field]: value },
    }))
  }

  const saveContext = async (campaignId) => {
    setSavingContext(true)
    const data = getContextDraft(campaignId)
    const res = await saveContextApi(campaignId, data)
    setSavingContext(false)
    if (res.ok) { flash("Business context saved"); fetchAll() }
    else flash("Failed to save context")
  }

  const enrollDualFit = async () => {
    const res = await enrollDualFitApi()
    if (res.ok) flash("Dual Fit enrollment started in background")
    else flash("Enrollment failed")
  }

  const addMailbox = async () => {
    setAddingMailbox(true)
    const res = await addMailboxApi(mailboxForm)
    setAddingMailbox(false)
    if (res.ok) {
      flash("Mailbox added"); setShowAddMailbox(false)
      setMailboxForm({ business: "sfw", email: "", display_name: "", provider: "smtp", aws_region: "us-east-1", aws_access_key_id: "", aws_secret_access_key: "", smtp_host: "smtp.gmail.com", smtp_port: 587, smtp_username: "", smtp_password: "", use_tls: true, daily_limit: 400 })
      fetchAll()
    } else {
      const d = await res.json(); flash(`Error: ${d.detail}`)
    }
  }

  const removeMailbox = async (mid) => {
    if (!window.confirm("Remove this mailbox?")) return
    await removeMailboxApi(mid)
    flash("Mailbox removed"); fetchAll()
  }

  const addSuppression = async () => {
    if (!manualEmail.trim()) return
    const res = await addSuppressionApi(manualEmail)
    if (res.ok) { flash(`${manualEmail} suppressed`); setManualEmail(""); fetchSuppression(); fetchAll() }
    else flash("Failed to suppress")
  }

  const removeSuppression = async (email) => {
    if (!window.confirm(`Remove ${email} from suppression list?`)) return
    await removeSuppressionApi(email)
    flash(`${email} removed from suppression`); fetchSuppression(); fetchAll()
  }

  // ── Render helpers ─────────────────────────────────────────────────────────
  const selectedCampaign = selectedBiz && selectedBiz !== "dual_fit"
    ? getCampaignForBiz(selectedBiz)
    : null

  const bizMailboxes = selectedBiz
    ? mailboxes.filter(m => m.business === (selectedBiz === "dual_fit" ? null : selectedBiz))
    : []

  const statsRate = (num, denom) =>
    denom > 0 ? `${Math.round((num / denom) * 100)}%` : "—"

  if (loading) {
    return (
      <div className="ai-leads-page">
        <div className="loading-container"><div className="loading-spinner" /><span>Loading outreach…</span></div>
      </div>
    )
  }

  return (
    <div className="ai-leads-page">
      {/* ── Header ──────────────────────────────────────────────────────── */}
      <div className="page-header">
        <div className="header-left">
          <h1>Cold Outreach</h1>
          <p className="subtitle">
            {totalLeads.toLocaleString()} AI leads · 4-step sequences · {suppStats.total_suppressed.toLocaleString()} bounced addresses suppressed globally
          </p>
        </div>
      </div>

      {actionMsg && (
        <div style={{
          position: "fixed", top: 20, right: 20, zIndex: 9999, minWidth: 300, maxWidth: 500,
          background: actionMsg.startsWith("✓") || actionMsg.startsWith("✨") ? "#dcfce7" : actionMsg.startsWith("Send failed") || actionMsg.startsWith("Error") ? "#fee2e2" : "#dcfce7",
          border: `1px solid ${actionMsg.startsWith("✓") || actionMsg.startsWith("✨") ? "#86efac" : actionMsg.startsWith("Send failed") || actionMsg.startsWith("Error") ? "#fca5a5" : "#86efac"}`,
          borderRadius: 10, padding: "12px 18px", boxShadow: "0 4px 20px rgba(0,0,0,0.15)",
          color: actionMsg.startsWith("Send failed") || actionMsg.startsWith("Error") ? "#991b1b" : "#166534",
          fontWeight: 500, fontSize: "0.9rem", cursor: "pointer",
        }} onClick={() => setActionMsg("")}>
          {actionMsg}
        </div>
      )}

      {/* ── Business cards ───────────────────────────────────────────────── */}
      <div style={{ display: "grid", gridTemplateColumns: "repeat(4, 1fr)", gap: 16, marginBottom: 24 }}>
        {BUSINESSES.map(biz => {
          const campaign = biz.key === "dual_fit" ? null : getCampaignForBiz(biz.key)
          const stats = campaign?.stats || { enrolled: 0, sent: 0, opened: 0, replied: 0 }
          const basketTotal = basketCounts[biz.basket] || 0
          const isActive = campaign?.is_active
          const isSelected = selectedBiz === biz.key

          return (
            <div
              key={biz.key}
              onClick={() => { setSelectedBiz(biz.key); setActiveTab("templates") }}
              style={{
                background: isSelected ? biz.bg : "#fff",
                border: `2px solid ${isSelected ? biz.border : "#e5e7eb"}`,
                borderRadius: 12, padding: 20, cursor: "pointer",
                transition: "all 0.15s",
              }}
            >
              <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between", marginBottom: 12 }}>
                <div style={{ display: "flex", alignItems: "center", gap: 8 }}>
                  <span style={{ fontSize: 20 }}>{biz.icon}</span>
                  <span style={{ fontWeight: 700, fontSize: "0.95rem", color: "#111827" }}>{biz.label}</span>
                </div>
                <span style={{
                  padding: "2px 8px", borderRadius: 9999, fontSize: "0.7rem", fontWeight: 700,
                  background: biz.bg, color: biz.color, border: `1px solid ${biz.border}`,
                }}>
                  {biz.basket}
                </span>
              </div>

              {biz.key === "dual_fit" ? (
                <div style={{ color: "#6b7280", fontSize: "0.85rem" }}>
                  <div>Enrolled in all 3 sequences</div>
                  <div style={{ marginTop: 4 }}>Score-ordered · 21d gap</div>
                  <div style={{ marginTop: 8, fontWeight: 600, color: "#111827", fontSize: "0.95rem" }}>{basketTotal.toLocaleString()} <span style={{ fontSize: "0.75rem", color: "#6b7280", fontWeight: 400 }}>leads</span></div>
                  <button
                    style={{ marginTop: 12, width: "100%", padding: "8px", borderRadius: 8, border: "none", background: "#0e7490", color: "#fff", fontWeight: 600, cursor: "pointer", fontSize: "0.85rem" }}
                    onClick={(e) => { e.stopPropagation(); enrollDualFit() }}
                  >
                    ⚡ Enroll Dual Fit
                  </button>
                </div>
              ) : (
                <>
                  <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: 8, marginBottom: 12 }}>
                    <Stat label="Enrolled" value={`${stats.enrolled?.toLocaleString()} / ${basketTotal.toLocaleString()}`} />
                    <Stat label="Sent" value={stats.sent?.toLocaleString()} />
                    <Stat label="Open Rate" value={statsRate(stats.opened, stats.sent)} />
                    <Stat label="Reply Rate" value={statsRate(stats.replied, stats.sent)} />
                  </div>

                  <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between" }}>
                    <span style={{
                      padding: "2px 8px", borderRadius: 9999, fontSize: "0.72rem", fontWeight: 600,
                      background: campaign ? (isActive ? "#dcfce7" : "#fef9c3") : "#f3f4f6",
                      color: campaign ? (isActive ? "#15803d" : "#854d0e") : "#6b7280",
                    }}>
                      {campaign ? (isActive ? "● Active" : "⏸ Paused") : "○ Not created"}
                    </span>

                    {!campaign ? (
                      <button
                        style={{ padding: "5px 12px", borderRadius: 6, border: "none", background: "#2563eb", color: "#fff", fontSize: "0.8rem", fontWeight: 600, cursor: "pointer" }}
                        onClick={(e) => { e.stopPropagation(); createCampaign(biz.key) }}
                      >+ Create</button>
                    ) : isActive ? (
                      <button
                        style={{ padding: "5px 12px", borderRadius: 6, border: "1px solid #e5e7eb", background: "#fff", fontSize: "0.8rem", cursor: "pointer" }}
                        onClick={(e) => { e.stopPropagation(); pauseCampaign(campaign.campaign_id) }}
                      >⏸ Pause</button>
                    ) : (
                      <button
                        style={{ padding: "5px 12px", borderRadius: 6, border: "none", background: "#16a34a", color: "#fff", fontSize: "0.8rem", fontWeight: 600, cursor: "pointer" }}
                        onClick={(e) => { e.stopPropagation(); campaign.launched_at ? resumeCampaign(campaign.campaign_id) : launchCampaign(campaign.campaign_id) }}
                      >{campaign.launched_at ? "▶ Resume" : "🚀 Launch"}</button>
                    )}
                  </div>
                </>
              )}
            </div>
          )
        })}
      </div>

      {/* ── Basket breakdown summary ─────────────────────────────────────── */}
      {totalLeads > 0 && (
        <div style={{ display: "flex", gap: 12, marginBottom: 20, flexWrap: "wrap", fontSize: "0.8rem", color: "#6b7280" }}>
          {basketCounts["E"] > 0 && (
            <span style={{ background: "#f3f4f6", padding: "4px 10px", borderRadius: 6 }}>
              Basket E (Nurture): <strong style={{ color: "#374151" }}>{basketCounts["E"].toLocaleString()}</strong>
            </span>
          )}
          {BUSINESSES.map(b => (
            <span key={b.basket} style={{ background: "#f3f4f6", padding: "4px 10px", borderRadius: 6 }}>
              {b.basket}: <strong style={{ color: "#374151" }}>{(basketCounts[b.basket] || 0).toLocaleString()}</strong>
            </span>
          ))}
        </div>
      )}

      {/* ── Detail panel ─────────────────────────────────────────────────── */}
      {selectedBiz && selectedBiz !== "dual_fit" && (
        <div style={{ background: "#fff", border: "1px solid #e5e7eb", borderRadius: 12, overflow: "hidden" }}>
          {/* Tab bar */}
          <div style={{ display: "flex", borderBottom: "1px solid #e5e7eb", background: "#f9fafb" }}>
            {[
              { key: "templates", label: "📝 Templates" },
              { key: "context",   label: "🏢 AI Context" },
              { key: "leads",     label: "📋 Leads" },
              { key: "stats",     label: "📊 Stats" },
              { key: "mailboxes", label: "📬 Mailboxes" },
              { key: "suppression", label: "🚫 Suppression" },
            ].map(t => (
              <button
                key={t.key}
                onClick={() => setActiveTab(t.key)}
                style={{
                  padding: "12px 20px", border: "none", background: "transparent",
                  borderBottom: activeTab === t.key ? "2px solid #2563eb" : "2px solid transparent",
                  color: activeTab === t.key ? "#2563eb" : "#6b7280",
                  fontWeight: activeTab === t.key ? 600 : 400,
                  cursor: "pointer", fontSize: "0.9rem",
                }}
              >{t.label}</button>
            ))}
          </div>

          <div style={{ padding: 24 }}>
            {/* ── Templates tab ──────────────────────────────────────────── */}
            {activeTab === "templates" && (
              <div>
                {!selectedCampaign ? (
                  <div style={{ textAlign: "center", color: "#6b7280", padding: 40 }}>
                    <p>No campaign yet. Click <strong>"+ Create"</strong> on the card above to initialise.</p>
                  </div>
                ) : (
                  <div>
                    <p style={{ color: "#6b7280", fontSize: "0.9rem", marginBottom: 20 }}>
                      Click <strong>✨ Generate with AI</strong> to let GPT-4o-mini write the full email using your business context,
                      or paste your own copy. Tokens replaced per recipient at send time:&nbsp;
                      <code>{"{{first_name}}"}</code> <code>{"{{company}}"}</code> <code>{"{{title}}"}</code> <code>{"{{industry}}"}</code>
                    </p>
                    <div style={{ display: "flex", flexDirection: "column", gap: 24 }}>
                      {[1, 2, 3, 4].map(stepNum => {
                        const stepKey = `${selectedCampaign.campaign_id}-${stepNum}`
                        const data = getStepEdit(selectedCampaign.campaign_id, stepNum)
                        return (
                          <div key={stepNum} style={{ border: "1px solid #e5e7eb", borderRadius: 10, padding: 20 }}>
                            <div style={{ display: "flex", alignItems: "center", gap: 12, marginBottom: 14 }}>
                              <span style={{ background: "#2563eb", color: "#fff", borderRadius: 9999, width: 28, height: 28, display: "flex", alignItems: "center", justifyContent: "center", fontWeight: 700, fontSize: "0.85rem" }}>
                                {stepNum}
                              </span>
                              <span style={{ fontWeight: 600, color: "#111827" }}>Step {stepNum} — Day {STEP_DAYS[stepNum - 1]}</span>
                            </div>
                            <label style={{ fontSize: "0.8rem", color: "#6b7280", fontWeight: 600 }}>SUBJECT</label>
                            <input
                              value={data.subject}
                              onChange={e => setStepEdit(selectedCampaign.campaign_id, stepNum, "subject", e.target.value)}
                              placeholder={`Email ${stepNum} subject line…`}
                              style={{ width: "100%", marginTop: 4, marginBottom: 12, padding: "8px 12px", borderRadius: 8, border: "1px solid #d1d5db", fontSize: "0.9rem", boxSizing: "border-box" }}
                            />
                            <label style={{ fontSize: "0.8rem", color: "#6b7280", fontWeight: 600 }}>BODY (HTML or plain text)</label>
                            <textarea
                              value={data.body_html}
                              onChange={e => setStepEdit(selectedCampaign.campaign_id, stepNum, "body_html", e.target.value)}
                              placeholder={`Hi {{first_name}},\n\nI noticed {{company}} is in the {{industry}} space…`}
                              rows={8}
                              style={{ width: "100%", marginTop: 4, marginBottom: 12, padding: "10px 12px", borderRadius: 8, border: "1px solid #d1d5db", fontSize: "0.85rem", fontFamily: "monospace", resize: "vertical", boxSizing: "border-box" }}
                            />
                            <div style={{ display: "flex", alignItems: "center", gap: 10, flexWrap: "wrap" }}>
                              <button
                                disabled={generatingStep === stepKey}
                                onClick={() => generateStepWithAI(selectedCampaign.campaign_id, stepNum)}
                                style={{ padding: "8px 18px", borderRadius: 8, border: "none", background: generatingStep === stepKey ? "#7c3aed" : "#7c3aed", color: "#fff", fontWeight: 600, cursor: "pointer", fontSize: "0.9rem", opacity: generatingStep === stepKey ? 0.7 : 1, display: "flex", alignItems: "center", gap: 6 }}
                              >
                                {generatingStep === stepKey ? (
                                  <><span style={{ display: "inline-block", width: 14, height: 14, border: "2px solid #fff", borderTopColor: "transparent", borderRadius: "50%", animation: "spin 0.8s linear infinite" }} />Generating…</>
                                ) : "✨ Generate with AI"}
                              </button>
                              <button
                                disabled={savingStep === stepKey}
                                onClick={() => saveStep(selectedCampaign.campaign_id, stepNum)}
                                style={{ padding: "8px 20px", borderRadius: 8, border: "none", background: "#2563eb", color: "#fff", fontWeight: 600, cursor: "pointer", fontSize: "0.9rem", opacity: savingStep === stepKey ? 0.6 : 1 }}
                              >
                                {savingStep === stepKey ? "Saving…" : "💾 Save Step"}
                              </button>
                              <button
                                onClick={() => setShowTestInput(prev => ({ ...prev, [stepKey]: !prev[stepKey] }))}
                                style={{ padding: "8px 16px", borderRadius: 8, border: "1px solid #d1d5db", background: "#fff", color: "#374151", fontWeight: 500, cursor: "pointer", fontSize: "0.85rem" }}
                              >
                                📧 Send Test
                              </button>
                            </div>
                            {showTestInput[stepKey] && (
                              <div style={{ display: "flex", gap: 8, marginTop: 10, alignItems: "center", background: "#fef9c3", padding: "10px 14px", borderRadius: 8, border: "1px solid #fbbf24" }}>
                                <input
                                  type="email"
                                  placeholder="your@email.com"
                                  value={testRecipient[stepKey] || ""}
                                  onChange={e => setTestRecipient(prev => ({ ...prev, [stepKey]: e.target.value }))}
                                  style={{ flex: 1, padding: "7px 12px", borderRadius: 6, border: "1px solid #d1d5db", fontSize: "0.875rem" }}
                                />
                                <button
                                  disabled={sendingTest === stepKey}
                                  onClick={() => sendTestEmail(selectedCampaign.campaign_id, stepNum)}
                                  style={{ padding: "7px 16px", borderRadius: 6, border: "none", background: "#d97706", color: "#fff", fontWeight: 600, cursor: "pointer", fontSize: "0.85rem", opacity: sendingTest === stepKey ? 0.6 : 1 }}
                                >
                                  {sendingTest === stepKey ? "Sending…" : "Send"}
                                </button>
                              </div>
                            )}
                          </div>
                        )
                      })}
                    </div>
                  </div>
                )}
              </div>
            )}

            {/* ── Context tab ───────────────────────────────────────────── */}
            {activeTab === "context" && (
              <ContextPanel
                campaign={selectedCampaign}
                draft={getContextDraft(selectedCampaign?.campaign_id)}
                onChange={(field, val) => setContextField(selectedCampaign?.campaign_id, field, val)}
                onSave={() => saveContext(selectedCampaign?.campaign_id)}
                saving={savingContext}
              />
            )}

            {/* ── Leads by status tab ──────────────────────────────────── */}
            {activeTab === "leads" && (
              <LeadsByStatusPanel campaignId={selectedCampaign?.campaign_id} />
            )}

            {/* ── Stats tab ──────────────────────────────────────────────── */}
            {activeTab === "stats" && (
              <StatsPanel campaignId={selectedCampaign?.campaign_id} campaign={selectedCampaign} />
            )}

            {/* ── Mailboxes tab ──────────────────────────────────────────── */}
            {activeTab === "mailboxes" && (
              <div>
                <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", marginBottom: 16 }}>
                  <p style={{ color: "#6b7280", fontSize: "0.9rem", margin: 0 }}>
                    Mailboxes for <strong>{BUSINESSES.find(b => b.key === selectedBiz)?.label}</strong>.
                    Need 5 mailboxes at 400/day to hit 2000/day.
                  </p>
                  <button
                    onClick={() => setShowAddMailbox(v => !v)}
                    style={{ padding: "8px 16px", borderRadius: 8, border: "none", background: "#2563eb", color: "#fff", fontWeight: 600, cursor: "pointer" }}
                  >+ Add Mailbox</button>
                </div>

                {showAddMailbox && (
                  <div style={{ background: "#f9fafb", border: "1px solid #e5e7eb", borderRadius: 10, padding: 20, marginBottom: 20 }}>
                    <h4 style={{ margin: "0 0 16px", color: "#111827" }}>Add Mailbox</h4>

                    {/* Provider selector */}
                    <div style={{ marginBottom: 16 }}>
                      <label style={{ fontSize: "0.8rem", color: "#6b7280", fontWeight: 600 }}>SENDING PROVIDER</label>
                      <select
                        value={mailboxForm.provider}
                        onChange={e => setMailboxForm(f => ({ ...f, provider: e.target.value }))}
                        style={{ width: "100%", marginTop: 4, padding: "8px 12px", borderRadius: 8, border: "1px solid #d1d5db", fontSize: "0.85rem", boxSizing: "border-box" }}
                      >
                        <option value="smtp">SMTP / Gmail Workspace</option>
                        <option value="ses">AWS SES</option>
                      </select>
                    </div>

                    <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: 12 }}>
                      {/* Common fields */}
                      {[
                        ["Email address", "email", "text", "sender@domain.com"],
                        ["Display name", "display_name", "text", "First Last"],
                      ].map(([label, field, type, ph]) => (
                        <div key={field}>
                          <label style={{ fontSize: "0.8rem", color: "#6b7280", fontWeight: 600 }}>{label.toUpperCase()}</label>
                          <input
                            type={type} placeholder={ph} value={mailboxForm[field]}
                            onChange={e => setMailboxForm(f => ({ ...f, [field]: e.target.value }))}
                            style={{ width: "100%", marginTop: 4, padding: "8px 12px", borderRadius: 8, border: "1px solid #d1d5db", fontSize: "0.85rem", boxSizing: "border-box" }}
                          />
                        </div>
                      ))}

                      {/* SES-specific fields */}
                      {mailboxForm.provider === "ses" && [
                        ["AWS region", "aws_region", "text", "us-east-1"],
                        ["Access key ID (blank = use IAM role)", "aws_access_key_id", "text", "AKIA…"],
                        ["Secret access key (blank = use IAM role)", "aws_secret_access_key", "password", ""],
                      ].map(([label, field, type, ph]) => (
                        <div key={field}>
                          <label style={{ fontSize: "0.8rem", color: "#6b7280", fontWeight: 600 }}>{label.toUpperCase()}</label>
                          <input
                            type={type} placeholder={ph} value={mailboxForm[field]}
                            onChange={e => setMailboxForm(f => ({ ...f, [field]: e.target.value }))}
                            style={{ width: "100%", marginTop: 4, padding: "8px 12px", borderRadius: 8, border: "1px solid #d1d5db", fontSize: "0.85rem", boxSizing: "border-box" }}
                          />
                        </div>
                      ))}

                      {/* SMTP-specific fields */}
                      {mailboxForm.provider === "smtp" && [
                        ["SMTP host", "smtp_host", "text", "smtp.gmail.com"],
                        ["SMTP port", "smtp_port", "number", "587"],
                        ["SMTP username", "smtp_username", "text", "same as email"],
                        ["SMTP password / app password", "smtp_password", "password", ""],
                      ].map(([label, field, type, ph]) => (
                        <div key={field}>
                          <label style={{ fontSize: "0.8rem", color: "#6b7280", fontWeight: 600 }}>{label.toUpperCase()}</label>
                          <input
                            type={type} placeholder={ph}
                            value={mailboxForm[field]}
                            onChange={e => setMailboxForm(f => ({ ...f, [field]: type === "number" ? Number(e.target.value) : e.target.value }))}
                            style={{ width: "100%", marginTop: 4, padding: "8px 12px", borderRadius: 8, border: "1px solid #d1d5db", fontSize: "0.85rem", boxSizing: "border-box" }}
                          />
                        </div>
                      ))}

                      <div>
                        <label style={{ fontSize: "0.8rem", color: "#6b7280", fontWeight: 600 }}>BUSINESS</label>
                        <select
                          value={mailboxForm.business}
                          onChange={e => setMailboxForm(f => ({ ...f, business: e.target.value }))}
                          style={{ width: "100%", marginTop: 4, padding: "8px 12px", borderRadius: 8, border: "1px solid #d1d5db", fontSize: "0.85rem", boxSizing: "border-box" }}
                        >
                          <option value="sfw">Survey Fieldwork</option>
                          <option value="cogentix">Cogentix Research</option>
                          <option value="bimwave">BIMwave</option>
                        </select>
                      </div>
                      <div>
                        <label style={{ fontSize: "0.8rem", color: "#6b7280", fontWeight: 600 }}>DAILY LIMIT</label>
                        <input
                          type="number" value={mailboxForm.daily_limit}
                          onChange={e => setMailboxForm(f => ({ ...f, daily_limit: Number(e.target.value) }))}
                          style={{ width: "100%", marginTop: 4, padding: "8px 12px", borderRadius: 8, border: "1px solid #d1d5db", fontSize: "0.85rem", boxSizing: "border-box" }}
                        />
                      </div>
                    </div>
                    <div style={{ display: "flex", gap: 8, marginTop: 16 }}>
                      <button onClick={addMailbox} disabled={addingMailbox} style={{ padding: "8px 20px", borderRadius: 8, border: "none", background: "#16a34a", color: "#fff", fontWeight: 600, cursor: "pointer" }}>
                        {addingMailbox ? "Adding…" : "✓ Add Mailbox"}
                      </button>
                      <button onClick={() => setShowAddMailbox(false)} style={{ padding: "8px 16px", borderRadius: 8, border: "1px solid #e5e7eb", background: "#fff", cursor: "pointer" }}>
                        Cancel
                      </button>
                    </div>
                  </div>
                )}

                <MailboxTable mailboxes={mailboxes} filterBiz={selectedBiz} onRemove={removeMailbox} />
              </div>
            )}

            {/* ── Suppression tab ────────────────────────────────────────── */}
            {activeTab === "suppression" && (
              <SuppressionPanel
                suppList={suppList} suppTotal={suppTotal}
                suppSearch={suppSearch} setSuppSearch={setSuppSearch}
                manualEmail={manualEmail} setManualEmail={setManualEmail}
                onAdd={addSuppression} onRemove={removeSuppression}
                totalSuppressed={suppStats.total_suppressed}
              />
            )}
          </div>
        </div>
      )}

      {/* ── Suppression panel (available when no biz selected) ─────────── */}
      {!selectedBiz && (
        <div style={{ background: "#fff", border: "1px solid #e5e7eb", borderRadius: 12, padding: 24 }}>
          <div style={{ display: "flex", alignItems: "center", gap: 12, marginBottom: 16 }}>
            <span style={{ fontSize: 24 }}>🚫</span>
            <div>
              <h3 style={{ margin: 0, color: "#111827" }}>Global Bounce Suppression</h3>
              <p style={{ margin: 0, color: "#6b7280", fontSize: "0.9rem" }}>
                {suppStats.total_suppressed.toLocaleString()} addresses permanently blocked from all businesses
              </p>
            </div>
          </div>
          <p style={{ color: "#6b7280", fontSize: "0.875rem" }}>
            Select a business card above to manage its campaigns, mailboxes, and templates.
          </p>
        </div>
      )}
    </div>
  )
}

// ─────────────────────────────────────────────────────────────────────────────
// Sub-components
// ─────────────────────────────────────────────────────────────────────────────

function Stat({ label, value }) {
  return (
    <div style={{ textAlign: "center" }}>
      <div style={{ fontWeight: 700, fontSize: "1.1rem", color: "#111827" }}>{value ?? "—"}</div>
      <div style={{ fontSize: "0.72rem", color: "#6b7280", textTransform: "uppercase", letterSpacing: "0.05em" }}>{label}</div>
    </div>
  )
}

function StatsPanel({ campaignId, campaign }) {
  const [stats, setStats] = useState(null)
  const [loading, setLoading] = useState(false)

  useEffect(() => {
    if (!campaignId) return
    setLoading(true)
    fetchCampaignStats(campaignId)
      .then(r => r.ok ? r.json() : null)
      .then(d => { if (d) setStats(d) })
      .finally(() => setLoading(false))
  }, [campaignId])

  if (!campaignId) return <p style={{ color: "#6b7280" }}>Create a campaign first.</p>
  if (loading) return <div className="loading-container"><div className="loading-spinner" /></div>
  if (!stats) return <p style={{ color: "#6b7280" }}>No stats yet.</p>

  const o = stats.overall
  return (
    <div>
      <div style={{ display: "grid", gridTemplateColumns: "repeat(5, 1fr)", gap: 16, marginBottom: 24 }}>
        {[
          ["Enrolled", o.enrolled],
          ["Sent", o.total_sent],
          ["Open Rate", `${o.open_rate}%`],
          ["Reply Rate", `${o.reply_rate}%`],
          ["Bounce Rate", `${o.bounce_rate}%`],
        ].map(([label, val]) => (
          <div key={label} style={{ background: "#f9fafb", borderRadius: 10, padding: 16, textAlign: "center" }}>
            <div style={{ fontWeight: 700, fontSize: "1.3rem", color: "#111827" }}>{val ?? "—"}</div>
            <div style={{ fontSize: "0.75rem", color: "#6b7280", marginTop: 4 }}>{label}</div>
          </div>
        ))}
      </div>

      <h4 style={{ color: "#111827", marginBottom: 12 }}>Per-step breakdown</h4>
      <table className="data-table" style={{ width: "100%" }}>
        <thead>
          <tr>
            <th>Step</th><th>Day</th><th>Sent</th><th>Opened</th><th>Replied</th><th>Bounced</th><th>Open %</th><th>Reply %</th>
          </tr>
        </thead>
        <tbody>
          {(stats.by_step || []).map(s => (
            <tr key={s.step_number}>
              <td>{s.step_number}</td>
              <td>Day {s.day_offset + 1}</td>
              <td>{s.sent}</td>
              <td>{s.opened}</td>
              <td>{s.replied}</td>
              <td>{s.bounced}</td>
              <td>{s.open_rate}%</td>
              <td>{s.reply_rate}%</td>
            </tr>
          ))}
          {(stats.by_step || []).length === 0 && (
            <tr><td colSpan={8} style={{ textAlign: "center", color: "#9ca3af" }}>No sends yet</td></tr>
          )}
        </tbody>
      </table>
    </div>
  )
}

function MailboxTable({ mailboxes, filterBiz, onRemove }) {
  const filtered = filterBiz ? mailboxes.filter(m => m.business === filterBiz) : mailboxes
  if (filtered.length === 0)
    return <p style={{ color: "#6b7280" }}>No mailboxes configured yet. Add one above.</p>

  return (
    <table className="data-table" style={{ width: "100%" }}>
      <thead>
        <tr><th>Email</th><th>Display name</th><th>Daily limit</th><th>Sent today</th><th>Health</th><th></th></tr>
      </thead>
      <tbody>
        {filtered.map(m => (
          <tr key={m.mailbox_id || m.id}>
            <td style={{ fontFamily: "monospace", fontSize: "0.85rem" }}>{m.email_address}</td>
            <td>{m.display_name}</td>
            <td>{m.daily_limit}</td>
            <td>{m.daily_sent_count ?? 0}</td>
            <td>
              <span style={{ padding: "2px 8px", borderRadius: 9999, fontSize: "0.75rem", fontWeight: 600, background: m.health_status === "healthy" ? "#dcfce7" : "#fee2e2", color: m.health_status === "healthy" ? "#15803d" : "#dc2626" }}>
                {m.health_status || "unknown"}
              </span>
            </td>
            <td>
              <button onClick={() => onRemove(m.mailbox_id || m.id)} style={{ background: "none", border: "none", color: "#ef4444", cursor: "pointer", fontSize: "0.85rem" }}>Remove</button>
            </td>
          </tr>
        ))}
      </tbody>
    </table>
  )
}

function LeadsByStatusPanel({ campaignId }) {
  const [sends, setSends] = useState([])
  const [summary, setSummary] = useState({})
  const [loading, setLoading] = useState(false)
  const [statusFilter, setStatusFilter] = useState("all")
  const [page, setPage] = useState(1)
  const [totalPages, setTotalPages] = useState(1)
  const [total, setTotal] = useState(0)

  useEffect(() => {
    if (!campaignId) return
    setLoading(true)
    const params = new URLSearchParams({ status: statusFilter, page: String(page), limit: "50" })
    fetchLeadsByStatusApi(campaignId, statusFilter, page)
      .then(r => r.ok ? r.json() : null)
      .then(d => {
        if (d) {
          setSends(d.sends || [])
          setSummary(d.summary || {})
          setTotalPages(d.pages || 1)
          setTotal(d.total || 0)
        }
      })
      .finally(() => setLoading(false))
  }, [campaignId, statusFilter, page])

  if (!campaignId) return <p style={{ color: "#6b7280" }}>Create a campaign first.</p>

  const STATUS_TABS = [
    { key: "all",        label: "All",        count: summary.total_sent,  color: "#6b7280", bg: "#f3f4f6" },
    { key: "opened",     label: "Opened",     count: summary.opened,     color: "#059669", bg: "#d1fae5" },
    { key: "not_opened", label: "Not Opened", count: summary.not_opened, color: "#d97706", bg: "#fef3c7" },
    { key: "bounced",    label: "Bounced",    count: summary.bounced,    color: "#dc2626", bg: "#fee2e2" },
    { key: "replied",    label: "Replied",    count: summary.replied,    color: "#2563eb", bg: "#dbeafe" },
  ]

  return (
    <div>
      {/* Status filter badges */}
      <div style={{ display: "flex", gap: 8, marginBottom: 16, flexWrap: "wrap" }}>
        {STATUS_TABS.map(t => (
          <button
            key={t.key}
            onClick={() => { setStatusFilter(t.key); setPage(1) }}
            style={{
              padding: "6px 14px", borderRadius: 9999, border: "none", cursor: "pointer",
              fontSize: "0.8rem", fontWeight: statusFilter === t.key ? 700 : 500,
              background: statusFilter === t.key ? t.bg : "#f9fafb",
              color: statusFilter === t.key ? t.color : "#6b7280",
              outline: statusFilter === t.key ? `2px solid ${t.color}` : "1px solid #e5e7eb",
            }}
          >
            {t.label} {t.count != null ? `(${t.count})` : ""}
          </button>
        ))}
      </div>

      {loading ? (
        <div className="loading-container"><div className="loading-spinner" /></div>
      ) : sends.length === 0 ? (
        <p style={{ textAlign: "center", color: "#9ca3af", padding: 32 }}>No emails matching this filter.</p>
      ) : (
        <>
          <table className="data-table" style={{ width: "100%" }}>
            <thead>
              <tr>
                <th>Email</th>
                <th>Step</th>
                <th>Subject</th>
                <th>Status</th>
                <th>Opens</th>
                <th>Clicks</th>
                <th>Replied</th>
                <th>Sent At</th>
              </tr>
            </thead>
            <tbody>
              {sends.map(s => {
                const isOpen = (s.open_count || 0) > 0
                const isBounce = s.status === "bounced"
                const isReply = s.reply_received
                const statusLabel = isBounce ? "Bounced" : isReply ? "Replied" : isOpen ? "Opened" : "Not Opened"
                const statusColor = isBounce ? "#dc2626" : isReply ? "#2563eb" : isOpen ? "#059669" : "#d97706"
                const statusBg = isBounce ? "#fee2e2" : isReply ? "#dbeafe" : isOpen ? "#d1fae5" : "#fef3c7"
                return (
                  <tr key={s._id}>
                    <td style={{ fontFamily: "monospace", fontSize: "0.85rem" }}>{s.email}</td>
                    <td>Step {(s.workflow_step || 0) + 1}</td>
                    <td style={{ maxWidth: 250, overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}>{s.subject || "—"}</td>
                    <td>
                      <span style={{ padding: "2px 8px", borderRadius: 9999, fontSize: "0.75rem", fontWeight: 600, background: statusBg, color: statusColor }}>
                        {statusLabel}
                      </span>
                    </td>
                    <td>{s.open_count || 0}</td>
                    <td>{s.click_count || 0}</td>
                    <td>{isReply ? <span style={{ color: "#2563eb" }}>✓ {s.reply_snippet ? s.reply_snippet.slice(0, 60) + "…" : "Yes"}</span> : "—"}</td>
                    <td style={{ fontSize: "0.8rem", color: "#6b7280" }}>{s.created_at ? new Date(s.created_at).toLocaleString() : "—"}</td>
                  </tr>
                )
              })}
            </tbody>
          </table>

          {/* Pagination */}
          {totalPages > 1 && (
            <div style={{ display: "flex", justifyContent: "center", gap: 8, marginTop: 16, alignItems: "center" }}>
              <button disabled={page <= 1} onClick={() => setPage(p => p - 1)} style={{ padding: "6px 14px", borderRadius: 6, border: "1px solid #e5e7eb", cursor: page <= 1 ? "not-allowed" : "pointer", opacity: page <= 1 ? 0.5 : 1, background: "#fff" }}>←</button>
              <span style={{ fontSize: "0.85rem", color: "#374151" }}>Page {page} of {totalPages} ({total} total)</span>
              <button disabled={page >= totalPages} onClick={() => setPage(p => p + 1)} style={{ padding: "6px 14px", borderRadius: 6, border: "1px solid #e5e7eb", cursor: page >= totalPages ? "not-allowed" : "pointer", opacity: page >= totalPages ? 0.5 : 1, background: "#fff" }}>→</button>
            </div>
          )}
        </>
      )}
    </div>
  )
}

function ContextPanel({ campaign, draft, onChange, onSave, saving }) {
  if (!campaign) return <p style={{ color: "#6b7280" }}>Create a campaign first.</p>

  const TONE_OPTIONS = ["professional", "friendly", "direct", "conversational"]

  const fields = [
    { key: "description",       label: "What does this business do?",         rows: 3, ph: "We are a market research firm specialising in consumer insights across South Asia…" },
    { key: "value_proposition", label: "Value proposition (1–2 sentences)",   rows: 2, ph: "We help brands cut research costs by 40% with our proprietary panel network…" },
    { key: "target_customer",   label: "Ideal customer / target persona",      rows: 2, ph: "VP of Research, Head of Insights, or CMO at FMCG / pharma / retail companies…" },
  ]

  return (
    <div>
      <div style={{ background: "#eff6ff", border: "1px solid #bfdbfe", borderRadius: 10, padding: 16, marginBottom: 24 }}>
        <strong style={{ color: "#1e40af" }}>🤖 AI uses this context</strong>
        <p style={{ margin: "6px 0 0", color: "#374151", fontSize: "0.875rem" }}>
          When generating icebreakers or personalising email copy, the AI will draw on this information
          to write in the right voice, reference the right value, and speak to the right buyer.
          Fill in as much as you can — more detail = better emails.
        </p>
      </div>

      <div style={{ display: "flex", flexDirection: "column", gap: 20 }}>
        {fields.map(({ key, label, rows, ph }) => (
          <div key={key}>
            <label style={{ fontSize: "0.8rem", color: "#6b7280", fontWeight: 600, display: "block", marginBottom: 6 }}>
              {label.toUpperCase()}
            </label>
            <textarea
              rows={rows}
              value={draft[key] || ""}
              onChange={e => onChange(key, e.target.value)}
              placeholder={ph}
              style={{ width: "100%", padding: "10px 12px", borderRadius: 8, border: "1px solid #d1d5db", fontSize: "0.875rem", resize: "vertical", boxSizing: "border-box" }}
            />
          </div>
        ))}

        <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr 1fr", gap: 16 }}>
          <div>
            <label style={{ fontSize: "0.8rem", color: "#6b7280", fontWeight: 600, display: "block", marginBottom: 6 }}>SENDER NAME</label>
            <input
              value={draft.sender_name || ""}
              onChange={e => onChange("sender_name", e.target.value)}
              placeholder="e.g. Indira Sharma"
              style={{ width: "100%", padding: "8px 12px", borderRadius: 8, border: "1px solid #d1d5db", fontSize: "0.875rem", boxSizing: "border-box" }}
            />
          </div>
          <div>
            <label style={{ fontSize: "0.8rem", color: "#6b7280", fontWeight: 600, display: "block", marginBottom: 6 }}>SENDER TITLE</label>
            <input
              value={draft.sender_title || ""}
              onChange={e => onChange("sender_title", e.target.value)}
              placeholder="e.g. Head of Partnerships"
              style={{ width: "100%", padding: "8px 12px", borderRadius: 8, border: "1px solid #d1d5db", fontSize: "0.875rem", boxSizing: "border-box" }}
            />
          </div>
          <div>
            <label style={{ fontSize: "0.8rem", color: "#6b7280", fontWeight: 600, display: "block", marginBottom: 6 }}>EMAIL TONE</label>
            <select
              value={draft.tone || "professional"}
              onChange={e => onChange("tone", e.target.value)}
              style={{ width: "100%", padding: "8px 12px", borderRadius: 8, border: "1px solid #d1d5db", fontSize: "0.875rem", boxSizing: "border-box" }}
            >
              {TONE_OPTIONS.map(t => <option key={t} value={t}>{t.charAt(0).toUpperCase() + t.slice(1)}</option>)}
            </select>
          </div>
        </div>

        <div>
          <button
            onClick={onSave}
            disabled={saving}
            style={{ padding: "10px 28px", borderRadius: 8, border: "none", background: "#2563eb", color: "#fff", fontWeight: 600, cursor: "pointer", fontSize: "0.9rem", opacity: saving ? 0.6 : 1 }}
          >
            {saving ? "Saving…" : "💾 Save Context"}
          </button>
        </div>
      </div>
    </div>
  )
}

function SuppressionPanel({ suppList, suppTotal, suppSearch, setSuppSearch, manualEmail, setManualEmail, onAdd, onRemove, totalSuppressed }) {
  return (
    <div>
      <div style={{ background: "#fef2f2", border: "1px solid #fca5a5", borderRadius: 10, padding: 16, marginBottom: 20 }}>
        <strong style={{ color: "#dc2626" }}>🚫 {totalSuppressed.toLocaleString()} addresses</strong>
        <span style={{ color: "#6b7280", marginLeft: 8, fontSize: "0.9rem" }}>permanently blocked from ALL businesses. These will never receive email again.</span>
      </div>

      <div style={{ display: "flex", gap: 12, marginBottom: 16 }}>
        <input
          type="text" placeholder="Search suppressed addresses…" value={suppSearch}
          onChange={e => setSuppSearch(e.target.value)}
          style={{ flex: 1, padding: "8px 12px", borderRadius: 8, border: "1px solid #d1d5db", fontSize: "0.9rem" }}
        />
        <input
          type="email" placeholder="Manually suppress email…" value={manualEmail}
          onChange={e => setManualEmail(e.target.value)}
          style={{ flex: 1, padding: "8px 12px", borderRadius: 8, border: "1px solid #d1d5db", fontSize: "0.9rem" }}
        />
        <button onClick={onAdd} style={{ padding: "8px 16px", borderRadius: 8, border: "none", background: "#ef4444", color: "#fff", fontWeight: 600, cursor: "pointer" }}>
          + Suppress
        </button>
      </div>

      <p style={{ color: "#6b7280", fontSize: "0.85rem", marginBottom: 12 }}>
        Showing {suppList.length} of {suppTotal} · {suppSearch ? "filtered" : "latest first"}
      </p>

      <table className="data-table" style={{ width: "100%" }}>
        <thead><tr><th>Email</th><th>Bounced at</th><th>Reason</th><th></th></tr></thead>
        <tbody>
          {suppList.map(s => (
            <tr key={s.id || s.email}>
              <td style={{ fontFamily: "monospace", fontSize: "0.85rem" }}>{s.email}</td>
              <td style={{ fontSize: "0.85rem" }}>{s.bounced_at ? new Date(s.bounced_at).toLocaleDateString() : "—"}</td>
              <td><span style={{ padding: "2px 6px", background: "#fee2e2", color: "#dc2626", borderRadius: 4, fontSize: "0.75rem" }}>{s.reason || "bounce"}</span></td>
              <td><button onClick={() => onRemove(s.email)} style={{ background: "none", border: "none", color: "#6b7280", cursor: "pointer", fontSize: "0.8rem" }}>Undo</button></td>
            </tr>
          ))}
          {suppList.length === 0 && (
            <tr><td colSpan={4} style={{ textAlign: "center", color: "#9ca3af", padding: 24 }}>No suppressed addresses{suppSearch ? " matching search" : ""}</td></tr>
          )}
        </tbody>
      </table>
    </div>
  )
}

export default Outreach
