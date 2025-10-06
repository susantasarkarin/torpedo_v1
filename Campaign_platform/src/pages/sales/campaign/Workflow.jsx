"use client"

import { useLocation } from "react-router-dom"
import { useState, useEffect } from "react"
import "./workflow.css"

function Workflow() {
  const location = useLocation()
  const { selectedTemplate, list } = location.state || {}
  const [contacts, setContacts] = useState([])
  const [loading, setLoading] = useState(false)
  const [sending, setSending] = useState(false)

  // 🔹 Fetch contacts for selected list
  useEffect(() => {
    if (!list) return
    const fetchContacts = async () => {
      try {
        setLoading(true)
        let res = await fetch(`http://localhost:8000/contacts/${list._id}`)
        if (!res.ok) {
          res = await fetch(`http://localhost:8000/contacts/${encodeURIComponent(list.name)}`)
        }
        const data = await res.json()
        if (res.ok) {
          setContacts(data.contacts || [])
        } else {
          alert("Error fetching contacts: " + data.detail)
        }
      } catch (err) {
        console.error("Fetch contacts failed:", err)
        alert("Error fetching contacts: " + err.message)
      } finally {
        setLoading(false)
      }
    }
    fetchContacts()
  }, [list])

  // 🔹 Send emails
  const handleSendEmails = async () => {
    if (!selectedTemplate) {
      alert("No template selected!")
      return
    }
    if (contacts.length === 0) {
      alert("No contacts loaded for this list!")
      return
    }

    try {
      setSending(true)
      const res = await fetch("http://localhost:8000/send-emails/", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          contacts: contacts,
          template: selectedTemplate,
        }),
      })
      const data = await res.json()
      if (res.ok) {
        alert(`✅ ${data.message}`)
      } else {
        alert("❌ Send failed: " + data.detail)
      }
    } catch (err) {
      console.error("Send emails failed:", err)
      alert("Error sending emails: " + err.message)
    } finally {
      setSending(false)
    }
  }

  return (
    <div className="wf">
      <h2 className="wf-title">Workflow</h2>

      <p className="wf-row">
        <strong className="wf-label">Template:</strong>{" "}
        <span className={selectedTemplate ? "wf-badge wf-badge-ok" : "wf-badge wf-badge-bad"}>
          {selectedTemplate ? selectedTemplate.name : "None selected"}
        </span>
      </p>

      <p className="wf-row">
        <strong className="wf-label">List:</strong>{" "}
        <span className={list ? "wf-badge wf-badge-ok" : "wf-badge wf-badge-bad"}>
          {list ? list.name : "None selected"}
        </span>
      </p>

      <p className="wf-row" role="status" aria-live="polite">
        <strong className="wf-label">Contacts loaded:</strong>{" "}
        <span className={loading ? "wf-text-muted" : "wf-count"}>{loading ? "Loading..." : contacts.length}</span>
      </p>

      <button
        className="wf-btn wf-btn-primary"
        onClick={handleSendEmails}
        disabled={sending || loading || contacts.length === 0}
        aria-busy={sending ? "true" : "false"}
      >
        {sending ? "Sending..." : "Send Emails"}
      </button>
    </div>
  )
}

export default Workflow
