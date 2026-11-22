import { useEffect, useMemo, useState } from "react"
import { useNavigate } from "react-router-dom"
import { buildApiUrl } from "../../config"
import { authFetch } from "../../utils/api"
import { PageShell, StatTile, TileRow } from "../../components/panel-admin/ui"
import { card, th, td, colors, countryName } from "../../components/panel-admin/tokens"

const API = "/api/panel-admin"
const UNKNOWN_BG = "#fdf4e7"

const PERIODS = [
  { value: 0, label: "All members" },
  { value: 7, label: "Joined in the last 7 days" },
  { value: 30, label: "Joined in the last 30 days" },
  { value: 90, label: "Joined in the last 90 days" },
]

const select = { padding: "0.45rem 0.6rem", borderRadius: "8px", border: `1px solid #d4cec3`, fontSize: "0.85rem", background: "#fff", color: colors.text }

// Colour a stage-to-stage conversion: green healthy, amber weak, red roadblock.
const tone = (pct) => (pct >= 70 ? colors.good : pct >= 40 ? colors.warn : colors.bad)
const fmt = (n) => (typeof n === "number" ? n.toLocaleString("en-IN") : n ?? "—")
const dropOff = (s) => (s.reached > 0 ? `${(Math.round(((s.stoppedHere || 0) / s.reached) * 1000) / 10).toFixed(1)}%` : "—")

// True when the viewport is at least `px` wide (re-evaluated on resize).
function useWide(px) {
  const query = `(min-width: ${px}px)`
  const get = () => (typeof window !== "undefined" && window.matchMedia ? window.matchMedia(query).matches : true)
  const [wide, setWide] = useState(get)
  useEffect(() => {
    if (typeof window === "undefined" || !window.matchMedia) return undefined
    const mq = window.matchMedia(query)
    const on = () => setWide(mq.matches)
    on()
    mq.addEventListener?.("change", on)
    return () => mq.removeEventListener?.("change", on)
  }, [query])
  return wide
}

/**
 * Overview — the Panel at a glance, from one filtered member-funnel response:
 * alerts, headline numbers, the member journey and members by country.
 */
export default function PanelOverview() {
  const navigate = useNavigate()
  const [country, setCountry] = useState("")
  const [days, setDays] = useState(0)
  const [data, setData] = useState(null)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState(null)
  const [knownCountries, setKnownCountries] = useState([])

  useEffect(() => {
    let cancelled = false
    setLoading(true)
    setError(null)
    const params = new URLSearchParams()
    if (country) params.set("country", country)
    if (days) params.set("days", String(days))
    const qs = params.toString()
    authFetch(buildApiUrl(`${API}/member-funnel${qs ? `?${qs}` : ""}`), { headers: { Authorization: localStorage.getItem("session_id") } })
      .then(async (res) => {
        if (!res.ok) throw new Error(`Could not load the overview (HTTP ${res.status})`)
        return res.json()
      })
      .then((json) => {
        if (cancelled) return
        setData(json)
        // Keep every country seen so the filter list doesn't shrink once filtered.
        const codes = (json.countries || []).map((c) => c.code).filter(Boolean)
        setKnownCountries((prev) => [...new Set([...prev, ...codes])])
      })
      .catch((e) => { if (!cancelled) setError(e.message || "Could not load the overview") })
      .finally(() => { if (!cancelled) setLoading(false) })
    return () => { cancelled = true }
  }, [country, days])

  const wide = useWide(1000)
  const stages = useMemo(() => data?.stages || [], [data])

  const filters = (
    <>
      <label style={{ display: "flex", alignItems: "center", gap: "0.4rem", fontSize: "0.8rem", color: colors.muted }}>
        Country
        <select aria-label="Country" value={country} onChange={(e) => setCountry(e.target.value)} style={select}>
          <option value="">All countries</option>
          {[...knownCountries].sort((a, b) => countryName(a).localeCompare(countryName(b))).map((c) => (
            <option key={c} value={c}>{countryName(c)}</option>
          ))}
          <option value="??">Unknown</option>
        </select>
      </label>
      <label style={{ display: "flex", alignItems: "center", gap: "0.4rem", fontSize: "0.8rem", color: colors.muted }}>
        Members
        <select aria-label="Members" value={days} onChange={(e) => setDays(Number(e.target.value))} style={select}>
          {PERIODS.map((p) => <option key={p.value} value={p.value}>{p.label}</option>)}
        </select>
      </label>
    </>
  )

  const updated = data?.generatedAt
    ? `Updated ${new Date(data.generatedAt).toLocaleString("en-IN", { dateStyle: "medium", timeStyle: "short" })}`
    : loading ? "Loading…" : ""

  return (
    <PageShell title="Panel overview" description={updated} actions={filters}>
      {error && (
        <div role="alert" style={{ ...card, color: colors.bad, fontSize: "0.875rem", borderColor: "#f3c4c4", background: "#fff7f7" }}>
          {error}
        </div>
      )}
      {!data && loading && !error && <div style={{ ...card, color: colors.muted, fontSize: "0.875rem" }}>Loading the panel overview…</div>}

      {data && (
        <div style={{ opacity: loading ? 0.6 : 1, transition: "opacity 0.15s" }}>
          <Kpis data={data} navigate={navigate} />
          <div style={{ display: "grid", gridTemplateColumns: wide ? "minmax(0,2fr) minmax(260px,1fr)" : "minmax(0,1fr)", gap: "1rem", alignItems: "start" }}>
            <Journey data={data} stages={stages} />
            <Countries countries={data.countries || []} total={data.total} />
          </div>
        </div>
      )}
    </PageShell>
  )
}

function Kpis({ data, navigate }) {
  const k = data.kpis || {}
  return (
    <TileRow>
      <StatTile label="Total panel members" value={fmt(k.members ?? data.total)} onClick={() => navigate("/admin/panel-admin/members")} />
      <StatTile label="New signups in the past 30 days" value={fmt(k.joinedLast30d)} />
      <StatTile label="Active in the last 30 days" value={fmt(k.activeLast30d)} sub={`${k.activeLast30dPct ?? 0}% of members`} />
      <StatTile label="Survey attempts in the last 30 days" value={fmt(k.attemptsLast30d ?? 0)} sub="survey attempts, not members" />
      <StatTile label="Completed a survey in the last 30 days" value={fmt(k.completedLast30d)} color={colors.good}
        sub={`Conversion ${k.attemptConversionLast30d ?? 0}% (${fmt(k.completeAttemptsLast30d ?? 0)} of ${fmt(k.attemptsLast30d ?? 0)} attempts completed)`} />
    </TileRow>
  )
}

function Journey({ data, stages }) {
  const total = data.total || stages[0]?.reached || 0
  const stoppedSum = stages.reduce((n, s) => n + (s.stoppedHere || 0), 0)
  const redeemed = data.redeemed || 0
  const COLS = 4

  return (
    <div style={card}>
      <h2 style={{ margin: "0 0 0.25rem", fontSize: "1rem", color: colors.text }}>Member journey</h2>
      <p style={{ margin: "0 0 0.75rem", fontSize: "0.8rem", color: colors.muted }}>
        Each member counts once, at the furthest step they reached. Drop off is the share of members at a stage who went no further.
      </p>
      <div style={{ overflowX: "auto" }}>
        <table style={{ width: "100%", borderCollapse: "collapse", minWidth: 420 }}>
          <thead>
            <tr>
              <th scope="col" style={th}>Stage</th>
              <th scope="col" style={{ ...th, textAlign: "right" }}>Members reached</th>
              <th scope="col" style={{ ...th, textAlign: "right" }}>Conversion</th>
              <th scope="col" style={{ ...th, textAlign: "right" }}>Drop off (%)</th>
            </tr>
          </thead>
          <tbody>
            {stages.map((s, i) => (
              <tr key={s.key} data-stage={s.key}>
                <td style={{ ...td, fontWeight: 600, whiteSpace: "nowrap" }}>{s.label}</td>
                <td style={{ ...td, textAlign: "right", whiteSpace: "nowrap" }}>
                  <strong>{fmt(s.reached)}</strong> <span style={{ color: colors.muted, fontSize: "0.75rem" }}>{s.pctOfSignups}%</span>
                </td>
                <td data-col="conversion" style={{ ...td, textAlign: "right", whiteSpace: "nowrap", fontWeight: 600, color: i === 0 ? colors.muted : tone(s.pctOfPrevious) }}>
                  {i === 0 ? "—" : `${s.pctOfPrevious}%`}
                </td>
                <td data-col="dropoff" style={{ ...td, textAlign: "right", whiteSpace: "nowrap", fontWeight: 600 }}>{dropOff(s)}</td>
              </tr>
            ))}
            <tr data-stage="redeemed">
              <td style={{ ...td, fontWeight: 600 }}>Redeemed points</td>
              <td style={{ ...td, textAlign: "right" }}><strong>{fmt(redeemed)}</strong></td>
              <td data-col="conversion" style={{ ...td, textAlign: "right", color: colors.muted }}>—</td>
              <td data-col="dropoff" style={{ ...td, textAlign: "right", color: colors.muted }}>—</td>
            </tr>
          </tbody>
          <tfoot>
            <tr>
              <td colSpan={COLS} style={{ ...td, borderBottom: "none", color: colors.muted, fontSize: "0.8rem" }}>
                {`${fmt(stoppedSum)} stopped along the way + ${fmt(redeemed)} redeemed = ${fmt(total)}`}
                {stoppedSum + redeemed !== total && <span style={{ color: colors.bad }}>{` (doesn't add up: ${fmt(stoppedSum + redeemed)})`}</span>}
              </td>
            </tr>
          </tfoot>
        </table>
      </div>
    </div>
  )
}

function Countries({ countries, total }) {
  const known = countries.filter((c) => c.code).sort((a, b) => b.members - a.members)
  const unknown = countries.filter((c) => !c.code)
  const rows = [
    ...known.map((c) => ({ key: c.code, name: countryName(c.code) || c.name, members: c.members || 0 })),
    ...(unknown.length ? [{ key: "unknown", name: "Unknown", members: unknown.reduce((n, c) => n + (c.members || 0), 0), tint: true }] : []),
  ]
  const sum = rows.reduce((n, r) => n + r.members, 0)

  return (
    <div style={card}>
      <h2 style={{ margin: "0 0 0.75rem", fontSize: "1rem", color: colors.text }}>By country</h2>
      <div style={{ overflowX: "auto" }}>
        <table style={{ width: "100%", borderCollapse: "collapse" }}>
          <thead>
            <tr>
              <th scope="col" style={th}>Country</th>
              <th scope="col" style={{ ...th, textAlign: "right" }}>Panelists</th>
            </tr>
          </thead>
          <tbody>
            {rows.map((r) => (
              <tr key={r.key} data-country={r.key} style={{ background: r.tint ? UNKNOWN_BG : undefined }}>
                <td style={td}>{r.name}</td>
                <td style={{ ...td, textAlign: "right", fontWeight: 600 }}>{fmt(r.members)}</td>
              </tr>
            ))}
          </tbody>
          <tfoot>
            <tr data-country="total">
              <th scope="row" style={{ ...td, textAlign: "left", fontWeight: 700, borderBottom: "none" }}>
                Total
                {total != null && sum !== total && <div style={{ fontSize: "0.72rem", color: colors.bad, fontWeight: 400 }}>{`rows add up to ${fmt(sum)}, expected ${fmt(total)}`}</div>}
              </th>
              <td style={{ ...td, textAlign: "right", fontWeight: 700, borderBottom: "none" }}>{fmt(sum)}</td>
            </tr>
          </tfoot>
        </table>
      </div>
    </div>
  )
}
