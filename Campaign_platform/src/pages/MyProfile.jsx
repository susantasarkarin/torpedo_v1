"use client"

import { useState, useEffect } from "react"
import { useNavigate } from "react-router-dom"
import { API_BASE_URL, buildApiUrl } from "../config"
import "./Settings.css"

function MyProfile() {
  const navigate = useNavigate()
  const [loading, setLoading] = useState(true)
  const [saving, setSaving] = useState(false)
  const [error, setError] = useState(null)
  const [success, setSuccess] = useState(null)
  
  // User profile data
  const [profile, setProfile] = useState({
    username: "",
    displayName: "",
    email: "",
    role: "",
    createdAt: "",
  })
  
  // Password change form
  const [passwordForm, setPasswordForm] = useState({
    currentPassword: "",
    newPassword: "",
    confirmPassword: "",
  })
  const [changingPassword, setChangingPassword] = useState(false)

  // Fetch user profile on mount
  useEffect(() => {
    fetchProfile()
  }, [])

  const fetchProfile = async () => {
    const sessionId = localStorage.getItem("session_id")
    if (!sessionId) {
      navigate("/admin/login")
      return
    }

    try {
      const res = await fetch(buildApiUrl(`/profile/`), {
        headers: {
          "Content-Type": "application/json",
          Authorization: sessionId,
        },
      })

      if (res.status === 401) {
        localStorage.removeItem("session_id")
        navigate("/admin/login")
        return
      }

      const data = await res.json()
      if (!res.ok) throw new Error(data.detail || "Failed to load profile")

      setProfile({
        username: data.username || "",
        displayName: data.displayName || data.username || "",
        email: data.email || "",
        role: data.role || "admin",
        createdAt: data.createdAt || "",
      })
    } catch (e) {
      setError(e.message || "Failed to load profile")
    } finally {
      setLoading(false)
    }
  }

  const handleProfileChange = (field, value) => {
    setProfile((prev) => ({ ...prev, [field]: value }))
  }

  const handlePasswordChange = (field, value) => {
    setPasswordForm((prev) => ({ ...prev, [field]: value }))
  }

  const saveProfile = async () => {
    const sessionId = localStorage.getItem("session_id")
    if (!sessionId) {
      navigate("/admin/login")
      return
    }

    // Validate email
    if (profile.email && !/\S+@\S+\.\S+/.test(profile.email)) {
      setError("Please enter a valid email address")
      return
    }

    setSaving(true)
    setError(null)
    setSuccess(null)

    try {
      const res = await fetch(buildApiUrl(`/profile/update`), {
        method: "PUT",
        headers: {
          "Content-Type": "application/json",
          Authorization: sessionId,
        },
        body: JSON.stringify({
          email: profile.email,
          display_name: profile.displayName,
        }),
      })

      const data = await res.json()
      if (!res.ok) throw new Error(data.detail || "Failed to update profile")

      setSuccess("Profile updated successfully!")
    } catch (e) {
      setError(e.message || "Failed to update profile")
    } finally {
      setSaving(false)
    }
  }

  const changePassword = async () => {
    const sessionId = localStorage.getItem("session_id")
    if (!sessionId) {
      navigate("/admin/login")
      return
    }

    // Validate passwords
    if (!passwordForm.currentPassword) {
      setError("Current password is required")
      return
    }
    if (!passwordForm.newPassword) {
      setError("New password is required")
      return
    }
    if (passwordForm.newPassword.length < 6) {
      setError("New password must be at least 6 characters")
      return
    }
    if (passwordForm.newPassword !== passwordForm.confirmPassword) {
      setError("New passwords do not match")
      return
    }

    setChangingPassword(true)
    setError(null)
    setSuccess(null)

    try {
      const res = await fetch(buildApiUrl(`/profile/change-password`), {
        method: "PUT",
        headers: {
          "Content-Type": "application/json",
          Authorization: sessionId,
        },
        body: JSON.stringify({
          current_password: passwordForm.currentPassword,
          new_password: passwordForm.newPassword,
        }),
      })

      const data = await res.json()
      if (!res.ok) throw new Error(data.detail || "Failed to change password")

      setSuccess("Password changed successfully!")
      setPasswordForm({
        currentPassword: "",
        newPassword: "",
        confirmPassword: "",
      })
    } catch (e) {
      setError(e.message || "Failed to change password")
    } finally {
      setChangingPassword(false)
    }
  }

  const formatDate = (dateStr) => {
    if (!dateStr) return "N/A"
    try {
      return new Date(dateStr).toLocaleDateString("en-US", {
        year: "numeric",
        month: "long",
        day: "numeric",
      })
    } catch {
      return dateStr
    }
  }

  if (loading) {
    return (
      <div className="settings-container">
        <div className="settings-header">
          <h1>👤 My Profile</h1>
        </div>
        <div style={{ padding: "2rem", textAlign: "center" }}>Loading...</div>
      </div>
    )
  }

  return (
    <div className="settings-container">
      <div className="settings-header">
        <h1>👤 My Profile</h1>
        <p>View and manage your account information</p>
      </div>

      {error && (
        <div className="settings-alert error">
          ❌ {error}
          <button onClick={() => setError(null)}>×</button>
        </div>
      )}

      {success && (
        <div className="settings-alert success">
          ✅ {success}
          <button onClick={() => setSuccess(null)}>×</button>
        </div>
      )}

      <div className="settings-content">
        {/* Profile Information */}
        <div className="settings-section">
          <h2>Account Information</h2>
          <p className="section-description">
            Your account details and role information.
          </p>

          <div className="settings-group">
            <h3>📋 User Details</h3>
            
            <div className="setting-row">
              <label>Display Name</label>
              <input
                type="text"
                value={profile.displayName}
                onChange={(e) => handleProfileChange("displayName", e.target.value)}
                placeholder="Enter your display name"
              />
              <small style={{ color: "#666", marginTop: "4px" }}>
                This name will be shown across the application
              </small>
            </div>
            
            <div className="setting-row">
              <label>Username</label>
              <input
                type="text"
                value={profile.username}
                disabled
                style={{ backgroundColor: "#f5f5f5", cursor: "not-allowed" }}
              />
              <small style={{ color: "#666", marginTop: "4px" }}>
                Username cannot be changed
              </small>
            </div>

            <div className="setting-row">
              <label>Email</label>
              <input
                type="email"
                value={profile.email}
                onChange={(e) => handleProfileChange("email", e.target.value)}
                placeholder="Enter your email address"
              />
            </div>

            <div className="setting-row">
              <label>Role</label>
              <input
                type="text"
                value={profile.role}
                disabled
                style={{ backgroundColor: "#f5f5f5", cursor: "not-allowed" }}
              />
              <small style={{ color: "#666", marginTop: "4px" }}>
                Role is assigned by administrators
              </small>
            </div>

            <div className="setting-row">
              <label>Account Created</label>
              <input
                type="text"
                value={formatDate(profile.createdAt)}
                disabled
                style={{ backgroundColor: "#f5f5f5", cursor: "not-allowed" }}
              />
            </div>

            <div className="setting-row">
              <button
                className="save-button"
                onClick={saveProfile}
                disabled={saving}
              >
                {saving ? "Saving..." : "💾 Save Changes"}
              </button>
            </div>
          </div>
        </div>

        {/* Password Change Section */}
        <div className="settings-section">
          <h2>Security</h2>
          <p className="section-description">
            Change your password to keep your account secure.
          </p>

          <div className="settings-group">
            <h3>🔐 Change Password</h3>

            <div className="setting-row">
              <label>Current Password</label>
              <input
                type="password"
                value={passwordForm.currentPassword}
                onChange={(e) => handlePasswordChange("currentPassword", e.target.value)}
                placeholder="Enter current password"
              />
            </div>

            <div className="setting-row">
              <label>New Password</label>
              <input
                type="password"
                value={passwordForm.newPassword}
                onChange={(e) => handlePasswordChange("newPassword", e.target.value)}
                placeholder="Enter new password (min 6 characters)"
              />
            </div>

            <div className="setting-row">
              <label>Confirm New Password</label>
              <input
                type="password"
                value={passwordForm.confirmPassword}
                onChange={(e) => handlePasswordChange("confirmPassword", e.target.value)}
                placeholder="Confirm new password"
              />
            </div>

            <div className="setting-row">
              <button
                className="save-button"
                onClick={changePassword}
                disabled={changingPassword}
                style={{ backgroundColor: "#e74c3c" }}
              >
                {changingPassword ? "Changing..." : "🔑 Change Password"}
              </button>
            </div>
          </div>
        </div>
      </div>
    </div>
  )
}

export default MyProfile
