/**
 * Email Patterns Discovery
 * Path: /admin/sales/campaign/email-patterns
 * Discover email patterns from mail pool, lookup domains, guess emails
 */

import React, { useState, useEffect, useCallback } from "react";
import { buildApiUrl } from "../../../config";

const styles = {
  container: { padding: "24px", maxWidth: 1100, margin: "0 auto" },
  title: { fontSize: 22, fontWeight: 700, marginBottom: 20, color: "#1a1a2e" },
  statsGrid: { display: "grid", gridTemplateColumns: "repeat(auto-fit, minmax(150px, 1fr))", gap: 14, marginBottom: 28 },
  statCard: { background: "#fff", borderRadius: 10, padding: "18px 16px", textAlign: "center", boxShadow: "0 1px 4px rgba(0,0,0,0.07)" },
  statValue: { fontSize: 26, fontWeight: 700, color: "#4361ee" },
  statLabel: { fontSize: 12, color: "#666", marginTop: 4 },
  section: { background: "#fff", borderRadius: 10, padding: 22, marginBottom: 20, boxShadow: "0 1px 4px rgba(0,0,0,0.07)" },
  sectionTitle: { fontSize: 16, fontWeight: 600, marginBottom: 14, color: "#1a1a2e" },
  row: { display: "flex", gap: 12, alignItems: "flex-end", flexWrap: "wrap" },
  label: { fontSize: 13, fontWeight: 500, color: "#444", marginBottom: 4 },
  input: { padding: "8px 12px", borderRadius: 6, border: "1px solid #ddd", fontSize: 14, width: 240 },
  btn: { padding: "9px 18px", borderRadius: 6, border: "none", fontWeight: 600, fontSize: 14, cursor: "pointer", transition: "background 0.2s" },
  btnPrimary: { background: "#4361ee", color: "#fff" },
  btnSuccess: { background: "#2ec4b6", color: "#fff" },
  btnWarning: { background: "#f77f00", color: "#fff" },
  result: { marginTop: 14, padding: 14, background: "#f8f9fa", borderRadius: 8, fontSize: 14 },
  table: { width: "100%", borderCollapse: "collapse", fontSize: 14 },
  th: { textAlign: "left", padding: "10px 12px", borderBottom: "2px solid #e9ecef", color: "#555", fontWeight: 600, fontSize: 12, textTransform: "uppercase" },
  td: { padding: "10px 12px", borderBottom: "1px solid #f0f0f0" },
  badge: (color) => ({ display: "inline-block", padding: "3px 10px", borderRadius: 12, fontSize: 12, fontWeight: 600, background: color, color: "#fff" }),
  confidenceBar: (pct, color) => ({ width: 80, height: 8, borderRadius: 4, background: "#e9ecef", position: "relative", display: "inline-block", verticalAlign: "middle", overflow: "hidden" }),
  confidenceFill: (pct, color) => ({ position: "absolute", left: 0, top: 0, height: "100%", width: `${pct}%`, borderRadius: 4, background: color }),
  emptyState: { textAlign: "center", padding: 40, color: "#999" },
  error: { color: "#e63946", background: "#fff0f0", padding: 12, borderRadius: 8, marginTop: 10, fontSize: 14 },
};

const confidenceColor = (c) => c >= 0.8 ? "#2ec4b6" : c >= 0.5 ? "#f77f00" : "#e63946";

export default function EmailPatterns() {
  const [stats, setStats] = useState(null);
  const [patterns, setPatterns] = useState([]);
  const [loading, setLoading] = useState(true);

  // Domain lookup
  const [lookupDomain, setLookupDomain] = useState("");
  const [lookupResult, setLookupResult] = useState(null);
  const [lookupLoading, setLookupLoading] = useState(false);

  // Email builder
  const [buildDomain, setBuildDomain] = useState("");
  const [buildName, setBuildName] = useState("");
  const [buildResult, setBuildResult] = useState(null);
  const [buildLoading, setBuildLoading] = useState(false);

  // Analyze
  const [analyzing, setAnalyzing] = useState(false);
  const [analyzeResult, setAnalyzeResult] = useState(null);

  // Scan AI Database
  const [scanningAI, setScanningAI] = useState(false);
  const [scanAIResult, setScanAIResult] = useState(null);

  // Apply to Bounced & Missing
  const [applying, setApplying] = useState(false);
  const [applyResult, setApplyResult] = useState(null);

  // Pattern list filters
  const [minConf, setMinConf] = useState(0);
  const [sortBy, setSortBy] = useState("confidence");

  const [error, setError] = useState(null);

  const sessionId = localStorage.getItem("session_id");
  const headers = { Authorization: sessionId, "Content-Type": "application/json" };

  const fetchStats = useCallback(async () => {
    try {
      const res = await fetch(buildApiUrl("/email-patterns/stats"), { headers });
      if (res.ok) setStats(await res.json());
    } catch (e) { console.error(e); }
  }, []);

  const fetchPatterns = useCallback(async () => {
    try {
      const res = await fetch(buildApiUrl(`/email-patterns/list?min_confidence=${minConf}&limit=200&sort_by=${sortBy}`), { headers });
      if (res.ok) {
        const data = await res.json();
        setPatterns(data.patterns || []);
      }
    } catch (e) { console.error(e); }
  }, [minConf, sortBy]);

  useEffect(() => {
    Promise.all([fetchStats(), fetchPatterns()]).finally(() => setLoading(false));
  }, []);

  useEffect(() => { fetchPatterns(); }, [minConf, sortBy]);

  const handleLookup = async () => {
    if (!lookupDomain.trim()) return;
    setLookupLoading(true); setLookupResult(null); setError(null);
    try {
      const res = await fetch(buildApiUrl(`/email-patterns/${encodeURIComponent(lookupDomain.trim())}`), { headers });
      if (res.ok) setLookupResult(await res.json());
      else setError("Lookup failed");
    } catch (e) { setError(e.message); }
    setLookupLoading(false);
  };

  const handleBuild = async () => {
    if (!buildDomain.trim() || !buildName.trim()) return;
    setBuildLoading(true); setBuildResult(null); setError(null);
    try {
      const res = await fetch(buildApiUrl(`/email-patterns/build-email/${encodeURIComponent(buildDomain.trim())}/${encodeURIComponent(buildName.trim())}`), { headers });
      if (res.ok) setBuildResult(await res.json());
      else setError("Build failed");
    } catch (e) { setError(e.message); }
    setBuildLoading(false);
  };

  const handleAnalyze = async () => {
    setAnalyzing(true); setAnalyzeResult(null); setError(null);
    try {
      const res = await fetch(buildApiUrl("/email-patterns/analyze-mail-pool?limit=5000&min_samples=3"), { method: "POST", headers });
      if (res.ok) {
        const data = await res.json();
        setAnalyzeResult(data);
        fetchStats();
        fetchPatterns();
      } else setError("Analysis failed");
    } catch (e) { setError(e.message); }
    setAnalyzing(false);
  };

  const handleScanAI = async () => {
    setScanningAI(true); setScanAIResult(null); setError(null);
    try {
      const res = await fetch(buildApiUrl("/email-patterns/scan-ai-database?limit=2000"), { method: "POST", headers });
      if (res.ok) {
        const data = await res.json();
        setScanAIResult(data);
        fetchStats();
        fetchPatterns();
      } else setError("AI scan failed");
    } catch (e) { setError(e.message); }
    setScanningAI(false);
  };

  const handleApplyToLeads = async () => {
    setApplying(true); setApplyResult(null); setError(null);
    try {
      const res = await fetch(buildApiUrl("/email-patterns/apply-to-bounced-and-missing?limit=500"), { method: "POST", headers });
      if (res.ok) {
        const data = await res.json();
        setApplyResult(data);
      } else setError("Apply failed");
    } catch (e) { setError(e.message); }
    setApplying(false);
  };

  if (loading) return <div style={styles.container}><p>Loading...</p></div>;

  return (
    <div style={styles.container}>
      <h2 style={styles.title}>📧 Email Pattern Discovery</h2>

      {/* Stats */}
      {stats && (
        <div style={styles.statsGrid}>
          <div style={styles.statCard}><div style={styles.statValue}>{stats.total_domains}</div><div style={styles.statLabel}>Domains</div></div>
          <div style={styles.statCard}><div style={{ ...styles.statValue, color: "#2ec4b6" }}>{stats.high_confidence}</div><div style={styles.statLabel}>High Confidence</div></div>
          <div style={styles.statCard}><div style={{ ...styles.statValue, color: "#f77f00" }}>{stats.medium_confidence}</div><div style={styles.statLabel}>Medium</div></div>
          <div style={styles.statCard}><div style={{ ...styles.statValue, color: "#e63946" }}>{stats.low_confidence}</div><div style={styles.statLabel}>Low</div></div>
          <div style={styles.statCard}><div style={styles.statValue}>{stats.total_samples_analyzed}</div><div style={styles.statLabel}>Emails Analyzed</div></div>
          <div style={styles.statCard}><div style={styles.statValue}>{(stats.avg_confidence * 100).toFixed(0)}%</div><div style={styles.statLabel}>Avg Confidence</div></div>
        </div>
      )}

      {/* Analyze Mail Pool */}
      <div style={styles.section}>
        <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center" }}>
          <div>
            <div style={styles.sectionTitle}>🔍 Analyze Mail Pool</div>
            <p style={{ fontSize: 13, color: "#777", margin: 0 }}>Scan your mail pool to discover email patterns from known addresses. This learns how companies format their emails.</p>
          </div>
          <button
            style={{ ...styles.btn, ...styles.btnWarning, opacity: analyzing ? 0.6 : 1 }}
            onClick={handleAnalyze}
            disabled={analyzing}
          >
            {analyzing ? "Analyzing..." : "Run Analysis"}
          </button>
        </div>
        {analyzeResult && (
          <div style={styles.result}>
            ✅ Analyzed <b>{analyzeResult.analyzed}</b> emails across <b>{analyzeResult.unique_domains}</b> domains.
            Found <b>{analyzeResult.new_patterns}</b> new patterns, updated <b>{analyzeResult.updated_patterns || 0}</b>.
          </div>
        )}
      </div>

      {/* Scan AI Database */}
      <div style={styles.section}>
        <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center" }}>
          <div>
            <div style={styles.sectionTitle}>🤖 Scan AI Database</div>
            <p style={{ fontSize: 13, color: "#777", margin: 0 }}>Mine the AI-sourced leads database for confirmed emails to discover additional domain patterns.</p>
          </div>
          <button
            style={{ ...styles.btn, ...styles.btnWarning, opacity: scanningAI ? 0.6 : 1 }}
            onClick={handleScanAI}
            disabled={scanningAI}
          >
            {scanningAI ? "Scanning..." : "Scan AI Database"}
          </button>
        </div>
        {scanAIResult && (
          <div style={styles.result}>
            ✅ Scanned <b>{scanAIResult.domains_scanned}</b> domains — upserted <b>{scanAIResult.patterns_upserted}</b> patterns, skipped <b>{scanAIResult.patterns_skipped}</b>.
          </div>
        )}
      </div>

      {/* Apply to Bounced & Missing */}
      <div style={styles.section}>
        <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center" }}>
          <div>
            <div style={styles.sectionTitle}>🔄 Apply to Bounced & Missing</div>
            <p style={{ fontSize: 13, color: "#777", margin: 0 }}>Retry alternate email formats for bounced leads and generate emails for leads with missing addresses.</p>
          </div>
          <button
            style={{ ...styles.btn, ...styles.btnWarning, opacity: applying ? 0.6 : 1 }}
            onClick={handleApplyToLeads}
            disabled={applying}
          >
            {applying ? "Applying..." : "Apply Patterns"}
          </button>
        </div>
        {applyResult && (
          <div style={styles.result}>
            ✅ Bounced: <b>{applyResult.bounced_updated}</b> fixed ({applyResult.bounced_skipped} skipped).
            Missing: <b>{applyResult.missing_updated}</b> filled ({applyResult.missing_skipped} skipped).
            Total changes: <b>{applyResult.total_changes}</b>.
          </div>
        )}
      </div>

      {/* Domain Lookup + Email Builder side by side */}
      <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: 20, marginBottom: 20 }}>
        {/* Domain Lookup */}
        <div style={styles.section}>
          <div style={styles.sectionTitle}>🏢 Domain Lookup</div>
          <div style={styles.row}>
            <div>
              <div style={styles.label}>Domain</div>
              <input style={styles.input} placeholder="e.g. google.com" value={lookupDomain}
                onChange={e => setLookupDomain(e.target.value)}
                onKeyDown={e => e.key === "Enter" && handleLookup()} />
            </div>
            <button style={{ ...styles.btn, ...styles.btnPrimary, opacity: lookupLoading ? 0.6 : 1 }} onClick={handleLookup} disabled={lookupLoading}>
              {lookupLoading ? "..." : "Lookup"}
            </button>
          </div>
          {lookupResult && (
            <div style={styles.result}>
              {lookupResult.found ? (
                <>
                  <div><b>Pattern:</b> {lookupResult.pattern}</div>
                  <div><b>Confidence:</b> <span style={{ color: confidenceColor(lookupResult.confidence) }}>{(lookupResult.confidence * 100).toFixed(0)}%</span></div>
                  <div><b>Samples:</b> {lookupResult.sample_count}</div>
                  {lookupResult.sample_emails?.length > 0 && (
                    <div style={{ marginTop: 8 }}><b>Examples:</b> {lookupResult.sample_emails.map(s => s.email).join(", ")}</div>
                  )}
                </>
              ) : (
                <span style={{ color: "#999" }}>No pattern found for {lookupResult.domain}. Run analysis first.</span>
              )}
            </div>
          )}
        </div>

        {/* Email Builder */}
        <div style={styles.section}>
          <div style={styles.sectionTitle}>🛠️ Build Email</div>
          <div style={styles.row}>
            <div>
              <div style={styles.label}>Domain</div>
              <input style={{ ...styles.input, width: 160 }} placeholder="google.com" value={buildDomain}
                onChange={e => setBuildDomain(e.target.value)} />
            </div>
            <div>
              <div style={styles.label}>Full Name</div>
              <input style={{ ...styles.input, width: 180 }} placeholder="John Smith" value={buildName}
                onChange={e => setBuildName(e.target.value)}
                onKeyDown={e => e.key === "Enter" && handleBuild()} />
            </div>
            <button style={{ ...styles.btn, ...styles.btnSuccess, opacity: buildLoading ? 0.6 : 1 }} onClick={handleBuild} disabled={buildLoading}>
              {buildLoading ? "..." : "Generate"}
            </button>
          </div>
          {buildResult && (
            <div style={styles.result}>
              <div style={{ fontSize: 18, fontWeight: 700, color: "#4361ee" }}>{buildResult.email}</div>
              <div style={{ marginTop: 6 }}><b>Pattern:</b> {buildResult.pattern} · <b>Confidence:</b>{" "}
                <span style={{ color: confidenceColor(buildResult.confidence) }}>{(buildResult.confidence * 100).toFixed(0)}%</span>
                {buildResult.note && <span style={{ color: "#999" }}> — {buildResult.note}</span>}
              </div>
            </div>
          )}
        </div>
      </div>

      {error && <div style={styles.error}>{error}</div>}

      {/* Patterns List */}
      <div style={styles.section}>
        <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", marginBottom: 14 }}>
          <div style={styles.sectionTitle}>📋 Discovered Patterns ({patterns.length})</div>
          <div style={{ display: "flex", gap: 12, alignItems: "center" }}>
            <select style={{ ...styles.input, width: 140 }} value={minConf} onChange={e => setMinConf(parseFloat(e.target.value))}>
              <option value={0}>All confidence</option>
              <option value={0.5}>≥ 50%</option>
              <option value={0.8}>≥ 80%</option>
            </select>
            <select style={{ ...styles.input, width: 140 }} value={sortBy} onChange={e => setSortBy(e.target.value)}>
              <option value="confidence">Sort: Confidence</option>
              <option value="sample_count">Sort: Samples</option>
              <option value="domain">Sort: Domain</option>
            </select>
          </div>
        </div>

        {patterns.length === 0 ? (
          <div style={styles.emptyState}>No patterns discovered yet. Click "Run Analysis" above to scan your mail pool.</div>
        ) : (
          <table style={styles.table}>
            <thead>
              <tr>
                <th style={styles.th}>Domain</th>
                <th style={styles.th}>Pattern</th>
                <th style={styles.th}>Confidence</th>
                <th style={styles.th}>Samples</th>
                <th style={styles.th}>Last Updated</th>
              </tr>
            </thead>
            <tbody>
              {patterns.map((p, i) => {
                const c = p.confidence || 0;
                const color = confidenceColor(c);
                return (
                  <tr key={i} style={{ background: i % 2 === 0 ? "#fff" : "#fafafa" }}>
                    <td style={styles.td}><b>{p.domain}</b></td>
                    <td style={styles.td}><code style={{ background: "#f0f0f0", padding: "2px 6px", borderRadius: 4 }}>{p.pattern}</code></td>
                    <td style={styles.td}>
                      <div style={{ display: "flex", alignItems: "center", gap: 8 }}>
                        <div style={styles.confidenceBar(c * 100, color)}>
                          <div style={styles.confidenceFill(c * 100, color)} />
                        </div>
                        <span style={{ color, fontWeight: 600 }}>{(c * 100).toFixed(0)}%</span>
                      </div>
                    </td>
                    <td style={styles.td}>{p.sample_count}</td>
                    <td style={styles.td}><span style={{ color: "#999", fontSize: 12 }}>{p.last_updated ? new Date(p.last_updated).toLocaleDateString() : "—"}</span></td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        )}
      </div>
    </div>
  );
}
