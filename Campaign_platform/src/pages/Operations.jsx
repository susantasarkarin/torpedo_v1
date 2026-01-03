import { useState, useEffect } from "react";
import { API_BASE_URL as API_URL } from "../config";

function Operations() {
  const [kpis, setKpis] = useState(null);
  const [recentActivity, setRecentActivity] = useState([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(null);

  const token = sessionStorage.getItem("session_token");

  useEffect(() => {
    fetchDashboardData();
  }, []);

  const fetchDashboardData = async () => {
    setLoading(true);
    setError(null);
    try {
      // Fetch KPIs
      const kpiRes = await fetch(`${API_URL}/operations/dashboard/kpis`, {
        headers: { Authorization: token },
      });
      if (kpiRes.ok) {
        const kpiData = await kpiRes.json();
        setKpis(kpiData);
      }

      // Fetch recent activity
      const activityRes = await fetch(`${API_URL}/operations/dashboard/recent-activity?limit=5`, {
        headers: { Authorization: token },
      });
      if (activityRes.ok) {
        const activityData = await activityRes.json();
        setRecentActivity(activityData.activities || []);
      }
    } catch (err) {
      console.error("Error fetching dashboard:", err);
      setError("Failed to load dashboard data");
    } finally {
      setLoading(false);
    }
  };

  // Format numbers with commas
  const formatNumber = (num) => {
    if (num === undefined || num === null) return "—";
    return Number(num).toLocaleString();
  };

  // Format currency
  const formatCurrency = (num) => {
    if (num === undefined || num === null) return "₹0";
    return `₹${Number(num).toLocaleString()}`;
  };

  // Build metrics from KPIs
  const operationsMetrics = kpis ? [
    { 
      title: "Active Projects", 
      value: kpis.projects?.active || 0, 
      change: `${kpis.projects?.total || 0} total projects`,
      color: "#3b82f6"
    },
    { 
      title: "Project Revenue", 
      value: formatCurrency(kpis.revenue?.total_invoiced || 0), 
      change: `${formatCurrency(kpis.revenue?.total_outstanding || 0)} outstanding`,
      color: "#10b981"
    },
    { 
      title: "Traffic Completion Rate", 
      value: `${kpis.traffic?.completion_rate || 0}%`, 
      change: `${formatNumber(kpis.traffic?.completed || 0)} / ${formatNumber(kpis.traffic?.total || 0)} completes`,
      color: "#8b5cf6"
    },
    { 
      title: "Unique Clients", 
      value: kpis.clients?.total || 0, 
      change: `${kpis.projects?.this_month || 0} new projects this month`,
      color: "#f59e0b"
    },
  ] : [];

  if (loading) {
    return (
      <div className="card" style={{ padding: "2rem", textAlign: "center" }}>
        <p>Loading dashboard...</p>
      </div>
    );
  }

  return (
    <div>
      <div className="card">
        <div className="card-header">
          <h2 className="card-title">Operations Dashboard</h2>
          <p className="card-description">Real-time project, revenue, and traffic metrics.</p>
        </div>

        {error && (
          <div style={{ padding: "1rem", background: "#fef2f2", color: "#dc2626", borderRadius: "6px", marginBottom: "1rem" }}>
            {error}
          </div>
        )}

        <div className="grid grid-cols-2 mb-6">
          {operationsMetrics.map((metric, index) => (
            <div key={index} className="card">
              <h3 className="card-title">{metric.title}</h3>
              <p style={{ fontSize: "2rem", fontWeight: "bold", color: metric.color, marginBottom: "0.5rem" }}>
                {metric.value}
              </p>
              <p style={{ fontSize: "0.875rem", color: "#6b7280" }}>{metric.change}</p>
            </div>
          ))}
        </div>

        <div className="grid grid-cols-2">
          <div className="card">
            <h3 className="card-title">Project Status Breakdown</h3>
            <div style={{ marginTop: "1rem" }}>
              {kpis?.projects?.status_breakdown && Object.entries(kpis.projects.status_breakdown).map(([status, count]) => (
                <div
                  key={status}
                  style={{ display: "flex", justifyContent: "space-between", alignItems: "center", marginBottom: "1rem" }}
                >
                  <span>{status || "Unknown"}</span>
                  <span style={{ 
                    fontWeight: "600",
                    color: status?.toLowerCase().includes("active") || status?.toLowerCase().includes("live") 
                      ? "#10b981" 
                      : status?.toLowerCase().includes("completed") 
                        ? "#3b82f6"
                        : "#6b7280"
                  }}>
                    {count} projects
                  </span>
                </div>
              ))}
              {(!kpis?.projects?.status_breakdown || Object.keys(kpis.projects.status_breakdown).length === 0) && (
                <p style={{ color: "#6b7280" }}>No project status data</p>
              )}
            </div>
            <button className="btn btn-outline" onClick={fetchDashboardData}>Refresh Data</button>
          </div>

          <div className="card">
            <h3 className="card-title">Recent Activities</h3>
            <div style={{ marginTop: "1rem" }}>
              {recentActivity.length > 0 ? recentActivity.map((activity, idx) => (
                <div
                  key={idx}
                  style={{
                    padding: "0.75rem 0",
                    borderBottom: "1px solid #f3f4f6",
                  }}
                >
                  <p style={{ fontWeight: "500", marginBottom: "0.25rem" }}>{activity.title}</p>
                  <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center" }}>
                    <p style={{ fontSize: "0.75rem", color: "#6b7280" }}>{activity.subtitle}</p>
                    <span
                      style={{
                        fontSize: "0.75rem",
                        padding: "0.125rem 0.5rem",
                        borderRadius: "9999px",
                        backgroundColor: activity.type === "invoice" ? "#dbeafe" : "#dcfce7",
                        color: activity.type === "invoice" ? "#1e40af" : "#166534",
                      }}
                    >
                      {activity.type}
                    </span>
                  </div>
                </div>
              )) : (
                <p style={{ color: "#6b7280" }}>No recent activity</p>
              )}
            </div>
          </div>
        </div>

        <div className="card">
          <h3 className="card-title">Revenue Summary</h3>
          <div className="grid grid-cols-3" style={{ marginTop: "1rem", textAlign: "center" }}>
            <div>
              <p style={{ fontSize: "1.5rem", fontWeight: "bold", color: "#10b981" }}>
                {formatCurrency(kpis?.revenue?.total_received || 0)}
              </p>
              <p style={{ color: "#6b7280", fontSize: "0.875rem" }}>Received</p>
            </div>
            <div>
              <p style={{ fontSize: "1.5rem", fontWeight: "bold", color: "#f59e0b" }}>
                {formatCurrency(kpis?.revenue?.total_outstanding || 0)}
              </p>
              <p style={{ color: "#6b7280", fontSize: "0.875rem" }}>Outstanding</p>
            </div>
            <div>
              <p style={{ fontSize: "1.5rem", fontWeight: "bold", color: "#3b82f6" }}>
                {kpis?.revenue?.collection_rate || 0}%
              </p>
              <p style={{ color: "#6b7280", fontSize: "0.875rem" }}>Collection Rate</p>
            </div>
          </div>
        </div>
      </div>
    </div>
  )
}

export default Operations
