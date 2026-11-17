import { useEffect, useId, useRef, useState } from "react";
import { addSurveySuppliers, lookupVendors, unwrapList, OpsApiError } from "../../../services/opsProjectsService";
import { ModalShell } from "./opsShared";
import { splitFieldErrors } from "./opsUtils";

const CURRENCIES = ["USD", "INR", "EUR", "GBP", "AUD", "CAD", "SGD", "AED"];
// Two ways to add a supplier to a survey.
const MODES = [
  { value: "link", label: "Attach existing link" },
  { value: "nolink", label: "Add vendor without link yet" },
];
// API field -> form key for the errors shown under inputs here.
const FIELD_MAP = { vendorIds: "vendors", links: "vendors", surveyNo: "surveyNo" };
const FORM_FIELDS = ["vendors", "surveyNo", "buyPrice"];

// /vendors/lookup rows are { vid, vendorName, vendorType }.
const vendorId = (v) => String(v.vid ?? v.id ?? v._id ?? "");
const vendorName = (v) => v.vendorName || v.name || `Vendor ${vendorId(v)}`;

// Vendor search and selection. "link" mode picks one vendor and needs a link number;
// "nolink" mode picks many vendors and creates them without traffic links.
// The same vendor may be added again, so existing rows do not block selection.
export default function AddSupplierModal({ surveyId, canPrice, onClose, onAdded }) {
  const [mode, setMode] = useState("link");
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
    if (mode === "link") {
      // One vendor per link row: picking another vendor replaces the choice.
      setSelected(isOn ? [] : [vendor]);
    } else {
      setSelected((list) => (isOn ? list.filter((v) => vendorId(v) !== id) : [...list, vendor]));
    }
    if (errors.vendors) setErrors((er) => ({ ...er, vendors: undefined }));
  };

  const validate = () => {
    const next = {};
    if (selected.length === 0) next.vendors = mode === "link" ? "Select a vendor." : "Select at least one vendor.";
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

    // buyPrice goes out as a string (the backend field is a string); the service converts.
    const body = mode === "link"
      ? { links: [{ vendorId: vendorId(selected[0]), surveyNo: surveyNo.trim() }] }
      : { vendorIds: selected.map(vendorId) };
    if (canPrice) {
      body.buyPrice = buyPrice.trim() === "" ? null : buyPrice.trim();
      body.currency = currency;
    }

    busy.current = true;
    setSaving(true);
    try {
      const created = await addSurveySuppliers(surveyId, body);
      onAdded(created);
    } catch (err) {
      if (err instanceof OpsApiError && err.status === 422) {
        const { inline, other } = splitFieldErrors(err.fieldErrors, FORM_FIELDS, FIELD_MAP);
        setErrors((er) => ({ ...er, ...inline }));
        setFormError(other || (Object.keys(inline).length ? null : err.message));
      } else {
        // Backend validation (unknown vendor, link already used, link of another vendor) comes back as text.
        setFormError(err instanceof OpsApiError ? err.message : "Could not add the supplier.");
      }
    } finally {
      busy.current = false;
      setSaving(false);
    }
  };

  const count = selected.length;
  const submitLabel = saving
    ? "Adding…"
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
                    type={mode === "link" ? "radio" : "checkbox"}
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
