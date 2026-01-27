import { useEffect, useState } from "react"
import { useNavigate } from "react-router-dom"
import { API_BASE_URL } from "../../../config"  // adjust path as per your structure
import { buildApiUrl } from "../../../config"

function Reports() {
  const navigate = useNavigate()
  const [campaigns, setCampaigns] = useState([])
  const [loading, setLoading] = useState(true)

  // 🔹 Helper for authenticated fetch
  async function apiFetch(path, options = {}) {
    const sessionId = localStorage.getItem("session_id")
    if (!sessionId) {
      alert("Session expired. Please login again.")
      navigate("/login")
      throw new Error("No session")
    }

    const res = await fetch(buildApiUrl(`${path}`), {
      ...options,
      headers: {
        "Content-Type": "application/json",
        Authorization: sessionId,
        ...options.headers,
      },
    })

    if (res.status === 401) {
      alert("Session expired. Please login again.")
      localStorage.removeItem("session_id")
      navigate("/login")
      throw new Error("Session expired")
    }
    return res
  }

  // Fetch reports from backend
  useEffect(() => {
    const fetchReports = async () => {
      try {
        const res = await apiFetch("/reports/")
        const data = await res.json()
        if (data.campaigns) {
          setCampaigns(data.campaigns)
        }
      } catch (err) {
        console.error("❌ Failed to fetch reports:", err)
      } finally {
        setLoading(false)
      }
    }
    fetchReports()
  }, [])

  return (
    <div>
      <div className="card">
        <div className="card-header">
          <h2 className="card-title">Top Campaigns</h2>
          <p className="card-description">
            Real-time open and click tracking from your campaigns.
          </p>
        </div>

        {loading ? (
          <p>Loading reports...</p>
        ) : campaigns.length === 0 ? (
          <p>No campaigns found.</p>
        ) : (
          <table style={{ width: "100%", borderCollapse: "collapse" }}>
            <thead>
              <tr style={{ borderBottom: "1px solid #e5e7eb", backgroundColor: "#1e293b", color: "#fff" }}>
                <th style={{ padding: "1rem", textAlign: "left" }}>Campaign</th>
                <th style={{ padding: "1rem", textAlign: "left" }}>Opens</th>
                <th style={{ padding: "1rem", textAlign: "left" }}>Clicks</th>
              </tr>
            </thead>
            <tbody>
              {campaigns.map((c, idx) => {
                const opens = new Set((c.opens || []).map(o => o.email)).size
                const clicks = new Set((c.clicks || []).map(cl => cl.email)).size
                return (
                  <tr key={idx} style={{ borderBottom: "1px solid #f3f4f6" }}>
                    <td style={{ padding: "1rem", fontWeight: "600" }}>{c.subject}</td>
                    <td style={{ padding: "1rem" }}>{opens}</td>
                    <td style={{ padding: "1rem" }}>{clicks}</td>
                  </tr>
                )
              })}
            </tbody>
          </table>
        )}
      </div>
    </div>
  )
}

export default Reports