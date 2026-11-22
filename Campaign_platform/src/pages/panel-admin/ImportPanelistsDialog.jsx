import { useRef, useState } from "react"
import Papa from "papaparse"
import { buildApiUrl } from "../../config"
import { authFetch } from "../../utils/api"
import { notify } from "../../utils/notify"
import { Modal, Tabs, Notice, CountGrid, Field } from "../../components/panel-admin/ui"
import { colors, control } from "../../components/panel-admin/tokens"
import { parseApiResponse } from "../../components/panel-admin/apiResponse"

const API = "/api/panel-admin"
const fmt = (n) => Number(n || 0).toLocaleString()
const input = { ...control, width: "100%" }
const TABS = [
  { key: "csv", label: "CSV file" },
  { key: "link", label: "From a link" },
]

// Mirrors the backend's row checks (_upsert_panelists in routers/panel_admin.py):
// a row is skipped when its email is empty, or when that email already
// appeared earlier in the same file. Knowing these up front lets the result
// split the server's single "skipped" count into its reasons.
function checkRows(rows) {
  const seen = new Set()
  let noEmail = 0
  let dupes = 0
  for (const r of rows) {
    const email = String(r.email || r.Email || r.mail || r.Mail || "").trim().toLowerCase()
    if (!email) { noEmail++; continue }
    if (seen.has(email)) { dupes++; continue }
    seen.add(email)
  }
  return { total: rows.length, unique: seen.size, noEmail, dupes }
}

// The upload is one request, so there is no real percentage to show.
function Working({ text }) {
  return (
    <div role="status" style={{ padding: "1.5rem 0" }}>
      <style>{"@keyframes pa-indeterminate { from { transform: translateX(-100%) } to { transform: translateX(250%) } }"}</style>
      <div style={{ height: "6px", background: "#f5f3ef", borderRadius: "99px", overflow: "hidden" }}>
        <div style={{ width: "40%", height: "100%", background: "#e8910a", borderRadius: "99px", animation: "pa-indeterminate 1.2s ease-in-out infinite" }} />
      </div>
      <p style={{ margin: "0.75rem 0 0", fontSize: "0.875rem", color: colors.muted }}>{text}</p>
    </div>
  )
}

function Errors({ errors }) {
  if (!errors?.length) return null
  return (
    <Notice tone="bad" style={{ marginTop: "0.5rem" }}>
      <strong>{errors.length >= 10 ? "Rows that failed (first 10 shown):" : "Rows that failed:"}</strong>
      <ul style={{ margin: "0.35rem 0 0", paddingLeft: "1.1rem" }}>
        {errors.map((e, i) => <li key={i}>{e}</li>)}
      </ul>
    </Notice>
  )
}

/**
 * Add panelists from a CSV file or a CSV/JSON link. Same endpoints and
 * payloads as before (/panelists/upload-csv, /panelists/import-link); this
 * only moves the workflow into a dialog with a preview and a clear result.
 */
export default function ImportPanelistsDialog({ open, onClose, onImported }) {
  const [tab, setTab] = useState("csv")
  const [busy, setBusy] = useState(false)

  const [file, setFile] = useState(null) // { name, rows, check }
  const [dragging, setDragging] = useState(false)
  const [csvResult, setCsvResult] = useState(null)
  const inputRef = useRef(null)

  const [url, setUrl] = useState("")
  const [format, setFormat] = useState("auto")
  const [rootKey, setRootKey] = useState("")
  const [linkResult, setLinkResult] = useState(null)

  const resetCsv = () => {
    setFile(null)
    setCsvResult(null)
    if (inputRef.current) inputRef.current.value = ""
  }

  const close = () => {
    if (busy) return
    resetCsv()
    setLinkResult(null)
    onClose()
  }

  const readFile = (f) => {
    if (!f) return
    setCsvResult(null)
    Papa.parse(f, {
      header: true,
      skipEmptyLines: true,
      complete: (res) => setFile({ name: f.name, rows: res.data, check: checkRows(res.data) }),
      error: (err) => {
        console.error("CSV parse error:", err)
        notify("Failed to parse CSV file. Please check the format.")
      },
    })
  }

  const post = async (path, body) => {
    const res = await authFetch(buildApiUrl(`${API}${path}`), {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(body),
    })
    return { ok: res.ok, data: await parseApiResponse(res) }
  }

  const uploadCsv = async () => {
    if (!file?.rows.length) return
    setBusy(true)
    setCsvResult(null)
    try {
      const { ok, data } = await post("/panelists/upload-csv", { panelists: file.rows })
      if (ok) {
        const { noEmail, dupes } = file.check
        setCsvResult({
          ok: true,
          inserted: data.inserted || 0,
          alreadyListed: Math.max(0, (data.skipped || 0) - noEmail - dupes),
          dupes,
          noEmail,
          errors: data.errors || [],
        })
        onImported?.()
      } else {
        setCsvResult({ ok: false, message: data.detail || "Upload failed" })
      }
    } catch (err) {
      setCsvResult({ ok: false, message: "Network error: " + err.message })
    } finally {
      setBusy(false)
    }
  }

  const importLink = async () => {
    if (!url.trim()) return
    setBusy(true)
    setLinkResult(null)
    try {
      const payload = { url: url.trim(), format }
      if (rootKey.trim()) payload.root_key = rootKey.trim()
      const { ok, data } = await post("/panelists/import-link", payload)
      if (ok) {
        setLinkResult({ ok: true, fetched: data.fetched_rows, inserted: data.inserted || 0, skipped: data.skipped || 0, errors: data.errors || [], format: data.format })
        onImported?.()
      } else {
        setLinkResult({ ok: false, message: data.detail || "Import from link failed" })
      }
    } catch (err) {
      setLinkResult({ ok: false, message: "Network error: " + err.message })
    } finally {
      setBusy(false)
    }
  }

  const csvDone = csvResult?.ok
  const linkDone = linkResult?.ok
  const cancel = <button key="cancel" type="button" className="btn btn-outline" onClick={close} disabled={busy}>Cancel</button>
  const done = <button key="done" type="button" className="btn btn-primary" onClick={close}>Done</button>

  let footer
  if (tab === "csv") {
    footer = csvDone
      ? [<button key="again" type="button" className="btn btn-outline" onClick={resetCsv}>Import another file</button>, done]
      : [cancel, (
        <button key="go" type="button" className="btn btn-primary" onClick={uploadCsv} disabled={busy || !file || file.check.unique === 0}>
          {busy ? "Importing…" : file ? `Import ${fmt(file.check.unique)} panelists` : "Import"}
        </button>
      )]
  } else {
    footer = linkDone
      ? [<button key="again" type="button" className="btn btn-outline" onClick={() => setLinkResult(null)}>Import another link</button>, done]
      : [cancel, (
        <button key="go" type="button" className="btn btn-primary" onClick={importLink} disabled={busy || !url.trim()}>
          {busy ? "Importing…" : "Import from link"}
        </button>
      )]
  }

  return (
    <Modal open={open} title="Import panelists" onClose={close} busy={busy} footer={footer}>
      <Tabs tabs={TABS} active={tab} onChange={(k) => !busy && setTab(k)} />

      {tab === "csv" && (
        busy ? (
          <Working text={`Uploading ${fmt(file?.rows.length)} rows… large files can take a minute.`} />
        ) : csvDone ? (
          <>
            <Notice tone="good">Import finished for <strong>{file?.name}</strong>.</Notice>
            <CountGrid items={[
              { label: "Added", value: csvResult.inserted, color: colors.good },
              { label: "Already on the list", value: csvResult.alreadyListed },
              { label: "Duplicates in file", value: csvResult.dupes },
              { label: "No email", value: csvResult.noEmail },
              { label: "Failed", value: csvResult.errors.length, color: csvResult.errors.length ? colors.bad : colors.text },
            ]} />
            <Errors errors={csvResult.errors} />
          </>
        ) : !file ? (
          <label
            onDragOver={(e) => { e.preventDefault(); setDragging(true) }}
            onDragLeave={() => setDragging(false)}
            onDrop={(e) => { e.preventDefault(); setDragging(false); readFile(e.dataTransfer.files[0]) }}
            style={{ display: "block", border: `2px dashed ${dragging ? "#e8910a" : "#d4cec3"}`, borderRadius: "10px", padding: "2rem 1rem", textAlign: "center", cursor: "pointer", background: dragging ? "#fdf4e7" : "#faf9f7" }}
          >
            <input ref={inputRef} type="file" accept=".csv" aria-label="CSV file" onChange={(e) => readFile(e.target.files[0])} style={{ display: "none" }} />
            <div style={{ fontSize: "0.95rem", color: colors.text }}><strong style={{ color: colors.accent }}>Choose a CSV file</strong> or drop it here</div>
            <div style={{ fontSize: "0.8rem", color: colors.muted, marginTop: "0.4rem" }}>Columns: first_name, last_name, email, country, language (optional)</div>
          </label>
        ) : (
          <>
            <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", gap: "0.5rem", flexWrap: "wrap" }}>
              <span style={{ fontSize: "0.875rem", color: colors.text }}>
                <strong>{file.name}</strong> · {fmt(file.check.total)} rows
              </span>
              <button type="button" className="btn btn-outline" onClick={resetCsv} style={{ padding: "0.3rem 0.75rem", fontSize: "0.8rem" }}>Change file</button>
            </div>
            <CountGrid items={[
              { label: "Will be imported", value: file.check.unique, color: colors.good },
              { label: "Duplicates in file", value: file.check.dupes },
              { label: "No email", value: file.check.noEmail },
            ]} />
            {file.check.unique === 0 ? (
              <Notice tone="warn">
                No rows have an email. The file needs an <code>email</code> column; found: {Object.keys(file.rows[0] || {}).join(", ") || "no columns"}.
              </Notice>
            ) : (
              <p style={{ fontSize: "0.8rem", color: colors.muted, margin: "0 0 0.5rem" }}>
                Emails already on the panelist list are skipped automatically.
              </p>
            )}
            {csvResult && !csvResult.ok && <Notice tone="bad" style={{ marginTop: "0.5rem" }}>{csvResult.message}</Notice>}
            {file.rows.length > 0 && (
              <div style={{ marginTop: "0.75rem", overflowX: "auto", border: `1px solid ${colors.border}`, borderRadius: "8px" }}>
                <table style={{ width: "100%", borderCollapse: "collapse", fontSize: "0.8rem" }}>
                  <thead>
                    <tr style={{ background: "#faf9f7" }}>
                      {Object.keys(file.rows[0]).map((col) => (
                        <th key={col} style={{ textAlign: "left", padding: "0.45rem 0.6rem", color: "#5c5c5c", whiteSpace: "nowrap" }}>{col}</th>
                      ))}
                    </tr>
                  </thead>
                  <tbody>
                    {file.rows.slice(0, 5).map((row, i) => (
                      <tr key={i} style={{ borderTop: "1px solid #f5f3ef" }}>
                        {Object.values(row).map((val, j) => (
                          <td key={j} style={{ padding: "0.45rem 0.6rem", whiteSpace: "nowrap" }}>{val}</td>
                        ))}
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            )}
            {file.rows.length > 5 && (
              <p style={{ fontSize: "0.8rem", color: colors.muted, margin: "0.4rem 0 0" }}>Preview: first 5 of {fmt(file.rows.length)} rows</p>
            )}
          </>
        )
      )}

      {tab === "link" && (
        busy ? (
          <Working text="Fetching the link and importing… this can take a minute." />
        ) : linkDone ? (
          <>
            <Notice tone="good">Import finished{linkResult.format ? ` (${linkResult.format.toUpperCase()})` : ""}.</Notice>
            <CountGrid items={[
              { label: "Rows fetched", value: linkResult.fetched },
              { label: "Added", value: linkResult.inserted, color: colors.good },
              { label: "Skipped", value: linkResult.skipped },
              { label: "Failed", value: linkResult.errors.length, color: linkResult.errors.length ? colors.bad : colors.text },
            ]} />
            <p style={{ fontSize: "0.8rem", color: colors.muted, margin: 0 }}>Skipped = already on the list, repeated in the source, or no email.</p>
            <Errors errors={linkResult.errors} />
          </>
        ) : (
          <>
            <p style={{ fontSize: "0.875rem", color: colors.muted, marginTop: 0 }}>
              Paste an API or export URL from sfw_panel or any system that returns CSV or a JSON array.
            </p>
            <Field label="Link" htmlFor="import-url" required>
              <input id="import-url" type="url" value={url} onChange={(e) => setUrl(e.target.value)} placeholder="https://example.com/panelists.csv" style={input} />
            </Field>
            <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fit, minmax(180px, 1fr))", gap: "0 0.75rem" }}>
              <Field label="Format" htmlFor="import-format">
                <select id="import-format" value={format} onChange={(e) => setFormat(e.target.value)} style={input}>
                  <option value="auto">Detect automatically</option>
                  <option value="csv">CSV</option>
                  <option value="json">JSON</option>
                </select>
              </Field>
              <Field label="JSON root key" hint="(optional)" htmlFor="import-root">
                <input id="import-root" type="text" value={rootKey} onChange={(e) => setRootKey(e.target.value)} placeholder="e.g. panelists" disabled={format === "csv"} style={{ ...input, opacity: format === "csv" ? 0.5 : 1 }} />
              </Field>
            </div>
            {linkResult && !linkResult.ok && <Notice tone="bad" style={{ marginTop: "0.75rem" }}>{linkResult.message}</Notice>}
          </>
        )
      )}
    </Modal>
  )
}
