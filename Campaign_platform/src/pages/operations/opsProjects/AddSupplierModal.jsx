import { useEffect, useId, useRef, useState } from "react";
import { addSurveySuppliers, lookupVendors, unwrapList, OpsApiError } from "../../../services/opsProjectsService";
import { ModalShell } from "./opsShared";

const CURRENCIES = ["USD", "INR", "EUR", "GBP", "AUD", "CAD", "SGD", "AED"];

// /vendors/lookup rows are { vid, vendorName, vendorType }.
const vendorId = (v) => String(v.vid ?? v.id ?? v._id ?? "");
const vendorName = (v) => v.vendorName || v.name || `Vendor ${vendorId(v)}`;

// Searchable multi-select of existing vendors. Creates one independent supplier row per vendor.
export default function AddSupplierModal({ surveyId, attachedVendorIds, canPrice, onClose, onAdded }) {
  const [query, setQuery] = useState("");
  const [results, setResults] = useState([]);
  const [searching, setSearching] = useState(false);
  const [searchError, setSearchError] = useState(null);
  const [selected, setSelected] = useState([]);
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

  const alreadyAttached = new Set((attachedVendorIds || []).map(String));
  const selectedIds = new Set(selected.map((v) => vendorId(v)));

  const toggle = (vendor) => {
    const id = vendorId(vendor);
    setSelected((list) => (list.some((v) => vendorId(v) === id) ? list.filter((v) => vendorId(v) !== id) : [...list, vendor]));
    if (errors.vendors) setErrors((er) => ({ ...er, vendors: undefined }));
  };

  const validate = () => {
    const next = {};
    if (selected.length === 0) next.vendors = "Select at least one vendor.";
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
    const body = { vendorIds: selected.map(vendorId) };
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
      setFormError(err instanceof OpsApiError ? err.message : "Could not add the suppliers.");
    } finally {
      busy.current = false;
      setSaving(false);
    }
  };

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
            {saving ? "Adding…" : selected.length > 0 ? `Add ${selected.length} supplier${selected.length === 1 ? "" : "s"}` : "Add supplier"}
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

        <div className="ops-vendor-results" id={listId} role="listbox" aria-multiselectable="true" aria-label="Vendors" aria-busy={searching}>
          {searchError && <p className="ops-field__error">{searchError}</p>}
          {!searchError && !searching && results.length === 0 && <p className="ops-field__hint">No vendors found.</p>}
          {results.map((v) => {
            const id = vendorId(v);
            const attached = alreadyAttached.has(id);
            const checked = selectedIds.has(id);
            return (
              <div key={id} role="option" aria-selected={checked} aria-disabled={attached} className={`ops-vendor-option ${attached ? "is-attached" : ""}`}>
                <label>
                  <input type="checkbox" checked={checked} disabled={attached} onChange={() => toggle(v)} />
                  {vendorName(v)}
                </label>
                {attached && <span className="ops-field__hint">Already added</span>}
              </div>
            );
          })}
        </div>

        {selected.length > 0 && (
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
