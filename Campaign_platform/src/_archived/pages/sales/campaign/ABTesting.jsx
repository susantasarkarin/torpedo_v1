"use client"

import { useState, useEffect } from "react"
import { useLocation, useNavigate } from "react-router-dom"
import { TrendingUp, CheckCircle, AlertCircle, BarChart3, Mail, Send } from "lucide-react"
import "./ABTesting.css"
import { API_BASE_URL } from "../../../config"
import { buildApiUrl } from "../../../config"

function ABTesting() {
  const location = useLocation()
  const navigate = useNavigate()
  const { campaignId } = location.state || {}

  const [variants, setVariants] = useState({ A: "", B: "", C: "" })
  const [splitRatio, setSplitRatio] = useState({ A: 0.5, B: 0.5, C: 0 })
  const [results, setResults] = useState(null)
  const [loading, setLoading] = useState(false)
  const [setting, setSetting] = useState(false)
  const [showResults, setShowResults] = useState(false)
  const [startTime, setStartTime] = useState(null)
  const [testRunning, setTestRunning] = useState(false)
  const [winnerDecided, setWinnerDecided] = useState(null)

  // Mock results data
  const generateMockResults = () => ({
    variantA: {
      variant: "A",
      template: "Variant A",
      sends: 450,
      opens: 168,
      clicks: 42,
      replies: 12,
      openRate: 0.373,
      clickRate: 0.093,
      replyRate: 0.027,
      pValue: 0.032,
      significant: true,
      confidence: 0.968
    },
    variantB: {
      variant: "B",
      template: "Variant B",
      sends: 450,
      opens: 135,
      clicks: 27,
      replies: 8,
      openRate: 0.3,
      clickRate: 0.06,
      replyRate: 0.018,
      pValue: 0.032,
      significant: true,
      confidence: 0.968
    },
    variantC: {
      variant: "C",
      template: "Variant C",
      sends: 300,
      opens: 96,
      clicks: 19,
      replies: 5,
      openRate: 0.32,
      clickRate: 0.063,
      replyRate: 0.017,
      pValue: 0.156,
      significant: false,
      confidence: 0.844
    }
  })

  // Fetch campaign for A/B test
  useEffect(() => {
    const fetchCampaign = async () => {
      const sessionId = localStorage.getItem("session_id")
      if (!sessionId) {
        navigate("/login")
        return
      }

      if (!campaignId) {
        // Demo mode - show test setup interface
        return
      }

      try {
        setLoading(true)
        const res = await fetch(buildApiUrl(`/campaigns/${campaignId}`), {
          headers: {
            "Content-Type": "application/json",
            "Authorization": sessionId,
          },
        })

        if (!res.ok) throw new Error("Failed to fetch campaign")

        const data = await res.json()
        if (data.campaign.abTest) {
          setVariants(data.campaign.abTest.variants || { A: "", B: "", C: "" })
          setSplitRatio(data.campaign.abTest.splitRatio || { A: 0.5, B: 0.5, C: 0 })
          if (data.campaign.abTest.results) {
            setResults(data.campaign.abTest.results)
          }
        }
      } catch (err) {
        console.error("Failed to fetch campaign:", err)
      } finally {
        setLoading(false)
      }
    }

    fetchCampaign()
  }, [campaignId, navigate])

  const handleVariantChange = (variant, value) => {
    setVariants({ ...variants, [variant]: value })
  }

  const handleSplitRatioChange = (variant, value) => {
    const numValue = parseFloat(value)
    const total = Object.entries(splitRatio)
      .filter(([k]) => k !== variant)
      .reduce((sum, [, v]) => sum + v, 0)

    if (numValue + total <= 1) {
      setSplitRatio({ ...splitRatio, [variant]: numValue })
    }
  }

  const handleSetupTest = async () => {
    const sessionId = localStorage.getItem("session_id")
    if (!sessionId) {
      navigate("/login")
      return
    }

    if (!variants.A || !variants.B) {
      alert("Please provide at least Variant A and B templates")
      return
    }

    try {
      setSetting(true)
      const res = await fetch(buildApiUrl(`/campaigns/${campaignId || "demo"}/ab-test/setup`), {
        method: "POST",
        headers: {
          "Content-Type": "application/json",
          "Authorization": sessionId,
        },
        body: JSON.stringify({
          variants,
          splitRatio,
        }),
      })

      if (!res.ok) throw new Error("Failed to setup A/B test")

      const data = await res.json()
      alert(`✅ A/B test configured!\nStarting with ${Math.round(splitRatio.A * 100)}% Variant A, ${Math.round(splitRatio.B * 100)}% Variant B`)
      setTestRunning(true)
      setStartTime(new Date())
      
      // Simulate results after delay
      setTimeout(() => {
        setResults(generateMockResults())
        setShowResults(true)
      }, 3000)
    } catch (err) {
      alert("Error setting up A/B test: " + err.message)
    } finally {
      setSetting(false)
    }
  }

  const handleDeclareWinner = async (winner) => {
    const sessionId = localStorage.getItem("session_id")
    if (!sessionId) {
      navigate("/login")
      return
    }

    if (!window.confirm(`Declare Variant ${winner} as winner?\n\nThis will roll out this template to 100% of recipients.`)) {
      return
    }

    try {
      const res = await fetch(buildApiUrl(`/campaigns/${campaignId || "demo"}/ab-test/winner`), {
        method: "POST",
        headers: {
          "Content-Type": "application/json",
          "Authorization": sessionId,
        },
        body: JSON.stringify({ winner }),
      })

      if (!res.ok) throw new Error("Failed to declare winner")

      alert(`✅ Variant ${winner} is now the winner!\n\nRolling out to 100% of new recipients.`)
      setWinnerDecided(winner)
      setTestRunning(false)
    } catch (err) {
      alert("Error declaring winner: " + err.message)
    }
  }

  const getSignificanceLabel = (pValue) => {
    if (pValue < 0.01) return "Highly Significant ***"
    if (pValue < 0.05) return "Significant **"
    if (pValue < 0.1) return "Marginally Significant *"
    return "Not Significant"
  }

  const getWinnerVariant = () => {
    if (!results) return null
    const variantResults = [results.variantA, results.variantB]
    if (results.variantC && splitRatio.C > 0) variantResults.push(results.variantC)
    return variantResults.reduce((best, current) =>
      current.openRate > best.openRate ? current : best
    )
  }

  const totalRatioValue = Object.values(splitRatio).reduce((a, b) => a + b, 0)
  const ratioWarning = Math.abs(totalRatioValue - (splitRatio.C > 0 ? 1 : 0.5 + 0.5)) > 0.01

  return (
    <div className="abtesting-container">
      {/* Header */}
      <div className="abtesting-header">
        <div>
          <h1>A/B Testing</h1>
          <p>Compare email templates and identify winning variations</p>
        </div>
        <div className="header-info">
          {testRunning && (
            <div className="test-badge">
              <span className="pulse"></span> Test Running
            </div>
          )}
          {winnerDecided && (
            <div className="winner-badge">
              <CheckCircle size={16} /> Winner: Variant {winnerDecided}
            </div>
          )}
        </div>
      </div>

      {/* Setup Phase */}
      <div className="setup-phase">
        <h2>1. Configure Test Variants</h2>
        <div className="variants-grid">
          {["A", "B", "C"].map(variant => (
            <div key={variant} className="variant-card">
              <div className="variant-header">
                <h3>Variant {variant}</h3>
                {variant === "C" && <span className="optional-badge">Optional</span>}
              </div>

              <div className="variant-form">
                <label>Template Content</label>
                <textarea
                  placeholder={`Enter template for Variant ${variant}`}
                  value={variants[variant]}
                  onChange={(e) => handleVariantChange(variant, e.target.value)}
                  className="variant-textarea"
                  disabled={winnerDecided !== null}
                />

                <label>Split Ratio: {Math.round(splitRatio[variant] * 100)}%</label>
                <input
                  type="range"
                  min="0"
                  max={variant === "C" ? "1" : "1"}
                  step="0.05"
                  value={splitRatio[variant]}
                  onChange={(e) => handleSplitRatioChange(variant, e.target.value)}
                  className="ratio-slider"
                  disabled={winnerDecided !== null}
                />
                <div className="ratio-display">
                  <input
                    type="number"
                    min="0"
                    max="1"
                    step="0.01"
                    value={splitRatio[variant].toFixed(2)}
                    onChange={(e) => handleSplitRatioChange(variant, e.target.value)}
                    className="ratio-input"
                    disabled={winnerDecided !== null}
                  />
                </div>
              </div>
            </div>
          ))}
        </div>

        {ratioWarning && (
          <div className="warning-message">
            <AlertCircle size={16} />
            <span>Ratios should sum to 1.0 (100%)</span>
          </div>
        )}

        <button
          className="btn-setup-test"
          onClick={handleSetupTest}
          disabled={setting || winnerDecided !== null || !variants.A || !variants.B}
        >
          {setting ? (
            <>
              <span className="spinner"></span> Setting Up Test...
            </>
          ) : (
            <>
              <Mail size={18} /> Setup Test ({Math.round(splitRatio.A * 100)}% A, {Math.round(splitRatio.B * 100)}% B{splitRatio.C > 0 ? `, ${Math.round(splitRatio.C * 100)}% C` : ""})
            </>
          )}
        </button>
      </div>

      {/* Results Phase */}
      {showResults && results && (
        <div className="results-phase">
          <h2>2. Live Test Results</h2>
          
          {/* Results Table */}
          <div className="results-table-wrapper">
            <table className="results-table">
              <thead>
                <tr>
                  <th>Variant</th>
                  <th className="numeric">Sends</th>
                  <th className="numeric">Opens</th>
                  <th className="numeric">Open Rate</th>
                  <th className="numeric">Clicks</th>
                  <th className="numeric">Click Rate</th>
                  <th className="numeric">Replies</th>
                  <th className="numeric">Reply Rate</th>
                  <th className="center">Significance</th>
                </tr>
              </thead>
              <tbody>
                {[results.variantA, results.variantB, ...(splitRatio.C > 0 && results.variantC ? [results.variantC] : [])].map(result => {
                  const isWinner = getWinnerVariant() && result.variant === getWinnerVariant().variant
                  return (
                    <tr key={result.variant} className={`${isWinner ? "winner-row" : ""}`}>
                      <td className="variant-cell">
                        <span className="variant-label">Variant {result.variant}</span>
                        {isWinner && <CheckCircle size={14} className="winner-icon" />}
                      </td>
                      <td className="numeric">{result.sends}</td>
                      <td className="numeric">{result.opens}</td>
                      <td className="numeric percentage">
                        <strong>{(result.openRate * 100).toFixed(1)}%</strong>
                      </td>
                      <td className="numeric">{result.clicks}</td>
                      <td className="numeric percentage">
                        <strong>{(result.clickRate * 100).toFixed(2)}%</strong>
                      </td>
                      <td className="numeric">{result.replies}</td>
                      <td className="numeric percentage">
                        <strong>{(result.replyRate * 100).toFixed(2)}%</strong>
                      </td>
                      <td className="center">
                        {result.significant ? (
                          <div className="significance-badge significant">
                            <CheckCircle size={14} />
                            <span>{getSignificanceLabel(result.pValue)}</span>
                          </div>
                        ) : (
                          <div className="significance-badge not-significant">
                            <AlertCircle size={14} />
                            <span>Not Significant</span>
                          </div>
                        )}
                      </td>
                    </tr>
                  )
                })}
              </tbody>
            </table>
          </div>

          {/* Confidence Intervals */}
          <div className="confidence-section">
            <h3>Confidence Intervals (95%)</h3>
            <div className="confidence-charts">
              {[results.variantA, results.variantB, ...(splitRatio.C > 0 && results.variantC ? [results.variantC] : [])].map(result => (
                <div key={result.variant} className="confidence-chart">
                  <h4>Variant {result.variant}</h4>
                  <div className="chart-content">
                    <div className="metric">
                      <label>Open Rate</label>
                      <div className="bar-chart">
                        <div className="bar-fill" style={{ width: `${result.openRate * 100}%` }}></div>
                        <span className="bar-label">{(result.openRate * 100).toFixed(1)}%</span>
                      </div>
                      <div className="confidence-info">Confidence: {(result.confidence * 100).toFixed(1)}%</div>
                    </div>
                    <div className="metric">
                      <label>Click Rate</label>
                      <div className="bar-chart">
                        <div className="bar-fill" style={{ width: `${result.clickRate * 100}%` }}></div>
                        <span className="bar-label">{(result.clickRate * 100).toFixed(2)}%</span>
                      </div>
                    </div>
                  </div>
                </div>
              ))}
            </div>
          </div>

          {/* Winner Declaration */}
          {testRunning && getWinnerVariant() && (
            <div className="winner-declaration">
              <div className="winner-info">
                <TrendingUp size={24} />
                <div>
                  <h3>Variant {getWinnerVariant().variant} is Leading</h3>
                  <p>{(getWinnerVariant().openRate * 100).toFixed(1)}% open rate vs alternatives</p>
                </div>
              </div>
              <button
                className="btn-declare-winner"
                onClick={() => handleDeclareWinner(getWinnerVariant().variant)}
              >
                <CheckCircle size={18} /> Declare as Winner
              </button>
            </div>
          )}

          {winnerDecided && (
            <div className="winner-banner">
              <CheckCircle size={24} />
              <div>
                <h3>Variant {winnerDecided} is Now Live</h3>
                <p>Rolling out to 100% of new recipients. Test completed.</p>
              </div>
            </div>
          )}
        </div>
      )}

      {/* Info Section */}
      <div className="info-section">
        <h3>A/B Testing Best Practices</h3>
        <div className="practices-grid">
          <div className="practice-card">
            <div className="practice-icon">📊</div>
            <h4>Test One Variable</h4>
            <p>Change only subject line, call-to-action, or sending time per test</p>
          </div>
          <div className="practice-card">
            <div className="practice-icon">🎯</div>
            <h4>Significant Size</h4>
            <p>Ensure sufficient sample size (300+ per variant) for statistical significance</p>
          </div>
          <div className="practice-card">
            <div className="practice-icon">⏰</div>
            <h4>Run Duration</h4>
            <p>Allow tests to run 2-4 weeks minimum to account for seasonal variations</p>
          </div>
          <div className="practice-card">
            <div className="practice-icon">📈</div>
            <h4>P-Value < 0.05</h4>
            <p>Wait for p-value below 0.05 to declare statistical significance</p>
          </div>
        </div>
      </div>
    </div>
  )
}

export default ABTesting
