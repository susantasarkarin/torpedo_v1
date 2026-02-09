import React, { useEffect, useMemo, useState } from "react";
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

function RateCard() {
  const { user, token } = useAuth();
  const [surveys, setSurveys] = useState([]);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState(null);
  const [markupPercent, setMarkupPercent] = useState(15);

  // Filters
  const [countryFilter, setCountryFilter] = useState("");
  const [loiMin, setLoiMin] = useState("");
  const [loiMax, setLoiMax] = useState("");
  const [irMin, setIrMin] = useState("");
  const [irMax, setIrMax] = useState("");

  useEffect(() => {
    if (token) {
      fetchAllSurveys();
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

  const rateRows = useMemo(() => {
    const groups = new Map();
    const allRates = [];

    surveys.forEach((survey) => {
      const source = (survey.source || survey.provider || "").toUpperCase();
      if (source !== "CINT" && !survey.account_name) return;

      const country = getCountryCode(survey);
      const loi = getLOIValue(survey);
      const ir = getIncidenceRateValue(survey);
      if (country === "N/A" || loi === null || ir === null) return;

      // Apply filters
      if (countryFilter && country !== countryFilter) return;
      if (loiMin !== "" && loi < Number(loiMin)) return;
      if (loiMax !== "" && loi > Number(loiMax)) return;
      if (irMin !== "" && ir < Number(irMin)) return;
      if (irMax !== "" && ir > Number(irMax)) return;

      const rate = getPayoutValue(survey);
      if (rate !== null && !isNaN(rate)) {
        allRates.push(rate);
      }

      const key = `${country}__${loi}__${ir}`;
      const entry = groups.get(key) || { country, loi, ir, count: 0, rates: [] };
      entry.count += 1;
      if (rate !== null && !isNaN(rate)) {
        entry.rates.push(rate);
      }
      groups.set(key, entry);
    });

    const globalMedian = getMedian(allRates);

    return Array.from(groups.values())
      .map((entry) => {
        const median = entry.rates.length ? getMedian(entry.rates) : globalMedian;
        const rate = applyMarkup(median);
        return {
          country: entry.country,
          loi: entry.loi,
          ir: entry.ir,
          count: entry.count,
          rate,
          rateSource: entry.rates.length
            ? `Median + ${markupPercent}%`
            : globalMedian
            ? `Estimated + ${markupPercent}%`
            : "N/A",
        };
      })
      .sort((a, b) => {
        const countryCompare = a.country.localeCompare(b.country);
        if (countryCompare !== 0) return countryCompare;
        if (a.loi !== b.loi) return a.loi - b.loi;
        return a.ir - b.ir;
      });
  }, [surveys, countryFilter, loiMin, loiMax, irMin, irMax, markupPercent]);

  if (!user) {
    return <div className="rate-card-page">Please login to access Rate Card.</div>;
  }

  return (
    <div className="rate-card-page">
      <div className="page-header">
        <div>
          <h1>Rate Card</h1>
          <p>Based on all Cint study pool entries (active + inactive) grouped by country, LOI, and IR.</p>
        </div>
        <button className="refresh-button" onClick={fetchAllSurveys} disabled={loading}>
          {loading ? "Refreshing..." : "Refresh"}
        </button>
      </div>

      <div className="filters-section">
        <div className="filter-group">
          <label>Country</label>
          <select value={countryFilter} onChange={(e) => setCountryFilter(e.target.value)}>
            <option value="">All Countries</option>
            {availableCountries.map((c) => (
              <option key={c} value={c}>{c}</option>
            ))}
          </select>
        </div>

        <div className="filter-group">
          <label>LOI (min)</label>
          <div className="range-inputs">
            <input
              type="number"
              placeholder="Min"
              value={loiMin}
              onChange={(e) => setLoiMin(e.target.value)}
              min="0"
            />
            <span>to</span>
            <input
              type="number"
              placeholder="Max"
              value={loiMax}
              onChange={(e) => setLoiMax(e.target.value)}
              min="0"
            />
          </div>
        </div>

        <div className="filter-group">
          <label>IR (%)</label>
          <div className="range-inputs">
            <input
              type="number"
              placeholder="Min"
              value={irMin}
              onChange={(e) => setIrMin(e.target.value)}
              min="0"
              max="100"
            />
            <span>to</span>
            <input
              type="number"
              placeholder="Max"
              value={irMax}
              onChange={(e) => setIrMax(e.target.value)}
              min="0"
              max="100"
            />
          </div>
        </div>

        <button
          className="clear-filters-btn"
          onClick={() => {
            setCountryFilter("");
            setLoiMin("");
            setLoiMax("");
            setIrMin("");
            setIrMax("");
          }}
        >
          Clear Filters
        </button>
      </div>

      <div className="page-controls">
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
        <div className="count-pill">{rateRows.length} combinations</div>
      </div>

      {error && (
        <div className="error-card">
          <div>Failed to load rate card.</div>
          <div className="error-detail">{error}</div>
        </div>
      )}

      <div className="table-card">
        <table className="data-table">
          <thead>
            <tr>
              <th>Country</th>
              <th>LOI</th>
              <th>IR</th>
              <th>Surveys</th>
              <th>Rate (USD)</th>
              <th>Rate Source</th>
            </tr>
          </thead>
          <tbody>
            {rateRows.map((row) => (
              <tr key={`${row.country}-${row.loi}-${row.ir}`}>
                <td>{row.country}</td>
                <td>{row.loi} min</td>
                <td>{row.ir}%</td>
                <td>{row.count}</td>
                <td>{row.rate !== null && !isNaN(row.rate) ? `$${row.rate.toFixed(2)}` : "N/A"}</td>
                <td>{row.rateSource}</td>
              </tr>
            ))}
            {!loading && rateRows.length === 0 && (
              <tr>
                <td colSpan={6} className="empty-row">
                  No Cint combinations available for rate card.
                </td>
              </tr>
            )}
          </tbody>
        </table>
      </div>
    </div>
  );
}

export default RateCard;
