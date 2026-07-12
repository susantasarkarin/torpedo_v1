/**
 * Account 360 — master/detail over the CRM spine.
 * Left: searchable account list. Right: editable account fields, linked
 * contacts (with AI email draft), open opportunities, tasks, note/call
 * logging, and the full activity timeline.
 */
import { useEffect, useState, useCallback } from "react";
import {
  Building2, Search, Mail, Phone, FileText, CheckSquare, Clock, Save,
  Plus, Target, Users, Sparkles,
} from "lucide-react";
import api from "../../utils/api";
import CrmNav, { Modal, Field, inputStyle } from "./CrmNav";
import "../../styles/crm-ui.css";

const ACTIVITY_ICONS = {
  email_sent: Mail, email_reply_positive: Mail, email_reply_negative: Mail,
  email_reply_neutral: Mail, call: Phone, meeting: Users, note: FileText,
  rfq_created: FileText, opportunity_won: Target, stage_changed: Target,
  record_updated: FileText,
};

function ActivityRow({ act }) {
  const Icon = ACTIVITY_ICONS[act.type] || FileText;
  return (
    <li className="crm-tl-item">
      <span className="crm-tl-dot"><Icon size={14} /></span>
      <div style={{ minWidth: 0, flex: 1 }}>
        <div style={{ display: "flex", alignItems: "center", gap: "0.5rem", flexWrap: "wrap" }}>
          <span className="crm-mono">{act.type}</span>
          <span style={{ fontWeight: 600, color: "#111827" }}>{act.subject || "—"}</span>
        </div>
        {act.description && <p className="crm-muted" style={{ margin: "0.15rem 0 0" }}>{act.description}</p>}
        {act.changes && (
          <p className="crm-muted" style={{ margin: "0.15rem 0 0", fontSize: "0.72rem" }}>
            {Object.entries(act.changes).map(([f, c]) => `${f}: ${c.from ?? "—"} → ${c.to}`).join("; ")}
          </p>
        )}
        <span className="crm-muted" style={{ fontSize: "0.72rem", display: "inline-flex", alignItems: "center", gap: "0.25rem" }}>
          <Clock size={12} /> {act.created_at ? new Date(act.created_at).toLocaleString() : ""}
          {act.author ? ` · ${act.author}` : ""}
        </span>
      </div>
    </li>
  );
}

const EDIT_FIELDS = [
  ["name", "Name"], ["account_type", "Type"], ["status", "Status"],
  ["owner", "Owner"], ["email", "Email"], ["phone", "Phone"], ["website", "Website"],
];

export default function AccountTimeline() {
  const [accounts, setAccounts] = useState([]);
  const [search, setSearch] = useState("");
  const [selected, setSelected] = useState(null);
  const [detail, setDetail] = useState({ timeline: null, contacts: [], opportunities: [] });
  const [edit, setEdit] = useState({});
  const [dirty, setDirty] = useState(false);
  const [loadingAccounts, setLoadingAccounts] = useState(true);
  const [loadingDetail, setLoadingDetail] = useState(false);
  const [error, setError] = useState(null);
  const [notice, setNotice] = useState(null);
  const [logForm, setLogForm] = useState(null);       // {type} modal
  const [taskForm, setTaskForm] = useState(null);     // task modal
  const [draftFor, setDraftFor] = useState(null);     // contact for AI draft
  const [draftContext, setDraftContext] = useState("");
  const [draftResult, setDraftResult] = useState(null);
  const [busy, setBusy] = useState(false);

  const loadAccounts = useCallback(async () => {
    setLoadingAccounts(true);
    try {
      const data = await api.get("/api/crm/accounts", { limit: 1000 }, { cacheTTL: 0 });
      const list = Array.isArray(data) ? data : [];
      setAccounts(list);
      if (list.length && !selected) setSelected(list[0]);
    } catch (e) {
      setError(e.message || "Failed to load accounts");
    } finally {
      setLoadingAccounts(false);
    }
  }, [selected]);

  useEffect(() => { loadAccounts(); }, []); // eslint-disable-line react-hooks/exhaustive-deps

  const loadDetail = useCallback(async (accountId) => {
    setLoadingDetail(true);
    setError(null);
    try {
      const [timeline, contacts, opportunities] = await Promise.all([
        api.get(`/api/crm/timeline/account/${accountId}`, {}, { cacheTTL: 0 }),
        api.get("/api/crm/contacts", { account_id: accountId, limit: 200 }, { cacheTTL: 0 }),
        api.get("/api/crm/opportunities", { account_id: accountId, limit: 200 }, { cacheTTL: 0 }),
      ]);
      setDetail({
        timeline,
        contacts: Array.isArray(contacts) ? contacts : [],
        opportunities: Array.isArray(opportunities) ? opportunities : [],
      });
    } catch (e) {
      setError(e.message || "Failed to load account detail");
    } finally {
      setLoadingDetail(false);
    }
  }, []);

  useEffect(() => {
    if (selected?._id) {
      setEdit(Object.fromEntries(EDIT_FIELDS.map(([f]) => [f, selected[f] || ""])));
      setDirty(false);
      loadDetail(selected._id);
    }
  }, [selected, loadDetail]);

  const saveAccount = async () => {
    setBusy(true);
    setError(null);
    try {
      const updated = await api.put(`/api/crm/accounts/${selected._id}`, edit);
      setSelected(updated);
      setAccounts((prev) => prev.map((a) => (a._id === updated._id ? updated : a)));
      setDirty(false);
      setNotice("Saved");
      setTimeout(() => setNotice(null), 2000);
    } catch (e) { setError(e.message || "Save failed"); }
    finally { setBusy(false); }
  };

  const submitLog = async () => {
    setBusy(true);
    try {
      await api.post("/api/crm/activities", {
        type: logForm.type,
        subject: logForm.subject,
        description: logForm.description || null,
        account_id: selected._id,
      });
      setLogForm(null);
      await loadDetail(selected._id);
    } catch (e) { setError(e.message || "Log failed"); }
    finally { setBusy(false); }
  };

  const submitTask = async () => {
    setBusy(true);
    try {
      await api.post("/api/crm/tasks", {
        title: taskForm.title,
        owner_id: taskForm.owner_id || null,
        due_date: taskForm.due_date || null,
        linked_object_type: "account",
        linked_object_id: selected._id,
      });
      setTaskForm(null);
      await loadDetail(selected._id);
    } catch (e) { setError(e.message || "Task creation failed"); }
    finally { setBusy(false); }
  };

  const toggleTask = async (t) => {
    try {
      await api.put(`/api/crm/tasks/${t._id}`, { status: t.status === "done" ? "pending" : "done" });
      await loadDetail(selected._id);
    } catch (e) { setError(e.message || "Task update failed"); }
  };

  const requestDraft = async () => {
    setBusy(true);
    setDraftResult(null);
    try {
      const res = await api.post(`/api/crm/contacts/${draftFor._id}/draft-email`,
        { context: draftContext });
      setDraftResult(res);
    } catch (e) { setError(e.message || "Draft failed"); }
    finally { setBusy(false); }
  };

  const filtered = accounts.filter((a) => (a.name || "").toLowerCase().includes(search.toLowerCase()));

  return (
    <div className="crm-page">
      <CrmNav />
      <div className="crm-head">
        <div>
          <h1 className="crm-title">Accounts</h1>
          <p className="crm-subtitle">360° view: profile, contacts, deals, tasks, and the full timeline.</p>
        </div>
      </div>

      {error && <div className="crm-error">{error}</div>}

      <div className="crm-md">
        <div className="crm-panel">
          <div className="crm-search">
            <Search size={16} className="crm-icon" />
            <input value={search} onChange={(e) => setSearch(e.target.value)} placeholder="Search accounts…" />
          </div>
          <div className="crm-list">
            {loadingAccounts ? (
              <p className="crm-muted" style={{ padding: "1rem" }}>Loading…</p>
            ) : filtered.length === 0 ? (
              <p className="crm-muted" style={{ padding: "1rem" }}>No accounts.</p>
            ) : (
              filtered.map((a) => (
                <button key={a._id} onClick={() => setSelected(a)}
                  className={`crm-list__item ${selected?._id === a._id ? "active" : ""}`}>
                  <Building2 size={16} className="crm-icon" />
                  <span style={{ overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}>{a.name || "(unnamed)"}</span>
                </button>
              ))
            )}
          </div>
        </div>

        <div className="crm-panel" style={{ padding: "1rem" }}>
          {!selected ? (
            <p className="crm-muted" style={{ textAlign: "center", padding: "3rem" }}>Select an account.</p>
          ) : (
            <>
              {/* ---- editable profile ---- */}
              <div style={{ borderBottom: "1px solid #f3f4f6", paddingBottom: "0.9rem", marginBottom: "1rem" }}>
                <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", gap: "0.5rem", flexWrap: "wrap" }}>
                  <h2 style={{ margin: 0, fontSize: "1.1rem", fontWeight: 600, color: "#111827" }}>{selected.name}</h2>
                  <div style={{ display: "flex", gap: "0.4rem", alignItems: "center" }}>
                    {notice && <span style={{ color: "#059669", fontSize: "0.78rem" }}>{notice}</span>}
                    <button className="crm-btn crm-btn--primary" disabled={!dirty || busy} onClick={saveAccount}>
                      <Save size={14} /> Save
                    </button>
                  </div>
                </div>
                <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fill, minmax(170px, 1fr))", gap: "0.5rem", marginTop: "0.7rem" }}>
                  {EDIT_FIELDS.map(([f, label]) => (
                    <label key={f} style={{ fontSize: "0.72rem", color: "#6b7280", fontWeight: 600 }}>
                      {label}
                      <input style={{ ...inputStyle, marginTop: "0.15rem", fontSize: "0.8rem" }}
                        value={edit[f] || ""}
                        onChange={(e) => { setEdit({ ...edit, [f]: e.target.value }); setDirty(true); }} />
                    </label>
                  ))}
                </div>
              </div>

              {loadingDetail ? <p className="crm-muted">Loading…</p> : (
                <>
                  {/* ---- contacts ---- */}
                  <h3 className="crm-section-title"><Users size={16} className="crm-icon" /> Contacts ({detail.contacts.length})</h3>
                  {detail.contacts.length === 0 ? (
                    <p className="crm-muted" style={{ fontSize: "0.8rem" }}>No linked contacts.</p>
                  ) : detail.contacts.map((c) => (
                    <div key={c._id} className="crm-row" style={{ border: "1px solid #f3f4f6", borderRadius: "0.4rem", marginBottom: "0.35rem" }}>
                      <div style={{ flex: 1, minWidth: 0 }}>
                        <span style={{ fontWeight: 600 }}>{c.name || c.email}</span>
                        <span className="crm-muted" style={{ fontSize: "0.75rem", marginLeft: "0.4rem" }}>
                          {c.email}{c.title ? ` · ${c.title}` : ""}
                        </span>
                      </div>
                      <button className="crm-btn" style={{ padding: "0.25rem 0.5rem", fontSize: "0.72rem" }}
                        title="AI-draft an email to this contact"
                        onClick={() => { setDraftFor(c); setDraftContext(""); setDraftResult(null); }}>
                        <Sparkles size={13} /> Draft email
                      </button>
                    </div>
                  ))}

                  {/* ---- opportunities ---- */}
                  <h3 className="crm-section-title" style={{ marginTop: "1.1rem" }}>
                    <Target size={16} className="crm-icon" /> Opportunities ({detail.opportunities.length})
                  </h3>
                  {detail.opportunities.length === 0 ? (
                    <p className="crm-muted" style={{ fontSize: "0.8rem" }}>No opportunities for this account.</p>
                  ) : detail.opportunities.map((o) => (
                    <div key={o._id} className="crm-row" style={{ border: "1px solid #f3f4f6", borderRadius: "0.4rem", marginBottom: "0.35rem" }}>
                      <span style={{ flex: 1 }}>{o.title}</span>
                      <span className="crm-mono">{o.stage}</span>
                      <span style={{ fontWeight: 600 }}>
                        {typeof o.amount === "number" ? `$${o.amount.toLocaleString()}` : "—"}
                      </span>
                    </div>
                  ))}

                  {/* ---- tasks ---- */}
                  <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between", marginTop: "1.1rem" }}>
                    <h3 className="crm-section-title" style={{ margin: 0 }}>
                      <CheckSquare size={16} className="crm-icon" /> Tasks ({detail.timeline?.tasks?.length || 0})
                    </h3>
                    <div style={{ display: "flex", gap: "0.35rem" }}>
                      <button className="crm-btn" style={{ padding: "0.25rem 0.5rem", fontSize: "0.72rem" }}
                        onClick={() => setTaskForm({ title: "" })}><Plus size={13} /> Task</button>
                      <button className="crm-btn" style={{ padding: "0.25rem 0.5rem", fontSize: "0.72rem" }}
                        onClick={() => setLogForm({ type: "note", subject: "" })}><FileText size={13} /> Note</button>
                      <button className="crm-btn" style={{ padding: "0.25rem 0.5rem", fontSize: "0.72rem" }}
                        onClick={() => setLogForm({ type: "call", subject: "" })}><Phone size={13} /> Log call</button>
                      <button className="crm-btn" style={{ padding: "0.25rem 0.5rem", fontSize: "0.72rem" }}
                        onClick={() => setLogForm({ type: "meeting", subject: "" })}><Users size={13} /> Meeting</button>
                    </div>
                  </div>
                  {(detail.timeline?.tasks || []).map((t) => {
                    const overdue = t.status !== "done" && t.due_date && new Date(t.due_date) < new Date();
                    return (
                      <div key={t._id} className="crm-row" style={{ border: "1px solid #f3f4f6", borderRadius: "0.4rem", marginBottom: "0.35rem" }}>
                        <input type="checkbox" checked={t.status === "done"} onChange={() => toggleTask(t)} />
                        <span style={{ flex: 1, textDecoration: t.status === "done" ? "line-through" : "none" }}>{t.title}</span>
                        {t.owner_id && <span className="crm-muted" style={{ fontSize: "0.72rem" }}>{t.owner_id}</span>}
                        {t.due_date && (
                          <span style={{ fontSize: "0.72rem", color: overdue ? "#b91c1c" : "#6b7280", fontWeight: overdue ? 700 : 400 }}>
                            {new Date(t.due_date).toLocaleDateString()}
                          </span>
                        )}
                      </div>
                    );
                  })}

                  {/* ---- timeline ---- */}
                  <h3 className="crm-section-title" style={{ marginTop: "1.1rem" }}>
                    <Clock size={16} className="crm-icon" /> Activity
                  </h3>
                  {detail.timeline?.activities?.length > 0 ? (
                    <ul className="crm-timeline">
                      {detail.timeline.activities.map((act) => <ActivityRow key={act._id} act={act} />)}
                    </ul>
                  ) : (
                    <p className="crm-muted">No activity linked to this account yet.</p>
                  )}
                </>
              )}
            </>
          )}
        </div>
      </div>

      {logForm && (
        <Modal title={logForm.type === "note" ? "Add note" : `Log ${logForm.type}`} onClose={() => setLogForm(null)}>
          <Field label="Subject">
            <input style={inputStyle} value={logForm.subject || ""} autoFocus
              onChange={(e) => setLogForm({ ...logForm, subject: e.target.value })} />
          </Field>
          <Field label="Details">
            <textarea style={{ ...inputStyle, minHeight: 90 }} value={logForm.description || ""}
              onChange={(e) => setLogForm({ ...logForm, description: e.target.value })} />
          </Field>
          <div style={{ display: "flex", justifyContent: "flex-end", gap: "0.5rem" }}>
            <button className="crm-btn" onClick={() => setLogForm(null)}>Cancel</button>
            <button className="crm-btn crm-btn--primary" disabled={busy || !logForm.subject}
              onClick={submitLog}>Save</button>
          </div>
        </Modal>
      )}

      {taskForm && (
        <Modal title="New task" onClose={() => setTaskForm(null)}>
          <Field label="Title">
            <input style={inputStyle} value={taskForm.title || ""} autoFocus
              onChange={(e) => setTaskForm({ ...taskForm, title: e.target.value })} />
          </Field>
          <Field label="Assignee">
            <input style={inputStyle} value={taskForm.owner_id || ""} placeholder="username or email"
              onChange={(e) => setTaskForm({ ...taskForm, owner_id: e.target.value })} />
          </Field>
          <Field label="Due date">
            <input type="date" style={inputStyle} value={taskForm.due_date || ""}
              onChange={(e) => setTaskForm({ ...taskForm, due_date: e.target.value })} />
          </Field>
          <div style={{ display: "flex", justifyContent: "flex-end", gap: "0.5rem" }}>
            <button className="crm-btn" onClick={() => setTaskForm(null)}>Cancel</button>
            <button className="crm-btn crm-btn--primary" disabled={busy || !taskForm.title}
              onClick={submitTask}>Create</button>
          </div>
        </Modal>
      )}

      {draftFor && (
        <Modal title={`AI email draft → ${draftFor.email}`} width={540} onClose={() => setDraftFor(null)}>
          {!draftResult ? (
            <>
              <Field label="What should the email be about?">
                <textarea style={{ ...inputStyle, minHeight: 70 }} value={draftContext} autoFocus
                  placeholder="e.g. follow up on the CX study proposal we sent last week"
                  onChange={(e) => setDraftContext(e.target.value)} />
              </Field>
              <div style={{ display: "flex", justifyContent: "flex-end", gap: "0.5rem" }}>
                <button className="crm-btn" onClick={() => setDraftFor(null)}>Cancel</button>
                <button className="crm-btn crm-btn--primary" disabled={busy}
                  onClick={requestDraft}>{busy ? "Drafting…" : "Generate draft"}</button>
              </div>
            </>
          ) : (
            <>
              <p style={{ fontWeight: 600, marginTop: 0 }}>{draftResult.subject}</p>
              <pre style={{ whiteSpace: "pre-wrap", fontSize: "0.83rem", background: "#f9fafb", padding: "0.7rem", borderRadius: "0.4rem" }}>
                {draftResult.body}
              </pre>
              <p className="crm-muted" style={{ fontSize: "0.75rem" }}>
                Saved to the follow-up drafts queue (Mail → follow-up drafts) for review — nothing was sent.
              </p>
              <div style={{ display: "flex", justifyContent: "flex-end" }}>
                <button className="crm-btn crm-btn--primary" onClick={() => setDraftFor(null)}>Done</button>
              </div>
            </>
          )}
        </Modal>
      )}
    </div>
  );
}
