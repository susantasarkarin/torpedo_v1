"use client"

import { useState } from "react"
import { useNavigate, Link } from "react-router-dom"
import "../styles/login.css"
import { API_BASE_URL } from "../config"

function Login() {
  const [credentials, setCredentials] = useState({ username: "", password: "" })
  const navigate = useNavigate()

  const handleSubmit = async (e) => {
    e.preventDefault()
    try {
      const response = await fetch(`${API_BASE_URL}/login/`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(credentials),
      })

      const data = await response.json().catch(() => ({}))

      if (!response.ok) {
        alert("❌ " + (data.detail || "Login failed"))
        return
      }

      localStorage.setItem("session_id", data.session_id)
      localStorage.setItem("username", data.username)
      localStorage.setItem("auth", "true")

      navigate("/admin/dashboard", { replace: true })
    } catch (error) {
      console.error("Login error:", error)
      alert("❌ Login failed. Please try again.")
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
              />
            </div>

            <button type="submit" className="btn-login">Login</button>

            <div className="login-meta">
              <Link to="#" className="forgot">Forgot password?</Link>
            </div>
          </form>
        </div>
      </section>

      <section className="login-right">
        <img
          src="/images/login-hero.jpg"
          alt="Login background"
          className="video-bg"
        />
      </section>
    </main>
  )
}

export default Login
