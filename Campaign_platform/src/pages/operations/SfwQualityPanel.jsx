import { useCallback, useEffect, useState } from "react";
import { ShieldCheck } from "lucide-react";
import { buildApiUrl } from "../../config";
import { authFetch } from "../../utils/api";
import { notify } from "../../utils/notify";
import "./SfwQualityPanel.css";

const FLAG_LABELS = {
  already_completed: "Already completed this project",
  reentry: "Re-entered this project",
  reentry_after_terminate: "Re-entered after terminate",
  answer_change: "Changed DOB / gender",
  device_ip_repeat: "Same device + IP again",
  bot_webdriver: "Automated browser",
  bot_headless: "Headless browser",
  bot_no_languages: "No browser languages",
  ip_velocity_high: "IP: >20 entries / hour",
  ip_velocity: "IP: >5 entries / hour",
  visitor_velocity: "Visitor: >3 entries / hour",
  geo_mismatch: "IP country ≠ project country",
  vpn_proxy: "VPN / proxy",
  tor: "Tor",
  datacenter_ip: "Datacenter IP",
  ip_high_fraud: "High-risk IP",
  ip_recent_abuse: "IP with recent abuse",
  prior_client_reject: "Rejected by a client before",
  terminate_history: "Many recent terminates",
  speeder: "Speeder (< ⅓ LOI)",
};

const BANDS = [
  { key: "good", label: "Good" },
  { key: "review", label: "Review" },
  { key: "block", label: "Block" },
  { key: "unscored", label: "Not scored" },
];

const DIMENSIONS = [
  { key: "vendor", label: "Vendor" },
  { key: "source", label: "Source" },
  { key: "campaign", label: "Meta campaign" },
  { key: "adset", label: "Ad set" },
  { key: "ad", label: "Ad" },
];

const pct = (v) => (v === null || v === undefined ? "—" : `${(v * 100).toFixed(1)}%`);

const authHeaders = (extra = {}) => ({ Authorization: localStorage.getItem("session_id") || "", ...extra });

// SFW respondent quality for one project: SFW-B behaviour score, traffic quality
// by vendor / source / Meta campaign, and the client reconciliation upload.
export default function SfwQualityPanel({ surveyNo }) {
  const [data, setData] = useState(null);
  const [traffic, setTraffic] = useState(null);
  const [dimension, setDimension] = useState("vendor");
  const [rejectText, setRejectText] = useState("");
  const [defaultReason, setDefaultReason] = useState("");
  const [saving, setSaving] = useState(false);

  const load = useCallback(() => {
    if (!surveyNo) return;
    const sn = encodeURIComponent(surveyNo);
    authFetch(buildApiUrl(`/api/sfw/projects/${sn}/quality`), { headers: authHeaders() })
      .then((r) => (r.ok ? r.json() : null))
      .then((d) => d && setData(d))
      .catch(() => {});
    authFetch(buildApiUrl(`/api/sfw/traffic-quality?pid=${sn}`), { headers: authHeaders() })
      .then((r) => (r.ok ? r.json() : null))
      .then((d) => d && setTraffic(d))
      .catch(() => {});
  }, [surveyNo]);

  useEffect(() => { load(); }, [load]);

  const submitRejects = async () => {
    if (!rejectText.trim()) return;
    setSaving(true);
    try {
      const res = await authFetch(buildApiUrl(`/api/sfw/projects/${encodeURIComponent(surveyNo)}/client-rejects`), {
        method: "POST",
        headers: authHeaders({ "Content-Type": "application/json" }),
        body: JSON.stringify({ text: rejectText, reason: defaultReason }),
      });
      const out = await res.json();
      if (!res.ok) throw new Error(out.detail || "Upload failed");
      notify(`Recorded ${out.matched} client reject(s)` +
        (out.unmatched?.length ? ` · ${out.unmatched.length} ID(s) not found in this project` : ""));
      setRejectText("");
      setDefaultReason("");
      load();
    } catch (err) {
      notify(err.message);
    } finally {
      setSaving(false);
    }
  };

  if (!data) return null;
  const { settings, scores, bands, flags, flagged } = data;
  const mode = !settings.enabled ? "Off" : settings.enforced ? "Enforcing" : "Flag only";
  const rows = traffic?.[dimension] || [];
  const overall = traffic?.overall;

  return (
    <div className="pd-section sfwq">
      <h4 className="pd-section-title">
        <ShieldCheck size={14} /> Respondent quality
        <span className={`sfwq-mode sfwq-mode-${mode.replace(" ", "-").toLowerCase()}`}>{mode}</span>
      </h4>

      <div className="sfwq-dims">
        {["B", "Q", "H"].map((k) => (
          <div key={k} className={`sfwq-dim ${scores?.[k]?.status === "live" ? "is-live" : ""}`}>
            <span className="sfwq-dim-code">SFW-{k}</span>
            <span className="sfwq-dim-label">{scores?.[k]?.label}</span>
            <span className="sfwq-dim-status">{scores?.[k]?.status === "live" ? "Live" : "Not built yet"}</span>
          </div>
        ))}
      </div>

      <p className="sfwq-note">
        Behaviour score (SFW-B): block below {settings.blockBelow}, review below {settings.reviewBelow}.
        {settings.enforced ? " Block-band entries are turned away." : " Nobody is turned away yet."}
      </p>

      <div className="sfwq-bands">
        {BANDS.map(({ key, label }) => (
          <div key={key} className={`sfwq-band sfwq-band-${key}`}>
            <span className="sfwq-band-label">{label}</span>
            <span className="sfwq-band-value">{bands[key]?.entries ?? 0}</span>
            <span className="sfwq-band-sub">{bands[key]?.completes ?? 0} completes</span>
          </div>
        ))}
      </div>

      {data.prescreen && (data.prescreen.checked > 0 || data.prescreen.routedIn > 0 || data.prescreen.routedOut > 0) && (
        <div className="sfwq-prescreen">
          <div className="sfwq-subtitle">Pre-screen &amp; routing</div>
          <div className="sfwq-bands">
            <div className="sfwq-band sfwq-band-good">
              <span className="sfwq-band-label">Qualification rate</span>
              <span className="sfwq-band-value">{pct(data.prescreen.rate)}</span>
              <span className="sfwq-band-sub">{data.prescreen.passed} of {data.prescreen.checked} checked</span>
            </div>
            <div className="sfwq-band sfwq-band-unscored">
              <span className="sfwq-band-label">Routed in</span>
              <span className="sfwq-band-value">{data.prescreen.routedIn}</span>
              <span className="sfwq-band-sub">from other surveys / router</span>
            </div>
            <div className="sfwq-band sfwq-band-unscored">
              <span className="sfwq-band-label">Routed out</span>
              <span className="sfwq-band-value">{data.prescreen.routedOut}</span>
              <span className="sfwq-band-sub">sent to other surveys</span>
            </div>
          </div>
          {Object.keys(data.prescreen.failReasons || {}).length > 0 && (
            <div className="sfwq-flags">
              {Object.entries(data.prescreen.failReasons).map(([reason, n]) => (
                <span key={reason} className="sfwq-flag">Failed: {reason.replace(/_/g, " ")} <b>{n}</b></span>
              ))}
            </div>
          )}
        </div>
      )}

      {traffic && (
        <div className="sfwq-traffic">
          <div className="sfwq-subtitle">Traffic quality</div>
          <div className="sfwq-tabs" role="tablist">
            {DIMENSIONS.map(({ key, label }) => (
              <button
                key={key}
                role="tab"
                aria-selected={dimension === key}
                className={`sfwq-tab ${dimension === key ? "is-active" : ""}`}
                onClick={() => setDimension(key)}
              >
                {label} <span className="sfwq-tab-count">{(traffic[key] || []).length}</span>
              </button>
            ))}
          </div>
          {rows.length === 0 ? (
            <p className="sfwq-note">
              {["campaign", "adset", "ad"].includes(dimension)
                ? "No Meta campaign data yet: the ad's URL parameters must include campaign_id / adset_id / ad_id."
                : "No traffic yet."}
            </p>
          ) : (
            <div className="sfwq-table-wrap">
              <table className="sfwq-table">
                <thead>
                  <tr>
                    <th>{DIMENSIONS.find((d) => d.key === dimension)?.label}</th>
                    <th>Entries</th><th>Completes</th><th>Complete %</th><th>Terminates</th>
                    <th>Flag %</th><th>Review %</th><th>Block %</th><th>Avg SFW-B</th>
                    <th>Rejects</th><th>Reject %</th>
                  </tr>
                </thead>
                <tbody>
                  {rows.map((r) => (
                    <tr key={String(r.key)}>
                      <td>{r.label || String(r.key ?? "—")}</td>
                      <td>{r.entries}</td><td>{r.completes}</td><td>{pct(r.completeRate)}</td>
                      <td>{r.terminates}</td><td>{pct(r.flagRate)}</td><td>{pct(r.reviewRate)}</td>
                      <td>{pct(r.blockRate)}</td><td>{r.avgSfwB ?? "—"}</td>
                      <td>{r.rejects}</td><td>{pct(r.rejectRate)}</td>
                    </tr>
                  ))}
                  {overall?.entries > 0 && (
                    <tr className="sfwq-total">
                      <td>Total</td>
                      <td>{overall.entries}</td><td>{overall.completes}</td><td>{pct(overall.completeRate)}</td>
                      <td>{overall.terminates}</td><td>{pct(overall.flagRate)}</td><td>{pct(overall.reviewRate)}</td>
                      <td>{pct(overall.blockRate)}</td><td>{overall.avgSfwB ?? "—"}</td>
                      <td>{overall.rejects}</td><td>{pct(overall.rejectRate)}</td>
                    </tr>
                  )}
                </tbody>
              </table>
            </div>
          )}
          <p className="sfwq-note">Flag / review / block rates are over scored entries; reject % = client rejects ÷ completes.</p>
        </div>
      )}

      {Object.keys(flags).length > 0 && (
        <div className="sfwq-flags">
          {Object.entries(flags).map(([flag, n]) => (
            <span key={flag} className="sfwq-flag">{FLAG_LABELS[flag] || flag} <b>{n}</b></span>
          ))}
        </div>
      )}

      {flagged.length > 0 && (
        <div className="sfwq-table-wrap">
          <table className="sfwq-table">
            <thead>
              <tr><th>RID</th><th>Respondent</th><th>Status</th><th>SFW-B</th><th>Flags</th><th>Client reject</th><th>Entered</th></tr>
            </thead>
            <tbody>
              {flagged.map((r) => (
                <tr key={r._id}>
                  <td className="mono">{r._id}</td>
                  <td className="mono">{r.respondentId || "—"}</td>
                  <td>{r.status}</td>
                  <td><span className={`sfwq-score sfwq-band-${r.sfwBand}`}>{r.sfwScore}</span></td>
                  <td>{(r.sfwFlags || []).map((f) => FLAG_LABELS[f] || f).join(", ")}</td>
                  <td>{r.clientRejected ? (r.clientRejectReason || "Rejected") : "—"}</td>
                  <td>{r.createdAt ? new Date(r.createdAt).toLocaleString() : "—"}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}

      <div className="sfwq-rejects">
        <label className="sfwq-rejects-label" htmlFor="sfwq-ids">Client reconciliation: rejected respondents</label>
        <p className="sfwq-note">
          One per line: <code>ID, reason</code> (reason optional, copied exactly as the client wrote it).
          ID = our RID or the vendor respondent ID. Rejects are recorded as outcomes; they don't change SFW-B.
        </p>
        <textarea
          id="sfwq-ids"
          className="sfwq-textarea"
          rows={4}
          placeholder={"6ac0aebf4d720f1b25ec43db, straight-lining in grid Q12\nad-23aac67c-f50e-451e-a59f-69265ec02d2c, failed attention check"}
          value={rejectText}
          onChange={(e) => setRejectText(e.target.value)}
        />
        <div className="sfwq-rejects-row">
          <input
            className="sfwq-input"
            placeholder="Reason for lines without one (optional)"
            value={defaultReason}
            onChange={(e) => setDefaultReason(e.target.value)}
          />
          <button className="sfwq-btn" disabled={saving || !rejectText.trim()} onClick={submitRejects}>
            {saving ? "Saving…" : "Record rejects"}
          </button>
        </div>
      </div>
    </div>
  );
}
