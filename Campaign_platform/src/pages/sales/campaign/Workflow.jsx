/**
 * Workflow.jsx — Outreach Pipeline Funnel
 *
 * Stages:
 *   1. Imported        – leads ingested (CSV / web-search / Gmail)
 *   2. Email Ready     – leads that have a usable email (CSV or predicted)
 *   3. SFW Outreach    – emails sent from @surveyfieldwork.com
 *   4. Cogentix Reach  – emails sent from @cogentixresearch.com (non-bounce)
 *   5. Replied         – prospects who replied
 *   6. Enriched        – replied leads enriched & promoted to CRM
 */

import React, { useEffect, useState, useCallback } from "react";
import { buildApiUrl } from "../../../config";
import "./Workflow.css";

const sessionId = localStorage.getItem("session_id") || "";
const AUTH = () => ({ Authorization: sessionId });

const STAGE_ICONS = {
  imported:    "📥",
  email_ready: "📧",
  sfw:         "🏢",
  cogentix:    "🔬",
  replied:     "💬",
  enriched:    "✨",
};

const STAGE_DESC = {
  imported:    "All leads imported via CSV, web search, or Gmail",
  email_ready: "Leads with a confirmed or predicted email address",
  sfw:         "Emails sent from Survey Fieldwork domain",
  cogentix:    "Emails sent from Cogentix domain (non-bounced)",
  replied:     "Prospects who replied to an outreach email",
  enriched:    "Replied leads enriched and added to CRM",
};

export default function Workflow() {
  const [stages, setStages] = useState([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");
  const [lastRefresh, setLastRefresh] = useState(null);
  const [syncing, setSyncing] = useState(false);
  const [syncResult, setSyncResult] = useState(null);

  const fetchPipeline = useCallback(async () => {
    setLoading(true);
    setError("");
    try {
      const res = await fetch(buildApiUrl("/leads/pipeline"), { headers: AUTH() });
      if (!res.ok) throw new Error(`HTTP ${res.status}`);
      const data = await res.json();
      setStages(data.stages || []);
      setLastRefresh(new Date());
    } catch (e) {
      setError(e.message);
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    fetchPipeline();
  }, [fetchPipeline]);

  // Trigger bounce/reply scan + promote replied leads to CRM
  const handleSyncReplies = async () => {
    setSyncing(true);
    setSyncResult(null);
    try {
      // 1. Scan for new bounces/replies
      const scanRes = await fetch(buildApiUrl("/api/cold-outreach/scan-bounces-replies"), {
        method: "POST", headers: AUTH(),
      });
      const scanData = await scanRes.json();

      // 2. Promote replied leads to CRM
      const syncRes = await fetch(buildApiUrl("/api/cold-outreach/sync-replies-to-leads"), {
        method: "POST", headers: AUTH(),
      });
      const syncData = await syncRes.json();

      setSyncResult({
        replies: scanData.replies || 0,
        bounces: scanData.bounces || 0,
        promoted: syncData.promoted || 0,
      });

      // Refresh counts
      await fetchPipeline();
    } catch (e) {
      setSyncResult({ error: e.message });
    } finally {
      setSyncing(false);
    }
  };

  const maxCount = stages.length > 0 ? Math.max(...stages.map(s => s.count), 1) : 1;

  return (
    <div className="workflow-container">
      {/* Header */}
      <div className="workflow-header-v2">
        <div style={{ display: "flex", justifyContent: "space-between", alignItems: "flex-start" }}>
          <div>
            <h1>🔄 Outreach Pipeline</h1>
            <p>
              Full funnel from lead import through email prediction, SFW outreach, Cogentix
              outreach, and reply enrichment.
            </p>
            {lastRefresh && (
              <p style={{ fontSize: "0.8rem", color: "#9ca3af", marginTop: "0.25rem" }}>
                Last refreshed: {lastRefresh.toLocaleTimeString()}
              </p>
            )}
          </div>
          <div style={{ display: "flex", gap: "0.75rem", flexShrink: 0 }}>
            <button
              className="btn btn-outline"
              onClick={fetchPipeline}
              disabled={loading}
              style={{ padding: "0.5rem 1rem" }}
            >
              {loading ? "⏳ Loading…" : "🔄 Refresh"}
            </button>
            <button
              className="btn btn-primary"
              onClick={handleSyncReplies}
              disabled={syncing}
              style={{ padding: "0.5rem 1rem" }}
            >
              {syncing ? "⏳ Syncing…" : "📨 Scan & Sync Replies"}
            </button>
          </div>
        </div>

        {syncResult && (
          <div
            style={{
              marginTop: "1rem",
              padding: "0.75rem 1rem",
              borderRadius: "8px",
              backgroundColor: syncResult.error ? "#fee2e2" : "#f0fdf4",
              border: `1px solid ${syncResult.error ? "#fca5a5" : "#86efac"}`,
              fontSize: "0.875rem",
              color: syncResult.error ? "#dc2626" : "#166534",
            }}
          >
            {syncResult.error
              ? `❌ Error: ${syncResult.error}`
              : `✅ Scan done — ${syncResult.replies} new replies, ${syncResult.bounces} bounces detected, ${syncResult.promoted} leads promoted to CRM`}
          </div>
        )}
      </div>

      {error && (
        <div style={{ padding: "1rem", backgroundColor: "#fee2e2", borderRadius: "8px", color: "#dc2626", marginBottom: "1.5rem" }}>
          Failed to load pipeline: {error}
        </div>
      )}

      {/* Funnel Visualization */}
      {!loading && stages.length > 0 && (
        <>
          {/* Bar chart funnel */}
          <div
            style={{
              background: "white",
              borderRadius: "12px",
              border: "1px solid #e5e7eb",
              padding: "2rem",
              marginBottom: "1.5rem",
            }}
          >
            <h2 style={{ fontSize: "1.1rem", fontWeight: 600, marginBottom: "1.5rem", color: "#111827" }}>
              Pipeline Funnel
            </h2>
            <div style={{ display: "flex", flexDirection: "column", gap: "1rem" }}>
              {stages.map((stage, idx) => {
                const pct = Math.round((stage.count / maxCount) * 100);
                const convPct =
                  idx > 0 && stages[idx - 1].count > 0
                    ? Math.round((stage.count / stages[idx - 1].count) * 100)
                    : null;
                return (
                  <div key={stage.id}>
                    <div style={{ display: "flex", justifyContent: "space-between", marginBottom: "0.35rem", fontSize: "0.875rem" }}>
                      <span style={{ fontWeight: 600, color: "#374151" }}>
                        {STAGE_ICONS[stage.id]} {stage.label}
                      </span>
                      <span style={{ color: "#6b7280" }}>
                        <strong style={{ color: "#111827" }}>{stage.count.toLocaleString()}</strong>
                        {convPct !== null && (
                          <span style={{ marginLeft: "0.5rem", fontSize: "0.8rem", color: convPct >= 50 ? "#16a34a" : "#dc2626" }}>
                            ({convPct}% of prev)
                          </span>
                        )}
                      </span>
                    </div>
                    <div style={{ height: "28px", backgroundColor: "#f3f4f6", borderRadius: "6px", overflow: "hidden" }}>
                      <div
                        style={{
                          height: "100%",
                          width: `${pct}%`,
                          backgroundColor: stage.color,
                          borderRadius: "6px",
                          transition: "width 0.6s ease",
                          minWidth: stage.count > 0 ? "4px" : "0",
                        }}
                      />
                    </div>
                    <div style={{ fontSize: "0.75rem", color: "#9ca3af", marginTop: "0.25rem" }}>
                      {STAGE_DESC[stage.id]}
                    </div>
                  </div>
                );
              })}
            </div>
          </div>

          {/* Stage cards */}
          <div className="workflow-info">
            {stages.map((stage) => (
              <div key={stage.id} className="info-card" style={{ borderTop: `3px solid ${stage.color}` }}>
                <div className="label">{STAGE_ICONS[stage.id]} {stage.label}</div>
                <div className="value" style={{ color: stage.color }}>
                  {stage.count.toLocaleString()}
                </div>
              </div>
            ))}
          </div>

          {/* Pipeline flow arrows */}
          <div
            style={{
              background: "white",
              borderRadius: "12px",
              border: "1px solid #e5e7eb",
              padding: "1.5rem 2rem",
            }}
          >
            <h2 style={{ fontSize: "1.1rem", fontWeight: 600, marginBottom: "1rem", color: "#111827" }}>
              Pipeline Flow
            </h2>
            <div style={{ display: "flex", alignItems: "center", gap: "0", overflowX: "auto", paddingBottom: "0.5rem" }}>
              {stages.map((stage, idx) => (
                <React.Fragment key={stage.id}>
                  <div
                    style={{
                      flex: "0 0 auto",
                      textAlign: "center",
                      padding: "0.75rem 1rem",
                      borderRadius: "10px",
                      border: `2px solid ${stage.color}`,
                      backgroundColor: `${stage.color}18`,
                      minWidth: "110px",
                    }}
                  >
                    <div style={{ fontSize: "1.4rem" }}>{STAGE_ICONS[stage.id]}</div>
                    <div style={{ fontSize: "0.75rem", fontWeight: 600, color: "#374151", marginTop: "0.25rem" }}>
                      {stage.label}
                    </div>
                    <div style={{ fontSize: "1.1rem", fontWeight: 700, color: stage.color }}>
                      {stage.count.toLocaleString()}
                    </div>
                  </div>
                  {idx < stages.length - 1 && (
                    <div style={{ flex: "0 0 auto", color: "#d1d5db", fontSize: "1.5rem", padding: "0 0.25rem" }}>
                      →
                    </div>
                  )}
                </React.Fragment>
              ))}
            </div>
          </div>
        </>
      )}

      {loading && (
        <div style={{ textAlign: "center", padding: "3rem", color: "#6b7280" }}>
          ⏳ Loading pipeline data…
        </div>
      )}
    </div>
  );
}
