import { useEffect, useRef, useState } from "react";
import { createProject, updateProject, listManagers, lookupRfq, OpsApiError } from "../../../services/opsProjectsService";
import { ModalShell } from "./opsShared";
import { splitFieldErrors, rfqStageLabel, rfqStageTone } from "./opsUtils";

// API field name -> form key, and the form keys that have an input here.
const FIELD_MAP = { fieldworkDatetime: "outOfFieldAt" };
const FORM_FIELDS = ["projectName", "managerId", "outOfFieldAt", "rfqId"];
const RFQ_SHOWN = 6;

// Manager is stored by username (backend looks managers up by username).
// New projects default to the admin user.
const DEFAULT_MANAGER_ID = "admin";
const DEFAULT_MANAGER_LABEL = "Admin";

const getDefaultDate = () => {
  const tomorrow = new Date();
  tomorrow.setDate(tomorrow.getDate() + 1);
  const pad = (n) => String(n).padStart(2, "0");
  // Local time (datetime-local input), not UTC: toISOString() would shift 10:00 IST to 04:30.
  return `${tomorrow.getFullYear()}-${pad(tomorrow.getMonth() + 1)}-${pad(tomorrow.getDate())}T10:00`;
};

const emptyForm = (project) => ({
  projectName: project?.projectName || "",
  managerId: project?.managerId ? String(project.managerId) : DEFAULT_MANAGER_ID,
  outOfFieldAt: project?.fieldworkDatetime ? String(project.fieldworkDatetime).slice(0, 16) : getDefaultDate(),
});

// Create or edit a project. Cancel discards the form; nothing is saved until Save.
// Create: project number is auto-allocated by backend, manager defaults to Admin,
// fieldwork date defaults to tomorrow 10:00, timezone uses backend default.
// Edit: cannot change the project number and cannot clear the manager.
export default function ProjectModal({ project, onClose, onSaved }) {
  const isEdit = Boolean(project?.id);
  const [form, setForm] = useState(() => emptyForm(project));
  const [errors, setErrors] = useState({});
  const [users, setUsers] = useState([]);
  const [usersError, setUsersError] = useState(null);
  const [saving, setSaving] = useState(false);
  const [formError, setFormError] = useState(null);
  const busy = useRef(false);
  // RFQ picker (create only): search follows the project name until the user types in it.
  const [rfq, setRfq] = useState(null);
  const [rfqQuery, setRfqQuery] = useState("");
  const [rfqTouched, setRfqTouched] = useState(false);
  const [rfqTerm, setRfqTerm] = useState("");
  const [rfqHits, setRfqHits] = useState({ items: [], loading: false, error: null });

  const rfqText = rfqTouched ? rfqQuery : form.projectName;
  useEffect(() => {
    const t = setTimeout(() => setRfqTerm(rfqText.trim()), 300);
    return () => clearTimeout(t);
  }, [rfqText]);

  useEffect(() => {
    if (isEdit || rfq || rfqTerm.length < 2) {
      setRfqHits({ items: [], loading: false, error: null });
      return undefined;
    }
    let ignore = false;
    setRfqHits((h) => ({ ...h, loading: true, error: null }));
    lookupRfq(rfqTerm)
      .then((items) => !ignore && setRfqHits({ items, loading: false, error: null }))
      .catch((e) => !ignore && setRfqHits({ items: [], loading: false, error: e.message || "RFQ search failed." }));
    return () => {
      ignore = true;
    };
  }, [rfqTerm, rfq, isEdit]);

  const pickRfq = (item) => {
    setRfq(item);
    if (errors.rfqId) setErrors((er) => ({ ...er, rfqId: undefined }));
    // An empty name takes the RFQ title, so the two match and stay easy to find.
    if (!form.projectName.trim() && item.title) setForm((f) => ({ ...f, projectName: item.title }));
  };

  useEffect(() => {
    let cancelled = false;
    listManagers()
      .then((list) => !cancelled && setUsers(list))
      .catch((e) => !cancelled && setUsersError(e.message || "Could not load managers."));
    return () => {
      cancelled = true;
    };
  }, []);

  const set = (key) => (e) => {
    const value = e?.target ? e.target.value : e;
    setForm((f) => ({ ...f, [key]: value }));
    if (errors[key]) setErrors((er) => ({ ...er, [key]: undefined }));
  };

  const validate = () => {
    const next = {};
    const name = form.projectName.trim();
    if (!name) next.projectName = "Project name is required.";
    else if (name.length > 200) next.projectName = "Project name must be 200 characters or fewer.";
    if (!form.managerId) next.managerId = "Choose a manager.";
    if (!isEdit && !form.outOfFieldAt) next.outOfFieldAt = "Fieldwork date and time is required.";
    setErrors(next);
    return Object.keys(next).length === 0;
  };

  const managerName = users.find((u) => u.username === form.managerId)?.name || project?.managerName || form.managerId;

  const submit = async (e) => {
    e.preventDefault();
    if (busy.current) return;
    setFormError(null);
    if (!validate()) return;

    // Create: backend allocates projectNumber and uses default timezone
    // Edit: optional fields are left out when empty
    const body = isEdit
      ? {
          projectName: form.projectName.trim(),
          managerId: form.managerId,
          managerName,
          ...(form.outOfFieldAt ? { fieldworkDatetime: form.outOfFieldAt } : {}),
        }
      : {
          projectName: form.projectName.trim(),
          managerId: form.managerId,
          fieldworkDatetime: form.outOfFieldAt,
          ...(rfq ? { rfqId: rfq.id } : {}),
        };

    busy.current = true;
    setSaving(true);
    try {
      const saved = isEdit ? await updateProject(project.id, body) : await createProject(body);
      onSaved(saved);
    } catch (err) {
      if (err instanceof OpsApiError && err.status === 409) {
        setErrors((er) => ({ ...er, projectNumber: "This project number is already in use." }));
      } else if (err instanceof OpsApiError && err.status === 422) {
        const { inline, other } = splitFieldErrors(err.fieldErrors, FORM_FIELDS, FIELD_MAP);
        setErrors((er) => ({ ...er, ...inline }));
        setFormError(other || (Object.keys(inline).length ? null : err.message) || "Please check the highlighted fields.");
      } else {
        setFormError(err.message || "Could not save the project.");
      }
    } finally {
      busy.current = false;
      setSaving(false);
    }
  };

  const labelFor = (username, name) =>
    username === DEFAULT_MANAGER_ID ? DEFAULT_MANAGER_LABEL : name || username;
  const managerOptions = users
    .map((u) => ({ value: u.username || "", label: labelFor(u.username, u.name) }))
    .filter((o) => o.value);
  // Admin is always selectable, even when the user list is empty.
  if (!managerOptions.some((o) => o.value === DEFAULT_MANAGER_ID)) {
    managerOptions.unshift({ value: DEFAULT_MANAGER_ID, label: DEFAULT_MANAGER_LABEL });
  }
  // Keep the current manager selectable even if they are missing from the user list.
  if (form.managerId && !managerOptions.some((o) => o.value === form.managerId)) {
    managerOptions.unshift({ value: form.managerId, label: labelFor(form.managerId, project?.managerName) });
  }

  const invalid = (key) => Boolean(errors[key]);

  return (
    <ModalShell
      title={isEdit ? "Edit project" : "New project"}
      onClose={onClose}
      footer={
        <>
          <button type="button" className="ops-btn ops-btn--ghost" onClick={onClose} disabled={saving}>
            Cancel
          </button>
          <button type="submit" form="ops-project-form" className="ops-btn ops-btn--primary" disabled={saving}>
            {saving ? "Saving…" : isEdit ? "Save changes" : "Create project"}
          </button>
        </>
      }
    >
      <form id="ops-project-form" className="ops-form" onSubmit={submit} noValidate>
        {formError && <p className="ops-form__error" role="alert">{formError}</p>}

        <div className="ops-field">
          <label htmlFor="op-name">Project name <span aria-hidden="true">*</span></label>
          <input
            id="op-name"
            className={`ops-input ${invalid("projectName") ? "ops-input--error" : ""}`}
            value={form.projectName}
            onChange={set("projectName")}
            aria-required="true"
            aria-invalid={invalid("projectName")}
            aria-describedby={invalid("projectName") ? "op-name-err" : undefined}
            autoFocus
          />
          {invalid("projectName") && <span id="op-name-err" className="ops-field__error">{errors.projectName}</span>}
        </div>


        <div className="ops-field">
          <label htmlFor="op-manager">Manager <span aria-hidden="true">*</span></label>
          <select
            id="op-manager"
            className={`ops-input ${invalid("managerId") ? "ops-input--error" : ""}`}
            value={form.managerId}
            onChange={set("managerId")}
            aria-required="true"
            aria-invalid={invalid("managerId")}
          >
            <option value="">Choose a manager</option>
            {managerOptions.map((o) => (
              <option key={o.value} value={o.value}>{o.label}</option>
            ))}
          </select>
          {invalid("managerId") && <span className="ops-field__error">{errors.managerId}</span>}
          {usersError && <span className="ops-field__hint">Could not load users: {usersError}</span>}
        </div>

        <div className="ops-field">
          <label htmlFor="op-oof">Fieldwork date and time {!isEdit && <span aria-hidden="true">*</span>}</label>
          <input
            id="op-oof"
            type="datetime-local"
            className={`ops-input ${invalid("outOfFieldAt") ? "ops-input--error" : ""}`}
            value={form.outOfFieldAt}
            onChange={set("outOfFieldAt")}
            aria-invalid={invalid("outOfFieldAt")}
          />
          {invalid("outOfFieldAt") && <span className="ops-field__error">{errors.outOfFieldAt}</span>}
        </div>

        {!isEdit && (
          <div className="ops-field">
            <label htmlFor="op-rfq">RFQ</label>
            {rfq ? (
              <div className="ops-rfq-current">
                <span className="ops-rfq-option__title">{rfq.title || rfq.id}</span>
                <span className={`ops-rfq-chip ops-rfq-chip--${rfqStageTone(rfq.stage)}`}>{rfqStageLabel(rfq.stage)}</span>
                <button type="button" className="ops-btn ops-btn--ghost ops-btn--sm" onClick={() => setRfq(null)} disabled={saving}>
                  Change
                </button>
              </div>
            ) : (
              <>
                <input
                  id="op-rfq"
                  type="search"
                  className={`ops-input ${invalid("rfqId") ? "ops-input--error" : ""}`}
                  value={rfqText}
                  onChange={(e) => {
                    setRfqTouched(true);
                    setRfqQuery(e.target.value);
                  }}
                  autoComplete="off"
                  placeholder="Search RFQs by title"
                />
                {rfqTerm.length >= 2 && rfqHits.loading && <span className="ops-field__hint" role="status">Searching…</span>}
                {rfqHits.error && <span className="ops-field__error">{rfqHits.error}</span>}
                {rfqTerm.length >= 2 && !rfqHits.loading && !rfqHits.error && rfqHits.items.length === 0 && (
                  <span className="ops-field__hint">No RFQs match “{rfqTerm}”. You can link one later.</span>
                )}
                {rfqHits.items.length > 0 && (
                  <ul className="ops-rfq-options" aria-label="Matching RFQs">
                    {rfqHits.items.slice(0, RFQ_SHOWN).map((item) => (
                      <li key={item.id}>
                        <button type="button" className="ops-rfq-option" onClick={() => pickRfq(item)} disabled={saving}>
                          <span className="ops-rfq-option__title">{item.title || item.id}</span>
                          <span className={`ops-rfq-chip ops-rfq-chip--${rfqStageTone(item.stage)}`}>{rfqStageLabel(item.stage)}</span>
                        </button>
                      </li>
                    ))}
                  </ul>
                )}
                <span className="ops-field__hint">Optional. Unlinked projects are matched to their RFQ automatically every 15 minutes.</span>
              </>
            )}
            {invalid("rfqId") && <span className="ops-field__error">{errors.rfqId}</span>}
          </div>
        )}
      </form>
    </ModalShell>
  );
}
