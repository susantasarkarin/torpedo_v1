"use client"

import { useLocation } from "react-router-dom"
import { useState, useEffect } from "react"

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
          template: selectedTemplate
        })
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
    <div style={{ padding: "1rem" }}>
      <h2>Workflow</h2>
      <p>
        <strong>Template:</strong>{" "}
        {selectedTemplate ? selectedTemplate.name : "❌ None selected"}
      </p>
      <p>
        <strong>List:</strong> {list ? list.name : "❌ None selected"}
      </p>
      <p>
        <strong>Contacts loaded:</strong>{" "}
        {loading ? "Loading..." : contacts.length}
      </p>

      <button
        className="btn btn-primary"
        onClick={handleSendEmails}
        disabled={sending || loading || contacts.length === 0}
      >
        {sending ? "Sending..." : "Send Emails"}
      </button>
    </div>
  )
}

export default Workflow
