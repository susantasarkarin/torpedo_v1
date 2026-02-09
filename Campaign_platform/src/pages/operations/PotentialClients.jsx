import React, { useEffect, useMemo, useState } from "react";
import { useAuth } from "../../hooks/useAuth";
import { buildApiUrl } from "../../config";
import "./PotentialClients.css";

function PotentialClients() {
  const { user, token } = useAuth();
  const [surveys, setSurveys] = useState([]);
  const [clients, setClients] = useState([]);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState(null);
  const [search, setSearch] = useState("");

  useEffect(() => {
    if (token) {
      fetchAllSurveys();
      fetchClients();
    }
  }, [token]);

  const fetchAllSurveys = async () => {
    setLoading(true);
    setError(null);

    try {
      const cpxResponse = await fetch(buildApiUrl("/cpx/surveys?page=1&page_size=1000&show_all=true"), {
        headers: {
          Authorization: token,
          "Content-Type": "application/json",
        },
      });

      const cintQuery = "/api/cint/surveys?page=1&page_size=1000&show_all=true";
      const cintResponse = await fetch(buildApiUrl(cintQuery), {
        headers: {
          Authorization: token,
          "Content-Type": "application/json",
        },
      });

      let allSurveys = [];

      if (cpxResponse.ok) {
        const cpxData = await cpxResponse.json();
        const cpxSurveys = (cpxData.surveys || []).map((s) => ({ ...s, source: "CPX" }));
        allSurveys = allSurveys.concat(cpxSurveys);
      }

      let cintData = null;
      if (cintResponse.ok) {
        cintData = await cintResponse.json();
      } else {
        try {
          const fallbackUrl = `https://torpedo.cogentixresearch.com${cintQuery}`;
          const fallbackResponse = await fetch(fallbackUrl, {
            headers: {
              Authorization: token,
              "Content-Type": "application/json",
            },
          });
          if (fallbackResponse.ok) {
            cintData = await fallbackResponse.json();
          }
        } catch (fallbackError) {
          console.warn("CINT fallback fetch failed:", fallbackError);
        }
      }

      if (cintData) {
        const cintSurveys = (cintData.surveys || []).map((s) => ({ ...s, source: "CINT" }));
        allSurveys = allSurveys.concat(cintSurveys);
      }

      setSurveys(allSurveys);
    } catch (err) {
      console.error("Error fetching surveys:", err);
      setError(err.message);
    } finally {
      setLoading(false);
    }
  };

  const fetchClients = async () => {
    try {
      const response = await fetch(buildApiUrl("/finance/finance/customers/"), {
        headers: {
          Authorization: token,
          "Content-Type": "application/json",
        },
      });

      if (response.ok) {
        const data = await response.json();
        setClients(Array.isArray(data) ? data : data.customers || []);
      }
    } catch (err) {
      console.error("Error fetching clients:", err);
    }
  };

  const getClientByProvider = (survey) => {
    const source = survey.provider || survey.source || "CPX";
    const client = clients.find((c) => {
      const clientName = (c.company_name || c.name || "").toLowerCase();
      return (
        clientName.includes(source.toLowerCase()) ||
        clientName.includes("cpx research") ||
        source.toLowerCase().includes(clientName.split(" ")[0]?.toLowerCase())
      );
    });
    return client;
  };

  const getClientName = (survey) => {
    if (survey.account_name) {
      return survey.account_name;
    }

    if (survey.client_name) {
      return survey.client_name;
    }

    if (survey.client_id) {
      const client = clients.find((c) => c._id === survey.client_id);
      if (client) return client.company_name || client.name || "N/A";
    }

    const client = getClientByProvider(survey);
    return client?.company_name || client?.name || "N/A";
  };

  const clientStats = useMemo(() => {
    const statsMap = new Map();

    surveys.forEach((survey) => {
      const name = getClientName(survey);
      if (!name || name === "N/A") return;

      const trimmed = name.trim();
      if (!trimmed) return;

      const key = trimmed.toLowerCase();
      const entry = statsMap.get(key) || { name: trimmed, count: 0 };
      entry.count += 1;
      statsMap.set(key, entry);
    });

    let items = Array.from(statsMap.values()).sort((a, b) => a.name.localeCompare(b.name));

    if (search.trim()) {
      const term = search.trim().toLowerCase();
      items = items.filter((item) => item.name.toLowerCase().includes(term));
    }

    return items;
  }, [surveys, clients, search]);

  if (!user) {
    return <div className="potential-clients-page">Please login to access Potential Clients.</div>;
  }

  return (
    <div className="potential-clients-page">
      <div className="page-header">
        <div>
          <h1>Potential Client</h1>
          <p>Unique client names extracted from the Study Pool.</p>
        </div>
        <button className="refresh-button" onClick={fetchAllSurveys} disabled={loading}>
          {loading ? "Refreshing..." : "Refresh"}
        </button>
      </div>

      <div className="page-controls">
        <input
          type="text"
          value={search}
          onChange={(event) => setSearch(event.target.value)}
          placeholder="Search client name"
          className="search-input"
        />
        <div className="count-pill">{clientStats.length} clients</div>
      </div>

      {error && (
        <div className="error-card">
          <div>Failed to load clients.</div>
          <div className="error-detail">{error}</div>
        </div>
      )}

      <div className="table-card">
        <table className="data-table">
          <thead>
            <tr>
              <th>Client Name</th>
              <th>Surveys</th>
            </tr>
          </thead>
          <tbody>
            {clientStats.map((client) => (
              <tr key={client.name}>
                <td>{client.name}</td>
                <td>{client.count}</td>
              </tr>
            ))}
            {!loading && clientStats.length === 0 && (
              <tr>
                <td colSpan={2} className="empty-row">
                  No client names found in the Study Pool.
                </td>
              </tr>
            )}
          </tbody>
        </table>
      </div>
    </div>
  );
}

export default PotentialClients;
