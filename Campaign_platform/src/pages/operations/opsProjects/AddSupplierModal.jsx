import { useEffect, useId, useRef, useState } from "react";
import { addSurveySuppliers, getSurvey, lookupVendors, unwrapList, OpsApiError } from "../../../services/opsProjectsService";
import { ModalShell } from "./opsShared";
import { splitFieldErrors } from "./opsUtils";
import { createLegacyLink, deleteLegacyLink, entryLinkTemplate, fetchVendorByVid, normalizeUrl } from "./legacyLink";

const CURRENCIES = ["USD", "INR", "EUR", "GBP", "AUD", "CAD", "SGD", "AED"];
// Three ways to add a supplier to a survey.
const MODES = [
  { value: "create", label: "Create new link" },
  { value: "link", label: "Attach existing link" },
  { value: "nolink", label: "Add vendor without link yet" },
];
// One vendor per row in these modes (radio), many in "nolink" (checkbox).
const singleVendor = (mode) => mode !== "nolink";

const today = () => {
  const d = new Date();
  const pad = (n) => String(n).padStart(2, "0");
  return `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())}`;
};

// Classic link form, prefilled from the survey and project.
const linkFormFrom = (survey, project, vendor) => ({
  projectName: [survey?.surveyName || project?.projectName || "", vendor ? (vendor.vendorName || "") : ""]
    .filter(Boolean).join(" - "),
  client: project?.clientName || "",
  salesPerson: project?.managerName || "",
  projectLaunchDate: today(),
  totalCompletesRequired: survey?.targetN ?? "",
  loi: survey?.loi ?? "",
  clientIR: survey?.ir ?? "",
  cpi: "",
  countryCode: survey?.countryCode || "",
  liveLink: survey?.surveyUrl || "",
});

const positive = (v) => Number.isFinite(Number(v)) && Number(v) > 0;
// API field -> form key for the errors shown under inputs here.
const FIELD_MAP = { vendorIds: "vendors", links: "vendors", surveyNo: "surveyNo" };
const FORM_FIELDS = ["vendors", "surveyNo", "buyPrice"];

// /vendors/lookup rows are { vid, vendorName, vendorType }.
const vendorId = (v) => String(v.vid ?? v.id ?? v._id ?? "");
const vendorName = (v) => v.vendorName || v.name || `Vendor ${vendorId(v)}`;

// Vendor search and selection. "link" mode picks one vendor and needs a link number;
// "nolink" mode picks many vendors and creates them without traffic links.
// The same vendor may be added again, so existing rows do not block selection.
export default function AddSupplierModal({ surveyId, project, canPrice, onClose, onAdded }) {
  const [mode, setMode] = useState("create");
  const [survey, setSurvey] = useState(null);
  const [linkForm, setLinkForm] = useState(() => linkFormFrom(null, project, null));
  const [query, setQuery] = useState("");
  const [results, setResults] = useState([]);
  const [searching, setSearching] = useState(false);
  const [searchError, setSearchError] = useState(null);
  const [selected, setSelected] = useState([]);
  const [surveyNo, setSurveyNo] = useState("");
  const [buyPrice, setBuyPrice] = useState("");
  const [currency, setCurrency] = useState("USD");
  const [errors, setErrors] = useState({});
  const [saving, setSaving] = useState(false);
  const [formError, setFormError] = useState(null);
  const busy = useRef(false);
  const listId = useId();

  // Debounced vendor lookup. Stale responses are dropped via the `active` flag.
  useEffect(() => {
    let active = true;
    const timer = setTimeout(async () => {
      setSearching(true);
      setSearchError(null);
      try {
        const data = await lookupVendors(query.trim());
        if (active) setResults(unwrapList(data, "items", "vendors", "results"));
      } catch (e) {
        if (active) setSearchError(e.message || "Vendor lookup failed.");
      } finally {
        if (active) setSearching(false);
      }
    }, 250);
    return () => {
      active = false;
      clearTimeout(timer);
    };
  }, [query]);

  // Full survey (URL, target, LOI, IR, country) to prefill the classic link form.
  useEffect(() => {
    let active = true;
    getSurvey(surveyId)
      .then((s) => {
        if (!active) return;
        setSurvey(s);
        setLinkForm(linkFormFrom(s, project, null));
      })
      .catch(() => {});
    return () => {
      active = false;
    };
  }, [surveyId, project]);

  const setLink = (key) => (e) => {
    const value = e.target.value;
    setLinkForm((f) => ({ ...f, [key]: value }));
    if (errors[key]) setErrors((er) => ({ ...er, [key]: undefined }));
  };

  const selectedIds = new Set(selected.map((v) => vendorId(v)));

  const changeMode = (next) => {
    setMode(next);
    setSelected([]);
    setErrors({});
    setFormError(null);
  };

  const toggle = (vendor) => {
    const id = vendorId(vendor);
    const isOn = selected.some((v) => vendorId(v) === id);
    if (singleVendor(mode)) {
      // One vendor per link row: picking another vendor replaces the choice.
      setSelected(isOn ? [] : [vendor]);
      if (mode === "create") {
        const base = survey?.surveyName || project?.projectName || "";
        setLinkForm((f) => ({ ...f, projectName: isOn ? base : [base, vendorName(vendor)].filter(Boolean).join(" - ") }));
      }
    } else {
      setSelected((list) => (isOn ? list.filter((v) => vendorId(v) !== id) : [...list, vendor]));
    }
    if (errors.vendors) setErrors((er) => ({ ...er, vendors: undefined }));
  };

  const validate = () => {
    const next = {};
    if (selected.length === 0) next.vendors = singleVendor(mode) ? "Select a vendor." : "Select at least one vendor.";
    if (mode === "create") {
      // Same rules the classic page applies to a live project.
      const f = linkForm;
      if (!f.projectName.trim()) next.projectName = "Name is required.";
      if (!f.client.trim()) next.client = "Client is required.";
      if (!f.salesPerson.trim()) next.salesPerson = "Sales person is required.";
      if (!f.projectLaunchDate) next.projectLaunchDate = "Launch date is required.";
      if (!positive(f.totalCompletesRequired)) next.totalCompletesRequired = "Completes required must be more than 0.";
      if (!positive(f.loi)) next.loi = "LOI must be more than 0.";
      if (!positive(f.cpi)) next.cpi = "CPI must be more than 0.";
      const url = normalizeUrl(f.liveLink);
      if (!url) next.liveLink = "Live link is required.";
      else {
        try {
          const u = new URL(url);
          if (u.protocol !== "http:" && u.protocol !== "https:") next.liveLink = "Live link must start with http:// or https://.";
        } catch {
          next.liveLink = "Enter a valid URL.";
        }
      }
    }
    if (mode === "link") {
      if (!surveyNo.trim()) next.surveyNo = "Enter the link number.";
      else if (surveyNo.trim().length > 32) next.surveyNo = "Link number must be 32 characters or fewer.";
    }
    if (canPrice && buyPrice !== "") {
      const n = Number(buyPrice);
      if (Number.isNaN(n) || n < 0) next.buyPrice = "Buy price must be 0 or more.";
    }
    setErrors(next);
    return Object.keys(next).length === 0;
  };

  const submit = async (e) => {
    e.preventDefault();
    if (busy.current) return;
    setFormError(null);
    if (!validate()) return;

    busy.current = true;
    setSaving(true);
    let legacy = null;
    try {
      // "create": make the classic traffic link first; the server issues its link number.
      let linkNo = surveyNo.trim();
      if (mode === "create") {
        const vid = vendorId(selected[0]);
        const vendor = (await fetchVendorByVid(vid)) || { vid, vendorName: vendorName(selected[0]) };
        legacy = await createLegacyLink(linkForm, vendor);
        linkNo = String(legacy?.surveyNo || "");
        if (!linkNo) throw new Error("The link was created without a link number.");
      }

      // buyPrice goes out as a string (the backend field is a string); the service converts.
      const body = mode === "nolink"
        ? { vendorIds: selected.map(vendorId) }
        : { links: [{ vendorId: vendorId(selected[0]), surveyNo: linkNo }] };
      if (canPrice) {
        body.buyPrice = buyPrice.trim() === "" ? null : buyPrice.trim();
        body.currency = currency;
      }

      const created = await addSurveySuppliers(surveyId, body);
      legacy = null; // attached: keep it
      onAdded(created);
    } catch (err) {
      // A link created above but not attached would be an orphan: remove it.
      if (legacy?._id) await deleteLegacyLink(legacy._id);
      if (err instanceof OpsApiError && err.status === 422) {
        const { inline, other } = splitFieldErrors(err.fieldErrors, FORM_FIELDS, FIELD_MAP);
        setErrors((er) => ({ ...er, ...inline }));
        setFormError(other || (Object.keys(inline).length ? null : err.message));
      } else {
        // Backend validation (unknown vendor, link already used, link of another vendor) comes back as text.
        setFormError(err?.message || "Could not add the supplier.");
      }
    } finally {
      busy.current = false;
      setSaving(false);
    }
  };

  // One input of the classic link form, with its inline error.
  const linkField = (key, label, required, props = {}) => (
    <div className="ops-field">
      <label htmlFor={`sup-l-${key}`}>{label} {required && <span aria-hidden="true">*</span>}</label>
      <input
        id={`sup-l-${key}`}
        className={`ops-input ${errors[key] ? "ops-input--error" : ""}`}
        value={linkForm[key]}
        onChange={setLink(key)}
        aria-invalid={Boolean(errors[key])}
        autoComplete="off"
        {...props}
      />
      {errors[key] && <span className="ops-field__error">{errors[key]}</span>}
    </div>
  );

  const count = selected.length;
  const submitLabel = saving
    ? "Adding…"
    : mode === "create"
      ? "Create link"
      : mode === "link"
      ? "Attach link"
      : count > 0 ? `Add ${count} vendor${count === 1 ? "" : "s"}` : "Add vendors";

  return (
    <ModalShell
      title="Add supplier"
      onClose={onClose}
      wide
      footer={
        <>
          <button type="button" className="ops-btn ops-btn--ghost" onClick={onClose} disabled={saving}>
            Cancel
          </button>
          <button type="submit" form="ops-supplier-form" className="ops-btn ops-btn--primary" disabled={saving}>
            {submitLabel}
          </button>
        </>
      }
    >
      <form id="ops-supplier-form" className="ops-form" onSubmit={submit} noValidate>
        {formError && <p className="ops-form__error" role="alert">{formError}</p>}

        <div className="ops-segmented" role="group" aria-label="How to add the supplier">
          {MODES.map((m) => (
            <button
              key={m.value}
              type="button"
              className={`ops-segmented__btn ${mode === m.value ? "is-active" : ""}`}
              aria-pressed={mode === m.value}
              onClick={() => changeMode(m.value)}
              disabled={saving}
            >
              {m.label}
            </button>
          ))}
        </div>

        {mode === "nolink" && (
          <p className="ops-notice" role="note">
            A traffic link must be attached later; no traffic is recorded until then.
          </p>
        )}

        <div className="ops-field">
          <label htmlFor="sup-search">Search vendors</label>
          <input
            id="sup-search"
            type="search"
            className="ops-input"
            value={query}
            onChange={(e) => setQuery(e.target.value)}
            placeholder="Type a vendor name"
            role="combobox"
            aria-expanded="true"
            aria-controls={listId}
            aria-autocomplete="list"
            autoComplete="off"
            autoFocus
          />
        </div>

        <div className="ops-vendor-results" id={listId} role="listbox" aria-multiselectable={mode === "nolink"} aria-label="Vendors" aria-busy={searching}>
          {searchError && <p className="ops-field__error">{searchError}</p>}
          {!searchError && !searching && results.length === 0 && <p className="ops-field__hint">No vendors found.</p>}
          {results.map((v) => {
            const id = vendorId(v);
            const checked = selectedIds.has(id);
            return (
              <div key={id} role="option" aria-selected={checked} className="ops-vendor-option">
                <label>
                  <input
                    type={singleVendor(mode) ? "radio" : "checkbox"}
                    name="sup-vendor"
                    checked={checked}
                    onChange={() => toggle(v)}
                  />
                  {vendorName(v)}
                </label>
              </div>
            );
          })}
        </div>

        {count > 0 && (
          <ul className="ops-chips" aria-label="Selected vendors">
            {selected.map((v) => (
              <li key={vendorId(v)} className="ops-chip">
                {vendorName(v)}
                <button type="button" className="ops-chip__remove" aria-label={`Remove ${vendorName(v)}`} onClick={() => toggle(v)}>
                  ×
                </button>
              </li>
            ))}
          </ul>
        )}
        {errors.vendors && <span className="ops-field__error">{errors.vendors}</span>}

        {mode === "create" && count > 0 && (
          <fieldset className="ops-fieldset">
            <legend>Link details (classic project record)</legend>
            <p className="ops-field__hint">
              Saved as a project in Projects (classic). The link number and entry link are generated on save.
            </p>
            {linkField("projectName", "Name", true)}
            <div className="ops-field-row">
              {linkField("client", "Client", true)}
              {linkField("salesPerson", "Sales person", true)}
            </div>
            <div className="ops-field-row ops-field-row--3">
              {linkField("totalCompletesRequired", "Completes required", true, { type: "number", min: "1", step: "1" })}
              {linkField("loi", "LOI (minutes)", true, { type: "number", min: "0.1", step: "0.1" })}
              {linkField("clientIR", "Client IR (%)", false, { type: "number", min: "0", max: "100", step: "0.1" })}
            </div>
            <div className="ops-field-row ops-field-row--3">
              {linkField("cpi", "CPI", true, { type: "number", min: "0", step: "0.01" })}
              {linkField("projectLaunchDate", "Launch date", true, { type: "date" })}
              {linkField("countryCode", "Country", false, { maxLength: 2, placeholder: "IN" })}
            </div>
            {linkField("liveLink", "Live link (client survey URL)", true, { placeholder: "https://" })}
            <div className="ops-field">
              <label>Entry link</label>
              <input className="ops-input" readOnly
                value={entryLinkTemplate(vendorId(selected[0]), "(generated on save)")} />
            </div>
          </fieldset>
        )}

        {mode === "link" && (
          <div className="ops-field">
            <label htmlFor="sup-link-no">Link number</label>
            <input
              id="sup-link-no"
              className={`ops-input ${errors.surveyNo ? "ops-input--error" : ""}`}
              value={surveyNo}
              onChange={(e) => {
                setSurveyNo(e.target.value);
                if (errors.surveyNo) setErrors((er) => ({ ...er, surveyNo: undefined }));
              }}
              maxLength={32}
              aria-invalid={Boolean(errors.surveyNo)}
              autoComplete="off"
            />
            {errors.surveyNo && <span className="ops-field__error">{errors.surveyNo}</span>}
          </div>
        )}

        {canPrice && (
          <div className="ops-field-row">
            <div className="ops-field">
              <label htmlFor="sup-price">Buy price</label>
              <input
                id="sup-price"
                type="number"
                min="0"
                step="0.01"
                inputMode="decimal"
                className={`ops-input ${errors.buyPrice ? "ops-input--error" : ""}`}
                value={buyPrice}
                onChange={(e) => setBuyPrice(e.target.value)}
                aria-invalid={Boolean(errors.buyPrice)}
              />
              {errors.buyPrice && <span className="ops-field__error">{errors.buyPrice}</span>}
            </div>
            <div className="ops-field">
              <label htmlFor="sup-currency">Currency</label>
              <select id="sup-currency" className="ops-input" value={currency} onChange={(e) => setCurrency(e.target.value)}>
                {CURRENCIES.map((c) => (
                  <option key={c} value={c}>{c}</option>
                ))}
              </select>
            </div>
          </div>
        )}
      </form>
    </ModalShell>
  );
}
