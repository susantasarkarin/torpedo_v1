import { useEffect, useRef, useState } from "react";
import { createProject, updateProject, listManagers, OpsApiError } from "../../../services/opsProjectsService";
import { ModalShell, TimezoneSelect } from "./opsShared";
import { splitFieldErrors } from "./opsUtils";

// API field name -> form key, and the form keys that have an input here.
const FIELD_MAP = { fieldworkDatetime: "outOfFieldAt" };
const FORM_FIELDS = ["projectName", "projectNumber", "managerId", "outOfFieldAt", "timezone"];

// Manager is stored by username (backend looks managers up by username).
const emptyForm = (project) => ({
  projectName: project?.projectName || "",
  projectNumber: project?.projectNumber || "",
  managerId: project?.managerId ? String(project.managerId) : "",
  outOfFieldAt: project?.fieldworkDatetime ? String(project.fieldworkDatetime).slice(0, 16) : "",
  timezone: project?.timezone || "",
});

// Create or edit a project. Cancel discards the form; nothing is saved until Save.
// Create needs manager, fieldwork date and timezone (backend requires them). Edit
// cannot change the project number (backend ignores it) and cannot clear the manager.
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
    const number = form.projectNumber.trim();
    if (!name) next.projectName = "Project name is required.";
    else if (name.length > 200) next.projectName = "Project name must be 200 characters or fewer.";
    if (!isEdit) {
      if (!number) next.projectNumber = "Project number is required.";
      else if (number.length > 32) next.projectNumber = "Project number must be 32 characters or fewer.";
    }
    if (!form.managerId) next.managerId = "Choose a manager.";
    if (!isEdit && !form.outOfFieldAt) next.outOfFieldAt = "Fieldwork date and time is required.";
    if (!isEdit && !form.timezone) next.timezone = "Timezone is required.";
    setErrors(next);
    return Object.keys(next).length === 0;
  };

  const managerName = users.find((u) => u.username === form.managerId)?.name || project?.managerName || form.managerId;

  const submit = async (e) => {
    e.preventDefault();
    if (busy.current) return;
    setFormError(null);
    if (!validate()) return;

    // Optional fields are left out when empty: the backend treats null as invalid on update.
    const body = isEdit
      ? {
          projectName: form.projectName.trim(),
          managerId: form.managerId,
          managerName,
          ...(form.outOfFieldAt ? { fieldworkDatetime: form.outOfFieldAt } : {}),
          ...(form.timezone ? { timezone: form.timezone } : {}),
        }
      : {
          projectName: form.projectName.trim(),
          projectNumber: form.projectNumber.trim(),
          managerId: form.managerId,
          fieldworkDatetime: form.outOfFieldAt,
          timezone: form.timezone,
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

  const managerOptions = users
    .map((u) => ({ value: u.username || "", label: u.name || u.username || "" }))
    .filter((o) => o.value);
  // Keep the current manager selectable even if they are missing from the user list.
  if (form.managerId && !managerOptions.some((o) => o.value === form.managerId)) {
    managerOptions.unshift({ value: form.managerId, label: project?.managerName || form.managerId });
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
          <label htmlFor="op-number">Project number {!isEdit && <span aria-hidden="true">*</span>}</label>
          <input
            id="op-number"
            className={`ops-input ${invalid("projectNumber") ? "ops-input--error" : ""}`}
            value={form.projectNumber}
            onChange={set("projectNumber")}
            readOnly={isEdit}
            aria-required={!isEdit}
            aria-invalid={invalid("projectNumber")}
            aria-describedby={invalid("projectNumber") ? "op-number-err" : isEdit ? "op-number-hint" : undefined}
          />
          {isEdit && <span id="op-number-hint" className="ops-field__hint">The project number cannot be changed.</span>}
          {invalid("projectNumber") && <span id="op-number-err" className="ops-field__error">{errors.projectNumber}</span>}
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

        <div className="ops-field-row">
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
          <div className="ops-field">
            <label htmlFor="op-tz">Timezone {!isEdit && <span aria-hidden="true">*</span>}</label>
            <TimezoneSelect id="op-tz" value={form.timezone} onChange={set("timezone")} error={errors.timezone} />
            {invalid("timezone") && <span className="ops-field__error">{errors.timezone}</span>}
          </div>
        </div>
      </form>
    </ModalShell>
  );
}
