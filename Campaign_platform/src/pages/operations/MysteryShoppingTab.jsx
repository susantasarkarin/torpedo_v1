"use client";

/**
 * MysteryShoppingTab — detail view for a single mystery shopping audit.
 * Rendered by QREPage when a mystery-shopping study is selected from the list.
 * Tabs: Questionnaire | Score | Live Link
 */

import { useState, useCallback } from "react";
import { Save, CheckCircle, Copy, ExternalLink, Link } from "lucide-react";
import api from "../../utils/api";

// ─── Questionnaire schema (IDFC FIRST Bank Mystery Shopping) ─────────────────
export const QUESTIONNAIRE = {
  partA: [
    {
      id: "a1", title: "A1. External and Branch Appearance", maxPossible: 20,
      params: [
        { id: "a1_1", text: "Signage — Branch and ATM signage is clean, fully illuminated, and clearly visible from the road." },
        { id: "a1_2", text: "ATM Lobby — ATM lobby is clean, all machines are functional, and receipt paper is available." },
        { id: "a1_3", text: "Entrance — Glass doors are clean and clear; correct operating hours are displayed at the entrance." },
        { id: "a1_4", text: "Interior Cleanliness — Floors are spotless, counters are tidy, and brochure racks are organised." },
      ],
    },
    {
      id: "a2", title: "A2. Guard and Welcome Desk", maxPossible: 15,
      params: [
        { id: "a2_1", text: "Security Guard — Guard is alert, properly uniformed, and greets customers appropriately." },
        { id: "a2_2", text: "Welcome Desk — Welcome desk is attended by staff ready to direct customer traffic." },
        { id: "a2_3", text: "Queue Management — Token / queue machine is working and the waiting time is reasonable." },
      ],
    },
    {
      id: "a3", title: "A3. Staff Grooming and Behaviour", maxPossible: 20,
      params: [
        { id: "a3_1", text: "Dress Code — Staff wear professional attire with visible ID / name badges." },
        { id: "a3_2", text: "Body Language — Staff are attentive, make eye contact, and smile." },
        { id: "a3_3", text: "Greeting — Staff greet politely using a standard opening phrase." },
        { id: "a3_4", text: "Cell Phone Use — Staff are not using personal mobile phones in public view." },
      ],
    },
    {
      id: "a4", title: "A4. Counter and Teller Services", maxPossible: 20,
      params: [
        { id: "a4_1", text: "Efficiency — Cash handling is smooth and processing times are quick." },
        { id: "a4_2", text: "Accuracy — Note-counting machines are used and correct denominations are given." },
        { id: "a4_3", text: "Privacy — Account balances are not spoken aloud or made visible to others." },
        { id: "a4_4", text: "Closing — Teller thanks the customer and offers further assistance." },
      ],
    },
    {
      id: "a5", title: "A5. Branch Manager and Desk Operations", maxPossible: 15,
      params: [
        { id: "a5_1", text: "Availability — Branch Manager is visible or accessible in their cabin." },
        { id: "a5_2", text: "Query Resolution — Staff are knowledgeable about accounts, loans, and interest rates." },
        { id: "a5_3", text: "Tone — Staff are patient and helpful, especially when handling complex issues." },
      ],
    },
    {
      id: "a6", title: "A6. Compliance and Customer Comfort", maxPossible: 15,
      params: [
        { id: "a6_1", text: "Mandatory Displays — Interest-rate charts and grievance / redressal notices are displayed." },
        { id: "a6_2", text: "Seating — Adequate seating is available for waiting customers." },
        { id: "a6_3", text: "Environment — Air conditioning is comfortable and drinking-water stations are functional." },
      ],
    },
  ],
  partB: [
    {
      id: "b1", title: "B1. First Impression and Initial Inquiry", maxPossible: 20,
      params: [
        { id: "b1_1", text: 'Signage — Clear directions or desk counters are marked "Loans" or "Retail Assets".' },
        { id: "b1_2", text: "Initial Greeting — Staff acknowledge you promptly when you approach the loan desk." },
        { id: "b1_3", text: "Wait Time — Time taken to speak with a dedicated loan officer is under 10 minutes." },
        { id: "b1_4", text: "Privacy — Consultation takes place in a private booth or cabin, keeping details secure." },
      ],
    },
    {
      id: "b2", title: "B2. Loan Officer Professionalism and Behaviour", maxPossible: 20,
      params: [
        { id: "b2_1", text: "Active Listening — Officer asks about your income, employment, and funding needs before pitching." },
        { id: "b2_2", text: "Expert Knowledge — Officer confidently explains different loan types (e.g., fixed vs floating rates)." },
        { id: "b2_3", text: "Product Pitching — Officer recommends a specific loan product that fits your stated needs." },
        { id: "b2_4", text: "Tone — Officer is professional, welcoming, non-judgmental, and patient with questions." },
      ],
    },
    {
      id: "b3", title: "B3. Transparency and Information Gathering", maxPossible: 20,
      params: [
        { id: "b3_1", text: "Rate Disclosure — Officer clearly states the current interest rate and whether it is negotiable." },
        { id: "b3_2", text: "Fee Breakdown — Processing fees, documentation charges, and prepayment penalties are explained." },
        { id: "b3_3", text: "Turnaround Time (TAT) — A clear timeline is provided for loan approval and final disbursement." },
        { id: "b3_4", text: "Eligibility Check — Officer explains the minimum credit score and income criteria needed." },
      ],
    },
    {
      id: "b4", title: "B4. Documentation and Next Steps", maxPossible: 20,
      params: [
        { id: "b4_1", text: "Checklist Provided — A clear printed or digital list of required documents is given to you." },
        { id: "b4_2", text: "Digital Alternatives — Staff mention uploading documents online via the bank app or portal." },
        { id: "b4_3", text: "Follow-up Capture — Officer asks for your contact details to follow up on the discussion." },
        { id: "b4_4", text: "Closing — You are handed a business card and thanked politely for your time." },
      ],
    },
  ],
};

export const ALL_SECTIONS = [...QUESTIONNAIRE.partA, ...QUESTIONNAIRE.partB];

// ─── Scoring helpers (exported so QREPage can compute list scores) ────────────
const RESPONSE_SCORE = { Yes: 5, Partial: 3, No: 0 };

export function scoreFromResponse(r) { return RESPONSE_SCORE[r] ?? null; }

export function calcSectionScore(section, responses) {
  let score = 0, max = 0;
  for (const p of section.params) {
    const resp = responses?.[p.id]?.response;
    if (!resp || resp === "N/A") continue;
    max += 5;
    score += scoreFromResponse(resp) ?? 0;
  }
  return { score, max };
}

export function calcOverall(responses) {
  let total = 0, totalMax = 0;
  for (const s of ALL_SECTIONS) {
    const { score, max } = calcSectionScore(s, responses);
    total += score; totalMax += max;
  }
  return { total, totalMax, pct: totalMax > 0 ? Math.round((total / totalMax) * 100) : null };
}

export function initResponses() {
  const r = {};
  ALL_SECTIONS.forEach((s) => s.params.forEach((p) => { r[p.id] = { response: "", remarks: "" }; }));
  return r;
}

// ─── Rating helpers ───────────────────────────────────────────────────────────
export function ratingMeta(pct) {
  if (pct === null) return { label: "—", color: "#9ca3af" };
  if (pct >= 90) return { label: "Excellent", color: "#16a34a" };
  if (pct >= 75) return { label: "Good", color: "#2563eb" };
  if (pct >= 60) return { label: "Needs Improvement", color: "#f59e0b" };
  return { label: "Critical", color: "#dc2626" };
}

// ─── Toast ────────────────────────────────────────────────────────────────────
function useToast() {
  const [msg, setMsg] = useState("");
  const show = useCallback((text) => { setMsg(text); setTimeout(() => setMsg(""), 3000); }, []);
  return [msg, show];
}

// ─── Section block ────────────────────────────────────────────────────────────
function SectionBlock({ section, responses, onChange, readOnly }) {
  const { score, max } = calcSectionScore(section, responses);
  const displayMax = max === 0 ? section.maxPossible : max;

  return (
    <div className="ms-section-block">
      <div className="ms-section-header">
        <span className="ms-section-title">{section.title}</span>
        <span className="ms-section-score">{score} / {displayMax} pts</span>
      </div>
      <table className="ms-param-table">
        <thead>
          <tr>
            <th className="ms-col-num">#</th>
            <th className="ms-col-param">Parameter / What to observe</th>
            <th className="ms-col-response">Response</th>
            <th className="ms-col-score">Score</th>
            <th className="ms-col-remarks">Remarks / Observation</th>
          </tr>
        </thead>
        <tbody>
          {section.params.map((p, idx) => {
            const r = responses?.[p.id] || { response: "", remarks: "" };
            const sc = r.response && r.response !== "N/A" ? scoreFromResponse(r.response) : null;
            return (
              <tr key={p.id} className={r.response ? "ms-row-answered" : ""}>
                <td className="ms-col-num">{idx + 1}</td>
                <td className="ms-col-param">{p.text}</td>
                <td className="ms-col-response">
                  <div className="ms-response-group">
                    {["Yes", "Partial", "No", "N/A"].map((opt) => (
                      <label
                        key={opt}
                        className={`ms-radio-label ms-radio-${opt.toLowerCase().replace("/", "")} ${r.response === opt ? "ms-radio-selected" : ""}`}
                      >
                        <input type="radio" name={p.id} value={opt} checked={r.response === opt}
                          disabled={readOnly}
                          onChange={() => !readOnly && onChange(p.id, { ...r, response: opt })}
                        />
                        {opt}
                      </label>
                    ))}
                  </div>
                </td>
                <td className="ms-col-score">
                  {sc !== null
                    ? <span className={`ms-score-pill ms-score-${sc}`}>{sc}</span>
                    : r.response === "N/A"
                      ? <span className="ms-score-na">N/A</span>
                      : <span className="ms-score-empty">—</span>}
                </td>
                <td className="ms-col-remarks">
                  <textarea className="ms-remarks-input" rows={2}
                    placeholder="What was seen / said, staff name, time…"
                    value={r.remarks} disabled={readOnly}
                    onChange={(e) => !readOnly && onChange(p.id, { ...r, remarks: e.target.value })}
                  />
                </td>
              </tr>
            );
          })}
        </tbody>
      </table>
    </div>
  );
}

// ─── Score Summary ────────────────────────────────────────────────────────────
export function ScoreSummary({ responses }) {
  const partATotal = { score: 0, max: 0 };
  const partBTotal = { score: 0, max: 0 };

  const rows = (sections, subtotal) =>
    sections.map((s) => {
      const { score, max } = calcSectionScore(s, responses);
      const adjMax = max === 0 ? s.maxPossible : max;
      const pct = adjMax > 0 ? Math.round((score / adjMax) * 100) : null;
      subtotal.score += score; subtotal.max += adjMax;
      const { color } = ratingMeta(pct);
      return (
        <tr key={s.id}>
          <td>{s.title}</td>
          <td style={{ textAlign: "center" }}>{adjMax}</td>
          <td style={{ textAlign: "center" }}>{score}</td>
          <td style={{ textAlign: "center", color, fontWeight: 600 }}>{pct !== null ? `${pct}%` : "—"}</td>
        </tr>
      );
    });

  return (
    <div className="ms-section-block">
      <div className="ms-section-header">
        <span className="ms-section-title">Score Summary</span>
      </div>
      <table className="ms-param-table ms-score-summary-table">
        <thead>
          <tr>
            <th>Section</th>
            <th style={{ textAlign: "center" }}>Max</th>
            <th style={{ textAlign: "center" }}>Score</th>
            <th style={{ textAlign: "center" }}>%</th>
          </tr>
        </thead>
        <tbody>
          {rows(QUESTIONNAIRE.partA, partATotal)}
          <tr className="ms-subtotal-row">
            <td>PART A — BRANCH BANKING SUBTOTAL</td>
            <td style={{ textAlign: "center" }}>{partATotal.max || 105}</td>
            <td style={{ textAlign: "center" }}>{partATotal.score}</td>
            <td style={{ textAlign: "center" }}>
              {partATotal.max > 0 && (() => { const { label, color } = ratingMeta(Math.round((partATotal.score / partATotal.max) * 100)); return <span style={{ color }}>{Math.round((partATotal.score / partATotal.max) * 100)}% — {label}</span>; })()}
            </td>
          </tr>
          {rows(QUESTIONNAIRE.partB, partBTotal)}
          <tr className="ms-subtotal-row">
            <td>PART B — LOAN SERVICES SUBTOTAL</td>
            <td style={{ textAlign: "center" }}>{partBTotal.max || 80}</td>
            <td style={{ textAlign: "center" }}>{partBTotal.score}</td>
            <td style={{ textAlign: "center" }}>
              {partBTotal.max > 0 && (() => { const { label, color } = ratingMeta(Math.round((partBTotal.score / partBTotal.max) * 100)); return <span style={{ color }}>{Math.round((partBTotal.score / partBTotal.max) * 100)}% — {label}</span>; })()}
            </td>
          </tr>
          {(() => {
            const total = partATotal.score + partBTotal.score;
            const max = partATotal.max + partBTotal.max;
            const pct = max > 0 ? Math.round((total / max) * 100) : null;
            const { label, color } = ratingMeta(pct);
            return (
              <tr className="ms-overall-row">
                <td>OVERALL SCORE</td>
                <td style={{ textAlign: "center" }}>{max || 185}</td>
                <td style={{ textAlign: "center" }}>{total}</td>
                <td style={{ textAlign: "center" }}>
                  {pct !== null && <span style={{ color: "#a5b4fc" }}>{pct}% — {label}</span>}
                </td>
              </tr>
            );
          })()}
        </tbody>
      </table>
      <div className="ms-rating-legend">
        <span style={{ color: "#16a34a" }}>90%+ Excellent</span>
        <span className="ms-legend-dot">•</span>
        <span style={{ color: "#2563eb" }}>75–89% Good</span>
        <span className="ms-legend-dot">•</span>
        <span style={{ color: "#f59e0b" }}>60–74% Needs Improvement</span>
        <span className="ms-legend-dot">•</span>
        <span style={{ color: "#dc2626" }}>Below 60% Critical</span>
      </div>
    </div>
  );
}

// ─── Questionnaire tab (the editable form) ────────────────────────────────────
const EMPTY_VISIT = {
  branch_name: "", branch_code: "", branch_address: "", city_state: "",
  region_zone: "", date_of_visit: "", time_in: "", time_out: "",
  shopper_name: "", shopper_id: "", type_of_visit: "Branch Banking",
  scenario_used: "", staff_interacted: "", contact_collected: "",
};

function QuestionnaireTab({ audit, onSaved }) {
  const [visitDetails, setVisitDetails] = useState(audit?.visit_details || EMPTY_VISIT);
  const [responses, setResponses] = useState(audit?.responses || initResponses());
  const [observations, setObservations] = useState(audit?.observations || { strengths: "", improvements: "", recommendations: "" });
  const [saving, setSaving] = useState(false);
  const [toast, showToast] = useToast();

  const readOnly = audit?.status === "submitted";
  const { pct } = calcOverall(responses);
  const updateResponse = useCallback((id, val) => setResponses((p) => ({ ...p, [id]: val })), []);

  const save = async (status) => {
    if (!visitDetails.branch_name.trim()) { showToast("Branch Name is required."); return; }
    setSaving(true);
    try {
      const payload = { visit_details: visitDetails, responses, observations, status };
      const saved = await api.put(`/api/mystery-shopping/audits/${audit.id}`, payload);
      showToast(status === "submitted" ? "Audit submitted" : "Draft saved");
      setTimeout(() => onSaved(saved), 600);
    } catch (e) { showToast("Error: " + (e.message || "Save failed")); }
    setSaving(false);
  };

  const VISIT_FIELDS = [
    ["Branch Name *", "branch_name", "text"], ["Branch Code", "branch_code", "text"],
    ["Branch Address", "branch_address", "text"], ["City / State", "city_state", "text"],
    ["Region / Zone", "region_zone", "text"], ["Date of Visit", "date_of_visit", "date"],
    ["Time In", "time_in", "time"], ["Time Out", "time_out", "time"],
    ["Mystery Shopper Name", "shopper_name", "text"], ["Shopper ID", "shopper_id", "text"],
    ["Scenario Used", "scenario_used", "text"], ["Staff Interacted With (Name / Desk)", "staff_interacted", "text"],
    ["Contact No. Collected", "contact_collected", "text"],
  ];

  return (
    <div className="ms-form-root">
      {toast && <div className="qre-toast">{toast}</div>}

      {/* Visit Details */}
      <div className="ms-section-block">
        <div className="ms-section-header">
          <span className="ms-section-title">Visit Details</span>
          {pct !== null && (() => { const { label, color } = ratingMeta(pct); return <span style={{ color, fontWeight: 700, fontSize: "0.82rem" }}>{pct}% — {label}</span>; })()}
        </div>
        <div className="ms-visit-grid">
          {VISIT_FIELDS.map(([label, key, type]) => (
            <div key={key} className="ms-visit-field">
              <label className="qre-label">{label}</label>
              <input type={type} className="qre-input" value={visitDetails[key] || ""} disabled={readOnly}
                onChange={(e) => setVisitDetails((p) => ({ ...p, [key]: e.target.value }))} />
            </div>
          ))}
          <div className="ms-visit-field">
            <label className="qre-label">Type of Visit</label>
            <select className="qre-input" value={visitDetails.type_of_visit} disabled={readOnly}
              onChange={(e) => setVisitDetails((p) => ({ ...p, type_of_visit: e.target.value }))}>
              <option>Branch Banking</option>
              <option>Loan Services</option>
              <option>Both</option>
            </select>
          </div>
        </div>
      </div>

      <div className="ms-part-divider">
        <span className="ms-part-label">PART A — Branch Banking Services</span>
      </div>
      {QUESTIONNAIRE.partA.map((s) => (
        <SectionBlock key={s.id} section={s} responses={responses} onChange={updateResponse} readOnly={readOnly} />
      ))}

      <div className="ms-part-divider" style={{ marginTop: "2rem" }}>
        <span className="ms-part-label">PART B — Loan / Retail Asset Services</span>
      </div>
      {QUESTIONNAIRE.partB.map((s) => (
        <SectionBlock key={s.id} section={s} responses={responses} onChange={updateResponse} readOnly={readOnly} />
      ))}

      {/* Observations */}
      <div className="ms-section-block" style={{ marginTop: "1.5rem" }}>
        <div className="ms-section-header">
          <span className="ms-section-title">Overall Observations & Recommendations</span>
        </div>
        <div className="ms-obs-grid">
          {[["Key strengths noted during the visit:", "strengths"],
            ["Areas needing improvement / non-compliances:", "improvements"],
            ["Specific recommendations:", "recommendations"]].map(([label, key]) => (
            <div key={key}>
              <label className="qre-label">{label}</label>
              <textarea className="qre-textarea" rows={4} disabled={readOnly}
                value={observations[key]}
                onChange={(e) => setObservations((p) => ({ ...p, [key]: e.target.value }))} />
            </div>
          ))}
        </div>
      </div>

      {!readOnly && (
        <div className="ms-form-actions">
          <button className="qre-btn qre-btn-outline" disabled={saving} onClick={() => save("draft")}>
            <Save size={14} /> Save Draft
          </button>
          <button className="qre-btn" disabled={saving} onClick={() => save("submitted")}>
            <CheckCircle size={14} /> Submit Audit
          </button>
        </div>
      )}
    </div>
  );
}

// ─── Live Link tab ────────────────────────────────────────────────────────────
function LiveLinkTab({ auditId }) {
  const [toast, showToast] = useToast();
  const liveUrl = `${window.location.origin}/mystery-shopper/${auditId}`;

  const copy = () => { navigator.clipboard.writeText(liveUrl); showToast("Copied to clipboard!"); };

  return (
    <div className="qre-section">
      {toast && <div className="qre-toast">{toast}</div>}
      <h2 className="qre-section-title">Field Access Link</h2>
      <p className="qre-section-desc">
        Share this link with the mystery shopper. They can open it on any device and fill in the
        questionnaire without needing an admin account.
      </p>

      <div className="ms-live-link-card">
        <div className="ms-live-link-url-row">
          <input className="qre-input" readOnly value={liveUrl}
            style={{ flex: 1, background: "#f8fafc", fontFamily: "monospace", fontSize: "0.82rem" }}
            onFocus={(e) => e.target.select()} />
          <button className="qre-btn" onClick={copy} style={{ whiteSpace: "nowrap" }}>
            <Copy size={14} /> Copy Link
          </button>
          <a className="qre-btn qre-btn-outline" href={liveUrl} target="_blank" rel="noreferrer" style={{ whiteSpace: "nowrap" }}>
            <ExternalLink size={14} /> Open
          </a>
        </div>
        <div className="ms-live-link-meta">
          <span className="ms-live-link-id-label">Audit ID</span>
          <code className="ms-live-link-id">{auditId}</code>
        </div>
      </div>

      <div className="ms-live-link-instructions">
        <h3 style={{ fontSize: "0.88rem", fontWeight: 700, margin: "0 0 0.5rem" }}>Instructions for the shopper</h3>
        <ol style={{ margin: 0, paddingLeft: "1.2rem", fontSize: "0.82rem", color: "#4b5563", lineHeight: 1.7 }}>
          <li>Open the link above on your phone or tablet before entering the branch.</li>
          <li>Fill in the Visit Details section first (branch name, date, time).</li>
          <li>Rate each parameter <strong>Yes / Partial / No / N/A</strong> and add brief remarks.</li>
          <li>Complete Part A (Branch Banking) and Part B (Loan Services) as applicable.</li>
          <li>Tap <strong>Submit</strong> when done — your scores are saved automatically.</li>
        </ol>
      </div>
    </div>
  );
}

// ─── Main export — detail view with tabs ─────────────────────────────────────
const MS_TABS = ["Questionnaire", "Score", "Live Link"];

export default function MysteryShoppingDetail({ audit: initialAudit, onBack }) {
  const [audit, setAudit] = useState(initialAudit);
  const [activeTab, setActiveTab] = useState("Questionnaire");

  const handleSaved = (updated) => setAudit(updated);

  return (
    <div className="qre-root">
      {/* Header */}
      <div className="qre-page-header">
        <div>
          <button className="qre-btn qre-btn-outline qre-btn-sm"
            onClick={onBack}
            style={{ marginBottom: "0.5rem", fontSize: "0.78rem" }}>
            ← All Studies
          </button>
          <div className="qre-page-title-row">
            <span style={{ fontSize: "1.1rem" }}>🔍</span>
            <h1 className="qre-page-title">
              {audit.visit_details?.branch_name || "Mystery Shopping Audit"}
            </h1>
            <span className={`qre-badge ${audit.status === "submitted" ? "qre-badge-live" : "qre-badge-draft"}`}>
              {audit.status}
            </span>
          </div>
          <p className="qre-page-subtitle">
            Mystery Shopping · ID: <code style={{ fontSize: "0.78rem", background: "#f3f4f6", padding: "1px 5px", borderRadius: 4 }}>{audit.id}</code>
            {audit.visit_details?.date_of_visit && ` · Visit: ${audit.visit_details.date_of_visit}`}
          </p>
        </div>
      </div>

      {/* Sub-tabs */}
      <div className="qre-tabs">
        {MS_TABS.map((t) => (
          <button key={t} className={`qre-tab-btn ${activeTab === t ? "active" : ""}`}
            onClick={() => setActiveTab(t)}>{t}</button>
        ))}
      </div>

      {activeTab === "Questionnaire" && <QuestionnaireTab audit={audit} onSaved={handleSaved} />}
      {activeTab === "Score"         && <ScoreSummary responses={audit.responses || {}} />}
      {activeTab === "Live Link"     && <LiveLinkTab auditId={audit.id} />}
    </div>
  );
}
