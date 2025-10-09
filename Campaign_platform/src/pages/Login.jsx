"use client"

import { useState } from "react"
import { useNavigate, Link } from "react-router-dom"
import "../styles/login.css"
import bgImg from "/images/login-hero.jpg"
//changes 2
import { API_BASE_URL } from "../config"

function Login() {
  const [credentials, setCredentials] = useState({ username: "", password: "" })
  const navigate = useNavigate()

  const handleSubmit = async (e) => {
    e.preventDefault()
    try {
      const response = await fetch(`${API_BASE_URL}/login/`, {
        //changes 1
        // const response = await fetch("http://localhost:8000/login/", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(credentials),
      })

      if (!response.ok) {
        //changes 3
        //const err = await response.json()
        const err = await response.json().catch(() => ({}))
        alert("❌ " + (err.detail || "Login failed"))
        return
      }

      const data = await response.json()
      console.log("✅ Login success:", data)
      localStorage.setItem("auth", "true")
      navigate("/dashboard", { replace: true })
    } catch (error) {
      console.error("Login error:", error)
      alert("❌ Login failed. Please try again.")
    }
  }

  const handleChange = (e) => {
    setCredentials((p) => ({ ...p, [e.target.name]: e.target.value }))
  }

  return (
    <main className="login-page" role="main">
      {/* Left panel: brand + form */}
      <section className="login-left" aria-labelledby="login-title">
        <div className="login-left-inner">
          <h1 id="login-title" className="brand">
            Cogentix Research
          </h1>
          <p className="subtitle">Login Form</p>

          <form onSubmit={handleSubmit} className="login-form" aria-describedby="login-help">
            {/* Username */}
            <div className="field">
              <label htmlFor="username" className="sr-only">Email</label>
              <input
                id="username"
                name="username"
                type="text"
                placeholder="Email"
                value={credentials.username}
                onChange={handleChange}
                autoComplete="username"
                required
                className="input"
              />
            </div>

            {/* Password */}
            <div className="field">
              <label htmlFor="password" className="sr-only">Password</label>
              <div className="password-wrap">
                <input
                  id="password"
                  name="password"
                  type="password"
                  placeholder="Password"
                  value={credentials.password}
                  onChange={handleChange}
                  autoComplete="current-password"
                  required
                  className="input"
                />
                <span className="chevron" aria-hidden="true">▾</span>
              </div>
            </div>

            <button type="submit" className="btn-login">
              Login
            </button>

            <div id="login-help" className="login-meta">
              <label className="remember">
                <input type="checkbox" /> <span>Remember me</span>
              </label>
              <Link to="#" className="forgot">
                Forgot password?
              </Link>
            </div>
          </form>
        </div>
      </section>

      {/* Right panel: hero image */}
      <section
        className="login-right"
        style={{ backgroundImage: `url(${bgImg})` }}
        aria-label="Rocket launching illustration"
        role="img"
      />
    </main>
  )
}

export default Login
