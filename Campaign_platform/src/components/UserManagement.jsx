"use client"

import { useState, useEffect } from "react"
import { buildApiUrl } from "../config"

function UserManagement() {
    const [users, setUsers] = useState([])
    const [loading, setLoading] = useState(false)
    const [error, setError] = useState(null)

    // Modal state
    const [isModalOpen, setIsModalOpen] = useState(false)
    const [editingUser, setEditingUser] = useState(null)

    // Form state
    const [formData, setFormData] = useState({
        name: "",
        email: "",
        username: "",
        password: "",
        role: "user", // Default role
        status: "active"
    })

    useEffect(() => {
        fetchUsers()
    }, [])

    const getAuthToken = () => localStorage.getItem("session_id")

    const fetchUsers = async () => {
        setLoading(true)
        try {
            const token = getAuthToken()
            // API endpoint for listing users - assuming backend supports GET /users/
            const res = await fetch(buildApiUrl("/users/"), {
                headers: { Authorization: token }
            })

            if (res.ok) {
                const data = await res.json()
                setUsers(data.users || [])
            } else {
                setError("Failed to fetch users")
            }
        } catch (e) {
            setError(e.message)
        } finally {
            setLoading(false)
        }
    }

    const handleDelete = async (userId) => {
        if (!confirm("Are you sure you want to delete this user?")) return

        try {
            const token = getAuthToken()
            const res = await fetch(buildApiUrl(`/users/${userId}`), {
                method: "DELETE",
                headers: { Authorization: token }
            })

            if (res.ok) {
                fetchUsers() // Refresh list
            } else {
                alert("Failed to delete user")
            }
        } catch (e) {
            alert("Error deleting user: " + e.message)
        }
    }

    const handleEdit = (user) => {
        setEditingUser(user)
        setFormData({
            name: user.name || "",
            email: user.email || "",
            username: user.username || "", // Username might be immutable
            password: "", // Don't show password
            role: (user.roles && user.roles[0]) || "user",
            status: user.status || "active"
        })
        setIsModalOpen(true)
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
    }

    const handleSubmit = async (e) => {
        e.preventDefault()

        // Validation
        if (!editingUser && !formData.password) {
            alert("Password is required for new users")
            return
        }

        try {
            const token = getAuthToken()
            const url = editingUser
                ? buildApiUrl(`/users/${editingUser.id}`)
                : buildApiUrl("/users/")

            const method = editingUser ? "PUT" : "POST"

            const payload = { ...formData }

            // For backend, roles is a list
            payload.roles = [formData.role]

            // Remove password if empty (for edit)
            if (editingUser && !payload.password) {
                delete payload.password
            }
            // Assuming backend expects username for logic (it handles it)
            if (editingUser) {
                // If immutable, backend ignores it usually
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
                setIsModalOpen(false)
                fetchUsers()
            } else {
                const err = await res.json()
                alert("Operation failed: " + (err.detail || "Unknown error"))
            }
        } catch (e) {
            alert("Error saving user: " + e.message)
        }
    }

    return (
        <div className="user-management">
            <div className="users-header" style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: '1rem' }}>
                <h3>System Users</h3>
                <button
                    onClick={handleAdd}
                    style={{ padding: '0.5rem 1rem', background: '#3b82f6', color: 'white', borderRadius: '4px', border: 'none', cursor: 'pointer' }}
                >
                    + Add User
                </button>
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
                                <td style={{ padding: '0.75rem' }}>{user.name}</td>
                                <td style={{ padding: '0.75rem' }}>{user.email || user.username}</td>
                                <td style={{ padding: '0.75rem' }}>{(user.roles || []).join(', ')}</td>
                                <td style={{ padding: '0.75rem' }}>
                                    <span style={{
                                        padding: '0.25rem 0.5rem',
                                        borderRadius: '999px',
                                        fontSize: '0.75rem',
                                        background: user.status === 'active' ? '#dcfce7' : '#f3f4f6',
                                        color: user.status === 'active' ? '#166534' : '#374151'
                                    }}>
                                        {user.status}
                                    </span>
                                </td>
                                <td style={{ padding: '0.75rem', textAlign: 'right' }}>
                                    <button onClick={() => handleEdit(user)} style={{ marginRight: '0.5rem', cursor: 'pointer' }}>✏️</button>
                                    <button onClick={() => handleDelete(user.id)} style={{ color: 'red', cursor: 'pointer' }}>🗑️</button>
                                </td>
                            </tr>
                        ))}
                        {users.length === 0 && (
                            <tr>
                                <td colSpan="5" style={{ padding: '1rem', textAlign: 'center', color: '#666' }}>No users found.</td>
                            </tr>
                        )}
                    </tbody>
                </table>
            )}

            {/* Modal */}
            {isModalOpen && (
                <div style={{
                    position: 'fixed', top: 0, left: 0, right: 0, bottom: 0,
                    background: 'rgba(0,0,0,0.5)', display: 'flex', alignItems: 'center', justifyContent: 'center', zIndex: 1000
                }}>
                    <div style={{ background: 'white', padding: '2rem', borderRadius: '8px', width: '400px', maxWidth: '90%' }}>
                        <h3>{editingUser ? "Edit User" : "Add New User"}</h3>
                        <form onSubmit={handleSubmit}>
                            <div style={{ marginBottom: '1rem' }}>
                                <label style={{ display: 'block', marginBottom: '0.5rem', fontSize: '0.875rem' }}>Name</label>
                                <input
                                    type="text"
                                    value={formData.name}
                                    onChange={e => setFormData({ ...formData, name: e.target.value })}
                                    style={{ width: '100%', padding: '0.5rem', border: '1px solid #d1d5db', borderRadius: '4px' }}
                                    required
                                />
                            </div>

                            <div style={{ marginBottom: '1rem' }}>
                                <label style={{ display: 'block', marginBottom: '0.5rem', fontSize: '0.875rem' }}>Email / Username</label>
                                <input
                                    type="text"
                                    value={formData.email}
                                    onChange={e => setFormData({ ...formData, email: e.target.value, username: e.target.value })}
                                    style={{ width: '100%', padding: '0.5rem', border: '1px solid #d1d5db', borderRadius: '4px' }}
                                    required
                                    placeholder="user@example.com (used as username)"
                                />
                            </div>

                            <div style={{ marginBottom: '1rem' }}>
                                <label style={{ display: 'block', marginBottom: '0.5rem', fontSize: '0.875rem' }}>Password {editingUser && '(Leave blank to keep current)'}</label>
                                <input
                                    type="password"
                                    value={formData.password}
                                    onChange={e => setFormData({ ...formData, password: e.target.value })}
                                    style={{ width: '100%', padding: '0.5rem', border: '1px solid #d1d5db', borderRadius: '4px' }}
                                    required={!editingUser}
                                />
                            </div>

                            <div style={{ marginBottom: '1rem' }}>
                                <label style={{ display: 'block', marginBottom: '0.5rem', fontSize: '0.875rem' }}>Role</label>
                                <select
                                    value={formData.role}
                                    onChange={e => setFormData({ ...formData, role: e.target.value })}
                                    style={{ width: '100%', padding: '0.5rem', border: '1px solid #d1d5db', borderRadius: '4px' }}
                                >
                                    <option value="user">User</option>
                                    <option value="admin">Admin</option>
                                    <option value="manager">Manager</option>
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
                                    Save
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
