/**
 * CRM Dashboard — overview of the canonical CRM spine.
 *
 * Consumes the Phase 2 backend (/api/crm/*): object counts + recent activity.
 * Data lives in the dedicated crm_db; until the legacy migration is run it will
 * show empty/zero states, which is expected.
 */
import { useEffect, useState } from "react";
import { Link } from "react-router-dom";
import {
  Building2,
  Users,
  UserPlus,
  Target,
  Activity as ActivityIcon,
  KanbanSquare,
  ArrowRight,
} from "lucide-react";
import api from "../../utils/api";

const CARDS = [
  { key: "accounts", label: "Accounts", icon: Building2, color: "text-indigo-600" },
  { key: "contacts", label: "Contacts", icon: Users, color: "text-sky-600" },
  { key: "leads", label: "Leads", icon: UserPlus, color: "text-emerald-600" },
  { key: "opportunities", label: "Opportunities", icon: Target, color: "text-amber-600" },
];

export default function CrmDashboard() {
  const [counts, setCounts] = useState({});
  const [activities, setActivities] = useState([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(null);

  useEffect(() => {
    (async () => {
      try {
        const [accounts, contacts, leads, opportunities, recent] = await Promise.all([
          api.get("/api/crm/accounts", { limit: 1000 }),
          api.get("/api/crm/contacts", { limit: 1000 }),
          api.get("/api/crm/leads", { limit: 1000 }),
          api.get("/api/crm/opportunities", { limit: 1000 }),
          api.get("/api/crm/activities", { limit: 12 }),
        ]);
        setCounts({
          accounts: accounts.length,
          contacts: contacts.length,
          leads: leads.length,
          opportunities: opportunities.length,
        });
        setActivities(Array.isArray(recent) ? recent : []);
      } catch (e) {
        setError(e.message || "Failed to load CRM data");
      } finally {
        setLoading(false);
      }
    })();
  }, []);

  return (
    <div className="p-6">
      <div className="mb-6 flex items-center justify-between">
        <div>
          <h1 className="text-xl font-semibold text-gray-900">CRM Dashboard</h1>
          <p className="text-sm text-gray-500">Canonical accounts, contacts, leads and opportunities.</p>
        </div>
        <div className="flex gap-2">
          <Link
            to="/admin/crm/accounts"
            className="inline-flex items-center gap-1.5 rounded-md border border-gray-300 px-3 py-1.5 text-sm font-medium text-gray-700 hover:bg-gray-50"
          >
            <Building2 className="h-4 w-4" /> Accounts
          </Link>
          <Link
            to="/admin/crm/pipeline"
            className="inline-flex items-center gap-1.5 rounded-md bg-indigo-600 px-3 py-1.5 text-sm font-medium text-white hover:bg-indigo-700"
          >
            <KanbanSquare className="h-4 w-4" /> Pipeline
          </Link>
        </div>
      </div>

      {error && (
        <div className="mb-4 rounded-md bg-red-50 px-4 py-2 text-sm text-red-700">{error}</div>
      )}

      <div className="mb-8 grid grid-cols-2 gap-4 md:grid-cols-4">
        {CARDS.map((card) => {
          const CardIcon = card.icon;
          return (
            <div key={card.key} className="rounded-lg border border-gray-200 bg-white p-4 shadow-sm">
              <div className="flex items-center justify-between">
                <span className="text-sm font-medium text-gray-500">{card.label}</span>
                <CardIcon className={`h-5 w-5 ${card.color}`} />
              </div>
              <div className="mt-2 text-3xl font-semibold text-gray-900">
                {loading ? "—" : (counts[card.key] ?? 0)}
              </div>
            </div>
          );
        })}
      </div>

      <div className="rounded-lg border border-gray-200 bg-white shadow-sm">
        <div className="flex items-center gap-2 border-b border-gray-100 px-4 py-3">
          <ActivityIcon className="h-4 w-4 text-gray-400" />
          <h2 className="text-sm font-semibold text-gray-900">Recent activity</h2>
        </div>
        {loading ? (
          <p className="px-4 py-6 text-sm text-gray-500">Loading…</p>
        ) : activities.length === 0 ? (
          <p className="px-4 py-6 text-sm text-gray-500">
            No activity yet. Run the legacy migration / agents to populate the spine.
          </p>
        ) : (
          <ul className="divide-y divide-gray-100">
            {activities.map((a) => (
              <li key={a._id} className="flex items-center gap-3 px-4 py-2.5 text-sm">
                <span className="rounded bg-gray-100 px-1.5 py-0.5 text-xs text-gray-600">{a.type}</span>
                <span className="flex-1 truncate text-gray-800">{a.subject || a.description || "—"}</span>
                <span className="text-xs text-gray-400">
                  {a.created_at ? new Date(a.created_at).toLocaleString() : ""}
                </span>
              </li>
            ))}
          </ul>
        )}
      </div>

      <p className="mt-4 text-xs text-gray-400">
        <Link to="/admin/ai/approvals" className="inline-flex items-center gap-1 hover:text-gray-600">
          AI Approvals queue <ArrowRight className="h-3 w-3" />
        </Link>
      </p>
    </div>
  );
}
