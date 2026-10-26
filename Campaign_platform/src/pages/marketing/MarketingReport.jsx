import { useEffect, useState } from "react"
import { RefreshCw } from "lucide-react"
import { buildApiUrl } from "../../config"
import { authFetch } from "../../utils/api"
import { notify } from "../../utils/notify"
import { formatDateTime } from "../../utils/format"

// Marketing > Weekly report (MARKETING_PLAN 6.4). The HTML is built and escaped on the server.
export default function MarketingReport() {
  const [r, setR] = useState(null)
  const load = async (rebuild = false) => {
    try {
      const res = await authFetch(buildApiUrl(`/api/marketing/inbox/weekly-report${rebuild ? "?rebuild=true" : ""}`))
      const data = await res.json()
      if (!res.ok) throw new Error(data.detail || `Request failed (${res.status})`)
      setR(data)
    } catch (e) {
      notify(e.message, "error")
    }
  }
  useEffect(() => { load() }, [])
  if (!r) return <div className="card">Loading…</div>
  return (
    <div className="card">
      <div className="card-header flex items-center justify-between">
        <p className="card-description">Week {r.week} · built {formatDateTime(r.built_at)} · every Monday 09:00 IST</p>
        <button type="button" className="btn btn-secondary flex items-center gap-1" onClick={() => load(true)}><RefreshCw size={16} /> Rebuild</button>
      </div>
      <div className="marketing-report text-sm" dangerouslySetInnerHTML={{ __html: r.html }} />
    </div>
  )
}
