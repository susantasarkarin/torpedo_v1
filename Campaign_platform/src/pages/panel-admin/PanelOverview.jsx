import { useEffect, useState } from "react"
import { useNavigate } from "react-router-dom"
import { buildApiUrl } from "../../config"
import { authFetch } from "../../utils/api"
import { PageShell, Tabs, StatTile, TileRow } from "../../components/panel-admin/ui"
import { useTab, card, td, colors } from "../../components/panel-admin/tokens"
import MemberFunnel from "./MemberFunnel"

const API = "/api/panel-admin"

async function getJson(path) {
  const res = await authFetch(buildApiUrl(`${API}${path}`), { headers: { Authorization: localStorage.getItem("session_id") } })
  if (!res.ok) throw new Error(`${path}: HTTP ${res.status}`)
  return res.json()
}

const TABS = [
  { key: "summary", label: "Summary" },
  { key: "funnel", label: "Member funnel" },
]

/**
 * Overview — the Panel at a glance: headline numbers, the biggest roadblocks
 * in the member journey, and anything that needs action today.
 */
export default function PanelOverview() {
  const [tab, setTab] = useTab(TABS)
  const navigate = useNavigate()
  const [funnel, setFunnel] = useState(null)
  const [overview, setOverview] = useState(null)
  const [rewards, setRewards] = useState(null)
  const [flags, setFlags] = useState(null)
  const [alerts, setAlerts] = useState(null)
  const [errors, setErrors] = useState([])

  useEffect(() => {
    const load = (path, set) => getJson(path).then(set).catch((e) => setErrors((x) => [...x, e.message]))
    load("/member-funnel", setFunnel)
    load("/dashboard/sfwpanel-overview", setOverview)
    load("/panel-rewards", setRewards)
    load("/profiling/flags", setFlags)
    load("/overview-alerts", setAlerts)
  }, [])

  const stage = (key) => funnel?.stages?.find((s) => s.key === key)?.reached ?? "…"
  const flagCount = flags?.members?.length ?? 0
  const toSend = rewards?.totals?.toSend ?? 0
  const securityToday = alerts?.securityTermsToday ?? 0

  const actionItems = [
    toSend > 0 && { text: `${toSend} gift card${toSend === 1 ? "" : "s"} to send`, go: "/admin/panel-admin/rewards", tone: colors.bad },
    flagCount > 0 && { text: `${flagCount} profile${flagCount === 1 ? "" : "s"} flagged for quality review`, go: "/admin/panel-admin/profiling", tone: colors.warn },
    securityToday > 0 && { text: `${securityToday} security-check termination${securityToday === 1 ? "" : "s"} today (${alerts.securityTermsWeek} this week)`, go: null, tone: colors.warn },
  ].filter(Boolean)

  return (
    <PageShell title="Overview" description="The SurveyFieldwork Panel at a glance — members, the member journey, and what needs action.">
      <Tabs tabs={TABS} active={tab} onChange={setTab} />
      {errors.length > 0 && <div style={{ ...card, color: colors.bad, fontSize: "0.85rem" }}>Some numbers could not load: {errors.join(" · ")}</div>}

      {tab === "funnel" && <MemberFunnel embedded />}

      {tab === "summary" && (
        <>
          <TileRow>
            <StatTile label="Panel members" value={funnel?.total ?? "…"} sub={overview ? `${overview.users.this_week} joined this week` : ""} onClick={() => navigate("/admin/panel-admin/members")} />
            <StatTile label="Quick start done" value={stage("quickDone")} sub="profile ready for matching" />
            <StatTile label="Active in 7 days" value={overview?.users?.active_week ?? "…"} sub="logged in or answered" />
            <StatTile label="Completed a survey" value={stage("completed")} sub={`${stage("repeat")} with 2+ completes`} color={colors.good} />
            <StatTile label="Points owed" value={rewards ? rewards.totals.balancePoints.toLocaleString() : "…"} sub="in member balances" onClick={() => navigate("/admin/panel-admin/rewards")} />
          </TileRow>

          <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fit, minmax(320px, 1fr))", gap: "1.25rem" }}>
            <div style={{ ...card, marginBottom: 0 }}>
              <h3 style={{ margin: "0 0 0.75rem", fontSize: "1rem" }}>Needs action</h3>
              {actionItems.length === 0 ? (
                <p style={{ margin: 0, color: colors.muted, fontSize: "0.875rem" }}>Nothing waiting — all clear.</p>
              ) : actionItems.map((a) => (
                <div key={a.text} onClick={() => a.go && navigate(a.go)} role={a.go ? "button" : undefined}
                  style={{ display: "flex", alignItems: "center", gap: "0.6rem", padding: "0.6rem 0", borderBottom: "1px solid #f3f4f6", cursor: a.go ? "pointer" : "default" }}>
                  <span style={{ width: 8, height: 8, borderRadius: 999, background: a.tone, flexShrink: 0 }} />
                  <span style={{ fontSize: "0.9rem" }}>{a.text}</span>
                  {a.go && <span style={{ marginLeft: "auto", color: colors.accent, fontSize: "0.8rem" }}>Open →</span>}
                </div>
              ))}
            </div>

            <div style={{ ...card, marginBottom: 0 }}>
              <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", marginBottom: "0.75rem" }}>
                <h3 style={{ margin: 0, fontSize: "1rem" }}>Biggest roadblocks</h3>
                <button type="button" onClick={() => setTab("funnel")} style={{ border: "none", background: "none", color: colors.accent, cursor: "pointer", fontSize: "0.8rem" }}>Full funnel →</button>
              </div>
              {!funnel ? <p style={{ margin: 0, color: colors.muted }}>Loading…</p> : (
                <table style={{ width: "100%", borderCollapse: "collapse" }}>
                  <tbody>
                    {funnel.roadblocks.map((r, i) => (
                      <tr key={r.key}>
                        <td style={{ ...td, width: 24, color: i === 0 ? colors.bad : colors.warn, fontWeight: 700 }}>{i + 1}</td>
                        <td style={td}>{r.label}</td>
                        <td style={{ ...td, textAlign: "right", fontWeight: 700 }}>{r.members}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              )}
            </div>
          </div>

          {funnel && (
            <div style={{ ...card, marginTop: "1.25rem" }}>
              <h3 style={{ margin: "0 0 0.75rem", fontSize: "1rem" }}>Member journey</h3>
              <div style={{ display: "flex", gap: "0.5rem", flexWrap: "wrap" }}>
                {funnel.stages.map((s, i) => (
                  <div key={s.key} style={{ flex: "1 1 110px", background: "#f9fafb", borderRadius: 8, padding: "0.6rem 0.75rem" }}>
                    <div style={{ fontSize: "1.1rem", fontWeight: 700 }}>{s.reached}</div>
                    <div style={{ fontSize: "0.75rem", color: colors.muted }}>{s.label}</div>
                    {i > 0 && <div style={{ fontSize: "0.7rem", color: s.pctOfPrevious >= 70 ? colors.good : s.pctOfPrevious >= 40 ? colors.warn : colors.bad }}>{s.pctOfPrevious}% of previous</div>}
                  </div>
                ))}
              </div>
            </div>
          )}
        </>
      )}
    </PageShell>
  )
}
