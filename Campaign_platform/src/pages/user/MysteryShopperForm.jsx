/**
 * Public mystery shopping form — accessible via /mystery-shopper/:auditId
 * No admin auth required. One-question-at-a-time wizard flow.
 */

import { useState, useEffect, useCallback } from "react";
import { useParams } from "react-router-dom";
import {
  QUESTIONNAIRE,
  scoreFromResponse,
  calcOverall,
  ratingMeta,
  initResponses,
} from "../operations/MysteryShoppingTab";

const API_BASE = (() => {
  if (typeof window !== "undefined" && window.location.hostname === "localhost")
    return "http://localhost:8000";
  return "";
})();

async function fetchAudit(id) {
  const res = await fetch(`${API_BASE}/api/mystery-shopping/public/${id}`);
  if (!res.ok) throw new Error("Audit not found");
  return res.json();
}

async function saveAudit(id, payload) {
  const res = await fetch(`${API_BASE}/api/mystery-shopping/public/${id}/submit`, {
    method: "PUT",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(payload),
  });
  if (!res.ok) throw new Error("Save failed");
  return res.json();
}

// ─── Build flat list of all questions with section context ────────────────────
function buildQuestions() {
  const out = [];
  for (const section of [...QUESTIONNAIRE.partA, ...QUESTIONNAIRE.partB]) {
    const part = section.id.startsWith("a") ? "A" : "B";
    for (const param of section.params) {
      out.push({ ...param, section, part });
    }
  }
  return out;
}
const ALL_QUESTIONS = buildQuestions();
// Steps: 0 = Visit Details, 1…N = questions, N+1 = Observations
const TOTAL_STEPS = 1 + ALL_QUESTIONS.length + 1;

// ─── Empty visit details ──────────────────────────────────────────────────────
const EMPTY_VD = {
  branch_name: "", branch_code: "", branch_address: "",
  city_state: "", region_zone: "", date_of_visit: "",
  time_in: "", time_out: "",
  shopper_name: "", shopper_id: "",
  type_of_visit: "Branch Banking / Loan Services / Both",
  scenario_used: "", staff_interacted: "", contact_collected: "",
};

// ─── Sub-components ───────────────────────────────────────────────────────────

function Toast({ text, type }) {
  return (
    <div style={{
      position: "fixed", top: 18, left: "50%", transform: "translateX(-50%)",
      background: type === "ok" ? "#16a34a" : "#dc2626",
      color: "#fff", padding: "0.75rem 1.5rem", borderRadius: 10,
      fontWeight: 700, fontSize: "1rem", zIndex: 9999,
      boxShadow: "0 4px 16px rgba(0,0,0,0.18)",
    }}>
      {text}
    </div>
  );
}

function VisitDetailsStep({ vd, onChange, readOnly }) {
  const f = (key) => (e) => onChange((p) => ({ ...p, [key]: e.target.value }));
  const inputStyle = {
    width: "100%", boxSizing: "border-box",
    padding: "0.65rem 0.85rem",
    border: "1.5px solid #d1d5db", borderRadius: 8,
    fontSize: "1rem", fontFamily: "inherit", color: "#111827",
    background: readOnly ? "#f9fafb" : "#fff",
    outline: "none",
  };
  const labelStyle = {
    display: "block", fontSize: "0.88rem", fontWeight: 700,
    color: "#374151", marginBottom: "0.3rem",
  };
  const Row = ({ children }) => (
    <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: "1rem" }}>
      {children}
    </div>
  );
  const Field = ({ label, k, type = "text", placeholder }) => (
    <div>
      <label style={labelStyle}>{label}</label>
      <input
        type={type}
        disabled={readOnly}
        value={vd[k] || ""}
        onChange={f(k)}
        placeholder={placeholder}
        style={inputStyle}
      />
    </div>
  );

  return (
    <div>
      <h2 style={{ margin: "0 0 1.5rem", fontSize: "1.3rem", color: "#1a1a2e", fontWeight: 800 }}>
        Visit Details
      </h2>
      <div style={{ display: "flex", flexDirection: "column", gap: "1rem" }}>
        <Row>
          <Field label="Branch Name *" k="branch_name" placeholder="e.g. IDFC FIRST Bank – Connaught Place" />
          <Field label="Branch Code" k="branch_code" placeholder="e.g. DEL-042" />
        </Row>
        <Row>
          <Field label="Branch Address" k="branch_address" placeholder="Street address" />
          <Field label="City / State" k="city_state" placeholder="e.g. New Delhi, Delhi" />
        </Row>
        <Row>
          <Field label="Region / Zone" k="region_zone" placeholder="e.g. North Zone" />
          <Field label="Date of Visit" k="date_of_visit" type="date" />
        </Row>
        <Row>
          <Field label="Time In" k="time_in" type="time" />
          <Field label="Time Out" k="time_out" type="time" />
        </Row>
        <Row>
          <Field label="Mystery Shopper Name" k="shopper_name" placeholder="Full name" />
          <Field label="Shopper ID" k="shopper_id" placeholder="e.g. SH-2024-007" />
        </Row>
        <div>
          <label style={labelStyle}>Type of Visit</label>
          <div style={{ display: "flex", gap: "0.5rem", flexWrap: "wrap" }}>
            {["Branch Banking", "Loan Services", "Both"].map((opt) => {
              const sel = vd.type_of_visit === opt;
              return (
                <button
                  key={opt}
                  disabled={readOnly}
                  onClick={() => !readOnly && onChange((p) => ({ ...p, type_of_visit: opt }))}
                  style={{
                    padding: "0.6rem 1.1rem", borderRadius: 8,
                    border: `2px solid ${sel ? "#7c3aed" : "#d1d5db"}`,
                    background: sel ? "#f5f3ff" : "#fff",
                    color: sel ? "#7c3aed" : "#6b7280",
                    fontWeight: sel ? 700 : 500,
                    fontSize: "0.95rem", cursor: readOnly ? "default" : "pointer",
                  }}
                >
                  {opt}
                </button>
              );
            })}
          </div>
        </div>
        <Row>
          <Field label="Scenario Used" k="scenario_used" placeholder="Scenario description" />
          <Field label="Staff Interacted With (Name / Desk)" k="staff_interacted" placeholder="e.g. Rahul – Teller 2" />
        </Row>
        <div style={{ maxWidth: "50%" }}>
          <Field label="Contact No. Collected" k="contact_collected" placeholder="Yes / No / NA" />
        </div>
      </div>
    </div>
  );
}

function QuestionStep({ q, responses, onChange, readOnly, questionNumber, totalQuestions }) {
  const r = responses?.[q.id] || { response: "", remarks: "" };
  const sc = r.response && r.response !== "N/A" ? scoreFromResponse(r.response) : null;

  const OPTIONS = [
    { opt: "Yes",     bg: "#dcfce7", bc: "#16a34a", tc: "#14532d", score: 5 },
    { opt: "Partial", bg: "#fef3c7", bc: "#f59e0b", tc: "#78350f", score: 3 },
    { opt: "No",      bg: "#fee2e2", bc: "#dc2626", tc: "#7f1d1d", score: 0 },
    { opt: "N/A",     bg: "#f1f5f9", bc: "#94a3b8", tc: "#475569", score: null },
  ];

  return (
    <div>
      {/* Section label */}
      <div style={{ marginBottom: "0.85rem" }}>
        <span style={{
          display: "inline-block",
          background: q.part === "A" ? "#eff6ff" : "#f5f3ff",
          color: q.part === "A" ? "#1d4ed8" : "#7c3aed",
          border: `1px solid ${q.part === "A" ? "#bfdbfe" : "#ddd6fe"}`,
          borderRadius: 20, padding: "0.25rem 0.85rem",
          fontSize: "0.85rem", fontWeight: 700,
        }}>
          {q.part === "A" ? "Part A — Branch Banking" : "Part B — Loan Services"}
        </span>
        <span style={{ marginLeft: "0.75rem", color: "#6b7280", fontSize: "0.88rem", fontWeight: 600 }}>
          {q.section.title}
        </span>
      </div>

      {/* Question text */}
      <p style={{
        fontSize: "1.2rem", fontWeight: 700, color: "#111827",
        lineHeight: 1.55, margin: "0 0 1.75rem",
      }}>
        {q.text}
      </p>

      {/* Response buttons */}
      <div style={{ display: "flex", flexDirection: "column", gap: "0.65rem", marginBottom: "1.5rem" }}>
        {OPTIONS.map(({ opt, bg, bc, tc, score }) => {
          const selected = r.response === opt;
          return (
            <button
              key={opt}
              disabled={readOnly}
              onClick={() => !readOnly && onChange(q.id, { ...r, response: opt })}
              style={{
                display: "flex", alignItems: "center", justifyContent: "space-between",
                padding: "0.9rem 1.25rem",
                borderRadius: 10,
                border: `2px solid ${selected ? bc : "#e5e7eb"}`,
                background: selected ? bg : "#fafafa",
                color: selected ? tc : "#374151",
                fontWeight: selected ? 700 : 500,
                fontSize: "1.05rem",
                cursor: readOnly ? "default" : "pointer",
                textAlign: "left",
                transition: "all 0.12s",
                boxShadow: selected ? `0 0 0 3px ${bc}33` : "none",
              }}
            >
              <span>{opt}</span>
              <span style={{ fontSize: "0.9rem", opacity: 0.75 }}>
                {score !== null ? `${score} pts` : "excluded"}
              </span>
            </button>
          );
        })}
      </div>

      {/* Remarks */}
      <div>
        <label style={{ display: "block", fontSize: "0.95rem", fontWeight: 600, color: "#374151", marginBottom: "0.4rem" }}>
          Remarks / Observation
          <span style={{ fontWeight: 400, color: "#9ca3af", marginLeft: 8 }}>
            (what was seen / said, staff name, time)
          </span>
        </label>
        <textarea
          rows={3}
          disabled={readOnly}
          placeholder="Record specific, factual evidence here…"
          value={r.remarks || ""}
          onChange={(e) => !readOnly && onChange(q.id, { ...r, remarks: e.target.value })}
          style={{
            width: "100%", boxSizing: "border-box",
            padding: "0.65rem 0.85rem",
            border: "1.5px solid #d1d5db", borderRadius: 8,
            fontSize: "1rem", fontFamily: "inherit", color: "#374151",
            resize: "vertical",
            background: readOnly ? "#f9fafb" : "#fff",
          }}
        />
      </div>

      {/* Score indicator */}
      {sc !== null && (
        <div style={{ marginTop: "0.75rem", display: "flex", alignItems: "center", gap: "0.5rem" }}>
          <span style={{ fontSize: "0.9rem", color: "#6b7280" }}>Score for this parameter:</span>
          <span style={{ fontWeight: 800, fontSize: "1.05rem", color: "#7c3aed" }}>{sc} / 5</span>
        </div>
      )}
    </div>
  );
}

function ObservationsStep({ observations, onChange, readOnly }) {
  const f = (key) => (e) => onChange((p) => ({ ...p, [key]: e.target.value }));
  const areas = [
    { key: "strengths", label: "Key strengths noted during the visit:" },
    { key: "improvements", label: "Areas needing improvement / non-compliances:" },
    { key: "recommendations", label: "Specific recommendations:" },
  ];
  return (
    <div>
      <h2 style={{ margin: "0 0 1.5rem", fontSize: "1.3rem", color: "#1a1a2e", fontWeight: 800 }}>
        Overall Observations &amp; Recommendations
      </h2>
      <div style={{ display: "flex", flexDirection: "column", gap: "1.25rem" }}>
        {areas.map(({ key, label }) => (
          <div key={key}>
            <label style={{ display: "block", fontSize: "1rem", fontWeight: 700, color: "#374151", marginBottom: "0.4rem" }}>
              {label}
            </label>
            <textarea
              rows={4}
              disabled={readOnly}
              value={observations[key] || ""}
              onChange={f(key)}
              style={{
                width: "100%", boxSizing: "border-box",
                padding: "0.65rem 0.85rem",
                border: "1.5px solid #d1d5db", borderRadius: 8,
                fontSize: "1rem", fontFamily: "inherit", color: "#374151",
                resize: "vertical",
                background: readOnly ? "#f9fafb" : "#fff",
              }}
            />
          </div>
        ))}
      </div>
    </div>
  );
}

// ─── Main component ───────────────────────────────────────────────────────────
export default function MysteryShopperForm() {
  const { auditId } = useParams();
  const [audit, setAudit] = useState(null);
  const [loading, setLoading] = useState(true);
  const [notFound, setNotFound] = useState(false);
  const [step, setStep] = useState(0);
  const [visitDetails, setVisitDetails] = useState(EMPTY_VD);
  const [responses, setResponses] = useState(initResponses());
  const [observations, setObservations] = useState({ strengths: "", improvements: "", recommendations: "" });
  const [saving, setSaving] = useState(false);
  const [submitted, setSubmitted] = useState(false);
  const [toast, setToast] = useState(null);

  const showToast = useCallback((text, type = "ok") => {
    setToast({ text, type });
    setTimeout(() => setToast(null), 3500);
  }, []);

  useEffect(() => {
    fetchAudit(auditId)
      .then((data) => {
        setAudit(data);
        if (data.visit_details) {
          // Merge stored visit_details with defaults, normalising legacy field names
          const vd = data.visit_details;
          setVisitDetails((p) => ({
            ...p,
            ...vd,
            // Legacy field name mappings from creation form
            city_state: vd.city_state || vd.city || "",
            date_of_visit: vd.date_of_visit || vd.visit_date || "",
          }));
        }
        if (data.responses) setResponses(data.responses);
        if (data.observations) setObservations(data.observations);
        if (data.status === "submitted") setSubmitted(true);
      })
      .catch(() => setNotFound(true))
      .finally(() => setLoading(false));
  }, [auditId]);

  const updateResponse = useCallback(
    (id, val) => setResponses((p) => ({ ...p, [id]: val })),
    []
  );

  const buildPayload = (status) => ({
    visit_details: visitDetails,
    responses,
    observations,
    status,
  });

  const saveDraft = async () => {
    setSaving(true);
    try {
      await saveAudit(auditId, buildPayload("draft"));
      showToast("Progress saved.", "ok");
    } catch {
      showToast("Save failed — please try again.", "err");
    }
    setSaving(false);
  };

  const finalSubmit = async () => {
    setSaving(true);
    try {
      await saveAudit(auditId, buildPayload("submitted"));
      setSubmitted(true);
    } catch {
      showToast("Submission failed — please try again.", "err");
    }
    setSaving(false);
  };

  // ── Loading / error ────────────────────────────────────────────────────────
  if (loading) {
    return (
      <div style={S.page}>
        <div style={S.card}>
          <p style={{ color: "#6b7280", textAlign: "center", padding: "3rem", fontSize: "1.05rem" }}>
            Loading questionnaire…
          </p>
        </div>
      </div>
    );
  }

  if (notFound) {
    return (
      <div style={S.page}>
        <div style={S.card}>
          <p style={{ color: "#dc2626", textAlign: "center", padding: "3rem", fontWeight: 700, fontSize: "1.05rem" }}>
            Audit not found. Please check the link and try again.
          </p>
        </div>
      </div>
    );
  }

  // ── Submitted ──────────────────────────────────────────────────────────────
  const { total, totalMax, pct } = calcOverall(responses);
  const { label: ratingLabel, color: ratingColor } = ratingMeta(pct);

  if (submitted && !saving) {
    return (
      <div style={S.page}>
        <div style={S.card}>
          <div style={{ textAlign: "center", padding: "3rem 1.5rem" }}>
            <div style={{ fontSize: "4rem", marginBottom: "1rem" }}>✅</div>
            <h2 style={{ margin: "0 0 0.5rem", color: "#16a34a", fontSize: "1.5rem", fontWeight: 800 }}>
              Audit Submitted
            </h2>
            <p style={{ color: "#6b7280", fontSize: "1rem", margin: "0 0 1.5rem" }}>
              Your mystery shopping responses for{" "}
              <strong>{visitDetails.branch_name || "this branch"}</strong> have been recorded.
            </p>
            {pct !== null && (
              <div style={{
                display: "inline-block",
                background: "#f5f3ff", border: "2px solid #ddd6fe",
                borderRadius: 12, padding: "1rem 2rem",
              }}>
                <div style={{ fontSize: "2.5rem", fontWeight: 900, color: ratingColor }}>{pct}%</div>
                <div style={{ fontSize: "1.1rem", fontWeight: 700, color: "#374151" }}>
                  {total} / {totalMax} pts — {ratingLabel}
                </div>
              </div>
            )}
          </div>
        </div>
      </div>
    );
  }

  // ── Wizard steps ───────────────────────────────────────────────────────────
  const isVisitDetails = step === 0;
  const isObservations = step === TOTAL_STEPS - 1;
  const questionIdx = (!isVisitDetails && !isObservations) ? step - 1 : null;
  const currentQ = questionIdx !== null ? ALL_QUESTIONS[questionIdx] : null;
  const readOnly = submitted;
  const progressPct = Math.round((step / (TOTAL_STEPS - 1)) * 100);

  const stepLabel = isVisitDetails
    ? "Visit Details"
    : isObservations
    ? "Observations"
    : `Question ${questionIdx + 1} of ${ALL_QUESTIONS.length}`;

  return (
    <div style={S.page}>
      {toast && <Toast {...toast} />}

      {/* Sticky header */}
      <div style={S.header}>
        <div style={S.headerSub}>IDFC FIRST Bank · Mystery Shopping Audit</div>
        <div style={S.headerTitle}>{visitDetails.branch_name || "Branch Audit"}</div>
        {/* Progress bar */}
        <div style={S.progTrack}>
          <div style={{ ...S.progFill, width: `${progressPct}%` }} />
        </div>
        <div style={S.progLabel}>{stepLabel} · {progressPct}% complete</div>
      </div>

      <div style={S.card}>
        <div style={S.cardBody}>
          {isVisitDetails && (
            <VisitDetailsStep vd={visitDetails} onChange={setVisitDetails} readOnly={readOnly} />
          )}
          {currentQ && (
            <QuestionStep
              q={currentQ}
              responses={responses}
              onChange={updateResponse}
              readOnly={readOnly}
              questionNumber={questionIdx + 1}
              totalQuestions={ALL_QUESTIONS.length}
            />
          )}
          {isObservations && (
            <ObservationsStep observations={observations} onChange={setObservations} readOnly={readOnly} />
          )}
        </div>

        {/* Navigation row */}
        <div style={S.nav}>
          <button
            style={{ ...S.btnSecondary, visibility: step > 0 ? "visible" : "hidden" }}
            onClick={() => setStep((s) => s - 1)}
          >
            ← Back
          </button>
          <button style={S.btnGhost} onClick={saveDraft} disabled={saving || readOnly}>
            {saving ? "Saving…" : "Save Draft"}
          </button>
          {!isObservations ? (
            <button style={S.btnPrimary} onClick={() => setStep((s) => s + 1)}>
              Next →
            </button>
          ) : (
            <button style={S.btnSubmit} onClick={finalSubmit} disabled={saving || readOnly}>
              {saving ? "Submitting…" : "Submit Audit ✓"}
            </button>
          )}
        </div>
      </div>
    </div>
  );
}

// ─── Styles ───────────────────────────────────────────────────────────────────
const S = {
  page: {
    minHeight: "100vh",
    background: "#f1f5f9",
    paddingBottom: "4rem",
    fontFamily: "-apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif",
    WebkitFontSmoothing: "antialiased",
  },
  header: {
    background: "#1a1a2e",
    color: "#fff",
    padding: "1.25rem 1.25rem 0.9rem",
    position: "sticky", top: 0, zIndex: 10,
  },
  headerSub: {
    fontSize: "0.78rem", fontWeight: 700, textTransform: "uppercase",
    letterSpacing: "0.08em", color: "#a5b4fc", marginBottom: "0.25rem",
  },
  headerTitle: {
    fontSize: "1.2rem", fontWeight: 800, marginBottom: "0.75rem",
  },
  progTrack: {
    height: 6, background: "#374151", borderRadius: 3,
    overflow: "hidden", marginBottom: "0.4rem",
  },
  progFill: {
    height: "100%", background: "#818cf8", borderRadius: 3,
    transition: "width 0.3s ease",
  },
  progLabel: {
    fontSize: "0.82rem", color: "#94a3b8", paddingBottom: "0.1rem",
  },
  card: {
    maxWidth: 680,
    margin: "1.5rem auto 0",
    background: "#fff",
    borderRadius: 12,
    boxShadow: "0 4px 24px rgba(0,0,0,0.09)",
    overflow: "hidden",
  },
  cardBody: {
    padding: "1.75rem 1.5rem 1.25rem",
  },
  nav: {
    display: "flex", alignItems: "center", gap: "0.75rem",
    padding: "1rem 1.5rem",
    borderTop: "1.5px solid #e5e7eb",
    background: "#f9fafb",
  },
  btnPrimary: {
    background: "#7c3aed", color: "#fff",
    border: "none", borderRadius: 8,
    padding: "0.7rem 1.5rem",
    fontSize: "1rem", fontWeight: 700, cursor: "pointer",
  },
  btnSubmit: {
    background: "#16a34a", color: "#fff",
    border: "none", borderRadius: 8,
    padding: "0.7rem 1.5rem",
    fontSize: "1rem", fontWeight: 700, cursor: "pointer",
  },
  btnSecondary: {
    background: "#fff", color: "#374151",
    border: "1.5px solid #d1d5db", borderRadius: 8,
    padding: "0.7rem 1.25rem",
    fontSize: "1rem", fontWeight: 600, cursor: "pointer",
  },
  btnGhost: {
    background: "transparent", color: "#7c3aed",
    border: "1.5px solid #ddd6fe", borderRadius: 8,
    padding: "0.65rem 1rem",
    fontSize: "0.95rem", fontWeight: 600, cursor: "pointer",
    marginLeft: "auto",
    marginRight: "0.25rem",
  },
};
