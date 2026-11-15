import { useEffect, useRef, useState } from "react";
import { createProject, updateProject, listUsers, OpsApiError } from "../../../services/opsProjectsService";
import { ModalShell, TimezoneSelect } from "./opsShared";

const emptyForm = (project) => ({
  projectName: project?.projectName || "",
  projectNumber: project?.projectNumber || "",
  managerId: project?.managerId ? String(project.managerId) : "",
  outOfFieldAt: project?.fieldworkDatetime ? String(project.fieldworkDatetime).slice(0, 16) : "",
  timezone: project?.timezone || "",
});

// Create or edit a project. Cancel discards the form; nothing is saved until Save.
export default function ProjectModal({ project, onClose, onSaved }) {
  const isEdit = Boolean(project?.id);
  const [form, setForm] = useState(() => emptyForm(project));
  const [errors, setErrors] = useState({});
  const [users, setUsers] = useState([]);
  const [usersError, setUsersError] = useState(null);
  const [saving, setSaving] = useState(false);
  const [formError, setFormError] = useState(null);
  const busy = useRef(false);

  useEffect(() => {
    let cancelled = false;
    listUsers()
      .then((list) => !cancelled && setUsers(list))
      .catch((e) => !cancelled && setUsersError(e.message || "Could not load users."));
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
    if (!form.projectName.trim()) next.projectName = "Project name is required.";
    if (!form.projectNumber.trim()) next.projectNumber = "Project number is required.";
    setErrors(next);
    return Object.keys(next).length === 0;
  };

  const submit = async (e) => {
    e.preventDefault();
    if (busy.current) return;
    setFormError(null);
    if (!validate()) return;

    const body = {
      projectName: form.projectName.trim(),
      projectNumber: form.projectNumber.trim(),
      managerId: form.managerId || null,
      fieldworkDatetime: form.outOfFieldAt || null,
      timezone: form.timezone || null,
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
        setFormError(err.message || "Please check the highlighted fields.");
      } else {
        setFormError(err.message || "Could not save the project.");
      }
    } finally {
      busy.current = false;
      setSaving(false);
    }
  };

  const managerOptions = users.map((u) => ({
    value: String(u.id),
    label: u.name || u.username || u.email || `User ${u.id}`,
  }));
  // Keep the current manager selectable even if they are missing from the user list.
  if (form.managerId && !managerOptions.some((o) => o.value === form.managerId)) {
    managerOptions.unshift({ value: form.managerId, label: project?.managerName || `User ${form.managerId}` });
  }

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
            className={`ops-input ${errors.projectName ? "ops-input--error" : ""}`}
            value={form.projectName}
            onChange={set("projectName")}
            required
            aria-required="true"
            aria-invalid={Boolean(errors.projectName)}
            aria-describedby={errors.projectName ? "op-name-err" : undefined}
            autoFocus
          />
          {errors.projectName && <span id="op-name-err" className="ops-field__error">{errors.projectName}</span>}
        </div>

        <div className="ops-field">
          <label htmlFor="op-number">Project number <span aria-hidden="true">*</span></label>
          <input
            id="op-number"
            className={`ops-input ${errors.projectNumber ? "ops-input--error" : ""}`}
            value={form.projectNumber}
            onChange={set("projectNumber")}
            required
            aria-required="true"
            aria-invalid={Boolean(errors.projectNumber)}
            aria-describedby={errors.projectNumber ? "op-number-err" : undefined}
          />
          {errors.projectNumber && <span id="op-number-err" className="ops-field__error">{errors.projectNumber}</span>}
        </div>

        <div className="ops-field">
          <label htmlFor="op-manager">Manager</label>
          <select id="op-manager" className="ops-input" value={form.managerId} onChange={set("managerId")}>
            <option value="">Unassigned</option>
            {managerOptions.map((o) => (
              <option key={o.value} value={o.value}>{o.label}</option>
            ))}
          </select>
          {usersError && <span className="ops-field__hint">Could not load users: {usersError}</span>}
        </div>

        <div className="ops-field-row">
          <div className="ops-field">
            <label htmlFor="op-oof">Out-of-field date and time</label>
            <input id="op-oof" type="datetime-local" className="ops-input" value={form.outOfFieldAt} onChange={set("outOfFieldAt")} />
          </div>
          <div className="ops-field">
            <label htmlFor="op-tz">Timezone</label>
            <TimezoneSelect id="op-tz" value={form.timezone} onChange={set("timezone")} />
          </div>
        </div>
      </form>
    </ModalShell>
  );
}
