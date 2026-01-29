"use client"

import { useState, useEffect } from "react"
import { useNavigate } from "react-router-dom"
import { API_BASE_URL, buildApiUrl } from "../config"
import UserManagement from "../components/UserManagement"
import "./Settings.css"

function MyProfile() {
  const navigate = useNavigate()
  const [loading, setLoading] = useState(true)
  const [saving, setSaving] = useState(false)
  const [error, setError] = useState(null)
  const [success, setSuccess] = useState(null)
  const [activeTab, setActiveTab] = useState("profile") // profile, users, roles

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

  // Available roles for reference
  const [availableRoles, setAvailableRoles] = useState([])

  // Fetch user profile on mount
  useEffect(() => {
    fetchProfile()
    fetchRoles()
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

  const fetchRoles = async () => {
    const sessionId = localStorage.getItem("session_id")
    try {
      const res = await fetch(buildApiUrl(`/admin/roles/`), {
        headers: { Authorization: sessionId },
      })
      if (res.ok) {
        const data = await res.json()
        setAvailableRoles(data.roles || [])
      }
    } catch (e) {
      // Roles fetch is optional
      console.log("Could not fetch roles:", e)
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

      {/* Tab Navigation for Admins */}
      {profile.role === 'admin' && (
        <div style={{ 
          display: 'flex', 
          gap: '0', 
          marginBottom: '1.5rem',
          borderBottom: '2px solid #e5e7eb'
        }}>
          <button
            onClick={() => setActiveTab("profile")}
            style={{
              padding: '0.75rem 1.5rem',
              background: activeTab === 'profile' ? '#3b82f6' : 'transparent',
              color: activeTab === 'profile' ? 'white' : '#374151',
              border: 'none',
              borderRadius: '8px 8px 0 0',
              cursor: 'pointer',
              fontWeight: activeTab === 'profile' ? 'bold' : 'normal',
              fontSize: '0.95rem'
            }}
          >
            👤 My Profile
          </button>
          <button
            onClick={() => setActiveTab("users")}
            style={{
              padding: '0.75rem 1.5rem',
              background: activeTab === 'users' ? '#3b82f6' : 'transparent',
              color: activeTab === 'users' ? 'white' : '#374151',
              border: 'none',
              borderRadius: '8px 8px 0 0',
              cursor: 'pointer',
              fontWeight: activeTab === 'users' ? 'bold' : 'normal',
              fontSize: '0.95rem'
            }}
          >
            👥 User Management
          </button>
          <button
            onClick={() => setActiveTab("roles")}
            style={{
              padding: '0.75rem 1.5rem',
              background: activeTab === 'roles' ? '#3b82f6' : 'transparent',
              color: activeTab === 'roles' ? 'white' : '#374151',
              border: 'none',
              borderRadius: '8px 8px 0 0',
              cursor: 'pointer',
              fontWeight: activeTab === 'roles' ? 'bold' : 'normal',
              fontSize: '0.95rem'
            }}
          >
            🔑 Roles & Permissions
          </button>
        </div>
      )}

      <div className="settings-content">
        {/* Profile Tab */}
        {(activeTab === "profile" || profile.role !== 'admin') && (
          <>
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
                    Username cannot be changed (used for login)
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
                  <div style={{ display: 'flex', alignItems: 'center', gap: '0.5rem' }}>
                    <input
                      type="text"
                      value={profile.role}
                      disabled
                      style={{ backgroundColor: "#f5f5f5", cursor: "not-allowed", flex: 1 }}
                    />
                    <span style={{
                      padding: '0.25rem 0.75rem',
                      borderRadius: '999px',
                      fontSize: '0.75rem',
                      background: profile.role === 'admin' ? '#dbeafe' : '#f3f4f6',
                      color: profile.role === 'admin' ? '#1e40af' : '#374151',
                      fontWeight: 'bold'
                    }}>
                      {profile.role === 'admin' ? '🔐 Full Access' : 
                       profile.role === 'manager' ? '📊 Manager' : 
                       profile.role === 'viewer' ? '👁️ View Only' : '👤 Standard'}
                    </span>
                  </div>
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
          </>
        )}

        {/* User Management Tab - Admin Only */}
        {activeTab === "users" && profile.role === 'admin' && (
          <div className="settings-section">
            <h2>👥 User Management</h2>
            <p className="section-description">
              Create, edit, and manage system users. Assign roles to control access levels.
            </p>
            <UserManagement />
          </div>
        )}

        {/* Roles & Permissions Tab - Admin Only */}
        {activeTab === "roles" && profile.role === 'admin' && (
          <div className="settings-section">
            <h2>🔑 Roles & Permissions</h2>
            <p className="section-description">
              Overview of available roles and their permissions.
            </p>
            
            <div className="settings-group">
              <h3>📋 Available Roles</h3>
              
              {availableRoles.length > 0 ? (
                <table style={{ width: '100%', borderCollapse: 'collapse', marginTop: '1rem' }}>
                  <thead>
                    <tr style={{ background: '#f3f4f6', textAlign: 'left' }}>
                      <th style={{ padding: '0.75rem', borderBottom: '2px solid #e5e7eb' }}>Role</th>
                      <th style={{ padding: '0.75rem', borderBottom: '2px solid #e5e7eb' }}>Description</th>
                      <th style={{ padding: '0.75rem', borderBottom: '2px solid #e5e7eb' }}>Permissions</th>
                    </tr>
                  </thead>
                  <tbody>
                    {availableRoles.map(role => (
                      <tr key={role.code} style={{ borderBottom: '1px solid #e5e7eb' }}>
                        <td style={{ padding: '0.75rem' }}>
                          <span style={{
                            padding: '0.25rem 0.75rem',
                            borderRadius: '999px',
                            fontSize: '0.875rem',
                            background: role.code === 'admin' ? '#dbeafe' : 
                                       role.code === 'manager' ? '#fef3c7' :
                                       role.code === 'user' ? '#dcfce7' : '#f3f4f6',
                            color: role.code === 'admin' ? '#1e40af' : 
                                  role.code === 'manager' ? '#92400e' :
                                  role.code === 'user' ? '#166534' : '#374151',
                            fontWeight: 'bold'
                          }}>
                            {role.name}
                          </span>
                        </td>
                        <td style={{ padding: '0.75rem', color: '#666' }}>{role.description}</td>
                        <td style={{ padding: '0.75rem' }}>
                          <div style={{ display: 'flex', flexWrap: 'wrap', gap: '0.25rem' }}>
                            {role.permissions.slice(0, 3).map((perm, idx) => (
                              <span key={idx} style={{
                                padding: '0.125rem 0.5rem',
                                borderRadius: '4px',
                                fontSize: '0.75rem',
                                background: '#f3f4f6',
                                color: '#374151'
                              }}>
                                {perm}
                              </span>
                            ))}
                            {role.permissions.length > 3 && (
                              <span style={{
                                padding: '0.125rem 0.5rem',
                                borderRadius: '4px',
                                fontSize: '0.75rem',
                                background: '#e5e7eb',
                                color: '#374151'
                              }}>
                                +{role.permissions.length - 3} more
                              </span>
                            )}
                          </div>
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              ) : (
                <div style={{ 
                  padding: '2rem', 
                  textAlign: 'center', 
                  background: '#f9fafb', 
                  borderRadius: '8px',
                  marginTop: '1rem'
                }}>
                  <p style={{ color: '#666', marginBottom: '1rem' }}>
                    Available roles are defined in the system configuration.
                  </p>
                  <div style={{ display: 'flex', flexDirection: 'column', gap: '0.5rem', alignItems: 'center' }}>
                    <div style={{ display: 'flex', alignItems: 'center', gap: '0.5rem' }}>
                      <span style={{ padding: '0.25rem 0.75rem', borderRadius: '999px', background: '#dbeafe', color: '#1e40af', fontWeight: 'bold' }}>Admin</span>
                      <span>- Full system access</span>
                    </div>
                    <div style={{ display: 'flex', alignItems: 'center', gap: '0.5rem' }}>
                      <span style={{ padding: '0.25rem 0.75rem', borderRadius: '999px', background: '#fef3c7', color: '#92400e', fontWeight: 'bold' }}>Manager</span>
                      <span>- Campaigns, leads, reports</span>
                    </div>
                    <div style={{ display: 'flex', alignItems: 'center', gap: '0.5rem' }}>
                      <span style={{ padding: '0.25rem 0.75rem', borderRadius: '999px', background: '#dcfce7', color: '#166534', fontWeight: 'bold' }}>User</span>
                      <span>- View and edit access</span>
                    </div>
                    <div style={{ display: 'flex', alignItems: 'center', gap: '0.5rem' }}>
                      <span style={{ padding: '0.25rem 0.75rem', borderRadius: '999px', background: '#f3f4f6', color: '#374151', fontWeight: 'bold' }}>Viewer</span>
                      <span>- Read-only access</span>
                    </div>
                  </div>
                </div>
              )}
            </div>

            <div className="settings-group" style={{ marginTop: '2rem' }}>
              <h3>ℹ️ Role Assignment</h3>
              <div style={{ padding: '1rem', background: '#f0f9ff', borderRadius: '8px', borderLeft: '4px solid #3b82f6' }}>
                <p style={{ margin: 0, color: '#1e40af' }}>
                  <strong>To assign or change a user's role:</strong>
                </p>
                <ol style={{ marginTop: '0.5rem', marginBottom: 0, color: '#1e40af' }}>
                  <li>Go to the "User Management" tab</li>
                  <li>Click the edit (✏️) button for the user</li>
                  <li>Select the new role from the dropdown</li>
                  <li>Save changes</li>
                </ol>
              </div>
            </div>
          </div>
        )}
      </div>
    </div>
  )
}

export default MyProfile
