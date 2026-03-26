"use client";

import { useState, useEffect, useCallback } from "react";
import {
  BarChart2, RefreshCw, Plus, Trash2, Pencil, Play, Pause,
  Download, ExternalLink, X, ChevronRight,
} from "lucide-react";
import { qreApi } from "../../services/qreApi";
import "./QREPage.css";

// ── Quota label map ─────────────────────────────────────────────────────────
const QUOTA_LABELS = {
  band1_25_34: "Age 25–34",
  band2_35_44: "Age 35–44",
  band3_45_55: "Age 45–55",
  male: "Male",
  female: "Female",
  nccs_a: "NCCS A",
  nccs_b: "NCCS B",
  chennai: "Chennai",
  kolkata: "Kolkata",
  mumbai: "Mumbai",
  hyderabad: "Hyderabad",
  group_a: "Group A",
  group_b: "Group B",
  group_c: "Group C",
  group_d: "Group D",
  group_e: "Group E",
  group_f: "Group F",
  group_g: "Group G",
};

const label = (key) =>
  QUOTA_LABELS[key] ||
  key.replace(/_/g, " ").replace(/\b\w/g, (c) => c.toUpperCase());

// ── Status Badge ─────────────────────────────────────────────────────────────
function StatusBadge({ status }) {
  const cls = {
    live: "qre-badge-live",
    draft: "qre-badge-draft",
    paused: "qre-badge-paused",
    closed: "qre-badge-closed",
  }[status] || "qre-badge-draft";
  return <span className={`qre-badge ${cls}`}>{status}</span>;
}

// ── Toast helper ─────────────────────────────────────────────────────────────
function useToast() {
  const [msg, setMsg] = useState("");
  const show = useCallback((text) => {
    setMsg(text);
    setTimeout(() => setMsg(""), 3200);
  }, []);
  return [msg, show];
}

// ── Studies Tab ───────────────────────────────────────────────────────────────
function StudiesTab({ onSelectStudy, selectedStudyId }) {
  const [studies, setStudies] = useState([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(null);
  const [showCreate, setShowCreate] = useState(false);
  const [form, setForm] = useState({ name: "", client_name: "", description: "" });
  const [saving, setSaving] = useState(false);
  const [toast, showToast] = useToast();

  const load = useCallback(async () => {
    try {
      setError(null);
      const data = await qreApi.listStudies();
      setStudies(data);
    } catch (e) {
      setError(e.message);
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => { load(); }, [load]);

  const createStudy = async () => {
    if (!form.name.trim() || !form.client_name.trim()) return;
    setSaving(true);
    try {
      await qreApi.createStudy(form);
      showToast("Study created");
      setShowCreate(false);
      setForm({ name: "", client_name: "", description: "" });
      load();
    } catch (e) {
      showToast("Error: " + e.message);
    }
    setSaving(false);
  };

  const changeStatus = async (id, status) => {
    try {
      await qreApi.updateStudy(id, { status });
      showToast(`Study set to ${status}`);
      load();
    } catch (e) {
      showToast("Error: " + e.message);
    }
  };

  const deleteStudy = async (id, name) => {
    if (!window.confirm(`Delete study "${name}"? This removes all respondent data and cannot be undone.`)) return;
    try {
      await qreApi.deleteStudy(id);
      showToast("Study deleted");
      if (selectedStudyId === id) onSelectStudy(null);
      load();
    } catch (e) {
      showToast("Error: " + e.message);
    }
  };

  if (loading) return <div className="qre-loading">Loading studies…</div>;

  return (
    <>
      {toast && <div className="qre-toast">{toast}</div>}
      {error && (
        <div className="qre-error-banner">
          ⚠️ Could not connect to QRE backend — {error}
        </div>
      )}

      <div className="qre-section">
        <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", marginBottom: "0.85rem" }}>
          <h2 className="qre-section-title" style={{ margin: 0 }}>All Studies</h2>
          <button className="qre-btn qre-btn-sm" onClick={() => setShowCreate(true)}>
            <Plus size={13} /> New Study
          </button>
        </div>

        {studies.length === 0 ? (
          <div className="qre-empty">
            <div className="qre-empty-icon">📋</div>
            <div className="qre-empty-title">No studies yet</div>
            <div className="qre-empty-desc">Create your first QRE study to get started.</div>
          </div>
        ) : (
          <div className="qre-table-wrap">
            <table className="qre-table">
              <thead>
                <tr>
                  <th>Study Name</th>
                  <th>Client</th>
                  <th>Status</th>
                  <th>Created</th>
                  <th>Actions</th>
                </tr>
              </thead>
              <tbody>
                {studies.map((s) => (
                  <tr key={s.id} style={{ background: selectedStudyId === s.id ? "#f0f0ff" : undefined }}>
                    <td>
                      <button
                        className="qre-btn qre-btn-outline qre-btn-sm"
                        onClick={() => onSelectStudy(s)}
                        style={{ marginRight: 6 }}
                        title="View study dashboard"
                      >
                        <ChevronRight size={12} />
                      </button>
                      <strong>{s.name}</strong>
                    </td>
                    <td>{s.client_name}</td>
                    <td><StatusBadge status={s.status} /></td>
                    <td>{s.created_at ? new Date(s.created_at).toLocaleDateString() : "—"}</td>
                    <td>
                      <div className="actions-cell">
                        {s.status === "draft" || s.status === "paused" ? (
                          <button
                            className="qre-btn qre-btn-success qre-btn-sm"
                            title="Set Live"
                            onClick={() => changeStatus(s.id, "live")}
                          ><Play size={11} /></button>
                        ) : s.status === "live" ? (
                          <button
                            className="qre-btn qre-btn-secondary qre-btn-sm"
                            title="Pause"
                            onClick={() => changeStatus(s.id, "paused")}
                          ><Pause size={11} /></button>
                        ) : null}
                        <button
                          className="qre-btn qre-btn-danger qre-btn-sm"
                          title="Delete"
                          onClick={() => deleteStudy(s.id, s.name)}
                        ><Trash2 size={11} /></button>
                      </div>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </div>

      {/* Create modal */}
      {showCreate && (
        <div className="qre-modal-overlay" onClick={() => setShowCreate(false)}>
          <div className="qre-modal" onClick={(e) => e.stopPropagation()}>
            <h3 className="qre-modal-title">Create New Study</h3>
            <div className="qre-form">
              <div>
                <label className="qre-label">Study Name *</label>
                <input
                  className="qre-input"
                  placeholder="e.g. India Urban Consumer Health Survey"
                  value={form.name}
                  onChange={(e) => setForm((p) => ({ ...p, name: e.target.value }))}
                />
              </div>
              <div>
                <label className="qre-label">Client Name *</label>
                <input
                  className="qre-input"
                  placeholder="e.g. Cogentix Research"
                  value={form.client_name}
                  onChange={(e) => setForm((p) => ({ ...p, client_name: e.target.value }))}
                />
              </div>
              <div>
                <label className="qre-label">Description</label>
                <textarea
                  className="qre-textarea"
                  placeholder="Optional description…"
                  value={form.description}
                  onChange={(e) => setForm((p) => ({ ...p, description: e.target.value }))}
                />
              </div>
            </div>
            <div className="qre-modal-actions">
              <button className="qre-btn qre-btn-outline" onClick={() => setShowCreate(false)}>Cancel</button>
              <button
                className="qre-btn"
                disabled={saving || !form.name.trim() || !form.client_name.trim()}
                onClick={createStudy}
              >
                {saving ? "Creating…" : "Create Study"}
              </button>
            </div>
          </div>
        </div>
      )}
    </>
  );
}

// ── Overview Tab ─────────────────────────────────────────────────────────────
function OverviewTab({ studyId }) {
  const [stats, setStats] = useState(null);
  const [quotas, setQuotas] = useState([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(null);

  const load = useCallback(async () => {
    try {
      setError(null);
      const [s, q] = await Promise.all([
        qreApi.getStats(studyId),
        qreApi.getQuotas(studyId),
      ]);
      setStats(s);
      setQuotas(q);
    } catch (e) {
      setError(e.message);
    } finally {
      setLoading(false);
    }
  }, [studyId]);

  useEffect(() => {
    load();
    const iv = setInterval(load, 15000);
    return () => clearInterval(iv);
  }, [load]);

  if (loading) return <div className="qre-loading">Loading overview…</div>;
  if (error) return <div className="qre-error-banner">⚠️ {error}</div>;
  if (!stats) return <div className="qre-empty"><div className="qre-empty-icon">📊</div><div className="qre-empty-title">No data available</div></div>;

  const pct = stats.total_started > 0 ? Math.round((stats.completed / stats.total_started) * 100) : 0;

  return (
    <>
      {/* KPI row */}
      <div className="qre-kpi-grid">
        <div className="qre-kpi-card qre-kpi-info">
          <div className="qre-kpi-value">{stats.total_started ?? 0}</div>
          <div className="qre-kpi-label">Total Started</div>
        </div>
        <div className="qre-kpi-card qre-kpi-success">
          <div className="qre-kpi-value">{stats.completed ?? 0}</div>
          <div className="qre-kpi-label">Completed</div>
        </div>
        <div className="qre-kpi-card qre-kpi-danger">
          <div className="qre-kpi-value">{stats.terminated ?? 0}</div>
          <div className="qre-kpi-label">Terminated</div>
        </div>
        <div className="qre-kpi-card">
          <div className="qre-kpi-value">{stats.in_progress ?? 0}</div>
          <div className="qre-kpi-label">In Progress</div>
        </div>
        <div className="qre-kpi-card">
          <div className="qre-kpi-value">{stats.completion_rate ?? pct}%</div>
          <div className="qre-kpi-label">Completion Rate</div>
        </div>
        {stats.incidence_rate !== undefined && (
          <div className="qre-kpi-card">
            <div className="qre-kpi-value">{stats.incidence_rate}%</div>
            <div className="qre-kpi-label">Incidence Rate</div>
          </div>
        )}
      </div>

      {/* Fieldwork progress */}
      {stats.target_sample && (
        <div className="qre-section">
          <h3 className="qre-section-title">Fieldwork Progress</h3>
          <div className="qre-fieldwork-bar-wrap">
            <div className="qre-fieldwork-bar-labels">
              <span>{stats.completed} completes</span>
              <span>Target: {stats.target_sample}</span>
            </div>
            <div className="qre-fieldwork-bar-track">
              <div
                className="qre-fieldwork-bar-fill"
                style={{ width: `${Math.min(100, (stats.completed / stats.target_sample) * 100)}%` }}
              />
            </div>
          </div>
        </div>
      )}

      {/* Quota fill */}
      {quotas.length > 0 && (
        <div className="qre-section">
          <h3 className="qre-section-title">Quota Fill Status</h3>
          <div className="qre-quota-grid">
            {quotas.map((q) => {
              const fillPct = q.limit > 0 ? Math.min(100, Math.round((q.current / q.limit) * 100)) : 0;
              const barColor = q.is_full ? "#dc2626" : fillPct >= 80 ? "#f59e0b" : "#667eea";
              return (
                <div key={q.quota_key} className="qre-quota-card">
                  <div className="qre-quota-header">
                    <span>{label(q.quota_key)}</span>
                    <span className={q.is_full ? "qre-quota-full-label" : ""}>{q.current}/{q.limit}</span>
                  </div>
                  <div className="qre-quota-track">
                    <div className="qre-quota-fill" style={{ width: `${fillPct}%`, background: barColor }} />
                  </div>
                  <div className="qre-quota-pct">{fillPct}%</div>
                </div>
              );
            })}
          </div>
        </div>
      )}

      {/* Daily completions chart */}
      {stats.daily_completions?.length > 0 && (
        <div className="qre-section">
          <h3 className="qre-section-title">Daily Completions</h3>
          <div className="qre-daily-chart">
            {stats.daily_completions.map((d) => {
              const maxCount = Math.max(...stats.daily_completions.map((x) => x.count), 1);
              return (
                <div key={d.date} className="qre-daily-bar-wrap">
                  <div className="qre-daily-count">{d.count}</div>
                  <div className="qre-daily-bar" style={{ height: `${(d.count / maxCount) * 80}px` }} />
                  <div className="qre-daily-date">{d.date?.slice(5)}</div>
                </div>
              );
            })}
          </div>
        </div>
      )}

      {/* Termination reasons */}
      {stats.termination_reasons?.length > 0 && (
        <div className="qre-section">
          <h3 className="qre-section-title">Termination Reasons</h3>
          <div className="qre-table-wrap">
            <table className="qre-table qre-term-table">
              <thead><tr><th>Reason</th><th>Count</th></tr></thead>
              <tbody>
                {stats.termination_reasons.map((r) => (
                  <tr key={r.reason}><td>{r.reason}</td><td>{r.count}</td></tr>
                ))}
              </tbody>
            </table>
          </div>
        </div>
      )}
    </>
  );
}

// ── Quotas Tab ────────────────────────────────────────────────────────────────
function QuotasTab({ studyId }) {
  const [quotas, setQuotas] = useState([]);
  const [editLimits, setEditLimits] = useState({});
  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState(null);
  const [toast, showToast] = useToast();

  const load = useCallback(async () => {
    try {
      setError(null);
      const q = await qreApi.getQuotas(studyId);
      setQuotas(q);
      const lims = {};
      q.forEach((cell) => { lims[cell.quota_key] = cell.limit; });
      setEditLimits(lims);
    } catch (e) {
      setError(e.message);
    } finally {
      setLoading(false);
    }
  }, [studyId]);

  useEffect(() => { load(); }, [load]);

  const saveLimit = async (key) => {
    setSaving(true);
    try {
      await qreApi.updateQuota(key, editLimits[key], studyId);
      showToast(`Updated ${label(key)}`);
      load();
    } catch (e) {
      showToast("Error: " + e.message);
    }
    setSaving(false);
  };

  const resetAll = async () => {
    if (!window.confirm("Reset ALL quota counters to zero? This cannot be undone.")) return;
    try {
      await qreApi.resetQuotas(studyId);
      showToast("All quotas reset to zero");
      load();
    } catch (e) {
      showToast("Error: " + e.message);
    }
  };

  if (loading) return <div className="qre-loading">Loading quotas…</div>;

  return (
    <>
      {toast && <div className="qre-toast">{toast}</div>}
      {error && <div className="qre-error-banner">⚠️ {error}</div>}
      <div className="qre-section">
        <h2 className="qre-section-title">Manage Quota Cells</h2>
        <p className="qre-section-desc">
          Adjust the target limit per demographic cell. Changes apply immediately for new respondents.
        </p>
        {quotas.length === 0 ? (
          <div className="qre-empty">
            <div className="qre-empty-icon">🎯</div>
            <div className="qre-empty-title">No quota data</div>
          </div>
        ) : (
          <div className="qre-table-wrap">
            <table className="qre-table">
              <thead>
                <tr>
                  <th>Cell</th>
                  <th>Current</th>
                  <th>Limit</th>
                  <th>Fill %</th>
                  <th></th>
                </tr>
              </thead>
              <tbody>
                {quotas.map((q) => {
                  const fillPct = q.limit > 0 ? Math.round((q.current / q.limit) * 100) : 0;
                  return (
                    <tr key={q.quota_key}>
                      <td>{label(q.quota_key)}</td>
                      <td>{q.current}</td>
                      <td>
                        <input
                          type="number"
                          min="0"
                          className="qre-input-sm"
                          value={editLimits[q.quota_key] ?? q.limit}
                          onChange={(e) =>
                            setEditLimits((p) => ({ ...p, [q.quota_key]: parseInt(e.target.value) || 0 }))
                          }
                        />
                      </td>
                      <td>
                        <span style={{ color: q.is_full ? "#dc2626" : fillPct >= 80 ? "#f59e0b" : "#16a34a", fontWeight: 600 }}>
                          {fillPct}%
                        </span>
                      </td>
                      <td>
                        <button
                          className="qre-btn qre-btn-sm"
                          disabled={saving || editLimits[q.quota_key] === q.limit}
                          onClick={() => saveLimit(q.quota_key)}
                        >
                          Save
                        </button>
                      </td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
          </div>
        )}
        <div style={{ marginTop: "1.25rem" }}>
          <button className="qre-btn qre-btn-danger" onClick={resetAll}>
            Reset All Counters to Zero
          </button>
        </div>
      </div>
    </>
  );
}

// ── Redirects Tab ─────────────────────────────────────────────────────────────
function RedirectsTab({ studyId }) {
  const [redirects, setRedirects] = useState({ complete_url: "", terminate_url: "", overquota_url: "" });
  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);
  const [toast, showToast] = useToast();

  useEffect(() => {
    qreApi.getRedirects(studyId)
      .then(setRedirects)
      .catch(() => {})
      .finally(() => setLoading(false));
  }, [studyId]);

  const save = async () => {
    setSaving(true);
    try {
      await qreApi.setRedirects(redirects, studyId);
      showToast("Redirect URLs saved");
    } catch (e) {
      showToast("Error: " + e.message);
    }
    setSaving(false);
  };

  if (loading) return <div className="qre-loading">Loading redirects…</div>;

  const entryLink = `${window.location.origin}/survey/?study_id=${studyId}&rid=[RID]`;

  return (
    <>
      {toast && <div className="qre-toast">{toast}</div>}
      <div className="qre-section">
        <h2 className="qre-section-title">Entry Link</h2>
        <p className="qre-section-desc">
          Share this link with your panel vendor. Replace <code>[RID]</code> with the vendor's panelist ID variable.
        </p>
        <div className="qre-form" style={{ maxWidth: 600 }}>
          <div style={{ display: "flex", gap: 8, alignItems: "center" }}>
            <input
              className="qre-input"
              readOnly
              value={entryLink}
              style={{ flex: 1, background: "#f8fafc", cursor: "text" }}
              onFocus={(e) => e.target.select()}
            />
            <button
              className="qre-btn"
              style={{ whiteSpace: "nowrap" }}
              onClick={() => { navigator.clipboard.writeText(entryLink); showToast("Copied!"); }}
            >
              Copy
            </button>
          </div>
        </div>
      </div>
      <div className="qre-section">
        <h2 className="qre-section-title">Redirect URLs</h2>
        <p className="qre-section-desc">
          Configure end-of-survey redirect destinations. Use <code>[RID]</code> as a placeholder for the respondent ID.
        </p>
        <div className="qre-form" style={{ maxWidth: 600 }}>
          <div>
            <label className="qre-label">Complete URL</label>
            <input
              className="qre-input"
              placeholder="https://panel.example.com/complete?rid=[RID]"
              value={redirects.complete_url}
              onChange={(e) => setRedirects((p) => ({ ...p, complete_url: e.target.value }))}
            />
          </div>
          <div>
            <label className="qre-label">Terminate URL</label>
            <input
              className="qre-input"
              placeholder="https://panel.example.com/terminate?rid=[RID]"
              value={redirects.terminate_url}
              onChange={(e) => setRedirects((p) => ({ ...p, terminate_url: e.target.value }))}
            />
          </div>
          <div>
            <label className="qre-label">Overquota URL</label>
            <input
              className="qre-input"
              placeholder="https://panel.example.com/overquota?rid=[RID]"
              value={redirects.overquota_url}
              onChange={(e) => setRedirects((p) => ({ ...p, overquota_url: e.target.value }))}
            />
          </div>
          <div>
            <button className="qre-btn" disabled={saving} onClick={save} style={{ marginTop: 4 }}>
              {saving ? "Saving…" : "Save Redirects"}
            </button>
          </div>
        </div>
      </div>
    </>
  );
}

// ── Export Tab ────────────────────────────────────────────────────────────────
function ExportTab({ studyId }) {
  const [busy, setBusy] = useState(null); // tracks which export is in progress
  const [toast, showToast] = useToast();

  const download = async (type) => {
    if (busy) return;
    setBusy(type);
    const fileNames = {
      completed: "qre_completed_responses.csv",
      all: "qre_all_responses.csv",
      spss: "qre_responses.sav",
    };
    try {
      await qreApi.downloadExport(type, studyId, fileNames[type]);
    } catch (e) {
      showToast("Export failed: " + e.message);
    } finally {
      setBusy(null);
    }
  };

  return (
    <div className="qre-section">
      <h2 className="qre-section-title">Data Export</h2>
      <p className="qre-section-desc">
        Download survey response data. Each export fetches live data from the QRE backend.
      </p>
      {toast && <div className="qre-toast">{toast}</div>}
      <div className="qre-export-grid">
        <div className={`qre-export-card${busy === "completed" ? " qre-export-loading" : ""}`} onClick={() => download("completed")}>
          <div className="qre-export-icon">📊</div>
          <div className="qre-export-title">{busy === "completed" ? "Downloading…" : "Completed Responses (CSV)"}</div>
          <div className="qre-export-desc">
            All completed respondents with full demographic, module, and SoW data.
          </div>
        </div>
        <div className={`qre-export-card${busy === "all" ? " qre-export-loading" : ""}`} onClick={() => download("all")}>
          <div className="qre-export-icon">📋</div>
          <div className="qre-export-title">{busy === "all" ? "Downloading…" : "All Responses (CSV)"}</div>
          <div className="qre-export-desc">
            Every respondent record — including terminated and in-progress — with termination reasons.
          </div>
        </div>
        <div className={`qre-export-card${busy === "spss" ? " qre-export-loading" : ""}`} onClick={() => download("spss")}>
          <div className="qre-export-icon">🗂️</div>
          <div className="qre-export-title">{busy === "spss" ? "Downloading…" : "Completed Responses (SPSS .sav)"}</div>
          <div className="qre-export-desc">
            SPSS-compatible .sav file with variable labels for direct import into SPSS / PSPP.
          </div>
        </div>
      </div>
    </div>
  );
}

const STUDY_TABS = ["Overview", "Quotas", "Redirects", "Export"];

// ── Main QRE Page ─────────────────────────────────────────────────────────────
export default function QREPage() {
  const [view, setView] = useState("list"); // "list" | "detail"
  const [selectedStudy, setSelectedStudy] = useState(null);
  const [activeTab, setActiveTab] = useState("Overview");
  const [refreshKey, setRefreshKey] = useState(0);

  // Silent auto-login on mount
  useEffect(() => {
    const stored = sessionStorage.getItem("qre_admin_token");
    if (stored) {
      qreApi.setToken(stored);
    } else {
      qreApi.login("admin", "admin@QRE2026")
        .then((res) => {
          sessionStorage.setItem("qre_admin_token", res.token);
          qreApi.setToken(res.token);
        })
        .catch(() => {}); // errors will surface in tab components
    }
  }, []);

  const handleSelectStudy = (study) => {
    setSelectedStudy(study);
    setActiveTab("Overview");
    setView("detail");
  };

  const handleBackToList = () => {
    setView("list");
    setSelectedStudy(null);
    setRefreshKey((k) => k + 1); // re-mount StudiesTab to refresh list
  };

  // ── Detail view: study name + sub-tabs ──────────────────────────────────────
  if (view === "detail" && selectedStudy) {
    return (
      <div className="qre-root">
        {/* Header */}
        <div className="qre-page-header">
          <div>
            <button
              className="qre-btn qre-btn-outline qre-btn-sm"
              onClick={handleBackToList}
              style={{ marginBottom: "0.5rem", fontSize: "0.78rem" }}
            >
              ← All Studies
            </button>
            <div className="qre-page-title-row">
              <BarChart2 size={20} color="#667eea" />
              <h1 className="qre-page-title">{selectedStudy.name}</h1>
              <StatusBadge status={selectedStudy.status} />
            </div>
            {selectedStudy.client_name && (
              <p className="qre-page-subtitle">Client: {selectedStudy.client_name}</p>
            )}
          </div>
        </div>

        {/* Sub-tabs */}
        <div className="qre-tabs">
          {STUDY_TABS.map((t) => (
            <button
              key={t}
              className={`qre-tab-btn ${activeTab === t ? "active" : ""}`}
              onClick={() => setActiveTab(t)}
            >
              {t}
            </button>
          ))}
        </div>

        {/* Tab content */}
        {activeTab === "Overview"   && <OverviewTab   studyId={selectedStudy.id} />}
        {activeTab === "Quotas"     && <QuotasTab     studyId={selectedStudy.id} />}
        {activeTab === "Redirects" && <RedirectsTab studyId={selectedStudy.id} />}
        {activeTab === "Export"     && <ExportTab     studyId={selectedStudy.id} />}
      </div>
    );
  }

  // ── List view: all studies ───────────────────────────────────────────────────
  return (
    <div className="qre-root">
      <div className="qre-page-header">
        <div>
          <div className="qre-page-title-row">
            <BarChart2 size={20} color="#667eea" />
            <h1 className="qre-page-title">QRE Survey Platform</h1>
          </div>
          <p className="qre-page-subtitle">
            Quantitative Research Engine — manage studies, quotas, fieldwork and data exports
          </p>
        </div>
      </div>
      <StudiesTab key={refreshKey} onSelectStudy={handleSelectStudy} selectedStudyId={null} />
    </div>
  );
}
