import React, { useEffect, useState, useCallback } from "react";
import { useAuth } from "../../hooks/useAuth";
import { buildApiUrl } from "../../config";
import "./RateCard.css";

// Auto-refresh interval (5 minutes)
const AUTO_REFRESH_INTERVAL = 5 * 60 * 1000;

function RateCard() {
  const { user } = useAuth();
  const [rateCardData, setRateCardData] = useState(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState(null);
  const [countryFilter, setCountryFilter] = useState("");
  const [lastRefresh, setLastRefresh] = useState(null);

  const fetchRateCard = useCallback(async (country = null) => {
    setLoading(true);
    setError(null);

    try {
      const countryParam = country || countryFilter;
      const apiUrl = countryParam 
        ? `${buildApiUrl("/api/cint/surveys/rate-card")}?country=${countryParam}`
        : buildApiUrl("/api/cint/surveys/rate-card");
      
      console.log("Fetching rate card from:", apiUrl);
      
      const response = await fetch(apiUrl);
      
      if (!response.ok) {
        throw new Error(`API returned status ${response.status}`);
      }
      
      const data = await response.json();
      console.log("Rate card data:", data);
      
      if (data.success) {
        setRateCardData(data);
        setLastRefresh(new Date());
        
        // Set default country if not set
        if (!countryFilter && data.countries && data.countries.length > 0) {
          setCountryFilter(data.countries[0]);
        }
      } else {
        throw new Error(data.error || "Failed to load rate card");
      }
    } catch (err) {
      console.error("Error fetching rate card:", err);
      setError(err.message);
    } finally {
      setLoading(false);
    }
  }, [countryFilter]);

  // Initial fetch
  useEffect(() => {
    fetchRateCard();
  }, []);

  // Auto-refresh
  useEffect(() => {
    const interval = setInterval(() => fetchRateCard(), AUTO_REFRESH_INTERVAL);
    return () => clearInterval(interval);
  }, [fetchRateCard]);

  // Refetch when country changes
  const handleCountryChange = (newCountry) => {
    setCountryFilter(newCountry);
    fetchRateCard(newCountry);
  };

  // Calculate total surveys from matrix
  const totalSurveys = rateCardData?.matrix
    ? rateCardData.matrix.flat().reduce((sum, cell) => sum + (cell.count || 0), 0)
    : 0;

  if (!user) {
    return <div className="rate-card-page">Please login to access Rate Card.</div>;
  }

  return (
    <div className="rate-card-page">
      <div className="page-header">
        <div>
          <h1>Rate Card</h1>
          <p>Based on all Cint study pool entries (active + inactive). Rates shown are the exact averages from the backend.</p>
          {lastRefresh && (
            <p className="last-refresh">Last updated: {lastRefresh.toLocaleTimeString()} (auto-refreshes every 5 min)</p>
          )}
          {rateCardData && (
            <p style={{fontSize: '12px', color: '#666'}}>
              {rateCardData.filtered_surveys} of {rateCardData.total_surveys} surveys for {countryFilter || "all countries"}
            </p>
          )}
        </div>
        <button className="refresh-button" onClick={() => fetchRateCard()} disabled={loading}>
          {loading ? "Refreshing..." : "Refresh"}
        </button>
      </div>

      <div className="filters-section">
        <div className="filter-group">
          <label>Country</label>
          <select value={countryFilter} onChange={(e) => handleCountryChange(e.target.value)}>
            {(!rateCardData?.countries || rateCardData.countries.length === 0) && (
              <option value="">Loading...</option>
            )}
            {rateCardData?.countries?.map((c) => (
              <option key={c} value={c}>{c}</option>
            ))}
          </select>
        </div>

        <div className="count-pill">{totalSurveys} surveys</div>
      </div>

      {error && (
        <div className="error-card">
          <div>Failed to load rate card.</div>
          <div className="error-detail">{error}</div>
        </div>
      )}

      {rateCardData && (
        <div className="table-card">
          <table className="matrix-table">
            <thead>
              <tr>
                <th className="corner-cell">IR \ LOI</th>
                {rateCardData.loi_ranges.map((label) => (
                  <th key={label}>{label}</th>
                ))}
              </tr>
            </thead>
            <tbody>
              {rateCardData.ir_ranges.map((irLabel, irIdx) => (
                <tr key={irLabel}>
                  <th className="row-header">{irLabel}</th>
                  {rateCardData.loi_ranges.map((loiLabel, loiIdx) => {
                    const cell = rateCardData.matrix[irIdx]?.[loiIdx] || {};
                    const hasData = cell.count > 0 && cell.avg !== null;
                    const rate = hasData ? cell.avg : null;
                    
                    return (
                      <td
                        key={`${irLabel}-${loiLabel}`}
                        className={`rate-cell ${hasData ? "has-data" : "estimated"}`}
                        title={hasData 
                          ? `${cell.count} surveys\nAvg: $${cell.avg}\nMin: $${cell.min}\nMax: $${cell.max}`
                          : "No data"
                        }
                      >
                        {rate !== null && !isNaN(rate)
                          ? `$${rate.toFixed(2)}`
                          : "-"}
                      </td>
                    );
                  })}
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}

      <div className="legend">
        <span className="legend-item"><span className="legend-dot has-data"></span> Average rate from data</span>
        <span className="legend-item"><span className="legend-dot estimated"></span> No data</span>
      </div>
    </div>
  );
}

export default RateCard;
