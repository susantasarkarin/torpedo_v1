import { useEffect, useState } from "react"
import { buildApiUrl } from "../../config"
import { authFetch } from "../../utils/api"
import { StatTile, TileRow } from "../../components/panel-admin/ui"
import { colors } from "../../components/panel-admin/tokens"

const fmt = (n) => (n == null ? "—" : Number(n).toLocaleString())

/**
 * Four headline numbers for the Recruitment lists. Lead total and pending
 * merge come from data the list already loads (props); invited / joined come
 * from the existing panel funnel (server-cached for 10 minutes).
 */
// onMerge / merging: the "Merge now" action on the Pending merge card (shown
// only while recent leads are unmerged; the parent confirms before merging).
export default function RecruitmentSummary({ totalLeads, promotionStatus, onMerge, merging }) {
  const [funnel, setFunnel] = useState(null)
  const [failed, setFailed] = useState(false)

  useEffect(() => {
    let alive = true
    authFetch(buildApiUrl("/api/panel-admin/dashboard/funnel"))
      .then((r) => (r.ok ? r.json() : Promise.reject(new Error(`HTTP ${r.status}`))))
      .then((d) => { if (alive) setFunnel(d) })
      .catch((err) => {
        console.error("Failed to load panel funnel:", err)
        if (alive) setFailed(true)
      })
    return () => { alive = false }
  }, [])

  const stage = (key) => funnel?.stages?.find((s) => s.key === key)?.count
  const invited = stage("invited")
  const joined = stage("opted_in")
  const pending = promotionStatus?.not_yet_promoted
  const funnelSub = (text) => (failed ? "Couldn't load" : funnel ? text : "Loading…")

  return (
    <TileRow>
      <StatTile
        label="Total leads"
        value={fmt(totalLeads)}
        sub={totalLeads == null ? "Counted when the Leads list loads" : "Unique emails from landing pages"}
      />
      <StatTile
        label="Pending merge"
        value={fmt(pending)}
        color={pending > 0 ? colors.warn : colors.text}
        sub={promotionStatus
          ? `Of the latest ${fmt(promotionStatus.sampled)} leads. Not invited until merged; auto-merge runs daily at 08:20 IST.`
          : "Checking…"}
        action={pending > 0 && onMerge ? (
          <button type="button" className="btn btn-outline" onClick={onMerge} disabled={merging}
            style={{ padding: "0.3rem 0.75rem", fontSize: "0.8rem", whiteSpace: "nowrap" }}>
            {merging ? "Merging…" : "Merge now"}
          </button>
        ) : null}
      />
      <StatTile
        label="Invitations sent"
        value={fmt(invited)}
        sub={funnelSub(`Panelists invited at least once · ${fmt(funnel?.total_sends)} emails`)}
      />
      <StatTile
        label="Members joined"
        value={fmt(joined)}
        color={colors.good}
        sub={funnelSub(invited ? `Completed double opt-in · ${((joined / invited) * 100).toFixed(1)}% of invited` : "Completed double opt-in")}
      />
    </TileRow>
  )
}
