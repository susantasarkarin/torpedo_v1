import { useCallback, useEffect, useId, useRef, useState } from "react";
import {
  listAllProjectSurveys,
  listReconciliations,
  createReconciliation,
  getReconciliation,
  saveBlob,
  unwrapList,
  OpsApiError,
} from "../../../services/opsProjectsService";
import { notify as notifyToast } from "../../../utils/notify";
import { ModalShell, StateMessage } from "./opsShared";
import { fmtInt, fmtDateTime } from "./opsUtils";

const HEADER_TOKENS = new Set(["id", "ids", "respondent_id", "respondentid", "respondent id", "response_id", "uid", "rid"]);

// One ID per line, or the first column of a CSV. Blank lines, a leading header
// and duplicates are dropped. Order is kept.
function parseIdList(text) {
  const seen = new Set();
  const ids = [];
  let firstLine = true;
  String(text || "")
    .split(/\r?\n/)
    .forEach((line) => {
      const cell = line
        .split(",")[0]
        .replace(/^\uFEFF/, "")
        .trim()
        .replace(/^["']|["']$/g, "")
        .trim();
      if (!cell) return;
      const isHeader = firstLine && HEADER_TOKENS.has(cell.toLowerCase());
      firstLine = false;
      if (isHeader || seen.has(cell)) return;
      seen.add(cell);
      ids.push(cell);
    });
  return ids;
}

const COUNT_LABELS = [
  ["ourCompletes", "Our completes"],
  ["accepted", "Accepted by client"],
  ["rejected", "Rejected by client"],
  ["acceptedMatched", "Accepted and matched"],
  ["acceptedNotFound", "Accepted, not found with us"],
  ["acceptedNotComplete", "Accepted, not a complete with us"],
  ["completesNotInClientFile", "Our completes not in client file"],
];

const errorText = (e, fallback) => (e instanceof OpsApiError ? e.message : fallback);
const surveyKey = (s) => String(s.id ?? s._id ?? "");

// Paste box plus a file upload for one ID list.
function IdInput({ id, label, value, onChange, count, disabled }) {
  const hintId = useId();
  const onFile = async (e) => {
    const file = e.target.files?.[0];
    e.target.value = "";
    if (!file) return;
    try {
      onChange(await file.text());
    } catch {
      notifyToast("Could not read that file. Try a .csv or .txt file.", "error");
    }
  };
  return (
    <div className="ops-field">
      <label htmlFor={id}>{label}</label>
      <textarea
        id={id}
        className="ops-input ops-textarea"
        value={value}
        disabled={disabled}
        onChange={(e) => onChange(e.target.value)}
        placeholder="One respondent ID per line, or the first column of a CSV"
        aria-describedby={hintId}
        spellCheck={false}
      />
      <div className="ops-field-row">
        <input
          type="file"
          accept=".csv,.txt,text/csv,text/plain"
          onChange={onFile}
          disabled={disabled}
          aria-label={`Upload ${label.toLowerCase()} file (.csv or .txt)`}
        />
      </div>
      <span id={hintId} className="ops-field__hint">{count} ID{count === 1 ? "" : "s"} parsed</span>
    </div>
  );
}

function ResultView({ result, onBack, onDownloadUnmatched }) {
  const counts = result?.counts || {};
  const suppliers = Array.isArray(result?.bySupplier) ? result.bySupplier : [];
  const unmatched = Array.isArray(result?.unmatchedIds) ? result.unmatchedIds : [];
  return (
    <div className="ops-form">
      <div className="ops-section__head">
        <div>
          <h3 className="ops-section__title">
            Result for {result?.surveyNo ? `${result.surveyNo} ` : ""}{result?.surveyName || ""}
          </h3>
          <p className="ops-field__hint">
            Run {fmtDateTime(result?.createdAt)} by {result?.createdBy || "—"}
            {result?.note ? `. Note: ${result.note}` : ""}
          </p>
        </div>
        <button type="button" className="ops-btn ops-btn--ghost ops-btn--sm" onClick={onBack}>
          Back
        </button>
      </div>

      {result?.unmatchedIdsTruncated && (
        <p className="ops-notice" role="note">
          Only the first 5,000 unmatched IDs were stored, so the download below is partial.
        </p>
      )}

      <dl className="ops-kpis">
        {COUNT_LABELS.map(([key, label]) => (
          <div key={key} className="ops-kpi">
            <dt>{label}</dt>
            <dd>{counts[key] === undefined || counts[key] === null ? "—" : fmtInt(counts[key])}</dd>
          </div>
        ))}
      </dl>

      <div className="ops-table-wrap">
        <table className="ops-table">
          <caption className="ops-visually-hidden">Reconciliation by supplier</caption>
          <thead>
            <tr>
              <th scope="col" className="ops-th">Supplier</th>
              <th scope="col" className="ops-th ops-th--right">Our completes</th>
              <th scope="col" className="ops-th ops-th--right">Reconciled completes</th>
              <th scope="col" className="ops-th ops-th--right">Rejected</th>
            </tr>
          </thead>
          <tbody>
            {suppliers.length === 0 && (
              <tr>
                <td className="ops-td" colSpan={4}>No supplier breakdown returned.</td>
              </tr>
            )}
            {suppliers.map((s, i) => (
              <tr key={s.vendorId || i}>
                <td className="ops-td">{s.vendorName || s.vendorId || "—"}</td>
                <td className="ops-td ops-td--num">{fmtInt(s.ourCompletes) ?? "—"}</td>
                <td className="ops-td ops-td--num">{fmtInt(s.reconciledCompletes) ?? "—"}</td>
                <td className="ops-td ops-td--num">{fmtInt(s.rejected) ?? "—"}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>

      <div className="ops-section__head">
        <p className="ops-field__hint">{unmatched.length.toLocaleString()} accepted ID{unmatched.length === 1 ? "" : "s"} did not match a respondent with us.</p>
        <button type="button" className="ops-btn ops-btn--ghost ops-btn--sm" onClick={() => onDownloadUnmatched(unmatched)} disabled={unmatched.length === 0}>
          Download unmatched IDs (.txt)
        </button>
      </div>
    </div>
  );
}

export default function ReconciliationModal({ projectId, onClose, onRecorded }) {
  const [view, setView] = useState("form"); // "form" | "result"
  const [result, setResult] = useState(null);
  const [openingId, setOpeningId] = useState(null);

  const [surveys, setSurveys] = useState([]);
  const [surveysLoading, setSurveysLoading] = useState(true);
  const [surveysError, setSurveysError] = useState(null);

  const [pastRuns, setPastRuns] = useState([]);
  const [pastLoading, setPastLoading] = useState(true);
  const [pastError, setPastError] = useState(null);

  const [surveyId, setSurveyId] = useState("");
  const [acceptedText, setAcceptedText] = useState("");
  const [rejectedText, setRejectedText] = useState("");
  const [note, setNote] = useState("");
  const [errors, setErrors] = useState({});
  const [formError, setFormError] = useState(null);
  const [saving, setSaving] = useState(false);
  const busy = useRef(false);

  const acceptedIds = parseIdList(acceptedText);
  const rejectedIds = parseIdList(rejectedText);

  const loadPast = useCallback(async () => {
    setPastLoading(true);
    setPastError(null);
    try {
      setPastRuns(unwrapList(await listReconciliations(projectId), "items", "reconciliations"));
    } catch (e) {
      setPastError(errorText(e, "Could not load past reconciliations."));
    } finally {
      setPastLoading(false);
    }
  }, [projectId]);

  const loadSurveys = useCallback(async () => {
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
    loadSurveys();
    loadPast();
  }, [loadSurveys, loadPast]);

  const validate = () => {
    const next = {};
    if (!surveyId) next.surveyId = "Pick the survey this client file belongs to.";
    if (acceptedIds.length === 0) next.accepted = "Add at least one accepted respondent ID.";
    const rejectedSet = new Set(rejectedIds);
    const overlap = acceptedIds.filter((id) => rejectedSet.has(id)).length;
    if (overlap > 0) next.rejected = `${overlap} ID${overlap === 1 ? " is" : "s are"} in both lists. Each ID can only be accepted or rejected.`;
    setErrors(next);
    return Object.keys(next).length === 0;
  };

  // Full runs carry surveyNo but not the name; take the name from the survey list.
  const surveyNameOf = (run) => {
    const s = surveys.find((x) => surveyKey(x) === String(run.surveyId));
    return run.surveyName || s?.surveyName || "";
  };

  const showRun = (run) => {
    setResult({ ...run, surveyName: surveyNameOf(run) });
    setView("result");
  };

  const submit = async (e) => {
    e.preventDefault();
    if (busy.current) return;
    setFormError(null);
    if (!validate()) return;
    busy.current = true;
    setSaving(true);
    try {
      const res = await createReconciliation(projectId, {
        surveyId,
        acceptedIds,
        rejectedIds,
        note: note.trim(),
      });
      let run = res;
      if (!res?.counts && res?.id) {
        try {
          run = await getReconciliation(res.id);
        } catch {
          run = res;
        }
      }
      notifyToast("Reconciliation recorded. Respondent statuses were not changed.", "success");
      showRun(run);
      loadPast();
      onRecorded?.();
    } catch (err) {
      setFormError(errorText(err, "Could not run the reconciliation."));
    } finally {
      busy.current = false;
      setSaving(false);
    }
  };

  const openPast = async (run) => {
    if (openingId) return;
    setOpeningId(run.id);
    try {
      showRun(await getReconciliation(run.id));
    } catch (e) {
      notifyToast(errorText(e, "Could not open that reconciliation."), "error");
    } finally {
      setOpeningId(null);
    }
  };

  const downloadUnmatched = (ids) => {
    const name = `unmatched-${result?.surveyNo || result?.surveyId || "survey"}.txt`;
    saveBlob(new Blob([ids.join("\n") + "\n"], { type: "text/plain" }), name);
  };

  const title = view === "result" ? "Reconciliation result" : "Reconciliation";

  return (
    <ModalShell
      title={title}
      onClose={onClose}
      wide
      footer={
        view === "form" ? (
          <>
            <button type="button" className="ops-btn ops-btn--ghost" onClick={onClose} disabled={saving}>
              Close
            </button>
            <button type="submit" form="ops-recon-form" className="ops-btn ops-btn--primary" disabled={saving || surveysLoading || surveys.length === 0}>
              {saving ? "Running…" : "Run reconciliation"}
            </button>
          </>
        ) : (
          <button type="button" className="ops-btn ops-btn--ghost" onClick={onClose}>
            Close
          </button>
        )
      }
    >
      {view === "result" ? (
        <ResultView result={result} onBack={() => setView("form")} onDownloadUnmatched={downloadUnmatched} />
      ) : (
        <>
          <form id="ops-recon-form" className="ops-form" onSubmit={submit} noValidate>
            {formError && <p className="ops-form__error" role="alert">{formError}</p>}
            <p className="ops-notice" role="note">
              Reconciliation records the comparison between the client file and our completes. It does not change any respondent's status.
            </p>

            {surveysLoading && <StateMessage kind="loading" title="Loading surveys…" />}
            {surveysError && <StateMessage kind="error" title="Could not load surveys" message={surveysError} onRetry={loadSurveys} />}
            {!surveysLoading && !surveysError && surveys.length === 0 && (
              <StateMessage kind="empty" title="No surveys in this project" message="Create a survey before reconciling." />
            )}

            {!surveysLoading && !surveysError && surveys.length > 0 && (
              <>
                <div className="ops-field">
                  <label htmlFor="ops-recon-survey">Survey</label>
                  <select
                    id="ops-recon-survey"
                    className={`ops-input ${errors.surveyId ? "ops-input--error" : ""}`}
                    value={surveyId}
                    onChange={(e) => {
                      setSurveyId(e.target.value);
                      setErrors((er) => ({ ...er, surveyId: undefined }));
                    }}
                    aria-invalid={Boolean(errors.surveyId)}
                    aria-describedby={errors.surveyId ? "ops-recon-survey-err" : undefined}
                  >
                    <option value="">Choose a survey</option>
                    {surveys.map((s) => (
                      <option key={surveyKey(s)} value={surveyKey(s)}>
                        {s.surveyName || surveyKey(s)} {s.surveyNo ? `(${s.surveyNo})` : ""}
                      </option>
                    ))}
                  </select>
                  {errors.surveyId && <span id="ops-recon-survey-err" className="ops-field__error">{errors.surveyId}</span>}
                </div>

                <IdInput
                  id="ops-recon-accepted"
                  label="Accepted respondent IDs"
                  value={acceptedText}
                  onChange={(v) => {
                    setAcceptedText(v);
                    setErrors((er) => ({ ...er, accepted: undefined }));
                  }}
                  count={acceptedIds.length}
                  disabled={saving}
                />
                {errors.accepted && <span className="ops-field__error">{errors.accepted}</span>}

                <IdInput
                  id="ops-recon-rejected"
                  label="Rejected respondent IDs (optional)"
                  value={rejectedText}
                  onChange={(v) => {
                    setRejectedText(v);
                    setErrors((er) => ({ ...er, rejected: undefined }));
                  }}
                  count={rejectedIds.length}
                  disabled={saving}
                />
                {errors.rejected && <span className="ops-field__error">{errors.rejected}</span>}

                <div className="ops-field">
                  <label htmlFor="ops-recon-note">Note (optional)</label>
                  <input
                    id="ops-recon-note"
                    type="text"
                    className="ops-input"
                    value={note}
                    onChange={(e) => setNote(e.target.value)}
                    disabled={saving}
                    placeholder="For example: client file received 16 Nov"
                  />
                </div>
              </>
            )}
          </form>

          <section className="ops-section" aria-labelledby="ops-recon-past-title">
            <div className="ops-section__head">
              <h3 id="ops-recon-past-title" className="ops-section__title">Past reconciliations</h3>
            </div>
            {pastLoading && <StateMessage kind="loading" title="Loading past runs…" />}
            {pastError && <StateMessage kind="error" title="Could not load past runs" message={pastError} onRetry={loadPast} />}
            {!pastLoading && !pastError && pastRuns.length === 0 && (
              <StateMessage kind="empty" title="No reconciliations yet" message="Runs you record appear here." />
            )}
            {!pastError && pastRuns.length > 0 && (
              <ul className="ops-request-list">
                {pastRuns.map((run, i) => (
                  <li key={run.id || i} className="ops-request">
                    <div className="ops-request__head">
                      <span>{run.surveyNo ? `${run.surveyNo} ` : ""}{surveyNameOf(run) || run.surveyId || "Survey"}</span>
                      <button
                        type="button"
                        className="ops-btn ops-btn--ghost ops-btn--sm"
                        onClick={() => openPast(run)}
                        disabled={openingId !== null}
                      >
                        {openingId === run.id ? "Opening…" : "Open"}
                      </button>
                    </div>
                    <p className="ops-request__meta">
                      {fmtDateTime(run.createdAt)} by {run.createdBy || "—"}{run.note ? `. ${run.note}` : ""}
                    </p>
                  </li>
                ))}
              </ul>
            )}
          </section>
        </>
      )}
    </ModalShell>
  );
}
