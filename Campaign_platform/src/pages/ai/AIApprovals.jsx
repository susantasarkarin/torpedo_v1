/**
 * AI Approvals — human-in-the-loop queue for the AI decision engine.
 *
 * Consumes the Phase 4 backend:
 *   GET  /api/ai/queue?status=pending      -> pending actions awaiting approval
 *   POST /api/ai/queue/{id}/approve        -> approve (executes the action)
 *   POST /api/ai/queue/{id}/reject         -> reject (with optional reason)
 *   GET  /api/ai/decisions                 -> the full AI decision log
 *   GET  /api/ai/agents                    -> registered agents + autonomy modes
 *
 * Safety: nothing in the queue has executed yet — the operator decides.
 */
import { useEffect, useState, useCallback } from "react";
import {
  CheckCircle2,
  XCircle,
  RefreshCw,
  Bot,
  ShieldAlert,
  ListChecks,
  History,
} from "lucide-react";
import api from "../../utils/api";

const STATUS_STYLES = {
  pending: "bg-amber-100 text-amber-800",
  executed: "bg-green-100 text-green-800",
  approved: "bg-green-100 text-green-800",
  rejected: "bg-red-100 text-red-800",
  failed: "bg-red-100 text-red-800",
  recommended: "bg-blue-100 text-blue-800",
  observed: "bg-gray-100 text-gray-700",
};

const RISK_STYLES = {
  low: "bg-green-50 text-green-700 border border-green-200",
  medium: "bg-amber-50 text-amber-700 border border-amber-200",
  high: "bg-red-50 text-red-700 border border-red-200",
};

const Badge = ({ value, map }) => (
  <span
    className={`inline-block rounded-full px-2 py-0.5 text-xs font-medium ${
      map[value] || "bg-gray-100 text-gray-700"
    }`}
  >
    {value || "—"}
  </span>
);

function PendingQueue() {
  const [items, setItems] = useState([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(null);
  const [actingId, setActingId] = useState(null);

  const load = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const data = await api.get("/api/ai/queue", { status: "pending" });
      setItems(Array.isArray(data) ? data : []);
    } catch (e) {
      setError(e.message || "Failed to load queue");
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    load();
  }, [load]);

  const decide = async (id, approve) => {
    let reason = null;
    if (!approve) {
      reason = window.prompt("Reason for rejection (optional):") || null;
    }
    setActingId(id);
    try {
      if (approve) {
        await api.post(`/api/ai/queue/${id}/approve`);
      } else {
        await api.post(`/api/ai/queue/${id}/reject`, { reason });
      }
      // Optimistically drop the resolved item.
      setItems((prev) => prev.filter((it) => it._id !== id));
    } catch (e) {
      setError(e.message || "Action failed");
    } finally {
      setActingId(null);
    }
  };

  return (
    <div>
      <div className="mb-4 flex items-center justify-between">
        <p className="text-sm text-gray-500">
          {loading ? "Loading…" : `${items.length} action${items.length === 1 ? "" : "s"} awaiting approval`}
        </p>
        <button
          onClick={load}
          className="inline-flex items-center gap-1.5 rounded-md border border-gray-300 px-3 py-1.5 text-sm font-medium text-gray-700 hover:bg-gray-50"
        >
          <RefreshCw className="h-4 w-4" /> Refresh
        </button>
      </div>

      {error && (
        <div className="mb-4 rounded-md bg-red-50 px-4 py-2 text-sm text-red-700">{error}</div>
      )}

      {!loading && items.length === 0 && !error && (
        <div className="rounded-lg border border-dashed border-gray-300 py-12 text-center text-gray-500">
          <CheckCircle2 className="mx-auto mb-2 h-8 w-8 text-green-400" />
          Nothing pending. The AI queue is clear.
        </div>
      )}

      <div className="space-y-3">
        {items.map((item) => (
          <div
            key={item._id}
            className="rounded-lg border border-gray-200 bg-white p-4 shadow-sm"
          >
            <div className="flex flex-wrap items-center gap-2">
              <span className="inline-flex items-center gap-1.5 font-medium text-gray-900">
                <Bot className="h-4 w-4 text-indigo-500" />
                {item.agent_name}
              </span>
              <code className="rounded bg-gray-100 px-1.5 py-0.5 text-xs text-gray-700">
                {item.action_type}
              </code>
              <Badge value={item.risk} map={RISK_STYLES} />
              <Badge value={item.autonomy_mode} map={STATUS_STYLES} />
              <span className="ml-auto text-xs text-gray-400">
                {item.created_at ? new Date(item.created_at).toLocaleString() : ""}
              </span>
            </div>

            {item.payload && (
              <pre className="mt-3 max-h-40 overflow-auto rounded bg-gray-50 p-3 text-xs text-gray-600">
                {JSON.stringify(item.payload, null, 2)}
              </pre>
            )}

            <div className="mt-3 flex gap-2">
              <button
                disabled={actingId === item._id}
                onClick={() => decide(item._id, true)}
                className="inline-flex items-center gap-1.5 rounded-md bg-green-600 px-3 py-1.5 text-sm font-medium text-white hover:bg-green-700 disabled:opacity-50"
              >
                <CheckCircle2 className="h-4 w-4" /> Approve & execute
              </button>
              <button
                disabled={actingId === item._id}
                onClick={() => decide(item._id, false)}
                className="inline-flex items-center gap-1.5 rounded-md border border-red-300 px-3 py-1.5 text-sm font-medium text-red-700 hover:bg-red-50 disabled:opacity-50"
              >
                <XCircle className="h-4 w-4" /> Reject
              </button>
            </div>
          </div>
        ))}
      </div>
    </div>
  );
}

function DecisionLog() {
  const [decisions, setDecisions] = useState([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(null);

  useEffect(() => {
    (async () => {
      try {
        const data = await api.get("/api/ai/decisions", { limit: 200 });
        setDecisions(Array.isArray(data) ? data : []);
      } catch (e) {
        setError(e.message || "Failed to load decisions");
      } finally {
        setLoading(false);
      }
    })();
  }, []);

  if (loading) return <p className="text-sm text-gray-500">Loading…</p>;
  if (error) return <div className="rounded-md bg-red-50 px-4 py-2 text-sm text-red-700">{error}</div>;
  if (decisions.length === 0)
    return <p className="text-sm text-gray-500">No AI decisions logged yet.</p>;

  return (
    <div className="overflow-x-auto rounded-lg border border-gray-200">
      <table className="min-w-full divide-y divide-gray-200 text-sm">
        <thead className="bg-gray-50 text-left text-xs uppercase tracking-wide text-gray-500">
          <tr>
            <th className="px-4 py-2">Agent</th>
            <th className="px-4 py-2">Decision</th>
            <th className="px-4 py-2">Mode</th>
            <th className="px-4 py-2">Conf.</th>
            <th className="px-4 py-2">Status</th>
            <th className="px-4 py-2">When</th>
          </tr>
        </thead>
        <tbody className="divide-y divide-gray-100 bg-white">
          {decisions.map((d) => (
            <tr key={d._id} className="hover:bg-gray-50">
              <td className="px-4 py-2 font-medium text-gray-900">{d.agent_name}</td>
              <td className="px-4 py-2 text-gray-700">
                {d.decision}
                {d.reason && <span className="block text-xs text-gray-400">{d.reason}</span>}
              </td>
              <td className="px-4 py-2">
                <Badge value={d.autonomy_mode} map={STATUS_STYLES} />
              </td>
              <td className="px-4 py-2 text-gray-600">
                {d.confidence != null ? `${Math.round(d.confidence * 100)}%` : "—"}
              </td>
              <td className="px-4 py-2">
                <Badge value={d.status} map={STATUS_STYLES} />
              </td>
              <td className="px-4 py-2 text-xs text-gray-400">
                {d.created_at ? new Date(d.created_at).toLocaleString() : ""}
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

export default function AIApprovals() {
  const [tab, setTab] = useState("queue");

  const tabs = [
    { key: "queue", label: "Approval Queue", icon: ListChecks },
    { key: "decisions", label: "Decision Log", icon: History },
  ];

  return (
    <div className="p-6">
      <div className="mb-6 flex items-center gap-3">
        <ShieldAlert className="h-7 w-7 text-indigo-600" />
        <div>
          <h1 className="text-xl font-semibold text-gray-900">AI Approvals</h1>
          <p className="text-sm text-gray-500">
            Review and approve AI-proposed actions. Nothing here has run yet.
          </p>
        </div>
      </div>

      <div className="mb-5 flex gap-1 border-b border-gray-200">
        {tabs.map((t) => {
          const TabIcon = t.icon;
          return (
            <button
              key={t.key}
              onClick={() => setTab(t.key)}
              className={`inline-flex items-center gap-1.5 border-b-2 px-4 py-2 text-sm font-medium ${
                tab === t.key
                  ? "border-indigo-600 text-indigo-600"
                  : "border-transparent text-gray-500 hover:text-gray-700"
              }`}
            >
              <TabIcon className="h-4 w-4" /> {t.label}
            </button>
          );
        })}
      </div>

      {tab === "queue" ? <PendingQueue /> : <DecisionLog />}
    </div>
  );
}
