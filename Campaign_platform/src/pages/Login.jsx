"use client"

import { useState } from "react"
import { Link } from "react-router-dom"
import "../styles/login.css"
import { API_BASE_URL, buildApiUrl } from "../config"

function Login() {
  const [credentials, setCredentials] = useState({ username: "", password: "" })
  const [isLoading, setIsLoading] = useState(false)

  const handleSubmit = async (e) => {
    e.preventDefault()
    if (isLoading) return

    setIsLoading(true)

    try {
      const response = await fetch(buildApiUrl(`/login/`), {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(credentials),
      })

      const data = await response.json().catch(() => ({}))

      if (!response.ok) {
        alert("❌ " + (data.detail || "Login failed"))
        setIsLoading(false)
        return
      }

      // Store all session data synchronously
      localStorage.setItem("session_id", data.session_id)
      localStorage.setItem("username", data.username)
      localStorage.setItem("role", data.role || "admin")
      localStorage.setItem("auth", "true")

      // Use window.location for instant redirect (bypasses React Router overhead)
      window.location.href = "/admin/dashboard"
    } catch (error) {
      console.error("❌ Login error:", error)
      alert("❌ Login failed: " + error.message)
      setIsLoading(false)
    }
  }

  const handleChange = (e) => {
    setCredentials((p) => ({ ...p, [e.target.name]: e.target.value }))
  }

  return (
    <main className="login-page">
      <section className="login-left">
        <div className="login-left-inner">
          <h1 className="brand">Cogentix Research</h1>
          <p className="subtitle">Admin Login</p>

          <form onSubmit={handleSubmit} className="login-form">
            <div className="field">
              <input
                id="username"
                name="username"
                type="text"
                placeholder="Email"
                value={credentials.username}
                onChange={handleChange}
                required
                className="input"
                autoComplete="username"
              />
            </div>

            <div className="field">
              <input
                id="password"
                name="password"
                type="password"
                placeholder="Password"
                value={credentials.password}
                onChange={handleChange}
                required
                className="input"
                autoComplete="current-password"
              />
            </div>

            <button type="submit" className="btn-login" disabled={isLoading}>
              {isLoading ? "Logging in..." : "Login"}
            </button>

            <div className="login-meta">
              <Link to="#" className="forgot">Forgot password?</Link>
            </div>
          </form>
        </div>
      </section>

      <section className="login-right">
        <video
          className="video-bg"
          src="/videos/login-hero.mp4"
          autoPlay
          loop
          muted
          playsInline
        />
      </section>

    </main>
  )
}

export default Login
