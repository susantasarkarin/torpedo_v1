import { useEffect, useMemo, useState } from "react"
import { useNavigate, useParams } from "react-router-dom"
import { buildApiUrl } from "../../config"
import { authFetch } from "../../utils/api"
import { PageShell, StatTile, TileRow } from "../../components/panel-admin/ui"
import { card, colors, countryName, td, th } from "../../components/panel-admin/tokens"
import DeletePanelistDialog from "./DeletePanelistDialog"

// One SurveyFieldwork Panel member on its own page: account, points, survey
// history, profile answers, redemptions, referrals and flags. Opened from
// Panel → Members; data proxied from the Panel's admin API.

const API = "/api/panel-admin"
const session = () => ({ Authorization: localStorage.getItem("session_id") })

const fmtDate = (d) => (d ? new Date(d).toLocaleDateString("en-IN", { day: "numeric", month: "short", year: "numeric" }) : "—")
const fmtTime = (d) => (d ? new Date(d).toLocaleString("en-IN", { day: "numeric", month: "short", year: "numeric", hour: "2-digit", minute: "2-digit" }) : "—")
const points = (paise, country) => {
  const perPaise = { GB: 1 / 127.89, UK: 1 / 127.89, US: 1 / 96.73 }[String(country || "").toUpperCase()] || 1 / 10
  return `${Math.floor((paise || 0) * perPaise).toLocaleString()} pts`
}
const yesNo = (v) => (v ? "Yes" : "No")
const personName = (u) => [u?.firstName, u?.lastName].filter(Boolean).join(" ")

function Section({ title, right, children }) {
  return (
    <section style={card}>
      <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", gap: "0.75rem", marginBottom: "0.75rem", flexWrap: "wrap" }}>
        <h2 style={{ margin: 0, fontSize: "1rem", color: colors.text }}>{title}</h2>
        {right}
      </div>
      {children}
    </section>
  )
}

function Fields({ rows }) {
  return (
    <dl style={{ display: "grid", gridTemplateColumns: "repeat(auto-fill, minmax(220px, 1fr))", gap: "0.75rem 1.5rem", margin: 0 }}>
      {rows.filter(([, v]) => v !== undefined).map(([k, v]) => (
        <div key={k}>
          <dt style={{ fontSize: "0.75rem", color: colors.muted, textTransform: "uppercase", letterSpacing: "0.04em" }}>{k}</dt>
          <dd style={{ margin: "0.15rem 0 0", fontSize: "0.9rem", color: colors.text, wordBreak: "break-word" }}>{v === null || v === "" ? "—" : v}</dd>
        </div>
      ))}
    </dl>
  )
}

function Table({ head, rows, empty = "Nothing yet." }) {
  if (!rows.length) return <p style={{ color: colors.muted, fontSize: "0.875rem", margin: 0 }}>{empty}</p>
  return (
    <div style={{ overflowX: "auto", maxHeight: "420px", overflowY: "auto" }}>
      <table style={{ width: "100%", borderCollapse: "collapse" }}>
        <thead><tr style={{ background: "#faf9f7", position: "sticky", top: 0 }}>{head.map((h) => <th key={h} style={th}>{h}</th>)}</tr></thead>
        <tbody>{rows.map((cells, i) => <tr key={i}>{cells.map((c, j) => <td key={j} style={td}>{c}</td>)}</tr>)}</tbody>
      </table>
    </div>
  )
}

const statusColor = (s) => {
  const v = String(s || "").toLowerCase()
  if (v === "complete" || v === "paid" || v === "completed" || v === "credited") return colors.good
  if (v.includes("term") || v === "failed" || v === "rejected") return colors.bad
  return colors.warn
}
const Status = ({ value }) => <span style={{ fontWeight: 600, color: statusColor(value), textTransform: "capitalize" }}>{String(value || "—").replace(/_/g, " ").toLowerCase()}</span>

export default function PanelMemberDetail() {
  const { userId } = useParams()
  const navigate = useNavigate()
  const [data, setData] = useState(null)
  const [error, setError] = useState("")
  const [log, setLog] = useState(null)
  const [confirmDelete, setConfirmDelete] = useState(false)
  const [profileFilter, setProfileFilter] = useState("")

  useEffect(() => {
    let live = true
    setData(null)
    setError("")
    authFetch(buildApiUrl(`${API}/sfwpanel-panelists/${userId}`), { headers: session() })
      .then(async (r) => {
        if (!r.ok) throw new Error(r.status === 404 ? "This member no longer exists." : "Could not load this member.")
        return r.json()
      })
      .then((d) => {
        if (!live) return
        setData(d)
        const pid = d?.user?.panelistId
        if (pid) {
          authFetch(buildApiUrl(`${API}/panelists/${encodeURIComponent(pid)}/survey-log?limit=500`), { headers: session() })
            .then((r) => (r.ok ? r.json() : null))
            .then((l) => live && setLog(l || { total: 0, attempts: [], byStatus: {} }))
            .catch(() => live && setLog({ total: 0, attempts: [], byStatus: {} }))
        } else setLog({ total: 0, attempts: [], byStatus: {} })
      })
      .catch((e) => live && setError(e.message))
    return () => { live = false }
  }, [userId])

  const profileBySection = useMemo(() => {
    const q = profileFilter.trim().toLowerCase()
    const groups = []
    ;(data?.profile || []).forEach((r) => {
      if (q && !`${r.question} ${r.answer} ${r.id}`.toLowerCase().includes(q)) return
      let g = groups.find((x) => x.section === r.section)
      if (!g) { g = { section: r.section, rows: [] }; groups.push(g) }
      g.rows.push(r)
    })
    return groups
  }, [data, profileFilter])

  const downloadLog = async (pid) => {
    const res = await authFetch(buildApiUrl(`${API}/panelists/${encodeURIComponent(pid)}/survey-log?format=csv`), { headers: session() })
    if (!res.ok) return
    const url = URL.createObjectURL(await res.blob())
    const a = document.createElement("a")
    a.href = url
    a.download = `survey-log-${pid}.csv`
    a.click()
    URL.revokeObjectURL(url)
  }

  const back = () => navigate("/admin/panel-admin/members")
  const backBtn = (
    <button type="button" onClick={back} style={{ padding: "0.5rem 0.9rem", border: `1px solid ${colors.border}`, background: "#fff", borderRadius: "6px", cursor: "pointer", fontSize: "0.875rem" }}>
      ← All members
    </button>
  )

  if (error) return <PageShell title="Member" actions={backBtn}><p style={{ color: colors.bad }}>{error}</p></PageShell>
  if (!data) return <PageShell title="Member" actions={backBtn}><p style={{ color: colors.muted }}>Loading…</p></PageShell>

  const u = data.user || {}
  const s = data.surveyStats || {}
  const c = u.country
  const p = u.profiling || {}
  const redeemed = Math.max(0, (u.totalEarnedPaise || 0) - (u.balancePaise || 0))
  const denom = (s.complete || 0) + (s.terminate || 0)
  const flags = [
    ...(p.flags || []).map((f) => ({ ...f, kind: "Profile quality" })),
    ...(data.fraudFlags || []).map((f) => ({ ...f, kind: "Fraud", rule: f.flagType, at: f.createdAt, clearedAt: f.resolved ? (f.resolvedAt || f.updatedAt) : null })),
  ]
  const suspended = u.suspension && u.suspension.at && !u.suspension.releasedAt

  return (
    <PageShell
      title={personName(u) || u.email || "Member"}
      description={[u.email, u.panelistId, countryName(c)].filter(Boolean).join(" · ")}
      actions={(
        <>
          {backBtn}
          <button type="button" onClick={() => setConfirmDelete(true)}
            style={{ padding: "0.5rem 0.9rem", border: "1px solid #fecaca", background: "#fef2f2", color: colors.bad, borderRadius: "6px", cursor: "pointer", fontSize: "0.875rem", fontWeight: 600 }}>
            Delete member
          </button>
        </>
      )}
    >
      <TileRow>
        <StatTile label="Balance" value={points(u.balancePaise, c)} color="#7c3aed" />
        <StatTile label="Total earned" value={points(u.totalEarnedPaise, c)} />
        <StatTile label="Redeemed" value={points(redeemed, c)} />
        <StatTile label="Surveys" value={s.total || 0} sub={`${s.complete || 0} complete · ${s.terminate || 0} terminate · ${s.quotafull || 0} quota`} />
        <StatTile label="Completion rate" value={denom ? `${Math.round((s.complete / denom) * 100)}%` : "—"} />
        <StatTile label="Tier" value={p.tier ?? "—"} />
      </TileRow>

      <Section title="Account">
        <Fields rows={[
          ["Name", personName(u)],
          ["Email", u.email],
          ["Email verified", yesNo(u.emailVerified)],
          ["Panelist ID", u.panelistId],
          ["Mobile", u.phoneNumber],
          ["Mobile verified", yesNo(u.phoneVerified)],
          ["WhatsApp opt-in", yesNo(u.whatsappOptIn)],
          ["Country", countryName(c)],
          ["Gender", u.gender],
          ["Date of birth", fmtDate(u.dateOfBirth)],
          ["Joined", fmtTime(u.createdAt)],
          ["Last active", fmtTime(u.lastActiveAt)],
          ["Membership confirmed", fmtTime(u.membershipConfirmedAt)],
          ["Signup source", [u.signupSource, u.utm?.source].filter(Boolean).join(" / ") || null],
          ["Signed up with", u.googleId ? "Google" : "Email"],
          ["Level", u.level],
          ["Referral code", u.referralCode],
          ["Referrals (confirmed)", u.confirmedReferralCount || 0],
          ["Status", suspended ? `Suspended${u.suspension.reason ? ` — ${u.suspension.reason}` : ""}` : u.isActive === false ? "Deactivated" : "Active"],
        ]} />
      </Section>

      <Section title="Profile progress">
        <Fields rows={[
          ["Quick start done", fmtTime(p.layer0CompletedAt)],
          ["Tier since", fmtTime(p.tierAt)],
          ["Social grade (UK)", p.socialGrade || null],
          ["Last answer", fmtTime(p.lastAnswerAt)],
          ["Sections done", Object.keys(p.modules || {}).filter((k) => p.modules[k]?.completedAt).join(", ") || null],
          ["Mystery shopper", yesNo(p.mysteryShopper)],
        ]} />
      </Section>

      <Section title={`Profile answers · ${(data.profile || []).length}`}
        right={<input value={profileFilter} onChange={(e) => setProfileFilter(e.target.value)} placeholder="Search answers…"
          style={{ padding: "0.4rem 0.7rem", border: `1px solid ${colors.border}`, borderRadius: "6px", fontSize: "0.85rem", minWidth: "200px" }} />}>
        {profileBySection.length === 0 ? (
          <p style={{ color: colors.muted, fontSize: "0.875rem", margin: 0 }}>No profile answers{profileFilter ? " match" : " yet"}.</p>
        ) : profileBySection.map((g) => (
          <div key={g.section} style={{ marginBottom: "1rem" }}>
            <h3 style={{ fontSize: "0.85rem", color: colors.accent, margin: "0 0 0.4rem" }}>{g.section}</h3>
            <Table head={["Question", "Answer", "Answered"]} rows={g.rows.map((r) => [
              <span key="q" title={r.id}>{r.question}</span>, r.answer, <span key="d" style={{ whiteSpace: "nowrap", color: colors.muted }}>{fmtDate(r.answeredAt)}</span>,
            ])} />
          </div>
        ))}
      </Section>

      <Section title={`Survey log${log ? ` · ${log.total} attempt${log.total === 1 ? "" : "s"}` : ""}`}
        right={u.panelistId && (
          <button type="button" onClick={() => downloadLog(u.panelistId)}
            style={{ padding: "0.35rem 0.75rem", borderRadius: "6px", border: `1px solid ${colors.border}`, background: "#fff", cursor: "pointer", fontSize: "0.8rem" }}>
            Download log (CSV)
          </button>
        )}>
        {log && Object.keys(log.byStatus || {}).length > 0 && (
          <p style={{ fontSize: "0.8rem", color: colors.muted, margin: "0 0 0.5rem" }}>
            {Object.entries(log.byStatus).map(([k, v]) => `${k.replace(/_/g, " ").toLowerCase()}: ${v}`).join(" · ")}
          </p>
        )}
        {!log ? <p style={{ color: colors.muted, fontSize: "0.875rem" }}>Loading…</p> : (
          <Table head={["Date", "Status", "Source", "Survey", "RID", "SFWID"]} empty="No survey attempts yet." rows={log.attempts.map((a) => [
            <span key="d" style={{ whiteSpace: "nowrap" }}>{fmtTime(a.date)}</span>,
            <span key="s"><Status value={a.status === "SECURITY_TERM" ? "Security term" : a.status} />{a.reason ? ` (${a.reason.replace(/_/g, " ")})` : ""}</span>,
            a.source || "—", <code key="sv">{a.survey_id || "—"}</code>, <code key="r">{a.rid || "—"}</code>, <code key="f" style={{ color: colors.muted }}>{a.sfwid}</code>,
          ])} />
        )}
      </Section>

      <Section title={`Survey completions on the Panel · ${(data.recentSurveys || []).length}`}>
        <Table head={["Completed", "Status", "Survey", "RID", "Points"]} rows={(data.recentSurveys || []).map((r) => [
          <span key="d" style={{ whiteSpace: "nowrap" }}>{fmtTime(r.completedAt || r.createdAt)}</span>, <Status key="s" value={r.status} />,
          <code key="sv">{r.surveyId || "—"}</code>, <code key="r">{r.rid || "—"}</code>, r.pointsEarned > 0 ? points(r.pointsEarned, c) : "—",
        ])} />
      </Section>

      <Section title={`Points history · ${(data.rewards || []).length}`}>
        <Table head={["Date", "Type", "Status", "Amount", "Note"]} rows={(data.rewards || []).map((r) => [
          <span key="d" style={{ whiteSpace: "nowrap" }}>{fmtTime(r.createdAt)}</span>, String(r.type || "—").replace(/_/g, " "),
          <Status key="s" value={r.status} />, points(r.amountPaise, c), r.description || r.milestoneKey || "—",
        ])} />
      </Section>

      <Section title={`Redemptions & transactions · ${(data.transactions || []).length}`}>
        <Table head={["Date", "Type", "Status", "Amount", "Description", "Details"]} rows={(data.transactions || []).map((t) => [
          <span key="d" style={{ whiteSpace: "nowrap" }}>{fmtTime(t.createdAt)}</span>, String(t.type || "—").replace(/_/g, " "), <Status key="s" value={t.status} />,
          points(Math.abs(t.amountPaise || 0), c), t.description || "—",
          [t.holdReasons?.length && !t.releasedAt && `On hold: ${t.holdReasons.join(", ")}`, t.releasedAt && `Hold released ${fmtDate(t.releasedAt)}`,
            t.fulfilledAt && `Sent ${fmtDate(t.fulfilledAt)}${t.fulfilledBy ? ` by ${t.fulfilledBy}` : ""}`].filter(Boolean).join(" · ") || "—",
        ])} />
      </Section>

      <Section title={`Referrals · ${(data.referrals || []).length}`}>
        <Table head={["Date", "Role", "Other member", "Status"]} rows={(data.referrals || []).map((r) => {
          const iReferred = String(r.referrerId?._id || r.referrerId) === String(u._id)
          const other = iReferred ? r.referredId : r.referrerId
          return [fmtDate(r.createdAt), iReferred ? "Referred them" : "Was referred by",
            other ? `${personName(other) || other.email || ""} ${other.panelistId ? `(${other.panelistId})` : ""}` : "deleted member", <Status key="s" value={r.status} />]
        })} />
      </Section>

      <Section title={`Flags · ${flags.length}`}>
        <Table head={["Raised", "Kind", "Rule / reason", "Section", "Cleared"]} empty="No flags." rows={flags.map((f) => [
          fmtTime(f.at || f.createdAt), f.kind, f.rule || f.reason || f.type || "—", f.module || "—",
          f.clearedAt || f.resolvedAt ? fmtDate(f.clearedAt || f.resolvedAt) : <span key="o" style={{ color: colors.bad }}>Open</span>,
        ])} />
      </Section>

      {confirmDelete && (
        <DeletePanelistDialog panelist={u} onClose={() => setConfirmDelete(false)} onDeleted={back} />
      )}
    </PageShell>
  )
}
