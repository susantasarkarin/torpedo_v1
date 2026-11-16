import { useRef, useState } from "react";
import { createSurvey, updateSurvey, OpsApiError } from "../../../services/opsProjectsService";
import { ModalShell, TimezoneSelect } from "./opsShared";

const DEVICE_OPTIONS = [
  { value: "desktop", label: "Desktop" },
  { value: "mobile", label: "Mobile" },
  { value: "tablet", label: "Tablet" },
];

const emptyForm = (survey) => ({
  surveyName: survey?.surveyName || "",
  surveyUrl: survey?.surveyUrl || "",
  target: survey?.targetN ?? "",
  loi: survey?.loi ?? "",
  ir: survey?.ir ?? "",
  outOfFieldAt: survey?.outOfFieldAt ? String(survey.outOfFieldAt).slice(0, 16) : "",
  timezone: survey?.timezone || "",
  country: survey?.countryCode || "",
  language: survey?.languageCode || "",
  devices: survey?.devices && typeof survey.devices === "object" ? Object.keys(survey.devices).filter((k) => survey.devices[k]) : [],
  pii: Boolean(survey?.piiEnabled),
});

const isHttpUrl = (value) => {
  try {
    const u = new URL(value);
    return u.protocol === "http:" || u.protocol === "https:";
  } catch {
    return false;
  }
};

// Create (projectId given, no survey) or edit (survey given). Also used after duplicate.
export default function SurveyModal({ projectId, survey, onClose, onSaved }) {
  const isEdit = Boolean(survey?.id);
  const [form, setForm] = useState(() => emptyForm(survey));
  const [errors, setErrors] = useState({});
  const [saving, setSaving] = useState(false);
  const [formError, setFormError] = useState(null);
  const busy = useRef(false);

  const set = (key) => (e) => {
    const value = e?.target ? e.target.value : e;
    setForm((f) => ({ ...f, [key]: value }));
    if (errors[key]) setErrors((er) => ({ ...er, [key]: undefined }));
  };

  const toggleDevice = (value) => (e) => {
    const checked = e.target.checked;
    setForm((f) => ({
      ...f,
      devices: checked ? [...f.devices, value] : f.devices.filter((d) => d !== value),
    }));
  };

  // Mirrors the backend. On create every field below is required; on edit
  // (partial update) a field is only checked when it has a value.
  const validate = () => {
    const next = {};
    const required = !isEdit;
    const url = form.surveyUrl.trim();
    if (!form.surveyName.trim()) next.surveyName = "Survey name is required.";
    if (!url && required) next.surveyUrl = "Survey URL is required.";
    else if (url && !isHttpUrl(url)) next.surveyUrl = "Enter a full http:// or https:// URL.";
    const target = Number(form.target);
    if (form.target === "" || !Number.isInteger(target) || target <= 0) {
      next.target = "Target must be a whole number greater than 0.";
    }
    if (form.loi === "") {
      if (required) next.loi = "LOI is required.";
    } else if (Number.isNaN(Number(form.loi)) || Number(form.loi) <= 0) {
      next.loi = "LOI must be more than 0 minutes.";
    }
    if (form.ir === "") {
      if (required) next.ir = "IR is required.";
    } else {
      const ir = Number(form.ir);
      if (Number.isNaN(ir) || ir < 0 || ir > 100) next.ir = "IR must be between 0 and 100.";
    }
    const country = form.country.trim();
    if (!country && required) next.country = "Country is required.";
    else if (country && !/^[A-Za-z]{2}$/.test(country)) next.country = "Country must be a 2-letter code, for example IN.";
    const language = form.language.trim();
    if (!language && required) next.language = "Language is required.";
    else if (language && !/^[A-Za-z]{2}(-[A-Za-z0-9]{2,8})?$/.test(language)) {
      next.language = "Language must look like en or en-IN.";
    }
    setErrors(next);
    return Object.keys(next).length === 0;
  };

  const submit = async (e) => {
    e.preventDefault();
    if (busy.current) return;
    setFormError(null);
    if (!validate()) return;

    // Empty optional values are sent as null; the backend skips nulls on update.
    const body = {
      surveyName: form.surveyName.trim(),
      surveyUrl: form.surveyUrl.trim() || null,
      targetN: Number(form.target),
      loi: form.loi === "" ? null : Number(form.loi),
      ir: form.ir === "" ? null : Number(form.ir),
      outOfFieldAt: form.outOfFieldAt || null,
      timezone: form.timezone || null,
      countryCode: form.country.trim().toUpperCase() || null,
      languageCode: form.language.trim() || null,
      devices: { desktop: form.devices.includes("desktop"), mobile: form.devices.includes("mobile"), tablet: form.devices.includes("tablet") },
      piiEnabled: form.pii,
    };

    busy.current = true;
    setSaving(true);
    try {
      const saved = isEdit ? await updateSurvey(survey.id, body) : await createSurvey(projectId, body);
      onSaved(saved);
    } catch (err) {
      setFormError(err instanceof OpsApiError ? err.message : "Could not save the survey.");
    } finally {
      busy.current = false;
      setSaving(false);
    }
  };

  const invalid = (key) => Boolean(errors[key]);
  const errId = (key) => `sv-${key}-err`;

  return (
    <ModalShell
      title={isEdit ? "Edit survey" : "New survey"}
      onClose={onClose}
      wide
      footer={
        <>
          <button type="button" className="ops-btn ops-btn--ghost" onClick={onClose} disabled={saving}>
            Cancel
          </button>
          <button type="submit" form="ops-survey-form" className="ops-btn ops-btn--primary" disabled={saving}>
            {saving ? "Saving…" : isEdit ? "Save changes" : "Create survey"}
          </button>
        </>
      }
    >
      <form id="ops-survey-form" className="ops-form" onSubmit={submit} noValidate>
        {formError && <p className="ops-form__error" role="alert">{formError}</p>}

        <div className="ops-field">
          <label htmlFor="sv-name">Survey name <span aria-hidden="true">*</span></label>
          <input id="sv-name" className={`ops-input ${invalid("surveyName") ? "ops-input--error" : ""}`} value={form.surveyName}
            onChange={set("surveyName")} aria-required="true" aria-invalid={invalid("surveyName")}
            aria-describedby={invalid("surveyName") ? errId("surveyName") : undefined} autoFocus />
          {invalid("surveyName") && <span id={errId("surveyName")} className="ops-field__error">{errors.surveyName}</span>}
        </div>

        <div className="ops-field">
          <label htmlFor="sv-url">Survey URL {!isEdit && <span aria-hidden="true">*</span>}</label>
          <input id="sv-url" type="url" className={`ops-input ${invalid("surveyUrl") ? "ops-input--error" : ""}`} value={form.surveyUrl}
            onChange={set("surveyUrl")} placeholder="https://" aria-invalid={invalid("surveyUrl")}
            aria-describedby={invalid("surveyUrl") ? errId("surveyUrl") : undefined} />
          {invalid("surveyUrl") && <span id={errId("surveyUrl")} className="ops-field__error">{errors.surveyUrl}</span>}
        </div>

        <div className="ops-field-row ops-field-row--3">
          <div className="ops-field">
            <label htmlFor="sv-target">Target <span aria-hidden="true">*</span></label>
            <input id="sv-target" type="number" min="1" step="1" inputMode="numeric" className={`ops-input ${invalid("target") ? "ops-input--error" : ""}`}
              value={form.target} onChange={set("target")} aria-required="true" aria-invalid={invalid("target")}
              aria-describedby={invalid("target") ? errId("target") : undefined} />
            {invalid("target") && <span id={errId("target")} className="ops-field__error">{errors.target}</span>}
          </div>
          <div className="ops-field">
            <label htmlFor="sv-loi">LOI (minutes) {!isEdit && <span aria-hidden="true">*</span>}</label>
            <input id="sv-loi" type="number" min="0.1" step="0.1" inputMode="decimal" className={`ops-input ${invalid("loi") ? "ops-input--error" : ""}`}
              value={form.loi} onChange={set("loi")} aria-invalid={invalid("loi")}
              aria-describedby={invalid("loi") ? errId("loi") : undefined} />
            {invalid("loi") && <span id={errId("loi")} className="ops-field__error">{errors.loi}</span>}
          </div>
          <div className="ops-field">
            <label htmlFor="sv-ir">IR (%) {!isEdit && <span aria-hidden="true">*</span>}</label>
            <input id="sv-ir" type="number" min="0" max="100" step="0.1" inputMode="decimal" className={`ops-input ${invalid("ir") ? "ops-input--error" : ""}`}
              value={form.ir} onChange={set("ir")} aria-invalid={invalid("ir")}
              aria-describedby={invalid("ir") ? errId("ir") : undefined} />
            {invalid("ir") && <span id={errId("ir")} className="ops-field__error">{errors.ir}</span>}
          </div>
        </div>

        <div className="ops-field-row">
          <div className="ops-field">
            <label htmlFor="sv-oof">Out-of-field date and time</label>
            <input id="sv-oof" type="datetime-local" className="ops-input" value={form.outOfFieldAt} onChange={set("outOfFieldAt")} />
          </div>
          <div className="ops-field">
            <label htmlFor="sv-tz">Timezone</label>
            <TimezoneSelect id="sv-tz" value={form.timezone} onChange={set("timezone")} />
          </div>
        </div>

        <div className="ops-field-row">
          <div className="ops-field">
            <label htmlFor="sv-country">Country (2-letter code) {!isEdit && <span aria-hidden="true">*</span>}</label>
            <input id="sv-country" className={`ops-input ${invalid("country") ? "ops-input--error" : ""}`} value={form.country}
              onChange={set("country")} placeholder="IN" maxLength={2} aria-invalid={invalid("country")} />
            {invalid("country") && <span className="ops-field__error">{errors.country}</span>}
          </div>
          <div className="ops-field">
            <label htmlFor="sv-language">Language {!isEdit && <span aria-hidden="true">*</span>}</label>
            <input id="sv-language" className={`ops-input ${invalid("language") ? "ops-input--error" : ""}`} value={form.language}
              onChange={set("language")} placeholder="en or en-IN" aria-invalid={invalid("language")} />
            {invalid("language") && <span className="ops-field__error">{errors.language}</span>}
          </div>
        </div>

        <fieldset className="ops-fieldset">
          <legend>Devices</legend>
          <div className="ops-checks">
            {DEVICE_OPTIONS.map((d) => (
              <label key={d.value} className="ops-check">
                <input type="checkbox" checked={form.devices.includes(d.value)} onChange={toggleDevice(d.value)} />
                {d.label}
              </label>
            ))}
          </div>
        </fieldset>

        <label className="ops-check">
          <input type="checkbox" checked={form.pii} onChange={(e) => set("pii")(e.target.checked)} />
          Collects personally identifiable information (PII)
        </label>
      </form>
    </ModalShell>
  );
}
