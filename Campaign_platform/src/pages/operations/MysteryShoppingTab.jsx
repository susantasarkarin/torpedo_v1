"use client";

/**
 * MysteryShoppingTab — detail view for a single mystery shopping audit.
 * Rendered by QREPage when a mystery-shopping study is selected from the list.
 * Tabs: Questionnaire | Score | Live Link
 */

import { useState, useCallback, useEffect } from "react";
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

// ─── Quotas Tab ───────────────────────────────────────────────────────────────
// Locations from IDFC FIRST Bank brief — 8 visits total
const MS_LOCATIONS = [
  { label: "Powai",                  city: "Mumbai", type: "Branch" },
  { label: "Andheri East",           city: "Mumbai", type: "Branch" },
  { label: "Andheri Apple Heritage", city: "Mumbai", type: "Loan Centre" },
  { label: "Panvel",                 city: "Mumbai", type: "Branch" },
  { label: "Anand Vihar",            city: "Kolkata",  type: "Branch" },
  { label: "Mayur Vihar",            city: "Kolkata",  type: "Branch" },
  { label: "Rajendra Nagar",         city: "Kolkata",  type: "Branch" },
  { label: "Uttam Nagar",            city: "Kolkata",  type: "Loan Centre" },
];

// High-level quota cells: by City and by Visit Type
const MS_QUOTA_CELLS = [
  { group: "By City",       label: "Mumbai",      target: 4, match: (a) => /mumbai/i.test(a.visit_details?.city_state || a.visit_details?.city || "") },
  { group: "By City",       label: "Kolkata",     target: 4, match: (a) => /kolkata|delhi/i.test(a.visit_details?.city_state || a.visit_details?.city || "") },
  { group: "By Visit Type", label: "Branch Visit",      target: 6, match: (a) => !/loan/i.test(a.visit_details?.type_of_visit || "") && !/loan centre/i.test(a.visit_details?.branch_name || "") },
  { group: "By Visit Type", label: "Loan Centre Visit", target: 2, match: (a) => /loan/i.test(a.visit_details?.type_of_visit || "") || /loan centre|apple heritage|rajendra|uttam nagar/i.test(a.visit_details?.branch_name || "") },
];

function MSQuotasTab({ audit }) {
  const [allAudits, setAllAudits] = useState(null);

  useEffect(() => {
    api.get("/api/mystery-shopping/audits")
      .then((data) => setAllAudits(data?.audits || data || []))
      .catch(() => setAllAudits([]));
  }, []);

  const submitted = (allAudits || []).filter((a) => a.status === "submitted");
  const totalDone = submitted.length;
  const totalTarget = 8;
  const overallPct = Math.round((totalDone / totalTarget) * 100);

  const auditForLocation = (loc) => {
    if (!allAudits) return null;
    const key = loc.label.toLowerCase();
    return allAudits.find((a) => {
      const bn = (a.visit_details?.branch_name || "").toLowerCase();
      return bn.includes(key) || key.split(" ").every((w) => w.length > 2 && bn.includes(w));
    }) || null;
  };

  // Group quota cells
  const groups = [...new Set(MS_QUOTA_CELLS.map((c) => c.group))];

  return (
    <>
      {/* Overall fieldwork bar */}
      <div className="qre-section">
        <h3 className="qre-section-title">Field Progress — 8 Visits Target</h3>
        <div className="qre-fieldwork-bar-wrap">
          <div className="qre-fieldwork-bar-labels">
            <span>{allAudits ? totalDone : "…"} visits completed</span>
            <span>Target: {totalTarget}</span>
          </div>
          <div className="qre-fieldwork-bar-track">
            <div className="qre-fieldwork-bar-fill" style={{ width: `${overallPct}%` }} />
          </div>
        </div>
      </div>

      {/* Quota cells — By City and By Visit Type */}
      {groups.map((group) => {
        const cells = MS_QUOTA_CELLS.filter((c) => c.group === group);
        return (
          <div className="qre-section" key={group}>
            <h3 className="qre-section-title">{group}</h3>
            <div className="qre-quota-group">
              <div className="qre-quota-grid">
                {cells.map((cell) => {
                  const done = allAudits ? allAudits.filter((a) => a.status === "submitted" && cell.match(a)).length : 0;
                  const pct = Math.round((done / cell.target) * 100);
                  const full = done >= cell.target;
                  return (
                    <div className="qre-quota-card" key={cell.label}>
                      <div className="qre-quota-header">
                        <span style={{ fontWeight: 700 }}>{cell.label}</span>
                        <span style={{ fontWeight: 700, color: full ? "#16a34a" : "#374151" }}>
                          {allAudits ? done : "…"} / {cell.target}
                        </span>
                      </div>
                      <div className="qre-quota-track" style={{ marginTop: "0.5rem" }}>
                        <div className="qre-quota-fill" style={{ width: `${Math.min(pct, 100)}%`, background: full ? "#16a34a" : "#667eea" }} />
                      </div>
                      <div className="qre-quota-pct" style={{ color: full ? "#16a34a" : "#374151" }}>
                        {allAudits ? `${pct}%` : ""}
                      </div>
                    </div>
                  );
                })}
              </div>
            </div>
          </div>
        );
      })}

      {/* Location-level detail table */}
      <div className="qre-section">
        <h3 className="qre-section-title">Location Detail</h3>
        <div className="qre-table-wrap">
          <table className="qre-table">
            <thead>
              <tr>
                <th>Location</th>
                <th>City</th>
                <th>Type</th>
                <th>Status</th>
                <th>Visit Date</th>
                <th>Score</th>
              </tr>
            </thead>
            <tbody>
              {MS_LOCATIONS.map((loc) => {
                const matched = auditForLocation(loc);
                const status = !matched ? "Pending" : matched.status === "submitted" ? "Completed" : "In Progress";
                const statusColor = status === "Completed" ? "#16a34a" : status === "In Progress" ? "#f59e0b" : "#9ca3af";
                const visitDate = matched?.visit_details?.date_of_visit || matched?.visit_details?.visit_date || "—";
                const score = matched ? (() => {
                  let t = 0, m = 0;
                  ALL_SECTIONS.forEach((s) => { const r = calcSectionScore(s, matched.responses || {}); t += r.score; m += (r.max || s.maxPossible); });
                  return m > 0 ? `${Math.round(t / m * 100)}%` : "—";
                })() : "—";
                return (
                  <tr key={loc.label}>
                    <td style={{ fontWeight: 600 }}>{loc.label}</td>
                    <td style={{ color: "#6b7280" }}>{loc.city}</td>
                    <td>
                      <span className={`qre-badge ${loc.type === "Loan Centre" ? "qre-badge-paused" : "qre-badge-draft"}`}>
                        {loc.type}
                      </span>
                    </td>
                    <td><span style={{ color: statusColor, fontWeight: 700, fontSize: "0.8rem" }}>{status}</span></td>
                    <td style={{ color: "#6b7280", fontSize: "0.82rem" }}>{visitDate}</td>
                    <td style={{ fontWeight: 700, color: statusColor }}>{score}</td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        </div>
      </div>
    </>
  );
}

// ─── Export Tab ───────────────────────────────────────────────────────────────
function MSExportTab({ auditId, auditName }) {
  const [busy, setBusy] = useState(null);
  const [toast, showToast] = useToast();

  const download = async (format) => {
    if (busy) return;
    setBusy(format);
    try {
      const token = localStorage.getItem("session_id") || "";
      const res = await fetch(`/api/mystery-shopping/audits/${auditId}/export?format=${format}`, {
        headers: { Authorization: token },
        credentials: "include",
      });
      if (!res.ok) throw new Error(`Server error ${res.status}`);
      const blob = await res.blob();
      const url = URL.createObjectURL(blob);
      const a = document.createElement("a");
      a.href = url;
      const safe = (auditName || "audit").replace(/[^a-z0-9]/gi, "_").slice(0, 40);
      a.download = `ms_${safe}_${auditId.slice(0, 8)}.${format}`;
      a.click();
      URL.revokeObjectURL(url);
    } catch (e) {
      showToast("Export failed: " + e.message);
    }
    setBusy(null);
  };

  return (
    <div className="qre-section">
      <h2 className="qre-section-title">Data Export</h2>
      <p className="qre-section-desc">
        Download audit responses for this mystery shopping visit. Data includes all visit details, parameter responses, scores, and observations.
      </p>
      {toast && <div className="qre-toast">{toast}</div>}
      <div className="qre-export-grid">
        <div
          className={`qre-export-card${busy === "csv" ? " qre-export-loading" : ""}`}
          onClick={() => download("csv")}
        >
          <div className="qre-export-icon">📊</div>
          <div className="qre-export-title">{busy === "csv" ? "Downloading…" : "Audit Report (CSV)"}</div>
          <div className="qre-export-desc">
            Visit details, all 37 parameter responses with scores and remarks, section totals, and observations — ready for Excel.
          </div>
        </div>
        <div
          className={`qre-export-card${busy === "spss" ? " qre-export-loading" : ""}`}
          onClick={() => download("spss")}
        >
          <div className="qre-export-icon">🗂️</div>
          <div className="qre-export-title">{busy === "spss" ? "Downloading…" : "Audit Data (SPSS .sav)"}</div>
          <div className="qre-export-desc">
            SPSS-compatible .sav file with all parameter responses and scores. Import directly into SPSS or PSPP.
          </div>
        </div>
      </div>
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

// ─── Overview Tab ─────────────────────────────────────────────────────────────
function MSOverviewTab({ audit }) {
  const responses = audit.responses || {};
  const vd = audit.visit_details || {};
  const { total, totalMax, pct } = calcOverall(responses);
  const { label: ratingLabel, color: ratingColor } = ratingMeta(pct);

  const partATotal = { score: 0, max: 0 };
  const partBTotal = { score: 0, max: 0 };
  QUESTIONNAIRE.partA.forEach((s) => { const { score, max } = calcSectionScore(s, responses); partATotal.score += score; partATotal.max += (max || s.maxPossible); });
  QUESTIONNAIRE.partB.forEach((s) => { const { score, max } = calcSectionScore(s, responses); partBTotal.score += score; partBTotal.max += (max || s.maxPossible); });

  const answeredCount = ALL_SECTIONS.reduce((n, s) => n + s.params.filter((p) => responses?.[p.id]?.response).length, 0);
  const totalParams = ALL_SECTIONS.reduce((n, s) => n + s.params.length, 0);

  const visitRows = [
    ["Branch Name", vd.branch_name], ["Branch Code", vd.branch_code],
    ["City / State", vd.city_state || vd.city], ["Region / Zone", vd.region_zone],
    ["Date of Visit", vd.date_of_visit], ["Time In → Out", vd.time_in && vd.time_out ? `${vd.time_in} → ${vd.time_out}` : (vd.time_in || vd.time_out)],
    ["Shopper Name", vd.shopper_name], ["Shopper ID", vd.shopper_id],
    ["Type of Visit", vd.type_of_visit], ["Staff Interacted", vd.staff_interacted],
  ].filter(([, v]) => v);

  return (
    <>
      {/* KPI cards — same layout as QRE OverviewTab */}
      <div className="qre-kpi-grid">
        <div className="qre-kpi-card qre-kpi-info">
          <div className="qre-kpi-value" style={{ color: ratingColor }}>{pct !== null ? `${pct}%` : "—"}</div>
          <div className="qre-kpi-label">Overall Score</div>
        </div>
        <div className="qre-kpi-card qre-kpi-success">
          <div className="qre-kpi-value">{total}</div>
          <div className="qre-kpi-label">Points Scored</div>
        </div>
        <div className="qre-kpi-card">
          <div className="qre-kpi-value">{totalMax || 185}</div>
          <div className="qre-kpi-label">Max Points</div>
        </div>
        <div className="qre-kpi-card">
          <div className="qre-kpi-value">{answeredCount}/{totalParams}</div>
          <div className="qre-kpi-label">Parameters Rated</div>
        </div>
        <div className="qre-kpi-card" style={{ gridColumn: "span 2" }}>
          <div className="qre-kpi-value" style={{ color: ratingColor, fontSize: "1.1rem" }}>{ratingLabel}</div>
          <div className="qre-kpi-label">Rating Band</div>
        </div>
      </div>

      {/* Score summary table */}
      <div className="qre-section">
        <h3 className="qre-section-title">Score Summary</h3>
        <ScoreSummary responses={responses} />
      </div>
    </>
  );
}

// ─── Respondents Tab ──────────────────────────────────────────────────────────
function ResponseView({ audit }) {
  const responses = audit.responses || {};
  const vd = audit.visit_details || {};
  const obs = audit.observations || {};

  return (
    <div style={{ padding: "1rem 0" }}>
      {/* Visit details summary */}
      <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fill, minmax(200px, 1fr))", gap: "0.5rem 1.5rem", marginBottom: "1.5rem", fontSize: "0.82rem" }}>
        {[
          ["Branch", vd.branch_name], ["Branch Code", vd.branch_code],
          ["City / State", vd.city_state], ["Date", vd.date_of_visit],
          ["Time In → Out", vd.time_in && vd.time_out ? `${vd.time_in} → ${vd.time_out}` : vd.time_in || ""],
          ["Shopper", vd.shopper_name], ["Shopper ID", vd.shopper_id],
          ["Type of Visit", vd.type_of_visit],
        ].filter(([, v]) => v).map(([k, v]) => (
          <div key={k}>
            <span style={{ fontWeight: 600, color: "#6b7280" }}>{k}: </span>
            <span style={{ color: "#111827" }}>{v}</span>
          </div>
        ))}
      </div>

      {/* Responses by section */}
      {ALL_SECTIONS.map((section) => (
        <div key={section.id} style={{ marginBottom: "1.2rem" }}>
          <div style={{ fontWeight: 700, fontSize: "0.82rem", color: "#374151", borderBottom: "1px solid #e5e7eb", paddingBottom: "0.3rem", marginBottom: "0.5rem" }}>
            {section.title}
          </div>
          {section.params.map((p, i) => {
            const r = responses[p.id] || {};
            const sc = r.response && r.response !== "N/A" ? scoreFromResponse(r.response) : null;
            const respColor = r.response === "Yes" ? "#16a34a" : r.response === "No" ? "#dc2626" : r.response === "Partial" ? "#f59e0b" : "#9ca3af";
            return (
              <div key={p.id} style={{ display: "grid", gridTemplateColumns: "1.5rem 1fr auto auto", gap: "0 0.75rem", alignItems: "start", padding: "0.3rem 0", borderBottom: "1px solid #f3f4f6", fontSize: "0.8rem" }}>
                <span style={{ color: "#9ca3af" }}>{i + 1}.</span>
                <span style={{ color: "#374151" }}>{p.text}{r.remarks ? <span style={{ color: "#9ca3af", fontStyle: "italic" }}> — {r.remarks}</span> : ""}</span>
                <span style={{ fontWeight: 700, color: respColor, whiteSpace: "nowrap", minWidth: 52, textAlign: "right" }}>{r.response || "—"}</span>
                <span style={{ fontWeight: 700, color: respColor, minWidth: 28, textAlign: "right" }}>{sc !== null ? sc : r.response === "N/A" ? "N/A" : "—"}</span>
              </div>
            );
          })}
        </div>
      ))}

      {/* Observations */}
      {(obs.strengths || obs.improvements || obs.recommendations) && (
        <div style={{ marginTop: "1rem", fontSize: "0.82rem" }}>
          <div style={{ fontWeight: 700, color: "#374151", marginBottom: "0.4rem" }}>Observations</div>
          {obs.strengths     && <div><strong>Strengths:</strong> {obs.strengths}</div>}
          {obs.improvements  && <div><strong>Improvements:</strong> {obs.improvements}</div>}
          {obs.recommendations && <div><strong>Recommendations:</strong> {obs.recommendations}</div>}
        </div>
      )}
    </div>
  );
}

function RespondentsTab({ currentAuditId }) {
  const [audits, setAudits] = useState(null);
  const [expanded, setExpanded] = useState(null);

  useEffect(() => {
    api.get("/api/mystery-shopping/audits")
      .then((data) => setAudits(data?.audits || data || []))
      .catch(() => setAudits([]));
  }, []);

  if (!audits) return <div className="qre-section" style={{ color: "#9ca3af" }}>Loading…</div>;
  if (!audits.length) return <div className="qre-section" style={{ color: "#9ca3af" }}>No audits recorded yet.</div>;

  return (
    <div className="qre-section">
      <h3 className="qre-section-title">All Respondents ({audits.length})</h3>
      <div className="qre-table-wrap">
        <table className="qre-table">
          <thead>
            <tr>
              <th style={{ width: 32 }}></th>
              <th>Branch</th>
              <th>City / State</th>
              <th>Shopper</th>
              <th>Date</th>
              <th>Type</th>
              <th>Status</th>
              <th>Score</th>
            </tr>
          </thead>
          <tbody>
            {audits.map((a) => {
              const vd = a.visit_details || {};
              const isOpen = expanded === a.id;
              const { total, totalMax } = (() => { let t = 0, m = 0; ALL_SECTIONS.forEach((s) => { const r = calcSectionScore(s, a.responses || {}); t += r.score; m += (r.max || s.maxPossible); }); return { total: t, totalMax: m }; })();
              const pct = totalMax > 0 ? Math.round(total / totalMax * 100) : null;
              const { color } = pct !== null ? ratingMeta(pct) : { color: "#9ca3af" };
              return [
                <tr key={a.id} style={{ cursor: "pointer", background: isOpen ? "#f8faff" : undefined }}
                  onClick={() => setExpanded(isOpen ? null : a.id)}>
                  <td style={{ textAlign: "center", color: "#9ca3af", fontSize: "0.75rem" }}>{isOpen ? "▲" : "▶"}</td>
                  <td style={{ fontWeight: 600 }}>{vd.branch_name || "—"}</td>
                  <td style={{ color: "#6b7280" }}>{vd.city_state || "—"}</td>
                  <td style={{ color: "#6b7280" }}>{vd.shopper_name || "—"}</td>
                  <td style={{ color: "#6b7280", fontSize: "0.8rem" }}>{vd.date_of_visit || "—"}</td>
                  <td style={{ fontSize: "0.78rem" }}>{vd.type_of_visit || "—"}</td>
                  <td>
                    <span className={`qre-badge ${a.status === "submitted" ? "qre-badge-live" : a.status === "draft" ? "qre-badge-draft" : "qre-badge-paused"}`}>
                      {a.status}
                    </span>
                  </td>
                  <td style={{ fontWeight: 700, color }}>{pct !== null ? `${pct}%` : "—"}</td>
                </tr>,
                isOpen && (
                  <tr key={`${a.id}-detail`}>
                    <td colSpan={8} style={{ padding: "0 1.5rem 1rem", background: "#f8faff", borderTop: "none" }}>
                      <ResponseView audit={a} />
                    </td>
                  </tr>
                ),
              ];
            })}
          </tbody>
        </table>
      </div>
    </div>
  );
}

// ─── Main export — detail view with tabs ─────────────────────────────────────
const MS_TABS = ["Overview", "Quotas", "Respondents", "Live Link", "Export"];

export default function MysteryShoppingDetail({ audit: initialAudit, onBack }) {
  const [audit, setAudit] = useState(initialAudit);
  const [activeTab, setActiveTab] = useState("Overview");

  const handleSaved = (updated) => setAudit(updated);
  const vd = audit.visit_details || {};

  return (
    <div className="qre-root">
      {/* Header — identical structure to QRE study detail */}
      <div className="qre-page-header">
        <div>
          <button className="qre-btn qre-btn-outline qre-btn-sm"
            onClick={onBack}
            style={{ marginBottom: "0.5rem", fontSize: "0.78rem" }}>
            ← All Studies
          </button>
          <div className="qre-page-title-row">
            <span style={{ fontSize: "1.15rem" }}>🔍</span>
            <h1 className="qre-page-title">
              {vd.branch_name || "Mystery Shopping Audit"}
            </h1>
            <span className={`qre-badge ${audit.status === "submitted" ? "qre-badge-live" : "qre-badge-draft"}`}>
              {audit.status}
            </span>
          </div>
          <p className="qre-page-subtitle">
            Client: IDFC FIRST Bank
            {vd.city_state || vd.city ? ` · ${vd.city_state || vd.city}` : ""}
            {vd.date_of_visit ? ` · Visit: ${vd.date_of_visit}` : ""}
          </p>
        </div>
      </div>

      {/* Tabs */}
      <div className="qre-tabs">
        {MS_TABS.map((t) => (
          <button key={t} className={`qre-tab-btn ${activeTab === t ? "active" : ""}`}
            onClick={() => setActiveTab(t)}>{t}</button>
        ))}
      </div>

      {activeTab === "Overview"      && <MSOverviewTab audit={audit} />}
      {activeTab === "Quotas"        && <MSQuotasTab audit={audit} />}
      {activeTab === "Respondents"   && <RespondentsTab currentAuditId={audit.id} />}
      {activeTab === "Live Link"     && <LiveLinkTab auditId={audit.id} />}
      {activeTab === "Export"        && <MSExportTab auditId={audit.id} auditName={vd.branch_name} />}
    </div>
  );
}
