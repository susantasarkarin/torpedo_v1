"use client"

import { useState } from "react"
import { Link, useNavigate } from "react-router-dom"

function Login() {
  const [credentials, setCredentials] = useState({ username: "", password: "" })
  const navigate = useNavigate()

  const handleSubmit = (e) => {
    e.preventDefault()
    // Placeholder login logic
    console.log("Login attempt:", credentials)
    navigate("/")
  }

  const handleChange = (e) => {
    setCredentials({
      ...credentials,
      [e.target.name]: e.target.value,
    })
  }

  return (
    <div
      style={{
        minHeight: "100vh",
        display: "flex",
        alignItems: "center",
        justifyContent: "center",
        backgroundColor: "#f8fafc",
      }}
    >
      <div
        style={{
          width: "100%",
          maxWidth: "400px",
          padding: "2rem",
          backgroundColor: "white",
          borderRadius: "12px",
          boxShadow: "0 8px 32px rgba(0, 0, 0, 0.12)",
        }}
      >
        <div style={{ textAlign: "center", marginBottom: "2rem" }}>
          <h1 style={{ fontSize: "2rem", fontWeight: "bold", color: "#1e293b", marginBottom: "0.5rem" }}>
            Email Campaigns Platform
          </h1>
          <p style={{ color: "#64748b" }}>Sign in to your account</p>
        </div>

        <form onSubmit={handleSubmit}>
          <div className="form-group">
            <label htmlFor="username" className="form-label">
              Username
            </label>
            <input
              type="text"
              id="username"
              name="username"
              className="form-input"
              value={credentials.username}
              onChange={handleChange}
              placeholder="Enter your username"
              required
            />
          </div>

          <div className="form-group">
            <label htmlFor="password" className="form-label">
              Password
            </label>
            <input
              type="password"
              id="password"
              name="password"
              className="form-input"
              value={credentials.password}
              onChange={handleChange}
              placeholder="Enter your password"
              required
            />
          </div>

          <div
            style={{ display: "flex", alignItems: "center", justifyContent: "space-between", marginBottom: "1.5rem" }}
          >
            <label style={{ display: "flex", alignItems: "center", fontSize: "0.875rem" }}>
              <input type="checkbox" style={{ marginRight: "0.5rem" }} />
              Remember me
            </label>
            <a href="#" style={{ fontSize: "0.875rem", color: "#3b82f6", textDecoration: "none" }}>
              Forgot password?
            </a>
          </div>

          <button type="submit" className="btn btn-primary" style={{ width: "100%", marginBottom: "1rem" }}>
            Sign In
          </button>

          <div style={{ textAlign: "center" }}>
            <p style={{ fontSize: "0.875rem", color: "#64748b" }}>
              Don't have an account?{" "}
              <a href="#" style={{ color: "#3b82f6", textDecoration: "none" }}>
                Sign up
              </a>
            </p>
          </div>
        </form>

        <div style={{ marginTop: "2rem", textAlign: "center" }}>
          <Link to="/" style={{ fontSize: "0.875rem", color: "#6b7280", textDecoration: "none" }}>
            ← Back to Dashboard
          </Link>
        </div>
      </div>
    </div>
  )
}

export default Login
