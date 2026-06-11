"use client"

import { useEffect, useState } from "react"

const initialForm = {
  clientName: "",
  contactPerson: "",
  email: "",
  address: "",
  clientVariable: "",
  currency: "USD",
  clientType: "Offline",
  status: "Active",
}

export default function ClientFormModal({ isOpen, onClose, onSubmit, accountClients = [] }) {
  const [form, setForm] = useState(initialForm)
  const [errors, setErrors] = useState({})

  useEffect(() => {
    if (!isOpen) return
    const prev = document.body.style.overflow
    document.body.style.overflow = "hidden"
    return () => {
      document.body.style.overflow = prev
    }
  }, [isOpen])

  if (!isOpen) return null

  const handleChange = (e) => {
    const { name, value } = e.target
    setForm((prev) => ({ ...prev, [name]: value }))
  }

  const validate = () => {
    const next = {}
    if (!form.clientName) next.clientName = "Client Name is required"
    if (!form.email) next.email = "Email is required"
    setErrors(next)
    return Object.keys(next).length === 0
  }

  const handleSubmit = (e) => {
    e.preventDefault()
    if (!validate()) return
    onSubmit(form)
    setForm(initialForm)
  }

  return (
    <div className="c-modal-overlay" role="dialog" aria-modal="true" aria-labelledby="add-client-title">
      <div className="c-modal">
        <header className="c-modal-header">
          <h2 id="add-client-title">Add New Client</h2>
          <button className="c-icon-btn" aria-label="Close" onClick={onClose}>
            ✕
          </button>
        </header>

        <form onSubmit={handleSubmit} className="c-modal-body">
          {/* Client Name */}
          <div className="c-field">
            <label htmlFor="clientName">
              Client Name <span className="c-req">*</span>
            </label>
            <select id="clientName" name="clientName" value={form.clientName} onChange={handleChange}>
              <option value="">Select client from Accounts...</option>
              {accountClients.map((name) => (
                <option key={name} value={name}>
                  {name}
                </option>
              ))}
            </select>
            {errors.clientName && <div className="c-error">{errors.clientName}</div>}
          </div>

          {/* Email */}
          <div className="c-field">
            <label htmlFor="email">
              Email Address <span className="c-req">*</span>
            </label>
            <input
              id="email"
              name="email"
              type="email"
              placeholder="Enter email address"
              value={form.email}
              onChange={handleChange}
            />
            {errors.email && <div className="c-error">{errors.email}</div>}
          </div>

          {/* Contact Person */}
          <div className="c-field">
            <label htmlFor="contactPerson">Contact Person</label>
            <input
              id="contactPerson"
              name="contactPerson"
              placeholder="Enter contact person"
              value={form.contactPerson}
              onChange={handleChange}
            />
          </div>

          {/* Address */}
          <div className="c-field">
            <label htmlFor="address">Address</label>
            <textarea
              id="address"
              name="address"
              placeholder="Enter address"
              rows={3}
              value={form.address}
              onChange={handleChange}
            />
          </div>

          {/* Client Variable */}
          <div className="c-field">
            <label htmlFor="clientVariable">Client Variable</label>
            <input
              id="clientVariable"
              name="clientVariable"
              placeholder="Enter client variable"
              value={form.clientVariable}
              onChange={handleChange}
            />
          </div>

          {/* Currency */}
          <div className="c-field">
            <label htmlFor="currency">Currency</label>
            <select id="currency" name="currency" value={form.currency} onChange={handleChange}>
              <option value="USD">USD</option>
              <option value="EUR">EUR</option>
              <option value="INR">INR</option>
              <option value="GBP">GBP</option>
            </select>
          </div>

          {/* Client Type */}
          <div className="c-field">
            <label htmlFor="clientType">Client Type</label>
            <select id="clientType" name="clientType" value={form.clientType} onChange={handleChange}>
              <option value="Offline">Offline</option>
              <option value="Online">Online</option>
              <option value="API">API</option>
            </select>
          </div>

          {/* Status */}
          <div className="c-field">
            <label htmlFor="status">Status</label>
            <select id="status" name="status" value={form.status} onChange={handleChange}>
              <option value="Active">Active</option>
              <option value="Inactive">Inactive</option>
            </select>
          </div>

          <div className="c-modal-footer">
            <button type="button" className="c-btn c-btn-secondary" onClick={onClose}>
              Cancel
            </button>
            <button type="submit" className="c-btn c-btn-primary">
              Add Client
            </button>
          </div>
        </form>
      </div>
    </div>
  )
}
