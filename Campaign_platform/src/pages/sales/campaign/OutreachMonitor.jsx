import { useEffect, useMemo, useState } from "react"
import { buildApiUrl } from "../../../config"

const styles = {
  page: {
    padding: "20px",
    background: "#f8fafc",
    minHeight: "100vh",
    display: "flex",
    flexDirection: "column",
    gap: "16px",
  },
  row: {
    display: "grid",
    gridTemplateColumns: "repeat(4, minmax(0, 1fr))",
    gap: "12px",
  },
  card: {
    background: "#ffffff",
    border: "1px solid #e2e8f0",
    borderRadius: "10px",
    padding: "12px",
    boxShadow: "0 1px 2px rgba(0,0,0,0.04)",
  },
  statLabel: { fontSize: "12px", color: "#64748b" },
  statValue: { fontSize: "22px", fontWeight: 700, color: "#1e293b", marginTop: "4px" },
  panel: {
    background: "#fff",
    border: "1px solid #e2e8f0",
    borderRadius: "10px",
    padding: "14px",
  },
  panelTitle: { margin: 0, fontSize: "16px", fontWeight: 700, color: "#0f172a" },
  panelSub: { margin: "6px 0 0", fontSize: "12px", color: "#64748b" },
  toolbar: { display: "flex", gap: "8px", alignItems: "center", marginTop: "12px" },
  button: {
    border: "1px solid #cbd5e1",
    borderRadius: "8px",
    background: "#fff",
    color: "#0f172a",
    fontSize: "12px",
    padding: "8px 10px",
    cursor: "pointer",
  },
  primaryButton: {
    border: "1px solid #f97316",
    borderRadius: "8px",
    background: "#f97316",
    color: "#fff",
    fontSize: "12px",
    padding: "8px 10px",
    cursor: "pointer",
  },
  tableWrap: { overflowX: "auto", marginTop: "10px" },
  table: { width: "100%", borderCollapse: "collapse", fontSize: "12px" },
  th: { textAlign: "left", borderBottom: "1px solid #e2e8f0", color: "#334155", padding: "8px" },
  td: { borderBottom: "1px solid #f1f5f9", color: "#334155", padding: "8px", verticalAlign: "top" },
  statusTag: {
    display: "inline-block",
    padding: "3px 8px",
    borderRadius: "999px",
    background: "#f1f5f9",
    fontWeight: 600,
    fontSize: "11px",
  },
  twoCol: {
    display: "grid",
    gridTemplateColumns: "1fr 1.3fr",
    gap: "14px",
    alignItems: "start",
  },
  select: {
    width: "100%",
    border: "1px solid #cbd5e1",
    borderRadius: "8px",
    fontSize: "12px",
    padding: "8px",
    marginTop: "10px",
  },
  textarea: {
    width: "100%",
    minHeight: "300px",
    border: "1px solid #cbd5e1",
    borderRadius: "8px",
    fontSize: "12px",
    lineHeight: 1.5,
    padding: "10px",
    marginTop: "10px",
    resize: "vertical",
    fontFamily: "inherit",
  },
  message: { marginTop: "8px", fontSize: "12px" },
}

function getAuthHeader() {
  const sessionId = localStorage.getItem("session_id")
  return sessionId ? { Authorization: sessionId } : {}
}

function formatTime(value) {
  if (!value) return "-"
  const date = new Date(value)
  if (Number.isNaN(date.getTime())) return "-"
  return date.toLocaleString()
}

export default function OutreachMonitor() {
  const [loading, setLoading] = useState(false)
  const [saving, setSaving] = useState(false)
  const [error, setError] = useState("")
  const [ok, setOk] = useState("")

  const [summary, setSummary] = useState({})
  const [recent, setRecent] = useState([])
  const [prompts, setPrompts] = useState([])
  const [selectedPromptKey, setSelectedPromptKey] = useState("")
  const [promptContent, setPromptContent] = useState("")

  const selectedPrompt = useMemo(
    () => prompts.find((item) => item.prompt_key === selectedPromptKey),
    [prompts, selectedPromptKey]
  )

  async function loadDashboard() {
    const response = await fetch(buildApiUrl("/api/outreach/dashboard?limit=120"), {
      headers: { "Content-Type": "application/json", ...getAuthHeader() },
    })
    if (!response.ok) throw new Error(`Dashboard request failed (${response.status})`)
    return response.json()
  }

  async function loadPrompts() {
    const response = await fetch(buildApiUrl("/api/outreach/prompts"), {
      headers: { "Content-Type": "application/json", ...getAuthHeader() },
    })
    if (!response.ok) throw new Error(`Prompts request failed (${response.status})`)
    return response.json()
  }

  const refreshAll = async () => {
    setLoading(true)
    setError("")
    setOk("")
    try {
      const [dashboardRes, promptRes] = await Promise.all([loadDashboard(), loadPrompts()])
      setSummary(dashboardRes.summary || {})
      setRecent(dashboardRes.recent || [])

      const promptList = promptRes.prompts || []
      setPrompts(promptList)

      if (promptList.length > 0) {
        const key = selectedPromptKey && promptList.some((p) => p.prompt_key === selectedPromptKey)
          ? selectedPromptKey
          : promptList[0].prompt_key
        setSelectedPromptKey(key)
        const selected = promptList.find((p) => p.prompt_key === key)
        setPromptContent(selected?.content || "")
      }
    } catch (err) {
      setError(err.message || "Failed to load outreach monitor")
    } finally {
      setLoading(false)
    }
  }

  useEffect(() => {
    refreshAll()
  }, [])

  useEffect(() => {
    if (selectedPrompt) {
      setPromptContent(selectedPrompt.content || "")
    }
  }, [selectedPromptKey, selectedPrompt])

  const savePrompt = async () => {
    if (!selectedPromptKey) return
    setSaving(true)
    setError("")
    setOk("")
    try {
      const response = await fetch(buildApiUrl(`/api/outreach/prompts/${selectedPromptKey}`), {
        method: "PUT",
        headers: {
          "Content-Type": "application/json",
          ...getAuthHeader(),
        },
        body: JSON.stringify({ content: promptContent }),
      })

      const data = await response.json().catch(() => ({}))
      if (!response.ok || !data.success) {
        throw new Error(data.detail || "Failed to save prompt")
      }

      setOk("Prompt saved successfully")
      await refreshAll()
    } catch (err) {
      setError(err.message || "Failed to save prompt")
    } finally {
      setSaving(false)
    }
  }

  return (
    <div style={styles.page}>
      <div style={styles.panel}>
        <h2 style={styles.panelTitle}>Outreach Monitor</h2>
        <p style={styles.panelSub}>
          Track sent mail progress, delivery/open/click/reply outcomes, sender mail used, and edit outreach prompts.
        </p>
        <div style={styles.toolbar}>
          <button style={styles.primaryButton} onClick={refreshAll} disabled={loading}>
            {loading ? "Refreshing..." : "Refresh Data"}
          </button>
          {error ? <span style={{ ...styles.message, color: "#b91c1c" }}>{error}</span> : null}
          {ok ? <span style={{ ...styles.message, color: "#166534" }}>{ok}</span> : null}
        </div>
      </div>

      <div style={styles.row}>
        <div style={styles.card}>
          <div style={styles.statLabel}>Sent</div>
          <div style={styles.statValue}>{summary.sent || 0}</div>
          <div style={styles.statLabel}>Queued: {summary.queued || 0}</div>
        </div>
        <div style={styles.card}>
          <div style={styles.statLabel}>Opened</div>
          <div style={styles.statValue}>{summary.opened || 0}</div>
          <div style={styles.statLabel}>Open Rate: {summary.open_rate || 0}%</div>
        </div>
        <div style={styles.card}>
          <div style={styles.statLabel}>Replied</div>
          <div style={styles.statValue}>{summary.replied || 0}</div>
          <div style={styles.statLabel}>Reply Rate: {summary.reply_rate || 0}%</div>
        </div>
        <div style={styles.card}>
          <div style={styles.statLabel}>Bounced</div>
          <div style={styles.statValue}>{summary.bounced || 0}</div>
          <div style={styles.statLabel}>Bounce Rate: {summary.bounce_rate || 0}%</div>
        </div>
      </div>

      <div style={styles.panel}>
        <h3 style={styles.panelTitle}>Recent Outreach Emails</h3>
        <p style={styles.panelSub}>Shows mail content, status, send timestamp, and sender account used.</p>
        <div style={styles.tableWrap}>
          <table style={styles.table}>
            <thead>
              <tr>
                <th style={styles.th}>To</th>
                <th style={styles.th}>Sender Mail</th>
                <th style={styles.th}>Subject</th>
                <th style={styles.th}>Status</th>
                <th style={styles.th}>Sent At</th>
                <th style={styles.th}>Opened</th>
                <th style={styles.th}>Clicks</th>
                <th style={styles.th}>Content</th>
              </tr>
            </thead>
            <tbody>
              {recent.length === 0 ? (
                <tr>
                  <td style={styles.td} colSpan={8}>No outreach emails found.</td>
                </tr>
              ) : (
                recent.map((row) => (
                  <tr key={row.id}>
                    <td style={styles.td}>{row.to_email || "-"}</td>
                    <td style={styles.td}>{row.sender_email || row.sender_id || "-"}</td>
                    <td style={styles.td}>{row.subject || "-"}</td>
                    <td style={styles.td}>
                      <span style={styles.statusTag}>{row.status || "unknown"}</span>
                    </td>
                    <td style={styles.td}>{formatTime(row.sent_at || row.scheduled_for || row.updated_at)}</td>
                    <td style={styles.td}>{row.open_count || 0}</td>
                    <td style={styles.td}>{row.click_count || 0}</td>
                    <td style={styles.td}>
                      <div style={{ maxWidth: "340px", whiteSpace: "pre-wrap" }}>
                        {row.body ? `${row.body.slice(0, 220)}${row.body.length > 220 ? "..." : ""}` : "-"}
                      </div>
                    </td>
                  </tr>
                ))
              )}
            </tbody>
          </table>
        </div>
      </div>

      <div style={{ ...styles.panel, ...styles.twoCol }}>
        <div>
          <h3 style={styles.panelTitle}>Prompt Controls</h3>
          <p style={styles.panelSub}>Select and edit outreach prompts from this dashboard.</p>

          <select
            style={styles.select}
            value={selectedPromptKey}
            onChange={(e) => setSelectedPromptKey(e.target.value)}
          >
            {prompts.map((prompt) => (
              <option key={prompt.prompt_key} value={prompt.prompt_key}>
                {prompt.prompt_key}{prompt.is_overridden ? " (overridden)" : ""}
              </option>
            ))}
          </select>

          <div style={{ marginTop: "10px", fontSize: "12px", color: "#64748b" }}>
            Current prompt key: {selectedPromptKey || "-"}
          </div>
        </div>

        <div>
          <textarea
            style={styles.textarea}
            value={promptContent}
            onChange={(e) => setPromptContent(e.target.value)}
            placeholder="Prompt content"
          />
          <div style={{ ...styles.toolbar, justifyContent: "flex-end" }}>
            <button style={styles.button} onClick={() => setPromptContent(selectedPrompt?.content || "")}>Reset</button>
            <button style={styles.primaryButton} onClick={savePrompt} disabled={saving || !selectedPromptKey}>
              {saving ? "Saving..." : "Save Prompt"}
            </button>
          </div>
        </div>
      </div>
    </div>
  )
}
