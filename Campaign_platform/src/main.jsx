// v3 - force cache bust
const _b = 3;
import React from "react"
import ReactDOM from "react-dom/client"
import { BrowserRouter } from "react-router-dom"
import App from "./App.jsx"
import { PanelAuthProvider } from "./panel/context/PanelAuthContext"
import "./styles/index.css"
import "./styles/brand.css"
import "./styles/shell.css"
import { API_BASE_URL } from "./config"

// Every call to our own API carries the admin session when one exists
// (2026-10-19). The backend now refuses data-changing requests without a
// login; many pages call fetch() directly and never set the header, so it is
// added here once. A request that already has an Authorization header (panel
// members, explicit calls) is left alone; other sites never get it.
;(function attachSession() {
  if (typeof window === "undefined" || !window.fetch || window.__sfwFetchWrapped) return
  const original = window.fetch.bind(window)
  const apiBase = (API_BASE_URL || "").trim().replace(/\/$/, "")
  const isOurApi = (url) => {
    if (!url) return false
    if (url.startsWith("/")) return !url.startsWith("//")
    if (url.startsWith(window.location.origin)) return true
    return Boolean(apiBase) && url.startsWith(apiBase)
  }
  window.fetch = (input, init = {}) => {
    try {
      const url = typeof input === "string" ? input : (input && input.url) || ""
      if (isOurApi(url)) {
        const session = window.localStorage.getItem("session_id")
        const headers = new Headers(init.headers || (typeof input !== "string" && input && input.headers) || {})
        if (session && !headers.has("Authorization")) {
          headers.set("Authorization", session)
          init = { ...init, headers }
        }
      }
    } catch { /* never block a request over the header */ }
    return original(input, init)
  }
  window.__sfwFetchWrapped = true
})()

ReactDOM.createRoot(document.getElementById("root")).render(
  <React.StrictMode>
    <BrowserRouter>
      <PanelAuthProvider>
        <App />
      </PanelAuthProvider>
    </BrowserRouter>
  </React.StrictMode>,
)
