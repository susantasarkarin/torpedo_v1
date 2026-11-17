import { useRef, useState } from "react";
import { attachSupplierLink, OpsApiError } from "../../../services/opsProjectsService";
import { ModalShell } from "./opsShared";

// Attaches a traffic link number to an unlinked supplier participation.
// The backend checks the link (exists, belongs to this vendor, not already used) and its error text is shown as is.
export default function AttachLinkModal({ row, onClose, onAttached }) {
  const [surveyNo, setSurveyNo] = useState("");
  const [error, setError] = useState(null);
  const [saving, setSaving] = useState(false);
  const busy = useRef(false);

  const submit = async (e) => {
    e.preventDefault();
    if (busy.current) return;
    const no = surveyNo.trim();
    if (!no) {
      setError("Enter the link number.");
      return;
    }
    setError(null);
    busy.current = true;
    setSaving(true);
    try {
      const item = await attachSupplierLink(row.id, no);
      onAttached(item);
    } catch (err) {
      setError(err instanceof OpsApiError ? err.message : "Could not attach the link.");
    } finally {
      busy.current = false;
      setSaving(false);
    }
  };

  return (
    <ModalShell
      title={`Attach link to ${row.vendorName || "supplier"}`}
      onClose={onClose}
      footer={
        <>
          <button type="button" className="ops-btn ops-btn--ghost" onClick={onClose} disabled={saving}>
            Cancel
          </button>
          <button type="submit" form="ops-attach-link-form" className="ops-btn ops-btn--primary" disabled={saving}>
            {saving ? "Attaching…" : "Attach link"}
          </button>
        </>
      }
    >
      <form id="ops-attach-link-form" className="ops-form" onSubmit={submit} noValidate>
        {error && <p className="ops-form__error" role="alert">{error}</p>}
        <p className="ops-field__hint">
          Traffic starts counting once a link is attached. Enter the link number issued by the supplier.
        </p>
        <div className="ops-field">
          <label htmlFor="attach-link-no">Link number</label>
          <input
            id="attach-link-no"
            className={`ops-input ${error && !surveyNo.trim() ? "ops-input--error" : ""}`}
            value={surveyNo}
            onChange={(e) => {
              setSurveyNo(e.target.value);
              if (error) setError(null);
            }}
            maxLength={32}
            autoFocus
            autoComplete="off"
          />
        </div>
      </form>
    </ModalShell>
  );
}
