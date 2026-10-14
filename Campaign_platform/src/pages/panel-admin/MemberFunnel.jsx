import { useCallback, useEffect, useState } from "react"
import { buildApiUrl } from "../../config"
import { authFetch } from "../../utils/api"

const PANEL_ADMIN_API_PREFIX = "/api/panel-admin"

/**
 * Member funnel — where every SurveyFieldwork Panel member stands, from signup
 * to redeeming points, and the stages that lose the most members.
 */

const card = { background: "#fff", border: "1px solid #e5e7eb", borderRadius: "10px", padding: "1.25rem", marginBottom: "1.25rem" }
const th = { textAlign: "left", padding: "0.5rem 0.6rem", fontSize: "0.8rem", color: "#4b5563", borderBottom: "1px solid #e5e7eb", whiteSpace: "nowrap" }
const td = { padding: "0.5rem 0.6rem", fontSize: "0.875rem", color: "#1a1a1a", borderBottom: "1px solid #f3f4f6" }
const select = { padding: "0.4rem 0.6rem", borderRadius: "8px", border: "1px solid #d1d5db", fontSize: "0.85rem", background: "#fff" }

const COUNTRY_LABELS = { IN: "India", UK: "United Kingdom", GB: "United Kingdom", US: "United States", "??": "Unknown" }
const PERIODS = [
  { value: 0, label: "All members" },
  { value: 7, label: "Joined in the last 7 days" },
  { value: 30, label: "Joined in the last 30 days" },
  { value: 90, label: "Joined in the last 90 days" },
]

// Colour a stage-to-stage conversion: green healthy, amber weak, red roadblock.
const tone = (pct) => (pct >= 70 ? "#059669" : pct >= 40 ? "#d97706" : "#dc2626")

export default function MemberFunnel({ embedded = false }) {
  const [country, setCountry] = useState("")
  const [days, setDays] = useState(0)
  const [data, setData] = useState(null)
  const [error, setError] = useState("")
  const [loading, setLoading] = useState(false)

  const load = useCallback(async () => {
    setLoading(true)
    setError("")
    try {
      const qs = new URLSearchParams({ country, days: String(days) })
      const res = await authFetch(buildApiUrl(`${PANEL_ADMIN_API_PREFIX}/member-funnel?${qs}`), {
        headers: { Authorization: localStorage.getItem("session_id") },
      })
      const body = await res.json().catch(() => ({}))
      if (!res.ok) throw new Error(body.detail || `HTTP ${res.status}`)
      setData(body)
    } catch (e) {
      setError(e.message)
    } finally {
      setLoading(false)
    }
  }, [country, days])

  useEffect(() => { load() }, [load])

  const max = data?.stages?.[0]?.reached || 1
  const countryOptions = (data?.countries || []).map((c) => c.country)

  return (
    <div style={{ padding: embedded ? 0 : "1.5rem", maxWidth: "1200px" }}>
      <div style={{ display: "flex", justifyContent: "space-between", alignItems: "flex-end", flexWrap: "wrap", gap: "1rem", marginBottom: "1.25rem" }}>
        <div>
          {!embedded && <h1 style={{ margin: 0, fontSize: "1.5rem" }}>Member Funnel</h1>}
          <p style={{ margin: "0.25rem 0 0", color: "#6b7280", fontSize: "0.875rem" }}>
            Where every Panel member stands, from signup to redeeming points, and where they get stuck.
          </p>
        </div>
        <div style={{ display: "flex", gap: "0.5rem" }}>
          <select style={select} value={country} onChange={(e) => setCountry(e.target.value)}>
            <option value="">All countries</option>
            {(country && !countryOptions.includes(country) ? [country, ...countryOptions] : countryOptions)
              .filter((c) => c !== "??")
              .map((c) => <option key={c} value={c}>{COUNTRY_LABELS[c] || c}</option>)}
          </select>
          <select style={select} value={days} onChange={(e) => setDays(Number(e.target.value))}>
            {PERIODS.map((p) => <option key={p.value} value={p.value}>{p.label}</option>)}
          </select>
        </div>
      </div>

      {error && <div style={{ ...card, color: "#b91c1c" }}>{error}</div>}
      {!data && !error && <div style={card}>Loading…</div>}

      {data && (
        <div style={{ opacity: loading ? 0.5 : 1 }}>
          {data.roadblocks.length > 0 && (
            <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fit, minmax(240px, 1fr))", gap: "0.75rem", marginBottom: "1.25rem" }}>
              {data.roadblocks.map((r, i) => (
                <div key={r.key} style={{ ...card, marginBottom: 0, borderLeft: `4px solid ${i === 0 ? "#dc2626" : "#d97706"}` }}>
                  <p style={{ margin: 0, fontSize: "0.75rem", color: "#6b7280", textTransform: "uppercase", letterSpacing: "0.04em" }}>Roadblock {i + 1}</p>
                  <p style={{ margin: "0.25rem 0", fontWeight: 700 }}>{r.label}</p>
                  <p style={{ margin: 0, fontSize: "0.85rem", color: "#4b5563" }}>
                    <b>{r.members}</b> member{r.members === 1 ? "" : "s"} stuck · {r.quietOverAWeek} quiet for over a week
                  </p>
                </div>
              ))}
            </div>
          )}

          <div style={card}>
            <h3 style={{ margin: "0 0 1rem", fontSize: "1rem" }}>Funnel · {data.total} members</h3>
            {data.stages.map((s, i) => (
              <div key={s.key} style={{ display: "grid", gridTemplateColumns: "190px 1fr 150px", alignItems: "center", gap: "0.75rem", marginBottom: "0.5rem" }}>
                <div style={{ fontSize: "0.875rem", fontWeight: 600 }}>
                  {s.label}
                  {s.skipped > 0 && (
                    <div style={{ fontSize: "0.7rem", fontWeight: 400, color: "#9ca3af" }} title="Members past this stage who never did it — they joined before this step existed">
                      incl. {s.skipped} who skipped it
                    </div>
                  )}
                </div>
                <div style={{ background: "#f3f4f6", borderRadius: "6px", height: "26px", position: "relative" }}>
                  <div style={{ width: `${Math.max((s.reached / max) * 100, s.reached ? 1 : 0)}%`, height: "100%", borderRadius: "6px", background: "#6366f1" }} />
                  <span style={{ position: "absolute", left: "8px", top: "4px", fontSize: "0.8rem", fontWeight: 700, color: s.reached / max > 0.12 ? "#fff" : "#1f2937" }}>
                    {s.reached.toLocaleString()} · {s.pctOfSignups}%
                  </span>
                </div>
                <div style={{ fontSize: "0.8rem", color: i === 0 ? "#9ca3af" : tone(s.pctOfPrevious), fontWeight: 600 }}>
                  {i === 0 ? "start" : `${s.pctOfPrevious}% of previous`}
                </div>
              </div>
            ))}
            <p style={{ margin: "0.75rem 0 0", fontSize: "0.75rem", color: "#6b7280" }}>
              Bar = members who reached the stage or went past it (and % of signups). Right = conversion from the stage above: green ≥ 70%, amber 40–70%, red below 40%.
              "Skipped" = older members who joined before that step existed.
            </p>
          </div>

          <div style={card}>
            <h3 style={{ margin: "0 0 0.25rem", fontSize: "1rem" }}>Where members are stuck</h3>
            <p style={{ margin: "0 0 0.75rem", fontSize: "0.8rem", color: "#6b7280" }}>Members whose furthest stage is this one, by when they were last active.</p>
            <div style={{ overflowX: "auto" }}>
              <table style={{ width: "100%", borderCollapse: "collapse" }}>
                <thead>
                  <tr><th style={th}>Stopped at</th><th style={th}>What's missing</th><th style={th}>Members</th><th style={th}>Active today</th><th style={th}>This week</th><th style={th}>Quiet &gt; 7 days</th></tr>
                </thead>
                <tbody>
                  {data.stages.filter((s) => s.stuckHere > 0).map((s) => (
                    <tr key={s.key}>
                      <td style={td}>{s.label}</td>
                      <td style={td}>{s.stuckLabel}</td>
                      <td style={{ ...td, fontWeight: 700 }}>{s.stuckHere}</td>
                      <td style={td}>{s.stuckByLastSeen.today}</td>
                      <td style={td}>{s.stuckByLastSeen.week}</td>
                      <td style={{ ...td, color: s.stuckByLastSeen.older ? "#b91c1c" : td.color }}>{s.stuckByLastSeen.older}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          </div>

          <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fit, minmax(280px, 1fr))", gap: "1.25rem" }}>
            <div style={{ ...card, marginBottom: 0 }}>
              <h3 style={{ margin: "0 0 0.5rem", fontSize: "0.95rem" }}>Finished Quick start, never clicked a survey</h3>
              <p style={{ margin: 0, fontSize: "1.5rem", fontWeight: 700 }}>{data.blockers.neverClicked.members}</p>
              <p style={{ margin: 0, fontSize: "0.8rem", color: "#6b7280" }}>
                members · typically {data.blockers.neverClicked.medianDaysSinceQuickStart} days since Quick start. Usually: no surveys on their wall, or no reminder email.
              </p>
            </div>
            <div style={{ ...card, marginBottom: 0 }}>
              <h3 style={{ margin: "0 0 0.5rem", fontSize: "0.95rem" }}>Clicked, but no result came back</h3>
              <table style={{ width: "100%", borderCollapse: "collapse" }}>
                <tbody>
                  <tr><td style={td}>Left the survey part-way (drop-off)</td><td style={{ ...td, fontWeight: 700 }}>{data.blockers.noResultAttempts.dropOff}</td></tr>
                  <tr><td style={td}>Blocked before the survey (security / quality)</td><td style={{ ...td, fontWeight: 700 }}>{data.blockers.noResultAttempts.blocked}</td></tr>
                  <tr><td style={td}>Other outcome in Torpedo</td><td style={{ ...td, fontWeight: 700 }}>{data.blockers.noResultAttempts.other}</td></tr>
                </tbody>
              </table>
              <p style={{ margin: "0.5rem 0 0", fontSize: "0.75rem", color: "#6b7280" }}>Survey attempts by members at this stage.</p>
            </div>
            <div style={{ ...card, marginBottom: 0 }}>
              <h3 style={{ margin: "0 0 0.5rem", fontSize: "0.95rem" }}>Got results, never completed</h3>
              <table style={{ width: "100%", borderCollapse: "collapse" }}>
                <tbody>
                  <tr><td style={td}>Screened out (terminate)</td><td style={{ ...td, fontWeight: 700 }}>{data.blockers.screenedOutResults.terminate}</td></tr>
                  <tr><td style={td}>Survey full (quota full)</td><td style={{ ...td, fontWeight: 700 }}>{data.blockers.screenedOutResults.quotafull}</td></tr>
                </tbody>
              </table>
              <p style={{ margin: "0.5rem 0 0", fontSize: "0.75rem", color: "#6b7280" }}>Many screen-outs = surveys poorly matched to the member's profile.</p>
            </div>
          </div>

          <div style={{ ...card, marginTop: "1.25rem" }}>
            <h3 style={{ margin: "0 0 0.75rem", fontSize: "1rem" }}>By country</h3>
            <div style={{ overflowX: "auto" }}>
              <table style={{ width: "100%", borderCollapse: "collapse" }}>
                <thead>
                  <tr>
                    <th style={th}>Country</th>
                    {data.stages.map((s) => <th key={s.key} style={th}>{s.label}</th>)}
                  </tr>
                </thead>
                <tbody>
                  {data.countries.map((c) => (
                    <tr key={c.country}>
                      <td style={{ ...td, fontWeight: 600 }}>{COUNTRY_LABELS[c.country] || c.country}</td>
                      {c.counts.map((n, i) => (
                        <td key={i} style={td}>
                          {n}
                          {i > 0 && c.counts[0] > 0 && <span style={{ color: "#9ca3af", fontSize: "0.75rem" }}> ({Math.round((n / c.counts[0]) * 100)}%)</span>}
                        </td>
                      ))}
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          </div>
        </div>
      )}
    </div>
  )
}
