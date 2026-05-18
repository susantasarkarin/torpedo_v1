"use client"

import { useState } from "react"
import { Link } from "react-router-dom"
import "../styles/login.css"
import api, { APIError } from "../utils/api"

function Login() {
  const [credentials, setCredentials] = useState({ username: "", password: "" })
  const [isLoading, setIsLoading] = useState(false)

  const handleSubmit = async (e) => {
    e.preventDefault()
    if (isLoading) return

    setIsLoading(true)

    try {
      await api.login(credentials.username, credentials.password)
      localStorage.setItem("auth", "true")

      // Use window.location for instant redirect (bypasses React Router overhead)
      window.location.href = "/admin/dashboard"
    } catch (error) {
      console.error("❌ Login error:", error)
      const message =
        error instanceof APIError
          ? error.message
          : (error?.message || "Login failed")
      alert("❌ Login failed: " + message)
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
