import { useCallback, useEffect, useId, useRef, useState } from "react";
import {
  listAllProjectSurveys,
  listCleaningRequests,
  createCleaningRequest,
  updateCleaningRequestStatus,
  unwrapList,
  OpsApiError,
} from "../../../services/opsProjectsService";
import { notify as notifyToast } from "../../../utils/notify";
import { ModalShell, StateMessage } from "./opsShared";
import { fmtDateTime } from "./opsUtils";

const CLEANING_STATUSES = [
  { value: "submitted", label: "Submitted" },
  { value: "in_progress", label: "In progress" },
  { value: "completed", label: "Completed" },
  { value: "cancelled", label: "Cancelled" },
];

const statusLabel = (value) => CLEANING_STATUSES.find((s) => s.value === value)?.label || value || "—";
const surveyKey = (s) => String(s.id ?? s._id ?? "");
const errorText = (e, fallback) => (e instanceof OpsApiError ? e.message : fallback);

// One request row. Owns its status-change form so rows update independently.
function CleaningRequestRow({ request, surveyNames, onChanged }) {
  const [nextStatus, setNextStatus] = useState(request.status || "submitted");
  const [note, setNote] = useState("");
  const [busy, setBusy] = useState(false);
  const busyRef = useRef(false);
  const controlId = useId();

  const names = (request.surveyIds || []).map((id) => surveyNames[String(id)] || String(id));
  const unchanged = nextStatus === request.status;

  const updateStatus = async (e) => {
    e.preventDefault();
    if (busyRef.current || unchanged) return;
    busyRef.current = true;
    setBusy(true);
    try {
      await updateCleaningRequestStatus(request.id, { status: nextStatus, note: note.trim() });
      notifyToast("Cleaning request updated.", "success");
      setNote("");
      onChanged();
    } catch (err) {
      notifyToast(errorText(err, "Could not update the request."), "error");
    } finally {
      busyRef.current = false;
      setBusy(false);
    }
  };

  return (
    <li className="ops-request">
      <div className="ops-request__head">
        <strong>{names.length ? names.join(", ") : "No surveys listed"}</strong>
        <span className={`ops-badge ops-badge--${request.status || "draft"}`}>{statusLabel(request.status)}</span>
      </div>
      <p className="ops-request__meta">
        Requested by {request.requestedBy || "—"} on {fmtDateTime(request.createdAt)}
      </p>
      {request.notes && <p className="ops-request__meta">{request.notes}</p>}

      <details>
        <summary>History ({(request.history || []).length})</summary>
        <ol className="ops-history">
          {(request.history || []).map((h, i) => (
            <li key={`${h.ts}-${i}`}>
              {fmtDateTime(h.ts)}: {statusLabel(h.status)} by {h.user || "—"}
              {h.note ? ` (${h.note})` : ""}
            </li>
          ))}
          {(request.history || []).length === 0 && <li>No history recorded.</li>}
        </ol>
      </details>

      <form className="ops-request__controls" onSubmit={updateStatus}>
        <label className="ops-visually-hidden" htmlFor={`${controlId}-status`}>Change status</label>
        <select
          id={`${controlId}-status`}
          className="ops-input ops-input--sm"
          value={nextStatus}
          disabled={busy}
          onChange={(e) => setNextStatus(e.target.value)}
        >
          {CLEANING_STATUSES.map((s) => (
            <option key={s.value} value={s.value}>{s.label}</option>
          ))}
        </select>
        <label className="ops-visually-hidden" htmlFor={`${controlId}-note`}>Status note</label>
        <input
          id={`${controlId}-note`}
          type="text"
          className="ops-input ops-input--sm"
          placeholder="Note (optional)"
          value={note}
          disabled={busy}
          onChange={(e) => setNote(e.target.value)}
        />
        <button type="submit" className="ops-btn ops-btn--ghost ops-btn--sm" disabled={busy || unchanged}>
          {busy ? "Saving…" : "Update status"}
        </button>
      </form>
    </li>
  );
}

export default function DataCleaningModal({ projectId, onClose, onSubmitted }) {
  const [surveys, setSurveys] = useState([]);
  const [surveysLoading, setSurveysLoading] = useState(true);
  const [surveysError, setSurveysError] = useState(null);

  const [requests, setRequests] = useState([]);
  const [requestsLoading, setRequestsLoading] = useState(true);
  const [requestsError, setRequestsError] = useState(null);

  const [selected, setSelected] = useState([]);
  const [notes, setNotes] = useState("");
  const [fieldError, setFieldError] = useState(null);
  const [formError, setFormError] = useState(null);
  const [saving, setSaving] = useState(false);
  const busy = useRef(false);

  const fetchRequests = useCallback(async () => {
    setRequestsLoading(true);
    setRequestsError(null);
    try {
      const res = await listCleaningRequests(projectId);
      setRequests(unwrapList(res, "items", "requests"));
    } catch (e) {
      setRequestsError(errorText(e, "Could not load previous requests."));
    } finally {
      setRequestsLoading(false);
    }
  }, [projectId]);

  const fetchSurveys = useCallback(async () => {
    setSurveysLoading(true);
    setSurveysError(null);
    try {
      setSurveys(await listAllProjectSurveys(projectId));
    } catch (e) {
      setSurveysError(errorText(e, "Could not load the surveys in this project."));
    } finally {
      setSurveysLoading(false);
    }
  }, [projectId]);

  useEffect(() => {
    fetchSurveys();
    fetchRequests();
  }, [fetchSurveys, fetchRequests]);

  const surveyNames = Object.fromEntries(surveys.map((s) => [surveyKey(s), s.surveyName || s.surveyNo || surveyKey(s)]));

  const toggle = (id) => {
    setSelected((list) => (list.includes(id) ? list.filter((x) => x !== id) : [...list, id]));
    setFieldError(null);
  };

  const submit = async (e) => {
    e.preventDefault();
    if (busy.current) return;
    setFormError(null);
    if (selected.length === 0) {
      setFieldError("Select at least one survey.");
      return;
    }
    busy.current = true;
    setSaving(true);
    try {
      await createCleaningRequest(projectId, { surveyIds: selected, notes: notes.trim() });
      notifyToast("Data cleaning request submitted.", "success");
      setSelected([]);
      setNotes("");
      await fetchRequests();
      onSubmitted?.();
    } catch (err) {
      setFormError(errorText(err, "Could not submit the request."));
    } finally {
      busy.current = false;
      setSaving(false);
    }
  };

  return (
    <ModalShell
      title="Request data cleaning"
      onClose={onClose}
      wide
      footer={
        <>
          <button type="button" className="ops-btn ops-btn--ghost" onClick={onClose} disabled={saving}>
            Close
          </button>
          <button type="submit" form="ops-cleaning-form" className="ops-btn ops-btn--primary" disabled={saving || surveysLoading || surveys.length === 0}>
            {saving ? "Submitting…" : "Submit request"}
          </button>
        </>
      }
    >
      <form id="ops-cleaning-form" className="ops-form" onSubmit={submit} noValidate>
        {formError && <p className="ops-form__error" role="alert">{formError}</p>}

        {surveysLoading && <StateMessage kind="loading" title="Loading surveys…" />}
        {surveysError && <StateMessage kind="error" title="Could not load surveys" message={surveysError} onRetry={fetchSurveys} />}
        {!surveysLoading && !surveysError && surveys.length === 0 && (
          <StateMessage kind="empty" title="No surveys in this project" message="Create a survey before requesting cleaning." />
        )}

        {!surveysLoading && !surveysError && surveys.length > 0 && (
          <fieldset className="ops-fieldset" aria-describedby="ops-clean-survey-hint">
            <legend>Surveys to clean</legend>
            <p id="ops-clean-survey-hint" className="ops-field__hint">Tick every survey the cleaning should cover.</p>
            <div className="ops-check-list">
              {surveys.map((s) => {
                const id = surveyKey(s);
                return (
                  <label key={id} className="ops-check">
                    <input type="checkbox" checked={selected.includes(id)} onChange={() => toggle(id)} />
                    {s.surveyName || id} {s.surveyNo ? `(${s.surveyNo})` : ""}
                  </label>
                );
              })}
            </div>
            {fieldError && <span className="ops-field__error">{fieldError}</span>}
          </fieldset>
        )}

        <div className="ops-field">
          <label htmlFor="ops-clean-notes">Notes for the cleaning team</label>
          <textarea
            id="ops-clean-notes"
            className="ops-input ops-textarea"
            value={notes}
            onChange={(e) => setNotes(e.target.value)}
            placeholder="What should be checked or removed, and why"
          />
        </div>
      </form>

      <section className="ops-section" aria-labelledby="ops-clean-history-title">
        <div className="ops-section__head">
          <h3 id="ops-clean-history-title" className="ops-section__title">Previous requests</h3>
        </div>
        {requestsLoading && <StateMessage kind="loading" title="Loading requests…" />}
        {requestsError && <StateMessage kind="error" title="Could not load requests" message={requestsError} onRetry={fetchRequests} />}
        {!requestsLoading && !requestsError && requests.length === 0 && (
          <StateMessage kind="empty" title="No cleaning requests yet" message="Submitted requests appear here." />
        )}
        {!requestsError && requests.length > 0 && (
          <ul className="ops-request-list">
            {requests.map((r) => (
              <CleaningRequestRow
                key={r.id}
                request={r}
                surveyNames={surveyNames}
                onChanged={fetchRequests}
              />
            ))}
          </ul>
        )}
      </section>
    </ModalShell>
  );
}
