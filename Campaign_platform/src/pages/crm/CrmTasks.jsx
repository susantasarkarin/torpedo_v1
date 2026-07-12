/**
 * CRM Tasks — assignable to-dos with due dates, overdue highlighting and an
 * owner filter ("my tasks"). Backed by the spine `tasks` collection.
 */
import { useEffect, useState, useCallback } from "react";
import { RefreshCw, Plus, CheckSquare } from "lucide-react";
import api from "../../utils/api";
import CrmNav, { Modal, Field, inputStyle } from "./CrmNav";
import "../../styles/crm-ui.css";

export default function CrmTasks() {
  const [tasks, setTasks] = useState([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(null);
  const [owner, setOwner] = useState(localStorage.getItem("crm_task_owner") || "");
  const [showDone, setShowDone] = useState(false);
  const [form, setForm] = useState(null);
  const [busy, setBusy] = useState(false);

  const load = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const params = { limit: 500 };
      if (owner) params.owner = owner;
      const data = await api.get("/api/crm/tasks", params, { cacheTTL: 0 });
      setTasks(Array.isArray(data) ? data : []);
    } catch (e) {
      setError(e.message || "Failed to load tasks");
    } finally {
      setLoading(false);
    }
  }, [owner]);

  useEffect(() => { load(); }, [load]);
  useEffect(() => { localStorage.setItem("crm_task_owner", owner); }, [owner]);

  const toggle = async (t) => {
    try {
      await api.put(`/api/crm/tasks/${t._id}`, { status: t.status === "done" ? "pending" : "done" });
      await load();
    } catch (e) { setError(e.message || "Update failed"); }
  };

  const createTask = async () => {
    setBusy(true);
    try {
      await api.post("/api/crm/tasks", {
        title: form.title,
        owner_id: form.owner_id || owner || null,
        due_date: form.due_date || null,
        priority: parseInt(form.priority, 10) || 3,
      });
      setForm(null);
      await load();
    } catch (e) { setError(e.message || "Creation failed"); }
    finally { setBusy(false); }
  };

  const visible = tasks
    .filter((t) => showDone || t.status !== "done")
    .sort((a, b) => (a.due_date || "9999") < (b.due_date || "9999") ? -1 : 1);
  const now = new Date();

  return (
    <div className="crm-page">
      <CrmNav />
      <div className="crm-head">
        <div>
          <h1 className="crm-title">Tasks</h1>
          <p className="crm-subtitle">Assignable to-dos across the CRM. Overdue items are highlighted.</p>
        </div>
        <div style={{ display: "flex", gap: "0.5rem" }}>
          <button className="crm-btn" onClick={load}><RefreshCw size={15} /> Refresh</button>
          <button className="crm-btn crm-btn--primary" onClick={() => setForm({})}>
            <Plus size={15} /> New Task
          </button>
        </div>
      </div>

      {error && <div className="crm-error">{error}</div>}

      <div style={{ display: "flex", gap: "0.5rem", marginBottom: "0.75rem", alignItems: "center" }}>
        <input style={{ ...inputStyle, maxWidth: 240 }} placeholder="Filter by assignee (my tasks)…"
          value={owner} onChange={(e) => setOwner(e.target.value)} />
        <label style={{ fontSize: "0.8rem", color: "#6b7280", display: "flex", alignItems: "center", gap: "0.3rem" }}>
          <input type="checkbox" checked={showDone} onChange={(e) => setShowDone(e.target.checked)} />
          show completed
        </label>
      </div>

      <div className="crm-panel">
        {loading ? <p className="crm-muted" style={{ padding: "1rem" }}>Loading…</p> :
          visible.length === 0 ? (
            <p className="crm-muted" style={{ padding: "1rem" }}>
              <CheckSquare size={15} style={{ verticalAlign: "-2px" }} /> Nothing here — enjoy the silence.
            </p>
          ) : visible.map((t) => {
            const overdue = t.status !== "done" && t.due_date && new Date(t.due_date) < now;
            return (
              <div key={t._id} className="crm-row"
                style={overdue ? { background: "#fef2f2" } : undefined}>
                <input type="checkbox" checked={t.status === "done"} onChange={() => toggle(t)} />
                <div style={{ flex: 1, minWidth: 0 }}>
                  <span style={{ fontWeight: 600, textDecoration: t.status === "done" ? "line-through" : "none" }}>
                    {t.title}
                  </span>
                  {t.linked_object_type && (
                    <span className="crm-muted" style={{ fontSize: "0.72rem", marginLeft: "0.4rem" }}>
                      on {t.linked_object_type}
                    </span>
                  )}
                </div>
                {t.owner_id && <span className="crm-badge">{t.owner_id}</span>}
                {t.due_date && (
                  <span style={{ fontSize: "0.75rem", fontWeight: overdue ? 700 : 400, color: overdue ? "#b91c1c" : "#6b7280" }}>
                    {new Date(t.due_date).toLocaleDateString()}{overdue ? " · overdue" : ""}
                  </span>
                )}
              </div>
            );
          })}
      </div>

      {form && (
        <Modal title="New task" onClose={() => setForm(null)}>
          <Field label="Title">
            <input style={inputStyle} value={form.title || ""} autoFocus
              onChange={(e) => setForm({ ...form, title: e.target.value })} />
          </Field>
          <Field label="Assignee">
            <input style={inputStyle} value={form.owner_id ?? owner} placeholder="username or email"
              onChange={(e) => setForm({ ...form, owner_id: e.target.value })} />
          </Field>
          <Field label="Due date">
            <input type="date" style={inputStyle} value={form.due_date || ""}
              onChange={(e) => setForm({ ...form, due_date: e.target.value })} />
          </Field>
          <Field label="Priority (1 high – 5 low)">
            <input type="number" min="1" max="5" style={inputStyle} value={form.priority || 3}
              onChange={(e) => setForm({ ...form, priority: e.target.value })} />
          </Field>
          <div style={{ display: "flex", justifyContent: "flex-end", gap: "0.5rem" }}>
            <button className="crm-btn" onClick={() => setForm(null)}>Cancel</button>
            <button className="crm-btn crm-btn--primary" disabled={busy || !form.title}
              onClick={createTask}>Create</button>
          </div>
        </Modal>
      )}
    </div>
  );
}
