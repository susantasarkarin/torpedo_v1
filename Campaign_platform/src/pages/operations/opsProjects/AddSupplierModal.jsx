import { useEffect, useId, useRef, useState } from "react";
import { addSurveySuppliers, getSurvey, lookupVendors, unwrapList, OpsApiError } from "../../../services/opsProjectsService";
import { fetchAllClients } from "../../../utils/api";
import { ModalShell } from "./opsShared";
import { splitFieldErrors } from "./opsUtils";
import { createLegacyLink, deleteLegacyLink, entryLinkTemplate, fetchVendorByVid, normalizeUrl } from "./legacyLink";

const CURRENCIES = ["USD", "INR", "EUR", "GBP", "AUD", "CAD", "SGD", "AED"];
// API field -> form key for the errors shown under inputs here.
const FIELD_MAP = { vendorIds: "vendors", links: "vendors" };
const FORM_FIELDS = ["vendors", "buyPrice"];

// /vendors/lookup rows are { vid, vendorName, vendorType }.
const vendorId = (v) => String(v.vid ?? v.id ?? v._id ?? "");
const vendorName = (v) => v.vendorName || v.name || `Vendor ${vendorId(v)}`;
const clientName = (c) => c.company_name || c.name || "";

const today = () => {
  const d = new Date();
  const pad = (n) => String(n).padStart(2, "0");
  return `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())}`;
};

// Classic link form, prefilled from the survey and project.
const linkFormFrom = (survey, project) => ({
  projectName: survey?.surveyName || project?.projectName || "",
  client: project?.clientName || "",
  salesPerson: project?.managerName || "",
  projectLaunchDate: today(),
  totalCompletesRequired: survey?.targetN ?? "",
  loi: survey?.loi ?? "",
  clientIR: survey?.ir ?? "",
  countryCode: survey?.countryCode || "",
  liveLink: survey?.surveyUrl || "",
});

const positive = (v) => Number.isFinite(Number(v)) && Number(v) > 0;

// Picks one vendor, shows the classic project form prefilled from the survey, and on
// save creates the classic traffic link (server issues the link number) and attaches
// it to the survey.
export default function AddSupplierModal({ surveyId, project, canPrice, onClose, onAdded }) {
  const [survey, setSurvey] = useState(null);
  const [linkForm, setLinkForm] = useState(() => linkFormFrom(null, project));
  const [clients, setClients] = useState([]);
  const [query, setQuery] = useState("");
  const [results, setResults] = useState([]);
  const [searching, setSearching] = useState(false);
  const [searchError, setSearchError] = useState(null);
  const [selected, setSelected] = useState(null);
  const [buyPrice, setBuyPrice] = useState("");
  const [currency, setCurrency] = useState("USD");
  const [errors, setErrors] = useState({});
  const [saving, setSaving] = useState(false);
  const [formError, setFormError] = useState(null);
  const busy = useRef(false);
  const listId = useId();

  // Full survey (URL, target, LOI, IR, country) to prefill the classic link form.
  useEffect(() => {
    let active = true;
    getSurvey(surveyId)
      .then((s) => {
        if (active) {
          setSurvey(s);
          setLinkForm(linkFormFrom(s, project));
        }
      })
      .catch(() => {});
    return () => {
      active = false;
    };
  }, [surveyId, project]);

  // Active (online) clients only, filled in as pages arrive.
  useEffect(() => {
    let active = true;
    const keep = (list) => list.filter((c) => String(c.status || "").toLowerCase() === "active" && clientName(c));
    fetchAllClients({ onBatch: (soFar) => active && setClients(keep(soFar)) })
      .then((all) => active && setClients(keep(all)))
      .catch(() => {});
    return () => {
      active = false;
    };
  }, []);

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

  const setLink = (key) => (e) => {
    const value = e.target.value;
    setLinkForm((f) => ({ ...f, [key]: value }));
    if (errors[key]) setErrors((er) => ({ ...er, [key]: undefined }));
  };

  const pick = (vendor) => {
    const isOn = selected && vendorId(selected) === vendorId(vendor);
    const next = isOn ? null : vendor;
    setSelected(next);
    const base = survey?.surveyName || project?.projectName || "";
    setLinkForm((f) => ({ ...f, projectName: next ? [base, vendorName(next)].filter(Boolean).join(" - ") : base }));
    if (errors.vendors) setErrors((er) => ({ ...er, vendors: undefined }));
  };

  // Same rules the classic page applies to a live project (CPI excepted).
  const validate = () => {
    const next = {};
    const f = linkForm;
    if (!selected) next.vendors = "Select a vendor.";
    if (!f.projectName.trim()) next.projectName = "Name is required.";
    if (!f.client.trim()) next.client = "Client is required.";
    if (!f.salesPerson.trim()) next.salesPerson = "Sales person is required.";
    if (!f.projectLaunchDate) next.projectLaunchDate = "Launch date is required.";
    if (!positive(f.totalCompletesRequired)) next.totalCompletesRequired = "Completes required must be more than 0.";
    if (!positive(f.loi)) next.loi = "LOI must be more than 0.";
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
      // Classic traffic link first; the server issues its link number (surveyNo).
      const vid = vendorId(selected);
      const vendor = (await fetchVendorByVid(vid)) || { vid, vendorName: vendorName(selected) };
      // The classic record's CPI is the buy price (no separate CPI input here).
      legacy = await createLegacyLink({ ...linkForm, cpi: buyPrice.trim() }, vendor);
      const linkNo = String(legacy?.surveyNo || "");
      if (!linkNo) throw new Error("The link was created without a link number.");

      // buyPrice goes out as a string (the backend field is a string); the service converts.
      const body = { links: [{ vendorId: vid, surveyNo: linkNo }] };
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

  // Keep the project's client selectable even if it is not in the active list.
  const clientOptions = clients.map(clientName);
  if (linkForm.client && !clientOptions.includes(linkForm.client)) clientOptions.unshift(linkForm.client);

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
            {saving ? "Creating…" : "Create link"}
          </button>
        </>
      }
    >
      <form id="ops-supplier-form" className="ops-form" onSubmit={submit} noValidate>
        {formError && <p className="ops-form__error" role="alert">{formError}</p>}

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

        <div className="ops-vendor-results" id={listId} role="listbox" aria-label="Vendors" aria-busy={searching}>
          {searchError && <p className="ops-field__error">{searchError}</p>}
          {!searchError && !searching && results.length === 0 && <p className="ops-field__hint">No vendors found.</p>}
          {results.map((v) => {
            const checked = Boolean(selected) && vendorId(selected) === vendorId(v);
            return (
              <div key={vendorId(v)} role="option" aria-selected={checked} className="ops-vendor-option">
                <label>
                  <input type="radio" name="sup-vendor" checked={checked} onChange={() => pick(v)} />
                  {vendorName(v)}
                </label>
              </div>
            );
          })}
        </div>

        {selected && (
          <ul className="ops-chips" aria-label="Selected vendor">
            <li className="ops-chip">
              {vendorName(selected)}
              <button type="button" className="ops-chip__remove" aria-label={`Remove ${vendorName(selected)}`} onClick={() => pick(selected)}>
                ×
              </button>
            </li>
          </ul>
        )}
        {errors.vendors && <span className="ops-field__error">{errors.vendors}</span>}

        {selected && (
          <fieldset className="ops-fieldset">
            <legend>Link details (classic project record)</legend>
            <p className="ops-field__hint">
              Saved as a project in Projects (classic). The link number and entry link are generated on save.
            </p>
            {linkField("projectName", "Name", true)}
            <div className="ops-field-row">
              <div className="ops-field">
                <label htmlFor="sup-l-client">Client <span aria-hidden="true">*</span></label>
                <select
                  id="sup-l-client"
                  className={`ops-input ${errors.client ? "ops-input--error" : ""}`}
                  value={linkForm.client}
                  onChange={setLink("client")}
                  aria-invalid={Boolean(errors.client)}
                >
                  <option value="">Choose a client</option>
                  {clientOptions.map((name) => (
                    <option key={name} value={name}>{name}</option>
                  ))}
                </select>
                {errors.client && <span className="ops-field__error">{errors.client}</span>}
              </div>
              {linkField("salesPerson", "Sales person", true)}
            </div>
            <div className="ops-field-row ops-field-row--3">
              {linkField("totalCompletesRequired", "Completes required", true, { type: "number", min: "1", step: "1" })}
              {linkField("loi", "LOI (minutes)", true, { type: "number", min: "0.1", step: "0.1" })}
              {linkField("clientIR", "Client IR (%)", false, { type: "number", min: "0", max: "100", step: "0.1" })}
            </div>
            <div className="ops-field-row">
              {linkField("projectLaunchDate", "Launch date", true, { type: "date" })}
              {linkField("countryCode", "Country", false, { maxLength: 2, placeholder: "IN" })}
            </div>
            {linkField("liveLink", "Live link (client survey URL)", true, { placeholder: "https://" })}
            <div className="ops-field">
              <label htmlFor="sup-l-entry">Entry link</label>
              <input id="sup-l-entry" className="ops-input" readOnly value={entryLinkTemplate(vendorId(selected), "(generated on save)")} />
            </div>
          </fieldset>
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
