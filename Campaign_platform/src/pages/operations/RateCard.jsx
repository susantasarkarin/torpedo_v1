import React, { useEffect, useMemo, useState, useCallback } from "react";
import { useAuth } from "../../hooks/useAuth";
import { buildApiUrl } from "../../config";
import "./RateCard.css";

const CINT_COUNTRY_LANGUAGE_MAP = {
  1: "UK", 2: "FR", 3: "DE", 4: "NL", 5: "AU", 6: "CA", 7: "NZ", 8: "IE", 9: "US",
  10: "ES", 11: "IT", 12: "BR", 13: "MX", 14: "AR", 15: "CL", 16: "CO", 17: "PE",
  18: "AT", 19: "CH", 20: "BE", 21: "SE", 22: "NO", 23: "DK", 24: "KR", 25: "JP",
  26: "CN", 27: "IN", 28: "BE", 29: "PL", 30: "RU", 31: "TR", 32: "ZA", 33: "SG",
  34: "MY", 35: "TH", 36: "PH", 37: "ID", 38: "VN", 39: "TW", 40: "HK", 41: "AE",
  42: "SA", 43: "EG", 44: "NG", 45: "KE", 46: "GH", 47: "PT", 48: "FI", 49: "CZ",
  50: "HU", 51: "RO", 52: "GR", 53: "UA", 54: "IL", 55: "PK", 56: "BD", 57: "LK",
  86: "KZ", 146: "EU",
};

// LOI ranges (columns)
const LOI_RANGES = [
  { label: "<5 min", min: 0, max: 4 },
  { label: "5-10 min", min: 5, max: 10 },
  { label: "10-15 min", min: 11, max: 15 },
  { label: "15-20 min", min: 16, max: 20 },
  { label: "20-30 min", min: 21, max: 30 },
  { label: ">30 min", min: 31, max: Infinity },
];

// IR ranges (rows)
const IR_RANGES = [
  { label: "<5%", min: 0, max: 5 },
  { label: "6-10%", min: 6, max: 10 },
  { label: "11-20%", min: 11, max: 20 },
  { label: "21-30%", min: 21, max: 30 },
  { label: "31-40%", min: 31, max: 40 },
  { label: "41-50%", min: 41, max: 50 },
  { label: "51-60%", min: 51, max: 60 },
  { label: "61-70%", min: 61, max: 70 },
  { label: "71-80%", min: 71, max: 80 },
  { label: "81-90%", min: 81, max: 90 },
  { label: "91-100%", min: 91, max: 100 },
];

// Default baseline rates (USD) when no data available - rates increase with lower IR and longer LOI
// Rows: IR ranges, Columns: LOI ranges
const DEFAULT_RATES = [
  // <5%    5-10   10-15  15-20  20-30  >30
  [8.50,  10.00, 12.00, 14.00, 17.00, 22.00], // <5%
  [6.00,   7.50,  9.00, 10.50, 13.00, 17.00], // 6-10%
  [4.50,   5.50,  6.50,  7.50,  9.50, 12.50], // 11-20%
  [3.50,   4.25,  5.00,  5.75,  7.25,  9.50], // 21-30%
  [2.75,   3.25,  3.75,  4.50,  5.75,  7.50], // 31-40%
  [2.25,   2.75,  3.25,  3.75,  4.75,  6.25], // 41-50%
  [1.90,   2.30,  2.70,  3.10,  4.00,  5.25], // 51-60%
  [1.60,   1.95,  2.30,  2.65,  3.40,  4.50], // 61-70%
  [1.35,   1.65,  1.95,  2.25,  2.90,  3.85], // 71-80%
  [1.15,   1.40,  1.65,  1.90,  2.45,  3.25], // 81-90%
  [1.00,   1.20,  1.40,  1.60,  2.10,  2.75], // 91-100%
];

// Auto-refresh interval (5 minutes)
const AUTO_REFRESH_INTERVAL = 5 * 60 * 1000;

function RateCard() {
  const { user, token } = useAuth();
  const [surveys, setSurveys] = useState([]);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState(null);
  const [markupPercent, setMarkupPercent] = useState(15);
  const [countryFilter, setCountryFilter] = useState("");
  const [lastRefresh, setLastRefresh] = useState(null);

  const fetchAllSurveys = useCallback(async () => {
    if (!token) return;
    setLoading(true);
    setError(null);

    try {
      const cpxResponse = await fetch(buildApiUrl("/cpx/surveys?page=1&page_size=500000&show_all=true"), {
        headers: {
          Authorization: token,
          "Content-Type": "application/json",
        },
      });

      const cintQuery = "/api/cint/surveys?page=1&page_size=500000&show_all=true";
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
      setLastRefresh(new Date());
    } catch (err) {
      console.error("Error fetching surveys:", err);
      setError(err.message);
    } finally {
      setLoading(false);
    }
  }, [token]);

  // Initial fetch and auto-refresh
  useEffect(() => {
    if (token) {
      fetchAllSurveys();
      const interval = setInterval(fetchAllSurveys, AUTO_REFRESH_INTERVAL);
      return () => clearInterval(interval);
    }
  }, [token, fetchAllSurveys]);

  const getCountryCode = (survey) => {
    const countryLanguage = survey.country_language;

    if (countryLanguage && typeof countryLanguage === "string") {
      const lastTwo = countryLanguage.slice(-2).toUpperCase();
      if (lastTwo && /^[A-Z]{2}$/.test(lastTwo)) {
        return lastTwo;
      }
      const parts = countryLanguage.split("_");
      if (parts.length >= 2) {
        return parts[parts.length - 1].toUpperCase();
      }
      return countryLanguage.toUpperCase();
    }

    if (countryLanguage && typeof countryLanguage === "number") {
      return CINT_COUNTRY_LANGUAGE_MAP[countryLanguage] || `ID:${countryLanguage}`;
    }

    if (survey.country && typeof survey.country === "string" && survey.country.length <= 3) {
      return survey.country.toUpperCase();
    }
    if (survey.country_code && typeof survey.country_code === "string" && survey.country_code.length <= 3) {
      return survey.country_code.toUpperCase();
    }

    return "N/A";
  };

  const getLOIValue = (survey) => {
    const loi =
      survey.loi ||
      survey.length_of_interview ||
      survey.bid_length_of_interview ||
      survey.LOI ||
      survey.survey_loi;

    if (loi !== undefined && loi !== null && !isNaN(loi) && loi > 0) {
      return Math.round(loi);
    }

    return null;
  };

  const getIncidenceRateValue = (survey) => {
    const incidence = survey.bid_incidence ?? survey.incidence_rate;

    if (incidence !== undefined && incidence !== null && !isNaN(incidence)) {
      const rate = parseFloat(incidence);
      if (rate <= 1) {
        return Math.round(rate * 100);
      }
      return Math.round(rate);
    }

    return null;
  };

  const getPayoutValue = (survey) => {
    if (survey.revenue_per_interview) {
      const rpi = survey.revenue_per_interview;
      if (typeof rpi === "object" && rpi.value) {
        return Number(rpi.value);
      }
      if (typeof rpi === "number") {
        return Number(rpi);
      }
    }
    if (survey.payout !== undefined && survey.payout !== null) {
      return Number(survey.payout);
    }
    if (survey.cpi !== undefined && survey.cpi !== null) {
      return Number(survey.cpi);
    }
    return null;
  };

  const getMedian = (values) => {
    if (!values.length) return null;
    const sorted = [...values].sort((a, b) => a - b);
    const mid = Math.floor(sorted.length / 2);
    if (sorted.length % 2 === 0) {
      return (sorted[mid - 1] + sorted[mid]) / 2;
    }
    return sorted[mid];
  };

  const applyMarkup = (value) => {
    if (value === null || value === undefined || isNaN(value)) return null;
    const safeMarkup = Number.isFinite(markupPercent) ? markupPercent : 0;
    return value * (1 + safeMarkup / 100);
  };

  // Get unique countries for dropdown
  const availableCountries = useMemo(() => {
    const countries = new Set();
    surveys.forEach((survey) => {
      const source = (survey.source || survey.provider || "").toUpperCase();
      if (source !== "CINT" && !survey.account_name) return;
      const country = getCountryCode(survey);
      if (country !== "N/A") {
        countries.add(country);
      }
    });
    return Array.from(countries).sort();
  }, [surveys]);

  // Set default country when countries load
  useEffect(() => {
    if (availableCountries.length > 0 && !countryFilter) {
      setCountryFilter(availableCountries[0]);
    }
  }, [availableCountries]);

  // Helper to find which range a value falls into
  const findLOIRange = (loi) => {
    return LOI_RANGES.findIndex((r) => loi >= r.min && loi <= r.max);
  };

  const findIRRange = (ir) => {
    return IR_RANGES.findIndex((r) => ir >= r.min && ir <= r.max);
  };

  // Build matrix data
  const rateMatrix = useMemo(() => {
    // Matrix: rows = IR ranges, cols = LOI ranges
    // Each cell contains { rates: [], count: 0 }
    const matrix = IR_RANGES.map(() =>
      LOI_RANGES.map(() => ({ rates: [], count: 0 }))
    );
    const allRates = [];

    surveys.forEach((survey) => {
      const source = (survey.source || survey.provider || "").toUpperCase();
      if (source !== "CINT" && !survey.account_name) return;

      const country = getCountryCode(survey);
      const loi = getLOIValue(survey);
      const ir = getIncidenceRateValue(survey);
      if (country === "N/A" || loi === null || ir === null) return;

      // Apply country filter
      if (countryFilter && country !== countryFilter) return;

      const loiIdx = findLOIRange(loi);
      const irIdx = findIRRange(ir);
      if (loiIdx === -1 || irIdx === -1) return;

      const rate = getPayoutValue(survey);
      if (rate !== null && !isNaN(rate)) {
        allRates.push(rate);
        matrix[irIdx][loiIdx].rates.push(rate);
      }
      matrix[irIdx][loiIdx].count += 1;
    });

    // Calculate median + markup for each cell, use DEFAULT_RATES as fallback
    return matrix.map((row, irIdx) =>
      row.map((cell, loiIdx) => {
        let baseRate;
        if (cell.rates.length > 0) {
          baseRate = getMedian(cell.rates);
        } else {
          // Use default rate for this IR/LOI combination
          baseRate = DEFAULT_RATES[irIdx][loiIdx];
        }
        const rate = applyMarkup(baseRate);
        return {
          rate,
          count: cell.count,
          hasData: cell.rates.length > 0,
        };
      })
    );
  }, [surveys, countryFilter, markupPercent]);

  // Calculate total surveys count
  const totalSurveys = useMemo(() => {
    return rateMatrix.flat().reduce((sum, cell) => sum + cell.count, 0);
  }, [rateMatrix]);

  if (!user) {
    return <div className="rate-card-page">Please login to access Rate Card.</div>;
  }

  return (
    <div className="rate-card-page">
      <div className="page-header">
        <div>
          <h1>Rate Card</h1>
          <p>Based on all Cint study pool entries (active + inactive). Rates shown are median + {markupPercent}% markup.</p>
          {lastRefresh && (
            <p className="last-refresh">Last updated: {lastRefresh.toLocaleTimeString()} (auto-refreshes every 5 min)</p>
          )}
        </div>
        <button className="refresh-button" onClick={fetchAllSurveys} disabled={loading}>
          {loading ? "Refreshing..." : "Refresh"}
        </button>
      </div>

      <div className="filters-section">
        <div className="filter-group">
          <label>Country</label>
          <select value={countryFilter} onChange={(e) => setCountryFilter(e.target.value)}>
            {availableCountries.map((c) => (
              <option key={c} value={c}>{c}</option>
            ))}
          </select>
        </div>

        <label className="markup-control">
          <span>Markup %</span>
          <input
            type="number"
            min="0"
            max="100"
            step="1"
            value={markupPercent}
            onChange={(event) => setMarkupPercent(Number(event.target.value))}
          />
        </label>

        <div className="count-pill">{totalSurveys} surveys</div>
      </div>

      {error && (
        <div className="error-card">
          <div>Failed to load rate card.</div>
          <div className="error-detail">{error}</div>
        </div>
      )}

      <div className="table-card">
        <table className="matrix-table">
          <thead>
            <tr>
              <th className="corner-cell">IR \ LOI</th>
              {LOI_RANGES.map((loiRange) => (
                <th key={loiRange.label}>{loiRange.label}</th>
              ))}
            </tr>
          </thead>
          <tbody>
            {IR_RANGES.map((irRange, irIdx) => (
              <tr key={irRange.label}>
                <th className="row-header">{irRange.label}</th>
                {LOI_RANGES.map((loiRange, loiIdx) => {
                  const cell = rateMatrix[irIdx][loiIdx];
                  return (
                    <td
                      key={`${irRange.label}-${loiRange.label}`}
                      className={`rate-cell ${cell.hasData ? "has-data" : "estimated"}`}
                      title={`${cell.count} surveys`}
                    >
                      {cell.rate !== null && !isNaN(cell.rate)
                        ? `$${cell.rate.toFixed(2)}`
                        : "-"}
                    </td>
                  );
                })}
              </tr>
            ))}
          </tbody>
        </table>
      </div>

      <div className="legend">
        <span className="legend-item"><span className="legend-dot has-data"></span> Median rate from data</span>
        <span className="legend-item"><span className="legend-dot estimated"></span> Estimated (global median)</span>
      </div>
    </div>
  );
}

export default RateCard;
