"use client"

import { useState, useEffect } from "react"
import { buildApiUrl } from "../config"

function UserManagement() {
    const [users, setUsers] = useState([])
    const [roles, setRoles] = useState([])
    const [loading, setLoading] = useState(false)
    const [error, setError] = useState(null)
    const [success, setSuccess] = useState(null)

    // Modal state
    const [isModalOpen, setIsModalOpen] = useState(false)
    const [editingUser, setEditingUser] = useState(null)
    const [isResetPasswordOpen, setIsResetPasswordOpen] = useState(false)
    const [resetPasswordUser, setResetPasswordUser] = useState(null)

    // Form state
    const [formData, setFormData] = useState({
        name: "",
        email: "",
        username: "",
        password: "",
        role: "user",
        status: "active"
    })

    const [newPassword, setNewPassword] = useState("")

    useEffect(() => {
        fetchUsers()
        fetchRoles()
    }, [])

    const getAuthToken = () => localStorage.getItem("session_id")

    const fetchUsers = async () => {
        setLoading(true)
        setError(null)
        try {
            const token = getAuthToken()
            const res = await fetch(buildApiUrl("/admin/users/"), {
                headers: { Authorization: token }
            })

            if (res.ok) {
                const data = await res.json()
                setUsers(data.users || [])
            } else if (res.status === 403) {
                setError("Admin access required to manage users")
            } else {
                const errData = await res.json()
                setError(errData.detail || "Failed to fetch users")
            }
        } catch (e) {
            setError("Network error: " + e.message)
        } finally {
            setLoading(false)
        }
    }

    const fetchRoles = async () => {
        try {
            const token = getAuthToken()
            const res = await fetch(buildApiUrl("/admin/roles/"), {
                headers: { Authorization: token }
            })

            if (res.ok) {
                const data = await res.json()
                setRoles(data.roles || [])
            }
        } catch (e) {
            console.log("Could not fetch roles:", e.message)
        }
    }

    const handleDelete = async (userId) => {
        if (!confirm("Are you sure you want to deactivate this user?")) return

        setError(null)
        setSuccess(null)
        try {
            const token = getAuthToken()
            const res = await fetch(buildApiUrl(`/admin/users/${userId}`), {
                method: "DELETE",
                headers: { Authorization: token }
            })

            if (res.ok) {
                setSuccess("User deactivated successfully")
                fetchUsers()
            } else {
                const errData = await res.json()
                setError(errData.detail || "Failed to deactivate user")
            }
        } catch (e) {
            setError("Error deactivating user: " + e.message)
        }
    }

    const handleEdit = (user) => {
        setEditingUser(user)
        setFormData({
            name: user.name || "",
            email: user.email || "",
            username: user.username || "",
            password: "",
            role: user.role || (user.roles && user.roles[0]) || "user",
            status: user.status || "active"
        })
        setIsModalOpen(true)
        setError(null)
        setSuccess(null)
    }

    const handleAdd = () => {
        setEditingUser(null)
        setFormData({
            name: "",
            email: "",
            username: "",
            password: "",
            role: "user",
            status: "active"
        })
        setIsModalOpen(true)
        setError(null)
        setSuccess(null)
    }

    const handleResetPassword = (user) => {
        setResetPasswordUser(user)
        setNewPassword("")
        setIsResetPasswordOpen(true)
        setError(null)
        setSuccess(null)
    }

    const submitResetPassword = async (e) => {
        e.preventDefault()
        if (!newPassword || newPassword.length < 6) {
            setError("Password must be at least 6 characters")
            return
        }

        try {
            const token = getAuthToken()
            const res = await fetch(buildApiUrl(`/admin/users/${resetPasswordUser.id}/reset-password`), {
                method: "PUT",
                headers: {
                    "Content-Type": "application/json",
                    Authorization: token
                },
                body: JSON.stringify({ new_password: newPassword })
            })

            if (res.ok) {
                setSuccess(`Password reset for ${resetPasswordUser.username}`)
                setIsResetPasswordOpen(false)
                setResetPasswordUser(null)
                setNewPassword("")
            } else {
                const errData = await res.json()
                setError(errData.detail || "Failed to reset password")
            }
        } catch (e) {
            setError("Error resetting password: " + e.message)
        }
    }

    const handleSubmit = async (e) => {
        e.preventDefault()
        setError(null)
        setSuccess(null)

        // Validation
        if (!editingUser && !formData.password) {
            setError("Password is required for new users")
            return
        }
        if (!formData.email && !formData.username) {
            setError("Email or username is required")
            return
        }

        try {
            const token = getAuthToken()
            const url = editingUser
                ? buildApiUrl(`/admin/users/${editingUser.id}`)
                : buildApiUrl("/admin/users/")

            const method = editingUser ? "PUT" : "POST"

            const payload = {
                name: formData.name,
                email: formData.email,
                username: formData.username || formData.email,
                role: formData.role,
                status: formData.status
            }

            // Only include password if provided
            if (formData.password) {
                payload.password = formData.password
            }

            const res = await fetch(url, {
                method: method,
                headers: {
                    "Content-Type": "application/json",
                    Authorization: token
                },
                body: JSON.stringify(payload)
            })

            if (res.ok) {
                setSuccess(editingUser ? "User updated successfully" : "User created successfully")
                setIsModalOpen(false)
                fetchUsers()
            } else {
                const err = await res.json()
                setError(err.detail || "Operation failed")
            }
        } catch (e) {
            setError("Error saving user: " + e.message)
        }
    }

    const getRoleDisplay = (roleName) => {
        const role = roles.find(r => r.code === roleName)
        return role ? role.name : roleName
    }

    const getStatusStyle = (status) => {
        switch (status) {
            case 'active':
                return { background: '#dcfce7', color: '#166534' }
            case 'inactive':
                return { background: '#fee2e2', color: '#991b1b' }
            case 'pending':
                return { background: '#fef3c7', color: '#92400e' }
            case 'locked':
                return { background: '#fce7f3', color: '#9d174d' }
            default:
                return { background: '#f3f4f6', color: '#374151' }
        }
    }

    return (
        <div className="user-management">
            {error && (
                <div style={{
                    padding: '0.75rem 1rem',
                    marginBottom: '1rem',
                    background: '#fee2e2',
                    color: '#991b1b',
                    borderRadius: '4px',
                    display: 'flex',
                    justifyContent: 'space-between',
                    alignItems: 'center'
                }}>
                    <span>❌ {error}</span>
                    <button onClick={() => setError(null)} style={{ border: 'none', background: 'none', cursor: 'pointer', fontSize: '1.2rem' }}>×</button>
                </div>
            )}

            {success && (
                <div style={{
                    padding: '0.75rem 1rem',
                    marginBottom: '1rem',
                    background: '#dcfce7',
                    color: '#166534',
                    borderRadius: '4px',
                    display: 'flex',
                    justifyContent: 'space-between',
                    alignItems: 'center'
                }}>
                    <span>✅ {success}</span>
                    <button onClick={() => setSuccess(null)} style={{ border: 'none', background: 'none', cursor: 'pointer', fontSize: '1.2rem' }}>×</button>
                </div>
            )}

            <div className="users-header" style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: '1rem' }}>
                <h3>System Users</h3>
                <div style={{ display: 'flex', gap: '0.5rem' }}>
                    <button
                        onClick={fetchUsers}
                        style={{ padding: '0.5rem 1rem', background: '#f3f4f6', borderRadius: '4px', border: '1px solid #d1d5db', cursor: 'pointer' }}
                    >
                        🔄 Refresh
                    </button>
                    <button
                        onClick={handleAdd}
                        style={{ padding: '0.5rem 1rem', background: '#3b82f6', color: 'white', borderRadius: '4px', border: 'none', cursor: 'pointer' }}
                    >
                        + Add User
                    </button>
                </div>
            </div>

            {loading ? (
                <p>Loading users...</p>
            ) : (
                <table style={{ width: '100%', borderCollapse: 'collapse' }}>
                    <thead>
                        <tr style={{ background: '#f3f4f6', textAlign: 'left' }}>
                            <th style={{ padding: '0.75rem' }}>Name</th>
                            <th style={{ padding: '0.75rem' }}>Username/Email</th>
                            <th style={{ padding: '0.75rem' }}>Role</th>
                            <th style={{ padding: '0.75rem' }}>Status</th>
                            <th style={{ padding: '0.75rem', textAlign: 'right' }}>Actions</th>
                        </tr>
                    </thead>
                    <tbody>
                        {users.map(user => (
                            <tr key={user.id} style={{ borderBottom: '1px solid #e5e7eb' }}>
                                <td style={{ padding: '0.75rem' }}>{user.name || user.username}</td>
                                <td style={{ padding: '0.75rem' }}>{user.email || user.username}</td>
                                <td style={{ padding: '0.75rem' }}>
                                    <span style={{
                                        padding: '0.25rem 0.5rem',
                                        borderRadius: '999px',
                                        fontSize: '0.75rem',
                                        background: user.role === 'admin' ? '#dbeafe' : '#f3f4f6',
                                        color: user.role === 'admin' ? '#1e40af' : '#374151'
                                    }}>
                                        {getRoleDisplay(user.role)}
                                    </span>
                                </td>
                                <td style={{ padding: '0.75rem' }}>
                                    <span style={{
                                        padding: '0.25rem 0.5rem',
                                        borderRadius: '999px',
                                        fontSize: '0.75rem',
                                        ...getStatusStyle(user.status)
                                    }}>
                                        {user.status}
                                    </span>
                                </td>
                                <td style={{ padding: '0.75rem', textAlign: 'right' }}>
                                    <button 
                                        onClick={() => handleEdit(user)} 
                                        style={{ marginRight: '0.5rem', cursor: 'pointer', border: 'none', background: 'none' }}
                                        title="Edit user"
                                    >
                                        ✏️
                                    </button>
                                    <button 
                                        onClick={() => handleResetPassword(user)} 
                                        style={{ marginRight: '0.5rem', cursor: 'pointer', border: 'none', background: 'none' }}
                                        title="Reset password"
                                    >
                                        🔑
                                    </button>
                                    <button 
                                        onClick={() => handleDelete(user.id)} 
                                        style={{ color: 'red', cursor: 'pointer', border: 'none', background: 'none' }}
                                        title="Deactivate user"
                                    >
                                        🗑️
                                    </button>
                                </td>
                            </tr>
                        ))}
                        {users.length === 0 && (
                            <tr>
                                <td colSpan="5" style={{ padding: '1rem', textAlign: 'center', color: '#666' }}>
                                    No users found. Click "Add User" to create one.
                                </td>
                            </tr>
                        )}
                    </tbody>
                </table>
            )}

            {/* Create/Edit User Modal */}
            {isModalOpen && (
                <div style={{
                    position: 'fixed', top: 0, left: 0, right: 0, bottom: 0,
                    background: 'rgba(0,0,0,0.5)', display: 'flex', alignItems: 'center', justifyContent: 'center', zIndex: 1000
                }}>
                    <div style={{ background: 'white', padding: '2rem', borderRadius: '8px', width: '450px', maxWidth: '90%', maxHeight: '90vh', overflow: 'auto' }}>
                        <h3 style={{ marginBottom: '1rem' }}>{editingUser ? "Edit User" : "Add New User"}</h3>
                        <form onSubmit={handleSubmit}>
                            <div style={{ marginBottom: '1rem' }}>
                                <label style={{ display: 'block', marginBottom: '0.5rem', fontSize: '0.875rem', fontWeight: 'bold' }}>Display Name</label>
                                <input
                                    type="text"
                                    value={formData.name}
                                    onChange={e => setFormData({ ...formData, name: e.target.value })}
                                    style={{ width: '100%', padding: '0.5rem', border: '1px solid #d1d5db', borderRadius: '4px' }}
                                    required
                                    placeholder="John Doe"
                                />
                            </div>

                            <div style={{ marginBottom: '1rem' }}>
                                <label style={{ display: 'block', marginBottom: '0.5rem', fontSize: '0.875rem', fontWeight: 'bold' }}>Email</label>
                                <input
                                    type="email"
                                    value={formData.email}
                                    onChange={e => setFormData({ ...formData, email: e.target.value })}
                                    style={{ width: '100%', padding: '0.5rem', border: '1px solid #d1d5db', borderRadius: '4px' }}
                                    required
                                    placeholder="user@example.com"
                                />
                            </div>

                            <div style={{ marginBottom: '1rem' }}>
                                <label style={{ display: 'block', marginBottom: '0.5rem', fontSize: '0.875rem', fontWeight: 'bold' }}>
                                    Username {editingUser && <span style={{ fontWeight: 'normal', color: '#666' }}>(cannot be changed)</span>}
                                </label>
                                <input
                                    type="text"
                                    value={formData.username || formData.email}
                                    onChange={e => setFormData({ ...formData, username: e.target.value })}
                                    style={{ 
                                        width: '100%', 
                                        padding: '0.5rem', 
                                        border: '1px solid #d1d5db', 
                                        borderRadius: '4px',
                                        backgroundColor: editingUser ? '#f5f5f5' : 'white'
                                    }}
                                    disabled={!!editingUser}
                                    placeholder="Will default to email if not provided"
                                />
                            </div>

                            <div style={{ marginBottom: '1rem' }}>
                                <label style={{ display: 'block', marginBottom: '0.5rem', fontSize: '0.875rem', fontWeight: 'bold' }}>
                                    Password {editingUser && <span style={{ fontWeight: 'normal', color: '#666' }}>(Leave blank to keep current)</span>}
                                </label>
                                <input
                                    type="password"
                                    value={formData.password}
                                    onChange={e => setFormData({ ...formData, password: e.target.value })}
                                    style={{ width: '100%', padding: '0.5rem', border: '1px solid #d1d5db', borderRadius: '4px' }}
                                    required={!editingUser}
                                    placeholder="Min 6 characters"
                                    minLength={editingUser ? 0 : 6}
                                />
                            </div>

                            <div style={{ marginBottom: '1rem' }}>
                                <label style={{ display: 'block', marginBottom: '0.5rem', fontSize: '0.875rem', fontWeight: 'bold' }}>Role</label>
                                <select
                                    value={formData.role}
                                    onChange={e => setFormData({ ...formData, role: e.target.value })}
                                    style={{ width: '100%', padding: '0.5rem', border: '1px solid #d1d5db', borderRadius: '4px' }}
                                >
                                    {roles.length > 0 ? (
                                        roles.map(role => (
                                            <option key={role.code} value={role.code}>
                                                {role.name} - {role.description}
                                            </option>
                                        ))
                                    ) : (
                                        <>
                                            <option value="viewer">Viewer - Read-only access</option>
                                            <option value="user">User - Standard access</option>
                                            <option value="manager">Manager - Team management</option>
                                            <option value="admin">Admin - Full access</option>
                                        </>
                                    )}
                                </select>
                            </div>

                            <div style={{ marginBottom: '1.5rem' }}>
                                <label style={{ display: 'block', marginBottom: '0.5rem', fontSize: '0.875rem', fontWeight: 'bold' }}>Status</label>
                                <select
                                    value={formData.status}
                                    onChange={e => setFormData({ ...formData, status: e.target.value })}
                                    style={{ width: '100%', padding: '0.5rem', border: '1px solid #d1d5db', borderRadius: '4px' }}
                                >
                                    <option value="active">Active</option>
                                    <option value="inactive">Inactive</option>
                                    <option value="pending">Pending</option>
                                    <option value="locked">Locked</option>
                                </select>
                            </div>

                            <div style={{ display: 'flex', justifyContent: 'flex-end', gap: '0.5rem' }}>
                                <button
                                    type="button"
                                    onClick={() => setIsModalOpen(false)}
                                    style={{ padding: '0.5rem 1rem', background: '#f3f4f6', border: 'none', borderRadius: '4px', cursor: 'pointer' }}
                                >
                                    Cancel
                                </button>
                                <button
                                    type="submit"
                                    style={{ padding: '0.5rem 1rem', background: '#3b82f6', color: 'white', border: 'none', borderRadius: '4px', cursor: 'pointer' }}
                                >
                                    {editingUser ? "Save Changes" : "Create User"}
                                </button>
                            </div>
                        </form>
                    </div>
                </div>
            )}

            {/* Reset Password Modal */}
            {isResetPasswordOpen && resetPasswordUser && (
                <div style={{
                    position: 'fixed', top: 0, left: 0, right: 0, bottom: 0,
                    background: 'rgba(0,0,0,0.5)', display: 'flex', alignItems: 'center', justifyContent: 'center', zIndex: 1000
                }}>
                    <div style={{ background: 'white', padding: '2rem', borderRadius: '8px', width: '400px', maxWidth: '90%' }}>
                        <h3 style={{ marginBottom: '1rem' }}>🔑 Reset Password</h3>
                        <p style={{ marginBottom: '1rem', color: '#666' }}>
                            Reset password for user: <strong>{resetPasswordUser.username}</strong>
                        </p>
                        <form onSubmit={submitResetPassword}>
                            <div style={{ marginBottom: '1rem' }}>
                                <label style={{ display: 'block', marginBottom: '0.5rem', fontSize: '0.875rem', fontWeight: 'bold' }}>New Password</label>
                                <input
                                    type="password"
                                    value={newPassword}
                                    onChange={e => setNewPassword(e.target.value)}
                                    style={{ width: '100%', padding: '0.5rem', border: '1px solid #d1d5db', borderRadius: '4px' }}
                                    required
                                    placeholder="Min 6 characters"
                                    minLength={6}
                                />
                            </div>

                            <div style={{ display: 'flex', justifyContent: 'flex-end', gap: '0.5rem' }}>
                                <button
                                    type="button"
                                    onClick={() => setIsResetPasswordOpen(false)}
                                    style={{ padding: '0.5rem 1rem', background: '#f3f4f6', border: 'none', borderRadius: '4px', cursor: 'pointer' }}
                                >
                                    Cancel
                                </button>
                                <button
                                    type="submit"
                                    style={{ padding: '0.5rem 1rem', background: '#ef4444', color: 'white', border: 'none', borderRadius: '4px', cursor: 'pointer' }}
                                >
                                    Reset Password
                                </button>
                            </div>
                        </form>
                    </div>
                </div>
            )}
        </div>
    )
}

export default UserManagement
