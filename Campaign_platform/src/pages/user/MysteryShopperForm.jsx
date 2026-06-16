/**
 * Public mystery shopping form — accessible via /mystery-shopper/:auditId
 * No admin auth required. Used by field shoppers on their devices.
 */

import { useState, useEffect, useCallback } from "react";
import { useParams } from "react-router-dom";
import { Save, CheckCircle } from "lucide-react";
import { QUESTIONNAIRE, ALL_SECTIONS, scoreFromResponse, calcSectionScore, calcOverall, ratingMeta, initResponses } from "../operations/MysteryShoppingTab";

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

async function submitAudit(id, payload) {
  const res = await fetch(`${API_BASE}/api/mystery-shopping/public/${id}/submit`, {
    method: "PUT",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(payload),
  });
  if (!res.ok) throw new Error("Submission failed");
  return res.json();
}

// ─── Toast ────────────────────────────────────────────────────────────────────
function useToast() {
  const [msg, setMsg] = useState(null); // { text, type: "ok"|"err" }
  const show = useCallback((text, type = "ok") => {
    setMsg({ text, type });
    setTimeout(() => setMsg(null), 3500);
  }, []);
  return [msg, show];
}

// ─── Section block ────────────────────────────────────────────────────────────
function SectionBlock({ section, responses, onChange, readOnly }) {
  const { score, max } = calcSectionScore(section, responses);
  const displayMax = max === 0 ? section.maxPossible : max;

  return (
    <div style={{ border: "1.5px solid #e5e7eb", borderRadius: 10, overflow: "hidden", marginBottom: "1.25rem", background: "#fff" }}>
      <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", padding: "0.65rem 1rem", background: "#f5f3ff", borderBottom: "1.5px solid #e5e7eb" }}>
        <span style={{ fontWeight: 700, fontSize: "0.85rem", color: "#1a1a2e" }}>{section.title}</span>
        <span style={{ fontWeight: 700, fontSize: "0.8rem", color: "#7c3aed", background: "#ede9fe", padding: "2px 10px", borderRadius: 20 }}>
          {score} / {displayMax} pts
        </span>
      </div>

      {section.params.map((p, idx) => {
        const r = responses?.[p.id] || { response: "", remarks: "" };
        const sc = r.response && r.response !== "N/A" ? scoreFromResponse(r.response) : null;
        return (
          <div key={p.id} style={{ borderBottom: "1px solid #f3f4f6", padding: "0.85rem 1rem", background: r.response ? "#fafbff" : undefined }}>
            <div style={{ display: "flex", gap: "0.5rem", marginBottom: "0.5rem" }}>
              <span style={{ fontWeight: 700, color: "#9ca3af", fontSize: "0.75rem", minWidth: 20 }}>{idx + 1}</span>
              <span style={{ fontSize: "0.83rem", color: "#374151", lineHeight: 1.5 }}>{p.text}</span>
            </div>

            {/* Response options */}
            <div style={{ display: "flex", gap: "0.4rem", flexWrap: "wrap", paddingLeft: "1.5rem", marginBottom: "0.4rem" }}>
              {[
                { opt: "Yes",     bg: "#dcfce7", bc: "#16a34a", tc: "#14532d" },
                { opt: "Partial", bg: "#fef3c7", bc: "#f59e0b", tc: "#78350f" },
                { opt: "No",      bg: "#fee2e2", bc: "#dc2626", tc: "#7f1d1d" },
                { opt: "N/A",     bg: "#f1f5f9", bc: "#94a3b8", tc: "#475569" },
              ].map(({ opt, bg, bc, tc }) => (
                <button
                  key={opt}
                  disabled={readOnly}
                  onClick={() => !readOnly && onChange(p.id, { ...r, response: opt })}
                  style={{
                    padding: "0.3rem 0.75rem",
                    borderRadius: 6,
                    border: `1.5px solid ${r.response === opt ? bc : "#e5e7eb"}`,
                    background: r.response === opt ? bg : "#fff",
                    color: r.response === opt ? tc : "#6b7280",
                    fontWeight: r.response === opt ? 700 : 500,
                    fontSize: "0.78rem",
                    cursor: readOnly ? "default" : "pointer",
                    transition: "all 0.12s",
                  }}
                >
                  {opt}
                  {r.response === opt && sc !== null && <span style={{ marginLeft: 4, opacity: 0.8 }}>({sc})</span>}
                </button>
              ))}
            </div>

            {/* Remarks */}
            <div style={{ paddingLeft: "1.5rem" }}>
              <textarea
                rows={2}
                placeholder="Remarks — what was seen / said, staff name, time…"
                disabled={readOnly}
                value={r.remarks}
                onChange={(e) => !readOnly && onChange(p.id, { ...r, remarks: e.target.value })}
                style={{
                  width: "100%", boxSizing: "border-box",
                  padding: "0.35rem 0.55rem",
                  border: "1.5px solid #e5e7eb", borderRadius: 6,
                  fontSize: "0.78rem", fontFamily: "inherit",
                  color: "#374151", resize: "vertical",
                  background: readOnly ? "#f9fafb" : undefined,
                }}
              />
            </div>
          </div>
        );
      })}
    </div>
  );
}

// ─── Main public form ─────────────────────────────────────────────────────────
export default function MysteryShopperForm() {
  const { auditId } = useParams();
  const [audit, setAudit] = useState(null);
  const [loading, setLoading] = useState(true);
  const [notFound, setNotFound] = useState(false);
  const [responses, setResponses] = useState(initResponses());
  const [observations, setObservations] = useState({ strengths: "", improvements: "", recommendations: "" });
  const [saving, setSaving] = useState(false);
  const [submitted, setSubmitted] = useState(false);
  const [toast, showToast] = useToast();

  useEffect(() => {
    fetchAudit(auditId)
      .then((data) => {
        setAudit(data);
        if (data.responses) setResponses(data.responses);
        if (data.observations) setObservations(data.observations);
        if (data.status === "submitted") setSubmitted(true);
      })
      .catch(() => setNotFound(true))
      .finally(() => setLoading(false));
  }, [auditId]);

  const updateResponse = useCallback((id, val) =>
    setResponses((p) => ({ ...p, [id]: val })), []);

  const save = async (finalSubmit) => {
    setSaving(true);
    try {
      const payload = { responses, observations, status: finalSubmit ? "submitted" : "draft" };
      await submitAudit(auditId, payload);
      if (finalSubmit) {
        setSubmitted(true);
        showToast("Audit submitted successfully!", "ok");
      } else {
        showToast("Progress saved as draft.", "ok");
      }
    } catch (e) {
      showToast("Save failed — please try again.", "err");
    }
    setSaving(false);
  };

  const { total, totalMax, pct } = calcOverall(responses);
  const { label: ratingLabel, color: ratingColor } = ratingMeta(pct);

  // ── Loading / error states ──────────────────────────────────────────────────
  if (loading) {
    return (
      <div style={pageStyle}>
        <div style={cardStyle}>
          <p style={{ color: "#6b7280", textAlign: "center", padding: "2rem" }}>Loading questionnaire…</p>
        </div>
      </div>
    );
  }

  if (notFound) {
    return (
      <div style={pageStyle}>
        <div style={cardStyle}>
          <p style={{ color: "#dc2626", textAlign: "center", padding: "2rem", fontWeight: 600 }}>
            Audit not found. Please check the link and try again.
          </p>
        </div>
      </div>
    );
  }

  const vd = audit?.visit_details || {};
  const readOnly = submitted;

  // ── Submitted confirmation ─────────────────────────────────────────────────
  if (submitted && !saving) {
    return (
      <div style={pageStyle}>
        <div style={cardStyle}>
          <div style={{ textAlign: "center", padding: "2.5rem 1rem" }}>
            <div style={{ fontSize: "3rem", marginBottom: "1rem" }}>✅</div>
            <h2 style={{ margin: "0 0 0.5rem", color: "#16a34a", fontSize: "1.2rem" }}>Audit Submitted</h2>
            <p style={{ color: "#6b7280", fontSize: "0.88rem", margin: 0 }}>
              Your mystery shopping responses for <strong>{vd.branch_name || "this branch"}</strong> have been recorded.
            </p>
            {pct !== null && (
              <p style={{ marginTop: "1rem", fontWeight: 700, fontSize: "1.1rem", color: ratingColor }}>
                Overall Score: {total} / {totalMax} ({pct}% — {ratingLabel})
              </p>
            )}
          </div>
        </div>
      </div>
    );
  }

  // ── Main form ──────────────────────────────────────────────────────────────
  return (
    <div style={pageStyle}>
      {/* Toast */}
      {toast && (
        <div style={{
          position: "fixed", top: 16, left: "50%", transform: "translateX(-50%)",
          background: toast.type === "ok" ? "#16a34a" : "#dc2626",
          color: "#fff", padding: "0.6rem 1.25rem", borderRadius: 8,
          fontWeight: 600, fontSize: "0.85rem", zIndex: 9999,
          boxShadow: "0 4px 12px rgba(0,0,0,0.15)",
        }}>
          {toast.text}
        </div>
      )}

      <div style={cardStyle}>
        {/* Header */}
        <div style={{ background: "#1a1a2e", color: "#fff", padding: "1.25rem 1.5rem", borderRadius: "10px 10px 0 0" }}>
          <div style={{ fontSize: "0.7rem", fontWeight: 700, textTransform: "uppercase", letterSpacing: "0.08em", color: "#a5b4fc", marginBottom: "0.3rem" }}>
            Mystery Shopping — Branch Visit Audit
          </div>
          <h1 style={{ margin: 0, fontSize: "1.1rem", fontWeight: 800 }}>
            {vd.branch_name || "Branch Audit"}
          </h1>
          {(vd.branch_code || vd.city_state) && (
            <p style={{ margin: "0.25rem 0 0", fontSize: "0.8rem", color: "#c7d2fe" }}>
              {[vd.branch_code, vd.city_state, vd.date_of_visit].filter(Boolean).join(" · ")}
            </p>
          )}
          {pct !== null && (
            <div style={{ marginTop: "0.75rem", display: "flex", alignItems: "center", gap: "0.5rem" }}>
              <div style={{ flex: 1, height: 6, background: "#374151", borderRadius: 3, overflow: "hidden" }}>
                <div style={{ width: `${pct}%`, height: "100%", background: ratingColor, borderRadius: 3, transition: "width 0.3s" }} />
              </div>
              <span style={{ fontSize: "0.82rem", fontWeight: 700, color: ratingColor }}>
                {pct}% — {ratingLabel}
              </span>
            </div>
          )}
        </div>

        <div style={{ padding: "1.25rem" }}>
          {/* Visit info */}
          {vd.shopper_name && (
            <div style={{ background: "#f8fafc", border: "1px solid #e5e7eb", borderRadius: 8, padding: "0.75rem 1rem", marginBottom: "1.25rem", fontSize: "0.82rem", color: "#4b5563" }}>
              <strong>Shopper:</strong> {vd.shopper_name}
              {vd.type_of_visit && <span style={{ marginLeft: 16 }}><strong>Visit Type:</strong> {vd.type_of_visit}</span>}
              {vd.staff_interacted && <span style={{ marginLeft: 16 }}><strong>Staff:</strong> {vd.staff_interacted}</span>}
            </div>
          )}

          {/* Scoring guide */}
          <div style={{ background: "#fffbeb", border: "1px solid #fde68a", borderRadius: 8, padding: "0.65rem 1rem", marginBottom: "1.25rem", fontSize: "0.78rem", color: "#78350f" }}>
            <strong>Scoring:</strong>&nbsp;
            <span style={{ color: "#16a34a", fontWeight: 700 }}>Yes = 5</span> &nbsp;·&nbsp;
            <span style={{ color: "#f59e0b", fontWeight: 700 }}>Partial = 3</span> &nbsp;·&nbsp;
            <span style={{ color: "#dc2626", fontWeight: 700 }}>No = 0</span> &nbsp;·&nbsp;
            <span style={{ color: "#94a3b8", fontWeight: 700 }}>N/A = excluded</span>
          </div>

          {/* Part A */}
          <div style={partDividerStyle}>
            <div style={partLineStyle} />
            <span style={partLabelStyle}>PART A — Branch Banking Services</span>
            <div style={partLineStyle} />
          </div>
          {QUESTIONNAIRE.partA.map((s) => (
            <SectionBlock key={s.id} section={s} responses={responses} onChange={updateResponse} readOnly={readOnly} />
          ))}

          {/* Part B */}
          <div style={{ ...partDividerStyle, marginTop: "1.5rem" }}>
            <div style={partLineStyle} />
            <span style={partLabelStyle}>PART B — Loan / Retail Asset Services</span>
            <div style={partLineStyle} />
          </div>
          {QUESTIONNAIRE.partB.map((s) => (
            <SectionBlock key={s.id} section={s} responses={responses} onChange={updateResponse} readOnly={readOnly} />
          ))}

          {/* Observations */}
          <div style={{ border: "1.5px solid #e5e7eb", borderRadius: 10, overflow: "hidden", marginBottom: "1.25rem", background: "#fff" }}>
            <div style={{ padding: "0.65rem 1rem", background: "#f5f3ff", borderBottom: "1.5px solid #e5e7eb" }}>
              <span style={{ fontWeight: 700, fontSize: "0.85rem", color: "#1a1a2e" }}>Overall Observations</span>
            </div>
            <div style={{ padding: "1rem", display: "flex", flexDirection: "column", gap: "0.85rem" }}>
              {[
                ["Key strengths noted during the visit:", "strengths"],
                ["Areas needing improvement / non-compliances:", "improvements"],
                ["Specific recommendations:", "recommendations"],
              ].map(([label, key]) => (
                <div key={key}>
                  <label style={{ fontSize: "0.78rem", fontWeight: 600, color: "#374151", display: "block", marginBottom: "0.3rem" }}>
                    {label}
                  </label>
                  <textarea
                    rows={3}
                    disabled={readOnly}
                    value={observations[key]}
                    onChange={(e) => setObservations((p) => ({ ...p, [key]: e.target.value }))}
                    style={{
                      width: "100%", boxSizing: "border-box",
                      padding: "0.4rem 0.6rem",
                      border: "1.5px solid #e5e7eb", borderRadius: 6,
                      fontSize: "0.82rem", fontFamily: "inherit",
                      resize: "vertical",
                      background: readOnly ? "#f9fafb" : undefined,
                    }}
                  />
                </div>
              ))}
            </div>
          </div>

          {/* Actions */}
          {!readOnly && (
            <div style={{ display: "flex", gap: "0.75rem", justifyContent: "flex-end", paddingTop: "0.75rem", borderTop: "1.5px solid #e5e7eb" }}>
              <button
                disabled={saving}
                onClick={() => save(false)}
                style={outlineBtnStyle}
              >
                <Save size={14} style={{ marginRight: 5 }} /> Save Draft
              </button>
              <button
                disabled={saving}
                onClick={() => save(true)}
                style={primaryBtnStyle}
              >
                <CheckCircle size={14} style={{ marginRight: 5 }} />
                {saving ? "Submitting…" : "Submit Audit"}
              </button>
            </div>
          )}

          {readOnly && (
            <p style={{ textAlign: "center", color: "#16a34a", fontWeight: 700, fontSize: "0.88rem", marginTop: "1rem" }}>
              ✓ This audit has been submitted and is read-only.
            </p>
          )}
        </div>
      </div>
    </div>
  );
}

// ─── Inline styles (no CSS file dependency for public page) ──────────────────
const pageStyle = {
  minHeight: "100vh",
  background: "#f1f5f9",
  padding: "1.5rem 1rem 4rem",
  fontFamily: "-apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif",
  WebkitFontSmoothing: "antialiased",
};
const cardStyle = {
  maxWidth: 780,
  margin: "0 auto",
  background: "#fff",
  borderRadius: 10,
  boxShadow: "0 4px 24px rgba(0,0,0,0.08)",
  overflow: "hidden",
};
const partDividerStyle = {
  display: "flex", alignItems: "center", gap: "0.75rem", marginBottom: "1rem",
};
const partLineStyle = {
  flex: 1, height: 2, background: "#ddd6fe",
};
const partLabelStyle = {
  fontSize: "0.75rem", fontWeight: 800, color: "#7c3aed",
  textTransform: "uppercase", letterSpacing: "0.05em",
  background: "#f5f3ff", padding: "0.25rem 0.85rem", borderRadius: 20,
  whiteSpace: "nowrap",
};
const primaryBtnStyle = {
  display: "inline-flex", alignItems: "center",
  padding: "0.55rem 1.25rem", borderRadius: 8,
  background: "#667eea", color: "#fff",
  border: "none", fontWeight: 700, fontSize: "0.85rem",
  cursor: "pointer",
};
const outlineBtnStyle = {
  display: "inline-flex", alignItems: "center",
  padding: "0.55rem 1.25rem", borderRadius: 8,
  background: "#fff", color: "#374151",
  border: "1.5px solid #d1d5db", fontWeight: 600, fontSize: "0.85rem",
  cursor: "pointer",
};
