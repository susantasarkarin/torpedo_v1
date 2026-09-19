"use client"

import { useState, useEffect } from "react"
import { Link } from "react-router-dom"
import { buildApiUrl } from "../../config"
import "./RFQ.css"
import "../../styles/SalesPages.css"

// RFQs proposed by the mail-pool local-Qwen extraction land here, not
// directly on the live RFQ list. Per the bucket_classifier incident, this
// model's self-reported confidence carries no information about
// correctness on real data -- so a human reviews every proposed RFQ before
// it becomes a real Opportunity (POST /rfq/review-queue/{id}/approve).

function formatMoney(value, currency) {
  if (value === null || value === undefined || value === "") return "—"
  try {
    return new Intl.NumberFormat("en-US", { style: "currency", currency: currency || "USD" }).format(value)
  } catch {
    return `${currency || ""} ${value}`
  }
}

function RFQReviewQueue() {
  const [items, setItems] = useState([])
  const [loading, setLoading] = useState(true)
  const [actingOn, setActingOn] = useState(null) // queue_id currently being approved/rejected
  const [message, setMessage] = useState({ type: "", text: "" })

  useEffect(() => {
    loadQueue()
  }, [])

  const authHeaders = () => ({ Authorization: localStorage.getItem("session_id") })

  const loadQueue = async () => {
    setLoading(true)
    try {
      const response = await fetch(buildApiUrl("/api/rfq/review-queue?limit=100"), {
        headers: authHeaders(),
      })
      if (response.ok) {
        const data = await response.json()
        setItems(data.items || [])
      } else {
        setMessage({ type: "error", text: "Failed to load the review queue" })
      }
    } catch (error) {
      console.error("Error loading RFQ review queue:", error)
      setMessage({ type: "error", text: "Failed to load the review queue" })
    } finally {
      setLoading(false)
    }
  }

  const approve = async (queueId) => {
    setActingOn(queueId)
    setMessage({ type: "", text: "" })
    try {
      const response = await fetch(buildApiUrl(`/api/rfq/review-queue/${queueId}/approve`), {
        method: "POST",
        headers: authHeaders(),
      })
      if (response.ok) {
        setItems((prev) => prev.filter((item) => item._id !== queueId))
        setMessage({ type: "success", text: "Approved — now a real RFQ on the pipeline." })
      } else {
        const data = await response.json().catch(() => ({}))
        setMessage({ type: "error", text: data.detail || "Approve failed" })
      }
    } catch (error) {
      console.error("Error approving RFQ:", error)
      setMessage({ type: "error", text: "Approve failed" })
    } finally {
      setActingOn(null)
    }
  }

  const reject = async (queueId) => {
    const reason = window.prompt("Reason for rejecting (optional):") || null
    setActingOn(queueId)
    setMessage({ type: "", text: "" })
    try {
      const response = await fetch(buildApiUrl(`/api/rfq/review-queue/${queueId}/reject`), {
        method: "POST",
        headers: { ...authHeaders(), "Content-Type": "application/json" },
        body: JSON.stringify({ reason }),
      })
      if (response.ok) {
        setItems((prev) => prev.filter((item) => item._id !== queueId))
        setMessage({ type: "success", text: "Rejected — no RFQ was created." })
      } else {
        const data = await response.json().catch(() => ({}))
        setMessage({ type: "error", text: data.detail || "Reject failed" })
      }
    } catch (error) {
      console.error("Error rejecting RFQ:", error)
      setMessage({ type: "error", text: "Reject failed" })
    } finally {
      setActingOn(null)
    }
  }

  return (
    <div className="rfq-container sales-page">
      {message.text && (
        <div className={`rfq-message ${message.type}`}>
          <span>{message.text}</span>
          <button onClick={() => setMessage({ type: "", text: "" })}>×</button>
        </div>
      )}

      <div className="card">
        <div className="card-header">
          <h2 className="card-title">RFQ Review Queue</h2>
          <p className="card-description">
            RFQs the mail-pool AI has proposed from incoming email. Nothing here is a real
            Opportunity yet — approve to create it on the pipeline, or reject to discard.{" "}
            <Link to="/admin/sales/rfq">Back to RFQ list</Link>
          </p>
        </div>

        {loading ? (
          <p style={{ padding: "1.5rem" }}>Loading…</p>
        ) : items.length === 0 ? (
          <p style={{ padding: "1.5rem", color: "#6b7280" }}>Nothing pending review right now.</p>
        ) : (
          <div className="rfq-table-container">
            <table className="rfq-table">
              <thead>
                <tr>
                  <th>Sender</th>
                  <th>Title</th>
                  <th>Value</th>
                  <th>Methodology</th>
                  <th>Country</th>
                  <th>LOI</th>
                  <th>IR</th>
                  <th>N</th>
                  <th>Model confidence</th>
                  <th>Proposed</th>
                  <th>Actions</th>
                </tr>
              </thead>
              <tbody>
                {items.map((item) => {
                  const payload = item.payload || {}
                  return (
                    <tr key={item._id}>
                      <td>
                        <div>{item.sender_name || "—"}</div>
                        <div style={{ color: "#6b7280", fontSize: "0.85em" }}>{item.sender_email}</div>
                      </td>
                      <td>{payload.title || "—"}</td>
                      <td>{formatMoney(payload.budget, payload.currency)}</td>
                      <td>{payload.methodology || "—"}</td>
                      <td>{payload.country || "—"}</td>
                      <td>{payload.loi ?? "—"}</td>
                      <td>{payload.ir ?? "—"}</td>
                      <td>{payload.sample_size ?? "—"}</td>
                      <td>{item.model_confidence || "—"}</td>
                      <td>{item.created_at ? new Date(item.created_at).toLocaleString() : "—"}</td>
                      <td>
                        <button
                          className="btn btn-primary"
                          disabled={actingOn === item._id}
                          onClick={() => approve(item._id)}
                          style={{ marginRight: "0.5rem" }}
                        >
                          Approve
                        </button>
                        <button
                          className="btn btn-outline"
                          disabled={actingOn === item._id}
                          onClick={() => reject(item._id)}
                        >
                          Reject
                        </button>
                      </td>
                    </tr>
                  )
                })}
              </tbody>
            </table>
          </div>
        )}
      </div>
    </div>
  )
}

export default RFQReviewQueue
