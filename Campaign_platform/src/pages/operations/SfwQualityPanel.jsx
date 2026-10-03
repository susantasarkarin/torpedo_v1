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
  client_reject: "Client rejected",
};

const BANDS = [
  { key: "good", label: "Good" },
  { key: "review", label: "Review" },
  { key: "block", label: "Block" },
  { key: "unscored", label: "Not scored" },
];

// SFW respondent quality for one project + client reconciliation upload.
export default function SfwQualityPanel({ surveyNo }) {
  const [data, setData] = useState(null);
  const [rejectIds, setRejectIds] = useState("");
  const [reason, setReason] = useState("");
  const [saving, setSaving] = useState(false);

  const load = useCallback(() => {
    if (!surveyNo) return;
    authFetch(buildApiUrl(`/api/sfw/projects/${encodeURIComponent(surveyNo)}/quality`), {
      headers: { Authorization: localStorage.getItem("session_id") || "" },
    })
      .then((r) => (r.ok ? r.json() : null))
      .then((d) => d && setData(d))
      .catch(() => {});
  }, [surveyNo]);

  useEffect(() => { load(); }, [load]);

  const submitRejects = async () => {
    const ids = rejectIds.split(/[\s,;]+/).filter(Boolean);
    if (!ids.length) return;
    setSaving(true);
    try {
      const res = await authFetch(buildApiUrl(`/api/sfw/projects/${encodeURIComponent(surveyNo)}/client-rejects`), {
        method: "POST",
        headers: { "Content-Type": "application/json", Authorization: localStorage.getItem("session_id") || "" },
        body: JSON.stringify({ ids, reason }),
      });
      const out = await res.json();
      if (!res.ok) throw new Error(out.detail || "Upload failed");
      notify(`Marked ${out.matched} respondent(s) as client-rejected` +
        (out.unmatched?.length ? ` · ${out.unmatched.length} ID(s) not found in this project` : ""));
      setRejectIds("");
      setReason("");
      load();
    } catch (err) {
      notify(err.message);
    } finally {
      setSaving(false);
    }
  };

  if (!data) return null;
  const { settings, bands, flags, flagged } = data;
  const mode = !settings.enabled ? "Off" : settings.enforced ? "Enforcing" : "Flag only";

  return (
    <div className="pd-section sfwq">
      <h4 className="pd-section-title">
        <ShieldCheck size={14} /> Respondent quality (SFW score)
        <span className={`sfwq-mode sfwq-mode-${mode.replace(" ", "-").toLowerCase()}`}>{mode}</span>
      </h4>
      <p className="sfwq-note">
        Block below {settings.blockBelow}, review below {settings.reviewBelow}.
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
              <tr><th>RID</th><th>Respondent</th><th>Status</th><th>Score</th><th>Flags</th><th>Entered</th></tr>
            </thead>
            <tbody>
              {flagged.map((r) => (
                <tr key={r._id}>
                  <td className="mono">{r._id}</td>
                  <td className="mono">{r.respondentId || "—"}</td>
                  <td>{r.clientRejected ? "REJECTED" : r.status}</td>
                  <td><span className={`sfwq-score sfwq-band-${r.sfwBand}`}>{r.sfwScore}</span></td>
                  <td>{(r.sfwFlags || []).map((f) => FLAG_LABELS[f] || f).join(", ")}</td>
                  <td>{r.createdAt ? new Date(r.createdAt).toLocaleString() : "—"}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}

      <div className="sfwq-rejects">
        <label className="sfwq-rejects-label" htmlFor="sfwq-ids">Client reconciliation: rejected IDs</label>
        <textarea
          id="sfwq-ids"
          className="sfwq-textarea"
          rows={3}
          placeholder="Paste RIDs or respondent IDs, separated by commas, spaces or new lines"
          value={rejectIds}
          onChange={(e) => setRejectIds(e.target.value)}
        />
        <div className="sfwq-rejects-row">
          <input
            className="sfwq-input"
            placeholder="Reason (optional), e.g. straight-lining"
            value={reason}
            onChange={(e) => setReason(e.target.value)}
          />
          <button className="sfwq-btn" disabled={saving || !rejectIds.trim()} onClick={submitRejects}>
            {saving ? "Saving…" : "Mark rejected"}
          </button>
        </div>
      </div>
    </div>
  );
}
