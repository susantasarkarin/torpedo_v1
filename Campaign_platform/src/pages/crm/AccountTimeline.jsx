/**
 * Account Timeline — master/detail view of the CRM central linking layer.
 *
 * Left: searchable account list (/api/crm/accounts).
 * Right: selected account's activities + open tasks, from
 *        /api/crm/timeline/account/{id}. This is the clearest demonstration
 *        that activities/tasks link back to canonical objects.
 */
import { useEffect, useState, useCallback } from "react";
import {
  Building2,
  Search,
  Mail,
  Phone,
  FileText,
  CheckSquare,
  Clock,
} from "lucide-react";
import api from "../../utils/api";

const ACTIVITY_ICONS = {
  email: Mail,
  call: Phone,
  note: FileText,
  rfq_created: FileText,
  opportunity_won: FileText,
};

function ActivityRow({ act }) {
  const Icon = ACTIVITY_ICONS[act.type] || FileText;
  return (
    <li className="relative flex gap-3 pb-4">
      <div className="flex h-7 w-7 flex-shrink-0 items-center justify-center rounded-full bg-indigo-50 text-indigo-600">
        <Icon className="h-3.5 w-3.5" />
      </div>
      <div className="min-w-0 flex-1">
        <div className="flex items-center gap-2">
          <span className="rounded bg-gray-100 px-1.5 py-0.5 text-xs text-gray-600">{act.type}</span>
          <span className="truncate text-sm font-medium text-gray-900">{act.subject || "—"}</span>
        </div>
        {act.description && <p className="mt-0.5 text-sm text-gray-600">{act.description}</p>}
        <span className="mt-0.5 flex items-center gap-1 text-xs text-gray-400">
          <Clock className="h-3 w-3" />
          {act.created_at ? new Date(act.created_at).toLocaleString() : ""}
        </span>
      </div>
    </li>
  );
}

export default function AccountTimeline() {
  const [accounts, setAccounts] = useState([]);
  const [search, setSearch] = useState("");
  const [selected, setSelected] = useState(null);
  const [timeline, setTimeline] = useState(null);
  const [loadingAccounts, setLoadingAccounts] = useState(true);
  const [loadingTimeline, setLoadingTimeline] = useState(false);
  const [error, setError] = useState(null);

  useEffect(() => {
    (async () => {
      try {
        const data = await api.get("/api/crm/accounts", { limit: 1000 });
        const list = Array.isArray(data) ? data : [];
        setAccounts(list);
        if (list.length) setSelected(list[0]);
      } catch (e) {
        setError(e.message || "Failed to load accounts");
      } finally {
        setLoadingAccounts(false);
      }
    })();
  }, []);

  const loadTimeline = useCallback(async (accountId) => {
    setLoadingTimeline(true);
    try {
      const data = await api.get(`/api/crm/timeline/account/${accountId}`);
      setTimeline(data);
    } catch (e) {
      setError(e.message || "Failed to load timeline");
    } finally {
      setLoadingTimeline(false);
    }
  }, []);

  useEffect(() => {
    if (selected?._id) loadTimeline(selected._id);
  }, [selected, loadTimeline]);

  const filtered = accounts.filter((a) =>
    (a.name || "").toLowerCase().includes(search.toLowerCase())
  );

  return (
    <div className="p-6">
      <div className="mb-5">
        <h1 className="text-xl font-semibold text-gray-900">Account Timeline</h1>
        <p className="text-sm text-gray-500">Activities and tasks linked to each account.</p>
      </div>

      {error && (
        <div className="mb-4 rounded-md bg-red-50 px-4 py-2 text-sm text-red-700">{error}</div>
      )}

      <div className="grid grid-cols-1 gap-4 md:grid-cols-[18rem_1fr]">
        {/* Account list */}
        <div className="rounded-lg border border-gray-200 bg-white shadow-sm">
          <div className="border-b border-gray-100 p-2">
            <div className="flex items-center gap-2 rounded-md bg-gray-50 px-2 py-1.5">
              <Search className="h-4 w-4 text-gray-400" />
              <input
                value={search}
                onChange={(e) => setSearch(e.target.value)}
                placeholder="Search accounts…"
                className="w-full bg-transparent text-sm outline-none"
              />
            </div>
          </div>
          <ul className="max-h-[28rem] overflow-y-auto">
            {loadingAccounts ? (
              <li className="px-3 py-4 text-sm text-gray-500">Loading…</li>
            ) : filtered.length === 0 ? (
              <li className="px-3 py-4 text-sm text-gray-500">No accounts.</li>
            ) : (
              filtered.map((a) => (
                <li key={a._id}>
                  <button
                    onClick={() => setSelected(a)}
                    className={`flex w-full items-center gap-2 px-3 py-2 text-left text-sm hover:bg-gray-50 ${
                      selected?._id === a._id ? "bg-indigo-50 text-indigo-700" : "text-gray-700"
                    }`}
                  >
                    <Building2 className="h-4 w-4 flex-shrink-0 text-gray-400" />
                    <span className="truncate">{a.name || "(unnamed)"}</span>
                  </button>
                </li>
              ))
            )}
          </ul>
        </div>

        {/* Timeline detail */}
        <div className="rounded-lg border border-gray-200 bg-white p-4 shadow-sm">
          {!selected ? (
            <p className="py-12 text-center text-sm text-gray-500">Select an account.</p>
          ) : (
            <>
              <div className="mb-4 border-b border-gray-100 pb-3">
                <h2 className="text-lg font-semibold text-gray-900">{selected.name}</h2>
                <div className="mt-1 flex flex-wrap gap-2 text-xs text-gray-500">
                  {selected.account_type && (
                    <span className="rounded-full bg-gray-100 px-2 py-0.5 capitalize">
                      {selected.account_type}
                    </span>
                  )}
                  {selected.website && <span>{selected.website}</span>}
                </div>
              </div>

              {loadingTimeline ? (
                <p className="text-sm text-gray-500">Loading timeline…</p>
              ) : (
                <>
                  {/* Open tasks */}
                  {timeline?.tasks?.length > 0 && (
                    <div className="mb-5">
                      <h3 className="mb-2 flex items-center gap-1.5 text-sm font-semibold text-gray-700">
                        <CheckSquare className="h-4 w-4 text-amber-500" /> Tasks ({timeline.tasks.length})
                      </h3>
                      <ul className="space-y-1.5">
                        {timeline.tasks.map((t) => (
                          <li
                            key={t._id}
                            className="flex items-center gap-2 rounded-md border border-gray-100 px-3 py-1.5 text-sm"
                          >
                            <span className="flex-1 truncate text-gray-800">{t.title}</span>
                            <span className="rounded-full bg-gray-100 px-2 py-0.5 text-xs capitalize text-gray-600">
                              {t.status}
                            </span>
                          </li>
                        ))}
                      </ul>
                    </div>
                  )}

                  {/* Activity timeline */}
                  <h3 className="mb-3 flex items-center gap-1.5 text-sm font-semibold text-gray-700">
                    <Clock className="h-4 w-4 text-indigo-500" /> Activity
                  </h3>
                  {timeline?.activities?.length > 0 ? (
                    <ul className="relative border-l border-gray-100 pl-1">
                      {timeline.activities.map((act) => (
                        <ActivityRow key={act._id} act={act} />
                      ))}
                    </ul>
                  ) : (
                    <p className="text-sm text-gray-500">
                      No activity linked to this account yet.
                    </p>
                  )}
                </>
              )}
            </>
          )}
        </div>
      </div>
    </div>
  );
}
